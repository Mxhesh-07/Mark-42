"""
J.A.R.V.I.S. — Life Tools Module
Habit tracker, focus/Pomodoro, knowledge base, meeting recorder,
daily routine scheduler, and finance / net-worth dashboard.
"""

import json
import re
import time
import threading
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta, date
from collections import Counter
from threading import RLock

BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "life_data.json"
_lock = RLock()

_routine_running = False
_routine_thread = None

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "we", "i",
    "you", "they", "he", "she", "at", "as", "by", "so", "if", "then", "than",
    "will", "would", "can", "could", "should", "have", "has", "had", "do", "does",
    "our", "us", "my", "me", "your", "their", "them", "not", "no", "yes", "ok",
}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _default_data() -> dict:
    return {
        "habits": [],
        "focus_sessions": [],
        "active_focus": None,
        "notes": [],
        "links": [],
        "recordings": [],
        "active_recording": None,
        "routines": [],
        "routine_alerts": [],
        "income": [],
        "invoices": [],
        "assets": [],
        "liabilities": [],
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
    base = _default_data()
    with _lock:
        if not DATA_PATH.exists():
            return base
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _deep_merge(base, data)
            return base
        except Exception:
            return _default_data()


def _save_data(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def _next_id(items: list, prefix: str) -> str:
    return f"{prefix}_{len(items) + 1}"


# ============================================================
# 1) HABIT TRACKER + STREAKS
# ============================================================

def _streaks(dates: list) -> tuple:
    """Return (current_streak, best_streak) from a list of YYYY-MM-DD strings."""
    ds = set(dates)
    if not ds:
        return 0, 0

    today = datetime.now().date()
    d = today
    if d.isoformat() not in ds:
        d = today - timedelta(days=1)
    current = 0
    while d.isoformat() in ds:
        current += 1
        d -= timedelta(days=1)

    ordered = sorted(datetime.strptime(x, "%Y-%m-%d").date() for x in ds)
    best = 1
    run = 1
    for i in range(1, len(ordered)):
        if (ordered[i] - ordered[i - 1]).days == 1:
            run += 1
        else:
            run = 1
        best = max(best, run)

    return current, best


def _habit_view(h: dict) -> dict:
    log = h.get("log", [])
    current, best = _streaks(log)
    week_start = (datetime.now().date() - timedelta(days=6)).isoformat()
    this_week = len([d for d in log if d >= week_start])
    done_today = _today() in log
    return {
        **h,
        "streak": current,
        "best_streak": max(best, h.get("best_streak", 0)),
        "done_today": done_today,
        "this_week": this_week,
        "total": len(log),
    }


@_locked
def add_habit(name: str, frequency: str = "daily", target_per_week: int = 7) -> dict:
    data = _load_data()
    name = (name or "").strip()
    for h in data["habits"]:
        if h["name"].lower() == name.lower():
            return _habit_view(h)
    habit = {
        "id": _next_id(data["habits"], "habit"),
        "name": name,
        "frequency": frequency or "daily",
        "target_per_week": int(target_per_week or 7),
        "log": [],
        "best_streak": 0,
        "created": datetime.now().isoformat(),
    }
    data["habits"].append(habit)
    _save_data(data)
    return _habit_view(habit)


@_locked
def log_habit(name: str) -> dict:
    data = _load_data()
    key = (name or "").strip().lower()
    for h in data["habits"]:
        if h["name"].lower() == key or h["id"] == name:
            if _today() not in h["log"]:
                h["log"].append(_today())
            view = _habit_view(h)
            h["best_streak"] = max(h.get("best_streak", 0), view["streak"])
            _save_data(data)
            return view
    # Auto-create if it doesn't exist
    return log_habit(add_habit(name)["name"])


def get_habits() -> list:
    data = _load_data()
    return [_habit_view(h) for h in data["habits"]]


def habit_status(name: str):
    key = (name or "").strip().lower()
    for h in get_habits():
        if h["name"].lower() == key or h["id"] == name:
            return h
    return None


def habits_at_risk() -> list:
    """Habits not yet done today (about to break the streak)."""
    return [h for h in get_habits() if not h["done_today"]]


# ============================================================
# 2) FOCUS MODE / POMODORO
# ============================================================

@_locked
def start_focus(task: str = "", minutes: int = 25) -> dict:
    data = _load_data()
    session = {
        "task": task or "Deep work",
        "minutes": int(minutes or 25),
        "started": datetime.now().isoformat(),
    }
    data["active_focus"] = session
    _save_data(data)
    return {"status": "started", **session}


@_locked
def end_focus() -> dict:
    data = _load_data()
    active = data.get("active_focus")
    if not active:
        return {"status": "none", "message": "No focus session running."}

    started = datetime.fromisoformat(active["started"])
    elapsed = (datetime.now() - started).total_seconds() / 60.0
    session = {
        "id": _next_id(data["focus_sessions"], "focus"),
        "task": active["task"],
        "planned_minutes": active["minutes"],
        "actual_minutes": round(elapsed, 1),
        "started": active["started"],
        "ended": datetime.now().isoformat(),
        "date": _today(),
    }
    data["focus_sessions"].append(session)
    data["active_focus"] = None
    _save_data(data)

    # Integrate with the health tracker: log a break after focusing.
    try:
        from business_tools import log_break
        log_break()
    except Exception:
        pass

    return {
        "status": "ended",
        "task": session["task"],
        "minutes": session["actual_minutes"],
        "message": f"Focus session ended — {session['actual_minutes']} minutes on {session['task']}. Take a break.",
    }


def get_focus_stats() -> dict:
    data = _load_data()
    sessions = data["focus_sessions"]
    today = _today()
    week_start = (datetime.now().date() - timedelta(days=6)).isoformat()

    today_min = sum(s["actual_minutes"] for s in sessions if s["date"] == today)
    week_min = sum(s["actual_minutes"] for s in sessions if s["date"] >= week_start)
    active = data.get("active_focus")

    return {
        "active": active,
        "sessions_today": len([s for s in sessions if s["date"] == today]),
        "minutes_today": round(today_min, 1),
        "sessions_week": len([s for s in sessions if s["date"] >= week_start]),
        "minutes_week": round(week_min, 1),
    }


def focus_report() -> str:
    s = get_focus_stats()
    if s["active"]:
        started = datetime.fromisoformat(s["active"]["started"])
        mins = round((datetime.now() - started).total_seconds() / 60.0, 1)
        state = f"Currently focusing on '{s['active']['task']}' for {mins} min."
    else:
        state = "No active session."
    return (
        f"Focus report: {state} Today {s['minutes_today']} min across {s['sessions_today']} sessions; "
        f"this week {s['minutes_week']} min across {s['sessions_week']} sessions."
    )


# ============================================================
# 3) KNOWLEDGE BASE / SECOND BRAIN
# ============================================================

@_locked
def save_note(title: str, content: str, tags: list = None) -> dict:
    data = _load_data()
    note = {
        "id": _next_id(data["notes"], "note"),
        "title": (title or "").strip() or (content or "")[:40],
        "content": content or "",
        "tags": [t.strip().lower() for t in (tags or [])],
        "created": datetime.now().isoformat(),
    }
    data["notes"].append(note)
    _save_data(data)
    return note


def get_notes(tag: str = None) -> list:
    data = _load_data()
    notes = data["notes"]
    if tag:
        t = tag.strip().lower()
        notes = [n for n in notes if t in n.get("tags", [])]
    return list(reversed(notes))


def search_notes(query: str) -> list:
    data = _load_data()
    q = (query or "").strip().lower()
    if not q:
        return []
    terms = [t for t in re.split(r"\s+", q) if t]
    results = []
    for n in data["notes"] + data["links"]:
        haystack = f"{n.get('title','')} {n.get('content','')} {n.get('url','')} {' '.join(n.get('tags', []))}".lower()
        if all(term in haystack for term in terms):
            results.append(n)
    return list(reversed(results))


@_locked
def delete_note(identifier: str) -> bool:
    data = _load_data()
    for i, n in enumerate(data["notes"]):
        if n["id"] == identifier or n["title"].lower() == (identifier or "").strip().lower():
            data["notes"].pop(i)
            _save_data(data)
            return True
    return False


@_locked
def save_link(url: str, title: str = "", tags: list = None) -> dict:
    data = _load_data()
    link = {
        "id": _next_id(data["links"], "link"),
        "url": (url or "").strip(),
        "title": (title or url or "").strip(),
        "tags": [t.strip().lower() for t in (tags or [])],
        "created": datetime.now().isoformat(),
    }
    data["links"].append(link)
    _save_data(data)
    return link


def get_links(tag: str = None) -> list:
    data = _load_data()
    links = data["links"]
    if tag:
        t = tag.strip().lower()
        links = [l for l in links if t in l.get("tags", [])]
    return list(reversed(links))


# ============================================================
# 4) MEETING RECORDER + AUTO-SUMMARY
# ============================================================

def _summarize_text(text: str) -> dict:
    """Lightweight extractive summary + action-item and decision detection."""
    text = text or ""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]

    action_kw = ["will", "should", "need to", "must", "action", "todo", "to-do",
                 "follow up", "follow-up", "assign", "deadline", "next step", "by "]
    decision_kw = ["decided", "agreed", "approved", "confirmed", "we'll go with",
                   "final", "signed off", "conclusion"]

    actions, decisions = [], []
    for s in sentences:
        low = s.lower()
        if any(k in low for k in action_kw):
            actions.append(s)
        if any(k in low for k in decision_kw):
            decisions.append(s)

    words = re.findall(r"[a-zA-Z']+", text.lower())
    freq = Counter(w for w in words if w not in STOPWORDS and len(w) > 2)
    scored = []
    for s in sentences:
        toks = re.findall(r"[a-zA-Z']+", s.lower())
        score = sum(freq[t] for t in toks if t not in STOPWORDS)
        scored.append((score, s))
    key_points = [s for _, s in sorted(scored, key=lambda x: x[0], reverse=True)[:5]]

    summary = " ".join(sentences[:3])[:600] if sentences else ""

    return {
        "word_count": len(words),
        "summary": summary,
        "key_points": key_points,
        "action_items": actions[:10],
        "decisions": decisions[:10],
    }


@_locked
def start_meeting_recording(title: str) -> dict:
    data = _load_data()
    active = {
        "title": (title or "Meeting").strip(),
        "started": datetime.now().isoformat(),
    }
    data["active_recording"] = active
    _save_data(data)
    return {"status": "recording", **active}


@_locked
def stop_meeting_recording(transcript: str = "") -> dict:
    data = _load_data()
    active = data.get("active_recording")
    if not active:
        return {"status": "none", "message": "No meeting recording in progress."}

    summary = _summarize_text(transcript) if transcript else None
    rec = {
        "id": _next_id(data["recordings"], "rec"),
        "title": active["title"],
        "started": active["started"],
        "ended": datetime.now().isoformat(),
        "transcript": transcript or "",
        "summary": summary,
    }
    data["recordings"].append(rec)
    data["active_recording"] = None
    _save_data(data)
    return {"status": "stopped", **rec}


@_locked
def save_transcript(title: str, transcript: str) -> dict:
    data = _load_data()
    rec = {
        "id": _next_id(data["recordings"], "rec"),
        "title": (title or "Meeting").strip(),
        "started": datetime.now().isoformat(),
        "ended": datetime.now().isoformat(),
        "transcript": transcript or "",
        "summary": _summarize_text(transcript),
    }
    data["recordings"].append(rec)
    _save_data(data)
    return rec


def summarize_meeting(transcript: str) -> dict:
    return _summarize_text(transcript)


def get_recordings() -> list:
    data = _load_data()
    return list(reversed(data["recordings"]))


# ============================================================
# 5) DAILY ROUTINE SCHEDULER
# ============================================================

@_locked
def add_routine(name: str, time_str: str, action: str = "", days: list = None) -> dict:
    data = _load_data()
    routine = {
        "id": _next_id(data["routines"], "routine"),
        "name": (name or "").strip(),
        "time": (time_str or "").strip(),
        "action": action or name,
        "days": days if days else [0, 1, 2, 3, 4, 5, 6],
        "active": True,
        "last_fired": None,
        "created": datetime.now().isoformat(),
    }
    data["routines"].append(routine)
    _save_data(data)
    return routine


def get_routines() -> list:
    data = _load_data()
    return data["routines"]


@_locked
def remove_routine(identifier: str) -> bool:
    data = _load_data()
    for i, r in enumerate(data["routines"]):
        if r["id"] == identifier or r["name"].lower() == (identifier or "").strip().lower():
            data["routines"].pop(i)
            _save_data(data)
            return True
    return False


@_locked
def check_due_routines(now: datetime = None) -> list:
    """Fire any routines whose time matches now. Returns the fired routines."""
    now = now or datetime.now()
    hhmm = now.strftime("%H:%M")
    stamp = now.strftime("%Y-%m-%d %H:%M")
    weekday = now.weekday()

    data = _load_data()
    fired = []
    for r in data["routines"]:
        if not r.get("active", True):
            continue
        if r.get("time") != hhmm:
            continue
        if weekday not in r.get("days", [0, 1, 2, 3, 4, 5, 6]):
            continue
        if r.get("last_fired") == stamp:
            continue
        r["last_fired"] = stamp
        alert = {
            "id": _next_id(data["routine_alerts"], "ralert"),
            "routine": r["name"],
            "message": r.get("action") or r["name"],
            "fired_at": now.isoformat(),
        }
        data["routine_alerts"].append(alert)
        fired.append(alert)

    if fired:
        _save_data(data)
    return fired


@_locked
def pop_routine_alerts() -> list:
    data = _load_data()
    alerts = data["routine_alerts"]
    data["routine_alerts"] = []
    _save_data(data)
    return alerts


def _routine_loop():
    global _routine_running
    while _routine_running:
        try:
            check_due_routines()
        except Exception as e:
            print(f"[Routine] scheduler error: {e}")
        time.sleep(30)


def start_routine_scheduler():
    global _routine_running, _routine_thread
    if _routine_running:
        return
    _routine_running = True
    _routine_thread = threading.Thread(target=_routine_loop, daemon=True)
    _routine_thread.start()
    print("[Routine] Daily routine scheduler started")


def stop_routine_scheduler():
    global _routine_running
    _routine_running = False
    print("[Routine] Daily routine scheduler stopped")


# ============================================================
# 6) FINANCE / NET-WORTH DASHBOARD
# ============================================================

@_locked
def add_income(amount: float, source: str, description: str = "") -> dict:
    data = _load_data()
    entry = {
        "id": _next_id(data["income"], "inc"),
        "amount": float(amount or 0),
        "source": source or "income",
        "description": description or "",
        "date": _today(),
        "logged_at": datetime.now().isoformat(),
    }
    data["income"].append(entry)
    _save_data(data)
    return entry


@_locked
def add_invoice(client: str, amount: float, status: str = "pending", due: str = "") -> dict:
    data = _load_data()
    inv = {
        "id": _next_id(data["invoices"], "inv"),
        "client": client or "",
        "amount": float(amount or 0),
        "status": status or "pending",
        "due": due or "",
        "created": datetime.now().isoformat(),
    }
    data["invoices"].append(inv)
    _save_data(data)
    return inv


@_locked
def update_invoice_status(identifier: str, status: str) -> bool:
    data = _load_data()
    for inv in data["invoices"]:
        if inv["id"] == identifier or inv["client"].lower() == (identifier or "").strip().lower():
            inv["status"] = status
            _save_data(data)
            return True
    return False


@_locked
def add_asset(name: str, value: float, kind: str = "asset") -> dict:
    data = _load_data()
    entry = {
        "id": _next_id(data["assets"], "asset"),
        "name": name or "",
        "value": float(value or 0),
        "kind": kind or "asset",
    }
    data["assets"].append(entry)
    _save_data(data)
    return entry


@_locked
def add_liability(name: str, value: float, kind: str = "loan") -> dict:
    data = _load_data()
    entry = {
        "id": _next_id(data["liabilities"], "liab"),
        "name": name or "",
        "value": float(value or 0),
        "kind": kind or "loan",
    }
    data["liabilities"].append(entry)
    _save_data(data)
    return entry


def get_net_worth() -> dict:
    data = _load_data()
    total_assets = sum(a["value"] for a in data["assets"])
    total_liab = sum(l["value"] for l in data["liabilities"])
    return {
        "assets": total_assets,
        "liabilities": total_liab,
        "net_worth": total_assets - total_liab,
        "asset_count": len(data["assets"]),
        "liability_count": len(data["liabilities"]),
    }


def get_finance_summary() -> dict:
    data = _load_data()
    month = datetime.now().strftime("%Y-%m")
    today = _today()

    income_today = sum(i["amount"] for i in data["income"] if i["date"] == today)
    income_month = sum(i["amount"] for i in data["income"] if i["date"].startswith(month))

    # Pull expenses from the business tools expense tracker if available.
    expenses_month = 0.0
    expenses_today = 0.0
    try:
        from business_tools import get_expenses
        exps = get_expenses()
        expenses_today = sum(e["amount"] for e in exps if e["date"] == today)
        expenses_month = sum(e["amount"] for e in exps if e["date"].startswith(month))
    except Exception:
        pass

    outstanding = sum(i["amount"] for i in data["invoices"] if i["status"] != "paid")
    paid = sum(i["amount"] for i in data["invoices"] if i["status"] == "paid")

    monthly_burn = expenses_month if expenses_month > 0 else 0
    nw = get_net_worth()
    runway_months = round(nw["net_worth"] / monthly_burn, 1) if monthly_burn > 0 else None
    profit_month = income_month - expenses_month

    return {
        "income_today": round(income_today, 2),
        "income_month": round(income_month, 2),
        "expenses_today": round(expenses_today, 2),
        "expenses_month": round(expenses_month, 2),
        "profit_month": round(profit_month, 2),
        "invoices_outstanding": round(outstanding, 2),
        "invoices_paid": round(paid, 2),
        "monthly_burn": round(monthly_burn, 2),
        "runway_months": runway_months,
        "net_worth": nw,
    }


def get_finance_dashboard() -> str:
    s = get_finance_summary()
    nw = s["net_worth"]
    runway = f"{s['runway_months']} months" if s["runway_months"] is not None else "n/a"
    return (
        "Finance dashboard:\n"
        f"- Income: \u20b9{s['income_today']} today, \u20b9{s['income_month']} this month\n"
        f"- Expenses: \u20b9{s['expenses_today']} today, \u20b9{s['expenses_month']} this month\n"
        f"- Profit this month: \u20b9{s['profit_month']}\n"
        f"- Invoices outstanding: \u20b9{s['invoices_outstanding']} (paid \u20b9{s['invoices_paid']})\n"
        f"- Net worth: \u20b9{nw['net_worth']} (assets \u20b9{nw['assets']}, liabilities \u20b9{nw['liabilities']})\n"
        f"- Runway: {runway}"
    )


# ============================================================
# COMBINED LIFE BRIEFING
# ============================================================

def life_briefing() -> str:
    lines = [f"Life briefing ({datetime.now().strftime('%H:%M')})", ""]

    at_risk = habits_at_risk()
    if at_risk:
        lines.append("Habits pending today: " + ", ".join(h["name"] for h in at_risk))
    else:
        lines.append("All habits done today. Well done.")

    f = get_focus_stats()
    lines.append(f"Focus: {f['minutes_today']} min today ({f['sessions_today']} sessions).")

    s = get_finance_summary()
    lines.append(f"Finance: \u20b9{s['income_month']} in, \u20b9{s['expenses_month']} out this month.")

    notes = get_notes()
    if notes:
        lines.append(f"Latest note: {notes[0]['title']}")

    return "\n".join(lines)
