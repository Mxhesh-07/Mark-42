"""Tier 2 H4 — subject controls: forget, export, and see what is held.

`D5` gave the assistant a single "forget everything" that emptied the SQLite
memory table. That is one of **eight** places a fact about the user survives:

    memory/jarvis.db            durable memories (SQLite)
    memory/long_term.json       the distilled profile
    memory/memories.json        AIMemory - preferences, projects, notes
    memory/procedural_memory.json  learned procedures
    memory/agent_tasks.json     queued work
    memory/self.json            what the assistant observed about itself
    memory/quota_ledger.json    which models you used, and when
    voice_profiles.json         your voiceprint - biometric
    companion_experiences.json  shared history
    notifications.json          subjects and senders of mail
    memory/crashes/*.json       crash bundles, which contain prompt text
    memory/audit_log.jsonl      every gated action, with details

A control that clears one of them and says "done" is worse than none: it teaches
the user that their data is gone when it is not. So "forget everything about me"
here means *everything*, and `inventory()` is the honest receipt of what was
there — a dry run prints exactly the same numbers that the real thing removes.

What is deliberately **not** touched: `config/*.json` credentials and
`memory/approval.key`. Those are not personal data, and deleting them would not
forget a person — it would break the assistant and, in the key's case, invalidate
the signed approvals that make the permission gate work. `inventory()` lists them
as "kept" so the boundary is visible rather than implied.

The audit log is the one store with a rule of its own. Deleting it is a real
thing users are entitled to do, and an audit log that cannot be deleted is not a
subscription it is a trap. But deleting it silently would also erase the record
of the deletion. So the log is the *last* thing cleared, and the tombstone is
written immediately after — the first entry of the new log says the old one was
wiped, when, and how many entries went. The chain restarts from that entry.

    python -m agent.forget                   # dry run: what is held
    python -m agent.forget --yes             # forget everything, keep the log
    python -m agent.forget --yes --audit     # and wipe the audit log too
    python -m agent.forget export [path]     # zip what is held
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

VERSION = 1

# The stores that hold something about the user or their machine.
FORGETTABLE = (
    "sql_memory", "long_term", "ai_memory", "procedural", "agent_tasks",
    "self_model", "quota_ledger", "voice_profiles", "companion", "notifications",
    "crashes", "audit_log",
)

# Kept on purpose - see the module docstring. `inventory()` still reports them so
# the user can see the line rather than guess where it is.
KEPT = (
    "config/*.json (credentials)",
    "memory/approval.key (approval signing key)",
)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()


def _store_path(name: str) -> Path:
    """Resolve a store's path *now*, so redirecting it in a test works.

    Reading the paths at import time would freeze them, and then a test that
    points a store somewhere disposable would silently exercise the real file.
    """
    from memory import memory_manager

    if name == "long_term":
        return Path(memory_manager.MEMORY_PATH)
    if name == "ai_memory":
        from memory import ai_memory

        return Path(ai_memory.BASE_DIR) / "memory" / "memories.json"
    if name == "procedural":
        return BASE_DIR / "memory" / "procedural_memory.json"
    if name == "agent_tasks":
        return BASE_DIR / "memory" / "agent_tasks.json"
    if name == "notifications":
        return BASE_DIR / "notifications.json"
    if name == "companion":
        return BASE_DIR / "companion_experiences.json"
    if name == "self_model":
        from core import self as self_model

        return Path(self_model.STATE_PATH)
    if name == "quota_ledger":
        from agent import quota

        return Path(quota.LEDGER_PATH)
    if name == "voice_profiles":
        from voice_id import PROFILES_PATH

        return Path(PROFILES_PATH)
    raise KeyError(name)


# --- inventory ------------------------------------------------------------------

def _json_count(path: Path) -> int:
    """Records in a JSON store.

    "Records" is the user-visible unit, not the top-level key count: the quota
    ledger is `{version, calls:[...]}`, and counting its keys would report 2 for
    an empty ledger and 3 for a full one. Where a store has an obvious record
    list, that list is counted instead.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        for key in ("calls", "entries", "records", "items", "memories"):
            value = raw.get(key)
            if isinstance(value, list):
                return len(value)
        return sum(len(v) for v in raw.values() if isinstance(v, list)) or (
            len(raw) if raw else 0)
    return 1 if raw else 0


