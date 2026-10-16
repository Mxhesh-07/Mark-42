"""
J.A.R.V.I.S. — Startup Partner Module
Co-founder assistant for metrics, strategy, pitches, and partner communication.
"""

import copy
import json
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta
from threading import RLock

BASE_DIR = Path(__file__).resolve().parent
STARTUP_PATH = BASE_DIR / "startup_data.json"
_lock = RLock()

_DEFAULT = {
    "name": "",
    "stage": "",
    "description": "",
    "metrics": [],
    "milestones": [],
    "pitch_drafts": [],
    "partner_messages": [],
    "competitors": [],
    "investor_updates": [],
    "product_features": [],
    "team": [],
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
        if not STARTUP_PATH.exists():
            return data
        try:
            with open(STARTUP_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _deep_merge(data, loaded)
            return data
        except Exception:
            return copy.deepcopy(_DEFAULT)


def _save_data(data: dict) -> None:
    STARTUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(STARTUP_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


@_locked
def set_startup_info(name: str, stage: str, description: str) -> dict:
    data = _load_data()
    data["name"] = name
    data["stage"] = stage
    data["description"] = description
    _save_data(data)
    return data


@_locked
def log_metric(metric_name: str, value: float, notes: str = "") -> dict:
    data = _load_data()
    entry = {
        "metric": metric_name,
        "value": value,
        "notes": notes,
        "date": datetime.now().isoformat(),
    }
    data["metrics"].append(entry)
    _save_data(data)
    return entry


def get_metric_trend(metric_name: str, days: int = 30) -> list:
    data = _load_data()
    cutoff = datetime.now().timestamp() - days * 86400
    return [
        m for m in data["metrics"]
        if m["metric"] == metric_name and datetime.fromisoformat(m["date"]).timestamp() > cutoff
    ]


@_locked
def add_milestone(title: str, description: str, due_date: str = None) -> dict:
    data = _load_data()
    milestone = {
        "id": f"ms_{len(data['milestones']) + 1}",
        "title": title,
        "description": description,
        "due": due_date,
        "status": "pending",
        "created": datetime.now().isoformat(),
    }
    data["milestones"].append(milestone)
    _save_data(data)
    return milestone


@_locked
def complete_milestone(milestone_id: str) -> bool:
    data = _load_data()
    key = str(milestone_id or "").strip().lower()
    for ms in data["milestones"]:
        if ms["id"] == milestone_id or str(ms.get("title", "")).strip().lower() == key:
            ms["status"] = "completed"
            ms["completed_at"] = datetime.now().isoformat()
            _save_data(data)
            return True
    return False


def get_milestones(status: str = None) -> list:
    data = _load_data()
    if status:
        return [m for m in data["milestones"] if m["status"] == status]
    return data["milestones"]


@_locked
def save_pitch_draft(title: str, content: str) -> dict:
    data = _load_data()
    draft = {
        "id": f"pitch_{len(data['pitch_drafts']) + 1}",
        "title": title,
        "content": content,
        "version": 1,
        "created": datetime.now().isoformat(),
    }
    data["pitch_drafts"].append(draft)
    _save_data(data)
    return draft


@_locked
def log_partner_message(partner_name: str, message: str, direction: str = "outgoing") -> dict:
    data = _load_data()
    entry = {
        "id": f"msg_{len(data['partner_messages']) + 1}",
        "partner": partner_name,
        "message": message,
        "direction": direction,
        "date": datetime.now().isoformat(),
    }
    data["partner_messages"].append(entry)
    _save_data(data)
    return entry


def get_partner_messages(partner_name: str = None) -> list:
    data = _load_data()
    if partner_name:
        return [m for m in data["partner_messages"] if m["partner"] == partner_name]
    return data["partner_messages"][-20:]


@_locked
def add_competitor(name: str, strengths: str, weaknesses: str) -> dict:
    data = _load_data()
    comp = {
        "id": f"comp_{len(data['competitors']) + 1}",
        "name": name,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "added": datetime.now().isoformat(),
    }
    data["competitors"].append(comp)
    _save_data(data)
    return comp


def get_competitors() -> list:
    data = _load_data()
    return data["competitors"]


@_locked
def add_product_feature(name: str, description: str, priority: str = "medium", status: str = "planned") -> dict:
    data = _load_data()
    feature = {
        "id": f"feat_{len(data['product_features']) + 1}",
        "name": name,
        "description": description,
        "priority": priority,
        "status": status,
        "created": datetime.now().isoformat(),
    }
    data["product_features"].append(feature)
    _save_data(data)
    return feature


def get_product_features(status: str = None) -> list:
    data = _load_data()
    if status:
        return [f for f in data["product_features"] if f["status"] == status]
    return data["product_features"]


@_locked
def add_team_member(name: str, role: str, equity: str = None) -> dict:
    data = _load_data()
    member = {
        "id": f"team_{len(data['team']) + 1}",
        "name": name,
        "role": role,
        "equity": equity,
        "added": datetime.now().isoformat(),
    }
    data["team"].append(member)
    _save_data(data)
    return member


def get_team() -> list:
    data = _load_data()
    return data["team"]


@_locked
def log_investor_update(investor_name: str, update: str, status: str = "pending") -> dict:
    data = _load_data()
    entry = {
        "id": f"inv_{len(data['investor_updates']) + 1}",
        "investor": investor_name,
        "update": update,
        "status": status,
        "date": datetime.now().isoformat(),
    }
    data["investor_updates"].append(entry)
    _save_data(data)
    return entry


def get_investor_updates() -> list:
    data = _load_data()
    return data["investor_updates"]


def startup_dashboard() -> dict:
    """Generate startup dashboard."""
    data = _load_data()
    pending_milestones = len([m for m in data["milestones"] if m["status"] == "pending"])
    total_milestones = len(data["milestones"])
    team_size = len(data["team"])
    features_planned = len([f for f in data["product_features"] if f["status"] == "planned"])
    features_shipped = len([f for f in data["product_features"] if f["status"] == "shipped"])
    pending_investor = len([i for i in data["investor_updates"] if i["status"] == "pending"])

    return {
        "startup_name": data.get("name", "Unknown"),
        "stage": data.get("stage", "Unknown"),
        "team_size": team_size,
        "milestones": {
            "total": total_milestones,
            "pending": pending_milestones,
            "completed": total_milestones - pending_milestones,
        },
        "product": {
            "features_planned": features_planned,
            "features_shipped": features_shipped,
        },
        "investors": {
            "pending_updates": pending_investor,
            "total_updates": len(data["investor_updates"]),
        },
        "competitors": len(data["competitors"]),
        "metrics_logged": len(data["metrics"]),
        "generated_at": datetime.now().isoformat(),
    }


def strategy_prompt(topic: str) -> str:
    """Generate a strategic thinking prompt."""
    prompts = {
        "general": "Think about market fit, competitive advantage, and scalability.",
        "fundraising": "Consider traction metrics, market size, and use of funds.",
        "product": "Focus on user pain points, differentiation, and roadmap.",
        "hiring": "Think about culture fit, equity distribution, and role clarity.",
        "competition": "Analyze strengths, weaknesses, and positioning.",
    }
    return prompts.get(topic, prompts["general"])
