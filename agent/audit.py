"""
Append-only audit log for the agent.

Every action the agent takes — and every action it is *refused* — is written
here as one JSON object per line, so there is a durable record of what ran on
this machine and why. Without it, "the agent did something while I was away"
cannot be verified after the fact.

Storage: memory/audit_log.jsonl (gitignored runtime data).
"""

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

    try:
        with _lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
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
    with _lock:
        try:
            LOG_PATH.write_text("", encoding="utf-8")
        except Exception:
            pass
    print("[Audit] 🧹 Audit log cleared")
