"""
Persistent task state for the agent queue.

The task queue is in-memory, so a crash or a Ctrl-C in the middle of a task
lost it silently. This module writes task records (goal, status, result, error
and an action journal) to disk and reads them back on startup, so an
interrupted task can be resumed instead of vanishing.

Storage: memory/agent_tasks.json (gitignored runtime data).
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


BASE_DIR   = get_base_dir()
STORE_PATH = BASE_DIR / "memory" / "agent_tasks.json"

MAX_RECORDS   = 200                 # keep the file bounded
MAX_JOURNAL   = 60                  # max journal entries kept per task
RESTORE_MAX_AGE_S = 24 * 60 * 60    # only resume tasks younger than this

_lock = threading.Lock()


def _empty() -> dict:
    return {"tasks": {}, "version": 1}


def _load() -> dict:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), dict):
            return _empty()
        return data
    except FileNotFoundError:
        return _empty()
    except Exception as e:
        print(f"[TaskStore] ⚠️ Could not read store ({e}) — starting fresh")
        return _empty()


def _save(data: dict) -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Bound the file: keep the newest MAX_RECORDS tasks.
        tasks = data.get("tasks", {})
        if len(tasks) > MAX_RECORDS:
            ordered = sorted(
                tasks.items(),
                key=lambda kv: kv[1].get("updated", 0),
                reverse=True,
            )[:MAX_RECORDS]
            data["tasks"] = dict(ordered)

        tmp = STORE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(STORE_PATH)
    except Exception as e:
        print(f"[TaskStore] ⚠️ Could not save store: {e}")


# --- public API ---------------------------------------------------------------

def upsert(task_id: str, **fields) -> None:
    """Create or update a task record."""
    if not task_id:
        return
    with _lock:
        data = _load()
        rec = data["tasks"].get(task_id, {"task_id": task_id, "created": time.time()})
        rec.update(fields)
        rec["updated"] = time.time()
        data["tasks"][task_id] = rec
        _save(data)


def set_status(task_id: str, status: str, **fields) -> None:
    upsert(task_id, status=status, **fields)


def append_journal(task_id: str, entry: dict) -> None:
    """Append one step (action + observation) to a task's live journal."""
    if not task_id:
        return
    with _lock:
        data = _load()
        rec = data["tasks"].get(task_id)
        if rec is None:
            # Callers other than the task queue also journal (e.g. a run started
            # directly), so create the record on first write instead of dropping
            # the entry.
            rec = {"task_id": task_id, "created": time.time(), "status": "running"}
            data["tasks"][task_id] = rec
        journal = rec.setdefault("journal", [])
        entry = dict(entry)
        entry["at"] = time.time()
        journal.append(entry)
        if len(journal) > MAX_JOURNAL:
            del journal[:-MAX_JOURNAL]
        rec["updated"] = time.time()
        _save(data)


def get(task_id: str) -> dict | None:
    with _lock:
        return _load()["tasks"].get(task_id)


def all_tasks() -> list[dict]:
    with _lock:
        return list(_load()["tasks"].values())


def resumable(max_age_s: int = RESTORE_MAX_AGE_S) -> list[dict]:
    """
    Tasks that were pending or running when the process stopped, and are young
    enough to be worth resuming. Oldest first, so order is preserved.
    """
    now = time.time()
    out = []
    for rec in all_tasks():
        if rec.get("status") not in ("pending", "running"):
            continue
        if now - rec.get("updated", now) > max_age_s:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("created", 0))
    return out


def mark_interrupted(task_id: str) -> None:
    """Flag a resumed task so it is not silently re-run forever."""
    rec = get(task_id) or {}
    upsert(task_id, resumes=rec.get("resumes", 0) + 1, status="pending")


def clear(task_id: str) -> None:
    with _lock:
        data = _load()
        data["tasks"].pop(task_id, None)
        _save(data)
