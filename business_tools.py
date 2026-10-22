"""
J.A.R.V.I.S. — Business Tools Module
Calendar, GitHub, Mood Music, Document Scanner, Meetings, Code Review, Health, Expenses
"""

import copy
import json
import time
import threading
import base64
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from threading import RLock

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "business_data.json"
_lock = RLock()

_DEFAULT = {
    "calendar": [],
    "github": {"repos": [], "issues": [], "prs": []},
    "mood_music": [],
    "scanned_docs": [],
    "meetings": [],
    "code_reviews": [],
    "health": {"water": 0, "breaks": 0, "last_break": None},
    "expenses": [],
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


def _load_data() -> dict:
    data = copy.deepcopy(_DEFAULT)
    with _lock:
        if not DATA_PATH.exists():
            return data
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _deep_merge(data, loaded)
            return data
        except Exception:
            return copy.deepcopy(_DEFAULT)


def _save_data(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# === Calendar Management ===

@_locked
def add_event(title: str, date: str, time: str, description: str = "") -> dict:
    data = _load_data()
    event = {
        "id": f"evt_{len(data['calendar']) + 1}",
        "title": title,
        "date": date,
        "time": time,
        "description": description,
        "created": datetime.now().isoformat(),
    }
    data["calendar"].append(event)
    _save_data(data)
    return event


def get_events(date: str = None) -> list:
    data = _load_data()
    if date:
        return [e for e in data["calendar"] if e["date"] == date]
    return data["calendar"]


def get_today_events() -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    return get_events(today)


@_locked
def delete_event(event_id: str) -> bool:
    data = _load_data()
    for i, e in enumerate(data["calendar"]):
        if e["id"] == event_id:
            data["calendar"].pop(i)
            _save_data(data)
            return True
    return False


# === GitHub Integration ===

@_locked
def add_github_repo(name: str, url: str, description: str = "") -> dict:
    data = _load_data()
    repo = {
        "id": f"repo_{len(data['github']['repos']) + 1}",
        "name": name,
        "url": url,
        "description": description,
        "added": datetime.now().isoformat(),
    }
    data["github"]["repos"].append(repo)
    _save_data(data)
    return repo


def get_github_repos() -> list:
    data = _load_data()
    return data["github"]["repos"]


@_locked
def log_github_issue(repo: str, title: str, status: str = "open") -> dict:
    data = _load_data()
    issue = {
        "id": f"issue_{len(data['github']['issues']) + 1}",
        "repo": repo,
        "title": title,
        "status": status,
        "logged": datetime.now().isoformat(),
    }
    data["github"]["issues"].append(issue)
    _save_data(data)
    return issue


def get_github_issues(status: str = None) -> list:
    data = _load_data()
    if status:
        return [i for i in data["github"]["issues"] if i["status"] == status]
    return data["github"]["issues"]


# === Mood-Based Music ===

MOOD_PLAYLISTS = {
    "happy": ["Happy - Pharrell Williams", "Can't Stop - Red Hot Chili Peppers", "Good Vibrations - Beach Boys"],
    "sad": ["Someone Like You - Adele", "Fix You - Coldplay", "The Sound of Silence - Simon & Garfunkel"],
    "stressed": ["Weightless - Marconi Union", "Clair de Lune - Debussy", "River Flows in You - Yiruma"],
    "excited": ["Uptown Funk - Bruno Mars", "Eye of the Tiger - Survivor", "Don't Stop Me Now - Queen"],
    "focused": ["Lo-Fi Hip Hop", "Brain Food - Luminary", "Study Lounge - Spotify"],
    "neutral": ["Imagine - John Lennon", "Hotel California - Eagles", "Bohemian Rhapsody - Queen"],
}


def get_mood_playlist(mood: str) -> list:
    mood = mood.lower().strip()
    return MOOD_PLAYLISTS.get(mood, MOOD_PLAYLISTS["neutral"])


@_locked
def log_mood_music(mood: str, song: str) -> dict:
    data = _load_data()
    entry = {
        "mood": mood,
        "song": song,
        "played_at": datetime.now().isoformat(),
    }
    data["mood_music"].append(entry)
    _save_data(data)
    return entry


# === Document Scanner ===

@_locked
def scan_document(image_path: str) -> dict:
    try:
        from PIL import Image
        import pytesseract
        import hashlib

        try:
            raw = open(image_path, "rb").read()
            ch = hashlib.sha256(raw).hexdigest()
        except Exception:
            ch = hashlib.sha256(str(image_path).encode("utf-8")).hexdigest()
        try:
            from agent import ocr_cache

            cached = ocr_cache.get("document", ch)
            if cached:
                return {"status": "ok", "cached": True, **cached}
        except Exception:
            pass

        img = Image.open(image_path)
        text = pytesseract.image_to_string(img)

        data = _load_data()
        doc = {
            "id": f"doc_{len(data['scanned_docs']) + 1}",
            "path": image_path,
            "text": text[:2000],
            "scanned_at": datetime.now().isoformat(),
        }
        data["scanned_docs"].append(doc)
        _save_data(data)
        try:
            from agent import ocr_cache

            ocr_cache.put("document", ch, doc)
        except Exception:
            pass
        return doc
    except Exception as e:
        return {"error": str(e), "text": ""}


def get_scanned_documents() -> list:
    data = _load_data()
    return data["scanned_docs"]


# === Meeting Scheduler ===

@_locked
def schedule_meeting(title: str, date: str, time: str, attendees: list, duration_min: int = 30) -> dict:
    data = _load_data()
    meeting = {
        "id": f"mtg_{len(data['meetings']) + 1}",
        "title": title,
        "date": date,
        "time": time,
        "attendees": attendees,
        "duration": duration_min,
        "status": "scheduled",
        "created": datetime.now().isoformat(),
    }
    data["meetings"].append(meeting)
    _save_data(data)
    return meeting


def get_meetings(date: str = None) -> list:
    data = _load_data()
    if date:
        return [m for m in data["meetings"] if m["date"] == date]
    return data["meetings"]


# === Code Review Assistant ===

@_locked
def review_code(code: str, language: str = "python") -> dict:
    issues = []
    suggestions = []

    lines = code.split("\n")

    if language == "python":
        if "import os" in code and "os.system" in code:
            issues.append("Avoid os.system() — use subprocess instead for security.")

        if "except:" in code and "except Exception" not in code:
            issues.append("Bare except clause — specify exception type.")

        if "print(" in code and "logging" not in code:
            suggestions.append("Consider using logging instead of print statements.")

        if len(lines) > 50:
            suggestions.append("File is getting long — consider splitting into modules.")

        if "TODO" in code or "FIXME" in code:
            issues.append("Found TODO/FIXME comments — complete or remove them.")

    elif language == "javascript":
        if "==" in code and "===" not in code:
            issues.append("Use === instead of == for strict comparison.")
        if "var " in code:
            issues.append("Use let/const instead of var.")
        if "console.log" in code:
            suggestions.append("Remove console.log statements before production.")

    if not code.strip():
        return {"score": 0, "issues": ["Empty code block"], "suggestions": []}

    score = 100 - len(issues) * 15 - len(suggestions) * 5
    score = max(0, min(100, score))

    data = _load_data()
    review = {
        "id": f"cr_{len(data['code_reviews']) + 1}",
        "language": language,
        "score": score,
        "issues": issues,
        "suggestions": suggestions,
        "reviewed_at": datetime.now().isoformat(),
    }
    data["code_reviews"].append(review)
    _save_data(data)
    return review


def get_code_reviews() -> list:
    data = _load_data()
    return data["code_reviews"]


# === Health Tracker ===

@_locked
def log_water(ml: int = 250) -> dict:
    data = _load_data()
    today = datetime.now().strftime("%Y-%m-%d")

    if not data["health"].get("last_water_date") == today:
        data["health"]["water"] = 0
        data["health"]["last_water_date"] = today

    try:
        amount = int(float(ml))
    except (TypeError, ValueError):
        amount = 0
    data["health"]["water"] = int(data["health"].get("water") or 0) + amount
    _save_data(data)
    return {"water_today_ml": data["health"]["water"], "goal_ml": 2500}


@_locked
def log_break() -> dict:
    data = _load_data()
    data["health"]["breaks"] += 1
    data["health"]["last_break"] = datetime.now().isoformat()
    _save_data(data)
    return {"breaks_today": data["health"]["breaks"]}


@_locked
def get_health_summary() -> dict:
    data = _load_data()
    today = datetime.now().strftime("%Y-%m-%d")

    if data["health"].get("last_water_date") != today:
        data["health"]["water"] = 0
        data["health"]["breaks"] = 0
        data["health"]["last_water_date"] = today
        _save_data(data)

    water = data["health"]["water"]
    breaks = data["health"]["breaks"]

    return {
        "water_today_ml": water,
        "water_goal_ml": 2500,
        "water_percentage": min(100, int(water / 2500 * 100)),
        "breaks_today": breaks,
        "recommended_breaks": 8,
        "last_break": data["health"].get("last_break"),
    }


# === Expense Tracker ===

@_locked
def log_expense(amount: float, category: str, description: str = "") -> dict:
    data = _load_data()
    expense = {
        "id": f"exp_{len(data['expenses']) + 1}",
        "amount": amount,
        "category": category,
        "description": description,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "logged_at": datetime.now().isoformat(),
    }
    data["expenses"].append(expense)
    _save_data(data)
    return expense


def get_expenses(date: str = None, category: str = None) -> list:
    data = _load_data()
    expenses = data["expenses"]
    if date:
        expenses = [e for e in expenses if e["date"] == date]
    if category:
        expenses = [e for e in expenses if e["category"] == category]
    return expenses


def get_expense_summary() -> dict:
    data = _load_data()
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")

    today_expenses = [e for e in data["expenses"] if e["date"] == today]
    month_expenses = [e for e in data["expenses"] if e["date"].startswith(month)]

    total_today = sum(e["amount"] for e in today_expenses)
    total_month = sum(e["amount"] for e in month_expenses)

    by_category = {}
    for e in month_expenses:
        by_category[e["category"]] = by_category.get(e["category"], 0) + e["amount"]

    return {
        "today_total": total_today,
        "month_total": total_month,
        "today_count": len(today_expenses),
        "month_count": len(month_expenses),
        "by_category": by_category,
    }


def get_dashboard() -> dict:
    """Combined dashboard for all business tools."""
    health = get_health_summary()
    expenses = get_expense_summary()
    calendar = get_today_events()
    meetings = get_meetings()
    issues = get_github_issues("open")

    today = datetime.now().strftime("%Y-%m-%d")
    upcoming = [m for m in meetings if str(m.get("date", "")) >= today]

    return {
        "generated_at": datetime.now().isoformat(),
        "health": health,
        "expenses": expenses,
        "calendar_today": len(calendar),
        "upcoming_meetings": len(upcoming),
        "open_issues": len(issues),
    }
