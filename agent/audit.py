"""
Append-only audit log for the agent.

Every action the agent takes — and every action it is *refused* — is written
here as one JSON object per line, so there is a durable record of what ran on
this machine and why. Without it, "the agent did something while I was away"
cannot be verified after the fact.

Storage: memory/audit_log.jsonl (gitignored runtime data).
"""

import hashlib
import json
import sys
import threading
import time
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
LOG_PATH = BASE_DIR / "memory" / "audit_log.jsonl"

MAX_BYTES  = 5 * 1024 * 1024   # trim once the log grows past ~5 MB
KEEP_LINES = 2000              # ...keeping the most recent entries

_lock = threading.Lock()
_LAST_HASH = ""     # chain head; loaded from disk on first use


def _canonical(entry: dict) -> str:
    """Deterministic JSON of an entry, excluding its own hash."""
    body = {k: v for k, v in entry.items() if k != "hash"}
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _chain(entry: dict, prev: str) -> str:
    return hashlib.sha256((prev + _canonical(entry)).encode("utf-8")).hexdigest()


def _load_last_hash() -> str:
    """The hash of the newest entry already on disk ("" when there is none)."""
    global _LAST_HASH
    if _LAST_HASH:
        return _LAST_HASH
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        _LAST_HASH = str(entry.get("hash") or "")
        break
    return _LAST_HASH


def _trim_if_needed() -> None:
    try:
        if LOG_PATH.stat().st_size <= MAX_BYTES:
            return
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        LOG_PATH.write_text("\n".join(lines[-KEEP_LINES:]) + "\n", encoding="utf-8")
        print(f"[Audit] 🧹 Trimmed log to the last {KEEP_LINES} entries")
    except Exception as e:
        print(f"[Audit] ⚠️ Could not trim log: {e}")


def record(
    event: str,
    *,
    tool: str | None = None,
    parameters: dict | None = None,
    level: str | None = None,
    outcome: str | None = None,
    detail: str = "",
    task_id: str | None = None,
    goal: str | None = None,
) -> None:
    """
    Append one audit entry. Never raises — auditing must not break the agent.

    event   : "task_start" | "action" | "action_denied" | "task_end" | "kill"
    outcome : "ok" | "failed" | "denied" | "blocked" | ...
    """
    entry = {
        "ts":      time.time(),
        "time":    time.strftime("%Y-%m-%d %H:%M:%S"),
        "event":   event,
        "task_id": task_id,
    }
    if goal:
        entry["goal"] = str(goal)[:300]
    if tool:
        entry["tool"] = tool
    if parameters is not None:
        try:
            entry["parameters"] = json.loads(
                json.dumps(parameters, ensure_ascii=False, default=str)
            )
        except Exception:
            entry["parameters"] = str(parameters)[:500]
    if level:
        entry["level"] = level
    if outcome:
        entry["outcome"] = outcome
    if detail:
        entry["detail"] = str(detail)[:1000]

    global _LAST_HASH
    try:
        with _lock:
            prev = _load_last_hash()
            entry["prev"] = prev
            entry["hash"] = _chain(entry, prev)
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _LAST_HASH = entry["hash"]
            _trim_if_needed()
    except Exception as e:
        print(f"[Audit] ⚠️ Could not write audit entry: {e}")


def tail(n: int = 50) -> list[dict]:
    """Return the last n audit entries (newest last)."""
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[Audit] ⚠️ Could not read log: {e}")
        return []

    out = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def path() -> str:
    return str(LOG_PATH)


def clear() -> None:
    """Wipe the log (maintenance/testing only)."""
    global _LAST_HASH
    with _lock:
        try:
            LOG_PATH.write_text("", encoding="utf-8")
        except Exception:
            pass
        _LAST_HASH = ""
    print("[Audit] 🧹 Audit log cleared")


def verify() -> tuple[bool, str]:
    """Recompute the hash chain and report the first problem, if any.

    Each entry stores ``prev`` (the previous entry's hash) and its own ``hash``,
    so any later edit, reorder or deletion shows up as a broken chain. The first
    entry of the file is the chain start and is not checked against a
    predecessor - that also covers logs trimmed to their most recent lines.
    """
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return True, "no audit log yet"
    except Exception as e:
        return False, f"could not read the log: {e}"

    prev: str | None = None
    checked = 0
    legacy = 0
    for num, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            return False, f"line {num} is not valid JSON"
        if not isinstance(entry, dict) or "hash" not in entry:
            legacy += 1
            continue
        if prev is not None and entry.get("prev") != prev:
            return False, f"line {num}: chain break (prev does not match the previous entry)"
        if _chain(entry, entry.get("prev") or "") != entry["hash"]:
            return False, f"line {num}: contents changed after the entry was written"
        prev = entry["hash"]
        checked += 1

    msg = f"{checked} entries verified"
    if legacy:
        msg += f" ({legacy} pre-chain entries skipped)"
    return True, msg


def _cli(argv: list[str]) -> int:
    cmd = (argv[0] if argv else "verify").lower()
    if cmd == "verify":
        ok, msg = verify()
        print(("✅ audit chain intact: " if ok else "❌ audit chain BROKEN: ") + msg)
        return 0 if ok else 1
    if cmd == "tail":
        n = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 20
        for e in tail(n):
            print(f"  {e.get('time', '')}  {e.get('event', '')}  {e.get('tool', '') or ''}")
        return 0
    print("usage: python -m agent.audit [verify|tail [n]]")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
