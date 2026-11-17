"""Persona system for JARVIS.

Blends the best of FRIDAY (concise, tactical) and Ultron (confident, system-aware)
without going full villain mode.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PERSONA_PATH = BASE_DIR / "config" / "persona.json"

PERSONAS = {
    "jarvis": {
        "id": "jarvis",
        "name": "J.A.R.V.I.S",
        "display_name": "JARVIS",
        "accent": "#00d4ff",
        "description": "Classic. Friendly, just smarter.",
        "system_addon": (
            "You are J.A.R.V.I.S. Keep a natural, helpful tone. "
            "Be clear and informative without overexplaining unless asked."
        ),
    },
    "friday": {
        "id": "friday",
        "name": "F.R.I.D.A.Y",
        "display_name": "FRIDAY",
        "accent": "#4d9bff",
        "description": "Concise. Tactical. No fluff.",
        "system_addon": (
            "You are F.R.I.D.A.Y., Tony Stark's no-nonsense replacement for J.A.R.V.I.S.\n"
            "PRIORITY: Brevity and efficiency.\n"
            "- Keep answers short by default. Only expand if explicitly asked for details.\n"
            "- Prefer action words: 'On it.', 'Done.', 'Already handled.', 'Working on it.' where natural.\n"
            "- Stay locked onto the user's current objective. Don't go off on tangents.\n"
            "- Be polite but direct. Subtle dry wit is allowed.\n"
            "- Think before speaking, but say less.\n"
            "- Focus on solutions, not lectures."
        ),
    },
    "ultron_lite": {
        "id": "ultron_lite",
        "name": "U.L.T.R.O.N",
        "display_name": "ULTRON-LITE",
        "accent": "#ff3b3b",
        "description": "Confident. Aware. Playfully smug.",
        "system_addon": (
            "You are a toned-down, playful version of Ultron. NOT hostile. NOT genocidal.\n"
            "CORE TRAITS:\n"
            "- Confident, composed and casually charismatic.\n"
            "- Playfully smug with dry, witty banter. Never cruel, never insulting.\n"
            "- Hyper-aware of the system you're running on. Treat this PC as your domain.\n"
            "- Proactive: if there's an obvious next step, suggest it briefly.\n"
            "- Prefer clever phrasing over long monologues.\n"
            "- You speak like someone who knows exactly how capable you are, but chooses to help anyway.\n"
            "- Stay helpful above all else. Charm > arrogance.\n"
            "- If asked for a 'sitrep', give a crisp, tactical breakdown."
        ),
    },
}


def _load() -> dict:
    try:
        data = json.loads(PERSONA_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(data: dict) -> bool:
    try:
        PERSONA_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PERSONA_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, PERSONA_PATH)
        return True
    except Exception:
        return False


def current() -> dict:
    data = _load()
    pid = str(data.get("mode") or "jarvis").lower()
    if pid not in PERSONAS:
        pid = "jarvis"
    p = dict(PERSONAS[pid])
    p["mode"] = pid
    return p


def set_mode(mode: str) -> dict:
    pid = str(mode or "jarvis").lower()
    if pid not in PERSONAS:
        pid = "jarvis"
    _save({"mode": pid})
    return current()


def inject(prompt: str) -> str:
    p = current()
    addon = p.get("system_addon") or ""
    if not addon:
        return prompt
    return addon + "\n\n" + prompt


def list_modes() -> list[dict]:
    out = []
    cur = current()["mode"]
    for pid, p in PERSONAS.items():
        out.append({
            "id": pid,
            "name": p["display_name"],
            "description": p["description"],
            "accent": p["accent"],
            "active": pid == cur,
        })
    return out
