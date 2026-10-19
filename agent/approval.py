"""Signed task manifests and intent binding (A1).

Today a confirmation approves a *tool name*. When the user says yes to
"file_controller", nothing pins **which** file, so the effect that actually runs
is not the effect that was shown. The same applies to a shell command: "confirm:
cmd_control" says nothing about the command.

This module makes the approval name the effect:

* ``manifest(tool, params)`` returns an unforgeable, expiring, single-use token
  bound to a hash of (tool, full arguments, expiry), together with a plain
  description of the effect ("delete C:\\x\\y.txt (2.1 MB)").
* ``authorize(manifest, granted)`` turns the user's yes into a *verified*
  approval, and consuming it makes a replay fail.

The token is an HMAC over the canonical arguments, keyed by a per-install secret
(``memory/approval.key``, created on first use, gitignored). A different action —
even the same tool with one argument changed — produces a different digest and
fails verification, so an approval can never be silently re-pointed.
"""

import hashlib
import hmac
import json
import os
import secrets as _secrets
import sys
import threading
import time
import uuid
from pathlib import Path

from agent import atomic

DEFAULT_TTL_S = 300.0


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR  = get_base_dir()
KEY_PATH  = BASE_DIR / "memory" / "approval.key"
USED_PATH = BASE_DIR / "memory" / "approval_used.json"

_lock = threading.Lock()
_secret_cache: bytes | None = None
_used: dict[str, float] | None = None


# --- the signing secret -------------------------------------------------------

def _secret() -> bytes:
    """The per-install HMAC key (env override, else memory/approval.key)."""
    global _secret_cache
    override = os.environ.get("JARVIS_APPROVAL_KEY", "").strip()
    if override:
        return override.encode("utf-8")
    if _secret_cache is not None:
        return _secret_cache
    with _lock:
        if _secret_cache is not None:
            return _secret_cache
        try:
            raw = KEY_PATH.read_text(encoding="utf-8").strip()
            if len(raw) >= 32:
                _secret_cache = raw.encode("utf-8")
                return _secret_cache
        except Exception:
            pass
        fresh = _secrets.token_hex(32)
        try:
            atomic.write_text(KEY_PATH, fresh + "\n")
        except Exception as e:
            print(f"[Approval] ⚠️ Could not persist the approval key: {e}")
        _secret_cache = fresh.encode("utf-8")
        return _secret_cache


# --- canonical arguments ------------------------------------------------------

def _normalise(params) -> dict:
    """A JSON-safe copy of the parameters, so the digest is deterministic."""
    if not isinstance(params, dict):
        return {}
    try:
        return json.loads(json.dumps(params, sort_keys=True, default=str))
    except Exception:
        return {"_repr": str(params)[:2000]}


