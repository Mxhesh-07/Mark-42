"""
J.A.R.V.I.S. — Work Assistant Module
Emails, documents, meetings, coding, and task management.
"""

import copy
import json
import subprocess
import tempfile
import os
from functools import wraps
from pathlib import Path
from datetime import datetime
from threading import RLock

BASE_DIR = Path(__file__).resolve().parent
WORK_PATH = BASE_DIR / "work_data.json"
_lock = RLock()

_DEFAULT = {
    "tasks": [],
    "meetings": [],
    "email_drafts": [],
    "code_snippets": [],
    "documents": [],
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively overlay non-default keys/values onto a default structure."""
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _locked(fn):
    """Hold the module lock across a full load→modify→save mutation."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper


def _load_work_data() -> dict:
    data = copy.deepcopy(_DEFAULT)
    with _lock:
        if not WORK_PATH.exists():
            return data
        try:
            with open(WORK_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _deep_merge(data, loaded)
            return data
        except Exception:
            return copy.deepcopy(_DEFAULT)


def _save_work_data(data: dict) -> None:
    WORK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(WORK_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


@_locked
def add_task(title: str, priority: str = "normal", due: str = None) -> dict:
    data = _load_work_data()
    task = {
        "id": f"task_{len(data['tasks']) + 1}",
        "title": title,
        "priority": priority,
        "due": due,
        "status": "pending",
        "created": datetime.now().isoformat(),
    }
    data["tasks"].append(task)
    _save_work_data(data)
    return task


@_locked
def complete_task(task_id: str) -> bool:
    data = _load_work_data()
    for task in data["tasks"]:
        if task["id"] == task_id or task["title"].lower() == str(task_id).lower():
            task["status"] = "completed"
            task["completed_at"] = datetime.now().isoformat()
            _save_work_data(data)
            return True
    return False


def get_pending_tasks() -> list:
    data = _load_work_data()
    return [t for t in data["tasks"] if t["status"] != "completed"]


def get_tasks_by_priority(priority: str) -> list:
    data = _load_work_data()
    return [t for t in data["tasks"] if t["priority"] == priority and t["status"] != "completed"]


@_locked
def save_meeting_notes(title: str, notes: str, action_items: list = None) -> dict:
    data = _load_work_data()
    meeting = {
        "id": f"mtg_{len(data['meetings']) + 1}",
        "title": title,
        "notes": notes,
        "action_items": action_items or [],
        "date": datetime.now().isoformat(),
    }
    data["meetings"].append(meeting)
    _save_work_data(data)
    return meeting


@_locked
def draft_email(to: str, subject: str, body: str) -> dict:
    data = _load_work_data()
    draft = {
        "id": f"email_{len(data['email_drafts']) + 1}",
        "to": to,
        "subject": subject,
        "body": body,
        "status": "draft",
        "created": datetime.now().isoformat(),
    }
    data["email_drafts"].append(draft)
    _save_work_data(data)
    return draft


def get_email_drafts() -> list:
    data = _load_work_data()
    return data["email_drafts"]


@_locked
def save_code_snippet(title: str, description: str = "", code: str = "", language: str = "python") -> dict:
    data = _load_work_data()
    snippet = {
        "id": f"code_{len(data['code_snippets']) + 1}",
        "title": title,
        "description": description,
        "code": code,
        "language": language,
        "created": datetime.now().isoformat(),
    }
    data["code_snippets"].append(snippet)
    _save_work_data(data)
    return snippet


def get_code_snippets() -> list:
    data = _load_work_data()
    return data["code_snippets"]


@_locked
def save_document(title: str, content: str, doc_type: str = "note") -> dict:
    data = _load_work_data()
    doc = {
        "id": f"doc_{len(data['documents']) + 1}",
        "title": title,
        "content": content,
        "type": doc_type,
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat(),
    }
    data["documents"].append(doc)
    _save_work_data(data)
    return doc


def get_documents() -> list:
    data = _load_work_data()
    return data["documents"]


def daily_briefing() -> dict:
    """Generate daily work briefing."""
    data = _load_work_data()
    pending = get_pending_tasks()
    high_priority = [t for t in pending if t["priority"] == "high"]
    meetings_today = [m for m in data["meetings"] if m["date"][:10] == datetime.now().strftime("%Y-%m-%d")]
    drafts = [e for e in data["email_drafts"] if e["status"] == "draft"]

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_pending_tasks": len(pending),
        "high_priority_tasks": len(high_priority),
        "meetings_today": len(meetings_today),
        "pending_emails": len(drafts),
        "high_priority_list": high_priority[:5],
        "pending_list": pending[:10],
    }


def weekly_summary() -> dict:
    """Generate weekly work summary."""
    data = _load_work_data()
    now = datetime.now()
    week_ago = now.timestamp() - 7 * 86400

    completed_this_week = [
        t for t in data["tasks"]
        if t.get("completed_at") and datetime.fromisoformat(t["completed_at"]).timestamp() > week_ago
    ]
    pending = get_pending_tasks()
    meetings_this_week = [
        m for m in data["meetings"]
        if datetime.fromisoformat(m["date"]).timestamp() > week_ago
    ]

    return {
        "week_of": now.strftime("%Y-%m-%d"),
        "tasks_completed": len(completed_this_week),
        "tasks_pending": len(pending),
        "meetings_this_week": len(meetings_this_week),
        "completion_rate": len(completed_this_week) / max(len(completed_this_week) + len(pending), 1) * 100,
    }
