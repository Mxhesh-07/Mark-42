"""Tier 3.22 — optional audio/visual cues for state changes.

Off by default: beeps in an assistant are easy to hate. Enable with
``config/ui.json`` -> ``{"cues": true}``. On Windows this uses the system beep
(winsound); elsewhere it is a no-op, and every failure is swallowed.
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG = BASE_DIR / "config" / "ui.json"

_CUES = {
    "listening": (880, 60),
    "thinking": (660, 50),
    "speaking": (520, 40),
    "error": (220, 160),
    "confirm": (990, 90),
}


def enabled() -> bool:
    try:
        return bool(json.loads(CONFIG.read_text(encoding="utf-8")).get("cues", False))
    except Exception:
        return False


def play(kind: str, *, force: bool = False) -> bool:
    """Play one short cue. Returns True only if something was played."""
    if not force and not enabled():
        return False
    if kind not in _CUES:
        return False
    freq, ms = _CUES[kind]
    try:
        import winsound

        winsound.Beep(freq, ms)
        return True
    except Exception:
        return False