def _canonical(params) -> str:
    return json.dumps(_normalise(params), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def digest(tool, params) -> str:
    """Digest of what an action *does* — its tool and its full arguments."""
    body = f"{tool}\x00{_canonical(params)}"
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _sign(tool, args_digest, expires_at, nonce) -> str:
    message = f"{tool}|{args_digest}|{expires_at}|{nonce}".encode("utf-8")
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


# --- the effect, in words -----------------------------------------------------

def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _size_of(path) -> str:
    try:
        return _human_bytes(Path(str(path)).stat().st_size)
    except Exception:
        return ""


def _short(value, limit: int = 60) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def effect_for(tool, params) -> str:
    """A one-line description of exactly what this call will do."""
    tool = str(tool or "")
    params = params if isinstance(params, dict) else {}
    action = str(params.get("action") or "").strip().lower()

    if tool == "file_controller":
        source = str(params.get("path") or params.get("source") or params.get("file") or "")
        target = str(params.get("destination") or params.get("dest") or source)
        verb = action or "access"
        if action in ("copy", "move") and source and target:
            return f"{verb} {source} -> {target}"
        size = _size_of(target)
        return f"{verb} {target}{f' ({size})' if size else ''}"
    if tool == "cmd_control":
        command = str(params.get("command") or params.get("cmd") or "")
        return f"run shell command: {_short(command, 120)}"
    if tool == "send_message":
        who = params.get("recipient") or params.get("to") or params.get("contact") or "someone"
        body = str(params.get("message") or params.get("body") or "")
        return f"send a message to {who}" + (f": {_short(body)}" if body else "")
    if tool == "computer_settings":
        return f"change a computer setting: {action}"
    if tool in ("code_helper", "dev_agent", "generated_code"):
        detail = str(params.get("task") or params.get("description") or params.get("goal") or "")
        return f"write and run code{': ' + _short(detail, 100) if detail else ''}"
    if tool == "screen_process":
        return "capture and analyse the screen"

    args = ", ".join(f"{k}={_short(v)}" for k, v in list(params.items())[:4])
    return f"{tool}({args})" if args else tool


# --- replay protection --------------------------------------------------------

def _load_used() -> dict:
    global _used
    if _used is not None:
        return _used
    now = time.time()
    loaded: dict[str, float] = {}
    try:
        raw = json.loads(USED_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            loaded = {str(k): float(v) for k, v in raw.items() if float(v) > now}
    except Exception:
        loaded = {}
    _used = loaded
    return _used


def _save_used() -> None:
    if _used is None:
        return
    try:
        atomic.write_json(USED_PATH, _used)
    except Exception:
        pass


def _already_used(nonce: str) -> bool:
    with _lock:
        store = _load_used()
        if nonce not in store:
            return False
        if store[nonce] <= time.time():
            del store[nonce]
            _save_used()
            return False
        return True


def consume(nonce) -> None:
    """Mark a token used so it can never be replayed."""
    if not nonce:
        return
    with _lock:
        store = _load_used()
        store[str(nonce)] = time.time() + DEFAULT_TTL_S + 60
        for key in [k for k, expiry in store.items() if expiry <= time.time()]:
            del store[key]
        _save_used()


# --- the public API -----------------------------------------------------------

def manifest(tool, params, *, ttl_s: float | None = None, task_id=None) -> dict:
    """Build the effect description and the unforgeable token that pins it."""
    ttl = DEFAULT_TTL_S if ttl_s is None else max(1.0, float(ttl_s))
    args = _normalise(params)
    now = time.time()
    # Milliseconds as an integer: a float would contain a ".", which is also the
    # token's field separator.
    expires_ms = int((now + ttl) * 1000)
    args_digest = digest(tool, args)
    nonce = uuid.uuid4().hex
    return {
        "tool": str(tool or ""),
        "args": args,
        "args_digest": args_digest,
        "issued_at": round(now, 3),
        "expires_at": expires_ms / 1000.0,
        "nonce": nonce,
        "token": f"{expires_ms}.{nonce}.{_sign(tool, args_digest, expires_ms, nonce)}",
        "effect": effect_for(tool, args),
        "task_id": task_id,
    }


def verify(token, tool, params=None, *, args_digest: str | None = None) -> tuple[bool, str]:
    """Check a token against this exact action, its expiry and its replay store."""
    parts = str(token or "").split(".", 2)
    if len(parts) != 3:
        return False, "malformed approval token"
    expires_raw, nonce, signature = parts
    try:
        expires_ms = int(expires_raw)
    except ValueError:
        return False, "malformed approval token"
    if time.time() * 1000.0 > expires_ms:
        return False, "approval expired"
    if args_digest is None:
        args_digest = digest(tool, params)
    expected = _sign(str(tool or ""), args_digest, expires_ms, nonce)
    if not hmac.compare_digest(expected, signature):
        return False, "approval token does not match this action"
    if _already_used(nonce):
        return False, "approval already used (replay rejected)"
    return True, "approved"


def _count(outcome: str, why: str = "") -> None:
    try:
        from agent import metrics

        metrics.inc("approval", outcome=outcome)
    except Exception:
        pass


def authorize(man: dict, granted: bool) -> tuple[bool, str]:
    """Turn a user's yes/no into a verified, single-use approval."""
    if not granted:
        _count("denied")
        return False, "not approved by the user"
    if not isinstance(man, dict):
        _count("invalid")
        return False, "no approval manifest"
    ok, why = verify(man.get("token"), man.get("tool"), args_digest=man.get("args_digest"))
    if not ok:
        _count("invalid")
        return False, why
    consume(man.get("nonce"))
    _count("granted")
    return True, why


def reset_for_tests() -> None:
    """Forget the cached secret and replay store (tests only)."""
    global _secret_cache, _used
    with _lock:
        _secret_cache = None
        _used = None
