"""Backup and restore of runtime state (Tier 2 D4 / H4).

"One command to export/import all runtime state." The state that matters is not
the code — it is the memory, the audit log, the approval key, the policy, the
local config and the task journal. This module bundles exactly those into a
single zip and can put them back.

Secrets are opt-in: ``include_secrets=False`` (the default) means a backup can
be shared or stored in cloud storage without leaking API keys.
"""

from __future__ import annotations

import json
import sys
import time
import zipfile
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()

# Files and directories that make up "runtime state".
STATE_FILES = (
    "memory/long_term.json",
    "memory/memories.json",
    "memory/procedural_memory.json",
    "memory/agent_tasks.json",
    "memory/audit_log.jsonl",
    "memory/approval.key",
    "memory/approval_used.json",
    "memory/jarvis.db",
    "voice_profiles.json",
    "business_data.json",
    "enterprise_data.json",
    "work_data.json",
    "life_data.json",
    "notifications.json",
    "alert_log.json",
    "startup_data.json",
    "companion_experiences.json",
    "companion_mood.json",
    "config/autonomy.json",
    "core/prompt.txt",
)

SECRET_FILES = (
    "config/api_keys.json",
    "config/email_config.json",
    "config/spotify_config.json",
    "config/alert_config.json",
    "config/audio.json",
)

MANIFEST_NAME = "manifest.json"


def _iter_paths(include_secrets: bool):
    for rel in STATE_FILES:
        yield rel, False
    if include_secrets:
        for rel in SECRET_FILES:
            yield rel, True


def export_backup(destination, *, include_secrets: bool = False) -> dict:
    """Write a zip of the runtime state. Returns a manifest dict."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    missing: list[str] = []

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, _is_secret in _iter_paths(include_secrets):
            src = BASE_DIR / rel
            if not src.exists():
                missing.append(rel)
                continue
            zf.write(src, rel)
            included.append(rel)
        manifest = {
            "created_at": time.time(),
            "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "base_dir": str(BASE_DIR),
            "include_secrets": bool(include_secrets),
            "included": included,
            "missing": missing,
            "version": 1,
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
    return manifest


def read_manifest(archive) -> dict:
    with zipfile.ZipFile(archive, "r") as zf:
        try:
            return json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except KeyError:
            return {"version": 0, "included": zf.namelist()}


def restore_backup(archive, *, overwrite: bool = True) -> dict:
    """Extract a backup over the current state.

    Members are validated: only paths that appear in the state or secret lists
    are written, so a crafted archive cannot drop files elsewhere.
    """
    allowed = set(STATE_FILES) | set(SECRET_FILES)
    restored: list[str] = []
    skipped: list[str] = []

    with zipfile.ZipFile(archive, "r") as zf:
        for member in zf.namelist():
            if member == MANIFEST_NAME:
                continue
            norm = member.replace("\\", "/")
            if norm not in allowed:
                skipped.append(member)
                continue
            target = BASE_DIR / norm
            if target.exists() and not overwrite:
                skipped.append(member)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src:
                target.write_bytes(src.read())
            restored.append(norm)
    return {"restored": restored, "skipped": skipped}


def _cli(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("export", "restore", "info"):
        print("usage: python -m memory.backup export|restore|info [path] [--with-secrets]")
        return 2
    command = argv[0]
    with_secrets = "--with-secrets" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]

    if command == "export":
        dest = Path(args[0]) if args else (BASE_DIR / "memory" / "backups" /
                                          f"jarvis-{time.strftime('%Y%m%d-%H%M%S')}.zip")
        manifest = export_backup(dest, include_secrets=with_secrets)
        print(f"Exported {len(manifest['included'])} file(s) to {dest}")
        if manifest["missing"]:
            print(f"  ({len(manifest['missing'])} not present, skipped)")
        return 0
    if command == "restore":
        if not args:
            print("restore needs an archive path")
            return 2
        result = restore_backup(args[0])
        print(f"Restored {len(result['restored'])} file(s); skipped {len(result['skipped'])}")
        return 0
    if command == "info":
        if not args:
            print("info needs an archive path")
            return 2
        print(json.dumps(read_manifest(args[0]), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