def _crash_bundles() -> list[Path]:
    try:
        from agent import crash

        directory = Path(crash.CRASH_DIR)
    except Exception:
        directory = BASE_DIR / "memory" / "crashes"
    try:
        return sorted(directory.glob("*.json"))
    except OSError:
        return []


def _voiceprint_count() -> int:
    try:
        path = _store_path("voice_profiles")
    except Exception:
        path = BASE_DIR / "voice_profiles.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(raw, dict):
        return 0
    # Two shapes are in the wild: named people -> embeddings, and a map of
    # embeddings under one key. Count records, not keys, so the number means
    # "how many voiceprints are on file".
    if all(isinstance(v, list) for v in raw.values()) and raw and isinstance(
            next(iter(raw.values())), list) and raw and all(
                isinstance(x, (int, float)) for x in next(iter(raw.values()))):
        return 1
    return sum(len(v) for v in raw.values() if isinstance(v, list)) + sum(
        1 for v in raw.values() if not isinstance(v, list))


def _audit_entries() -> tuple[int, int]:
    """(entries, of-which-tombstones) in the audit log.

    A `forget` tombstone is the record of a deletion, not data about the user,
    so it is not counted as something to forget — otherwise the log would never
    read as empty and a second forget would claim to have removed something.
    """
    try:
        from agent import audit

        entries = audit.tail(100000)
    except Exception:
        return (0, 0)
    tombstones = sum(1 for e in entries if e.get("event") == "forget")
    return (len(entries), tombstones)


def inventory() -> dict:
    """What is held right now, per store. The dry run and the receipt agree."""
    from memory import sql_memory

    counts: dict[str, int] = {}
    try:
        counts["sql_memory"] = int(sql_memory.stats().get("total") or 0)
    except Exception:
        counts["sql_memory"] = 0

    for name in ("long_term", "ai_memory", "procedural", "agent_tasks",
                 "notifications", "companion", "self_model", "quota_ledger"):
        try:
            counts[name] = _json_count(_store_path(name))
        except Exception:
            counts[name] = 0

    try:
        counts["voice_profiles"] = _voiceprint_count()
    except Exception:
        counts["voice_profiles"] = 0

    counts["crashes"] = len(_crash_bundles())

    entries, tombstones = _audit_entries()
    counts["audit_log"] = max(0, entries - tombstones)

    return {
        "version": VERSION,
        "counts": {name: counts.get(name, 0) for name in FORGETTABLE},
        "total": sum(counts.get(name, 0) for name in FORGETTABLE),
        "kept": list(KEPT),
    }


# --- forgetting -----------------------------------------------------------------

def _clear_json(path: Path) -> int:
    """Empty a JSON store, keeping the file so its reader finds a valid shape."""
    if not path.exists():
        return 0
    before = _json_count(path)
    empty: object = [] if _read_is_list(path) else {}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(empty), encoding="utf-8")
    except OSError:
        return 0
    return before


def _read_is_list(path: Path) -> bool:
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), list)
    except Exception:
        return False


