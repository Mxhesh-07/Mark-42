"""Tier 2 E3 — update check from a signed release manifest, applied on exit.

The manifest is JSON::

    {
      "version": "0.2.0",
      "url": "https://.../MARK-42-0.2.0.zip",
      "sha256": "<artifact digest>",
      "signature": "<base64 Ed25519 signature over the canonical manifest>",
      "notes": "optional"
    }

Rules, in order — all of them fail closed:

1. HTTPS only (a local ``file://`` path is allowed for tests/explicit offline).
2. The manifest must carry a ``signature`` and a ``sha256``. Without both,
   nothing is downloaded and nothing is staged.
3. The signature is verified with the public key in ``config/update_key.pem``
   (or ``JARVIS_UPDATE_KEY``). If ``cryptography`` is unavailable or the key is
   missing, the update is refused — "unsigned" is not a synonym for "trusted".
4. The artifact digest must match ``sha256`` before it is staged.

``apply_on_exit`` does not swap files while the app is running: it writes a
small script that waits for this process to exit, replaces the bundle and
restarts. If anything is missing it returns False and the staged file remains
for a manual apply. This is deliberately boring — an updater is the last place
to be clever.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPDATE_DIR = BASE_DIR / "memory" / "updates"
KEY_PATH = BASE_DIR / "config" / "update_key.pem"
STATE_PATH = BASE_DIR / "memory" / "update_state.json"
MAX_MANIFEST_BYTES = 64 * 1024


def _get(url: str, limit: int = MAX_MANIFEST_BYTES) -> bytes:
    if url.startswith("file://"):
        return Path(url[len("file://"):]).read_bytes()[:limit]
    if not url.lower().startswith("https://"):
        raise ValueError("update manifest must be https://")
    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("manifest is too large")
    return data


def canonical(manifest: dict) -> bytes:
    """Stable bytes for signing: the manifest without its signature field."""
    body = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def public_key_pem() -> bytes | None:
    raw = os.environ.get("JARVIS_UPDATE_KEY", "").strip()
    if raw:
        return raw.encode("utf-8")
    try:
        return KEY_PATH.read_bytes()
    except Exception:
        return None


def verify_signature(manifest: dict, pem: bytes | None = None) -> bool:
    """True only when the signature is present and valid for this manifest."""
    signature = str(manifest.get("signature") or "").strip()
    if not signature:
        return False
    key_pem = pem or public_key_pem()
    if not key_pem:
        return False
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except Exception:
        return False
    try:
        key = serialization.load_pem_public_key(key_pem)
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(base64.b64decode(signature), canonical(manifest))
        return True
    except Exception:
        return False


def _version_tuple(version: str) -> tuple:
    parts = []
    for piece in str(version or "").split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check(url: str | None = None, *, current: str | None = None) -> dict:
    """Fetch and verify the manifest. Returns a result dict, never raises."""
    from agent import version as version_mod

    url = url or os.environ.get("JARVIS_UPDATE_URL", "").strip()
    if not url:
        return {"status": "disabled", "reason": "no update URL configured"}
    current = current or version_mod.version()
    try:
        manifest = json.loads(_get(url))
    except Exception as exc:
        return {"status": "error", "reason": f"manifest: {exc}"}
    if not isinstance(manifest, dict):
        return {"status": "error", "reason": "manifest is not an object"}
    if not verify_signature(manifest):
        return {"status": "refused", "reason": "manifest is not signed by the update key"}
    if not manifest.get("sha256"):
        return {"status": "refused", "reason": "manifest has no artifact digest"}
    newer = _version_tuple(manifest.get("version", "")) > _version_tuple(current)
    return {"status": "ok", "current": current, "manifest": manifest,
            "newer": newer, "url": url}


def stage(result: dict) -> dict:
    """Download and verify the artifact for a checked manifest."""
    if result.get("status") != "ok" or not result.get("newer"):
        return {"status": "skipped", "reason": "nothing newer to stage"}
    manifest = result["manifest"]
    try:
        UPDATE_DIR.mkdir(parents=True, exist_ok=True)
        name = Path(str(manifest.get("url", "update.bin"))).name or "update.bin"
        target = UPDATE_DIR / name
        data = _get(manifest["url"], limit=1024 * 1024 * 1024)
        digest = hashlib.sha256(data).hexdigest()
        if digest.lower() != str(manifest["sha256"]).lower():
            return {"status": "refused", "reason": "artifact digest mismatch"}
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        state = {"version": manifest.get("version"), "path": str(target),
                 "sha256": digest, "staged_at": time.time()}
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return {"status": "staged", **state}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def pending() -> dict | None:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    path = Path(str(state.get("path", "")))
    if not path.exists():
        return None
    return state


def apply_on_exit(target: str | Path | None = None) -> dict:
    """Schedule the staged archive to replace `target` after this process exits.

    `target` defaults to the frozen executable's directory. On a source checkout
    there is nothing to replace, so it refuses rather than editing the repo.
    """
    state = pending()
    if state is None:
        return {"status": "none", "reason": "nothing staged"}
    executable = Path(sys.executable)
    if not getattr(sys, "frozen", False):
        return {"status": "refused", "reason": "not a frozen build; apply manually"}
    destination = Path(target) if target else executable.parent
    archive = Path(state["path"])
    if sys.platform == "win32":
        script = UPDATE_DIR / "apply_update.bat"
        body = (
            "@echo off\r\n"
            "timeout /t 3 /nobreak >nul\r\n"
            f'powershell -NoProfile -Command "Expand-Archive -Force \'{archive}\' \'{destination}\'"\r\n'
            f'start "" "{executable}"\r\n'
            "del \"%~f0\"\r\n"
        )
        script.write_text(body, encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(script)], close_fds=True,
                         creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    else:
        script = UPDATE_DIR / "apply_update.sh"
        body = (
            "#!/bin/sh\n"
            "sleep 3\n"
            f"tar -xf '{archive}' -C '{destination}'\n"
            f"'{executable}' &\n"
            "rm -f \"$0\"\n"
        )
        script.write_text(body, encoding="utf-8")
        script.chmod(0o700)
        subprocess.Popen(["/bin/sh", str(script)], close_fds=True, start_new_session=True)
    try:
        STATE_PATH.unlink()
    except OSError:
        pass
    return {"status": "scheduled", "script": str(script), "destination": str(destination)}


def _cli(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    action = argv[0] if argv else "check"
    if action == "check":
        result = check(argv[1] if len(argv) > 1 else None)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("status") in ("ok", "disabled") else 2
    if action == "stage":
        print(json.dumps(stage(check(argv[1] if len(argv) > 1 else None)), indent=2))
        return 0
    if action == "pending":
        print(json.dumps(pending(), indent=2))
        return 0
    print("usage: python -m agent.updater [check [url] | stage [url] | pending]")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