def _unlink_all(paths: list[Path]) -> int:
    removed = 0
    for path in paths:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def forget_all(*, include_audit: bool = True, include_voiceprints: bool = True) -> dict:
    """Forget everything about the user. Returns the same shape as `inventory()`.

    Order matters in one place: the audit log is cleared last and then written
    to, so the deletion is itself on the record.
    """
    before = inventory()
    removed: dict[str, int] = {}

    # 1. durable memories
    try:
        from memory import sql_memory

        removed["sql_memory"] = int(sql_memory.forget_all())
    except Exception:
        removed["sql_memory"] = 0

    # 2. the distilled profile, and the AIMemory store
    for name in ("long_term", "ai_memory", "procedural", "agent_tasks",
                 "notifications", "companion", "self_model"):
        try:
            removed[name] = _clear_json(_store_path(name))
        except Exception:
            removed[name] = 0

    # 3. the spend ledger - it is a record of the user's sessions. Not counted
    #    through `quota.clear()`'s return value: that call also writes a
    #    tombstone into the audit log, which is a different store.
    try:
        from agent import quota

        led = _store_path("quota_ledger")
        removed["quota_ledger"] = _json_count(led) if led.exists() else 0
        quota.clear()
    except Exception:
        removed["quota_ledger"] = 0

    # 4. the voiceprint. Biometric, and opt-out here rather than opt-in: a user
    #    asking to be forgotten is not asking to keep their voice on file.
    if include_voiceprints:
        try:
            profile = _store_path("voice_profiles")
            removed["voice_profiles"] = _clear_json(profile)
            _unlink_all([profile.with_suffix(".tmp")])
        except Exception:
            removed["voice_profiles"] = 0
    else:
        removed["voice_profiles"] = 0

    # 5. crash bundles - they quote the prompt that caused the fault
    removed["crashes"] = _unlink_all(_crash_bundles())

    # 6. the audit log, last
    if include_audit:
        from agent import audit

        entries, tombstones = _audit_entries()
        removed["audit_log"] = max(0, entries - tombstones)
        audit.clear()
        audit.record(
            "forget",
            outcome="audit cleared",
            detail=f"{removed['audit_log']} entries removed by the user",
        )
    else:
        removed["audit_log"] = 0

    after = inventory()
    return {
        "version": VERSION,
        "removed": removed,
        "before": before["counts"],
        "remaining": after["counts"],
        "total_removed": sum(removed.values()),
        "kept": list(KEPT),
        "audit_cleared": bool(include_audit),
        "voiceprints_cleared": bool(include_voiceprints),
    }


# --- export ---------------------------------------------------------------------

def export(destination=None, *, include_secrets: bool = False) -> dict:
    """Delegate to `memory.backup` so there is one archive format, not two.

    Credentials are excluded unless asked for: the point of the export is to
    hand the user *their* data, and a zip of API keys in a Downloads folder is
    how that goes wrong.
    """
    import time

    from memory import backup

    if destination is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        destination = BASE_DIR / "memory" / "backups" / f"export-{stamp}.zip"
    manifest = backup.export_backup(destination, include_secrets=include_secrets)
    manifest["path"] = str(destination)
    return manifest


# --- CLI ------------------------------------------------------------------------

_USAGE = (
    "usage: python -m agent.forget [--yes] [--keep-audit] [--keep-voiceprints]\n"
    "       python -m agent.forget export [destination]\n"
    "\n"
    "  (no arguments)   report what is held, change nothing\n"
    "  --yes            forget everything about you\n"
    "  --keep-audit     leave memory/audit_log.jsonl in place\n"
    "  --keep-voiceprints  leave voice_profiles.json in place\n"
)


def _render(inv: dict) -> str:
    lines = [f"held about you ({inv['total']} records):"]
    for name in FORGETTABLE:
        lines.append(f"  {name:<16} {inv['counts'][name]}")
    lines.append("kept:")
    for item in inv["kept"]:
        lines.append(f"  {item}")
    return "\n".join(lines)


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "export":
        result = export(argv[1] if len(argv) > 1 else None)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("path") else 1

    unknown = [a for a in argv if a not in
               ("--yes", "--keep-audit", "--keep-voiceprints")]
    if unknown:
        print(_USAGE)
        return 2

    if "--yes" not in argv:
        print(_render(inventory()))
        print("\nnothing was changed. add --yes to forget all of it.")
        return 0

    result = forget_all(include_audit="--keep-audit" not in argv,
                        include_voiceprints="--keep-voiceprints" not in argv)
    for name, count in result["removed"].items():
        if count:
            print(f"  forgot {name}: {count}")
    print(f"\nforgot {result['total_removed']} records.")
    if not result["audit_cleared"]:
        print("the audit log was kept (the record of this deletion is in it).")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
