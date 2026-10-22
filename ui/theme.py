"""Tier 3.17 / T3.24 — themes and one font helper.

The HUD used to spell `("Courier", n)` at 30-odd call sites, which made a second
theme impossible. This module is the single place colours and fonts come from.
Existing widgets keep their inline colours until they are touched; new code
should call `palette()` and `font()`.

Theme choice lives in ``config/ui.json`` (``{"theme": "arc_blue"}``). An unknown
name falls back to Arc Blue rather than failing — a bad config must not stop the
window from opening.
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG = BASE_DIR / "config" / "ui.json"

# Every theme carries the same keys so a widget never has to test which one is
# active. `contrast` is 1 for colour-only themes that need labels, not just hue.
THEMES = {
    "arc_blue": {
        "bg": "#000000", "pri": "#00d4ff", "mid": "#007a99", "dim": "#003344",
        "dimmer": "#001520", "acc": "#ff6600", "acc2": "#ffcc00",
        "text": "#8ffcff", "panel": "#010c10", "green": "#00ff88", "red": "#ff3333",
    },
    "warm_amber": {
        "bg": "#0a0704", "pri": "#ffb000", "mid": "#b36b00", "dim": "#5c3a00",
        "dimmer": "#2a1a00", "acc": "#ff7043", "acc2": "#ffe082",
        "text": "#ffe9b0", "panel": "#150f06", "green": "#9ccc65", "red": "#ef5350",
    },
    "mono": {
        "bg": "#000000", "pri": "#e0e0e0", "mid": "#9e9e9e", "dim": "#616161",
        "dimmer": "#303030", "acc": "#ffffff", "acc2": "#bdbdbd",
        "text": "#f5f5f5", "panel": "#0a0a0a", "green": "#c8e6c9", "red": "#ff8a80",
    },
    "high_contrast": {
        "bg": "#000000", "pri": "#ffffff", "mid": "#ffffff", "dim": "#d0d0d0",
        "dimmer": "#202020", "acc": "#ffff00", "acc2": "#00ffff",
        "text": "#ffffff", "panel": "#000000", "green": "#00ff00", "red": "#ff0000",
    },
}

DEFAULT_THEME = "arc_blue"
DEFAULT_FAMILY = "Courier"


def available() -> list[str]:
    return sorted(THEMES)


def configured_name() -> str:
    try:
        value = json.loads(CONFIG.read_text(encoding="utf-8")).get("theme")
        if isinstance(value, str) and value in THEMES:
            return value
    except Exception:
        pass
    return DEFAULT_THEME


def palette(name: str | None = None) -> dict:
    return dict(THEMES.get(name or configured_name(), THEMES[DEFAULT_THEME]))


_SCALE: float | None = None


def _scale() -> float:
    global _SCALE
    if _SCALE is not None:
        return _SCALE
    value = 1.0
    try:
        raw = json.loads(CONFIG.read_text(encoding="utf-8")).get("font_scale", 1.0)
        value = max(0.8, min(2.0, float(raw)))
    except Exception:
        value = 1.0
    _SCALE = value
    return value


def font(size: int = 10, *, bold: bool = False, family: str | None = None) -> tuple:
    """One tuple shape for Tk widgets: (family, size[, "bold"]).

    T3.14: `font_scale` in config/ui.json enlarges every call site at once.
    """
    fam = family or DEFAULT_FAMILY
    px = max(7, int(round(int(size) * _scale())))
    return (fam, px, "bold") if bold else (fam, px)


def save_theme(name: str) -> bool:
    """Persist a theme choice. Unknown names are refused, not written."""
    if name not in THEMES:
        return False
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        current = {}
        try:
            current = json.loads(CONFIG.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except Exception:
            current = {}
        current["theme"] = name
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        tmp.replace(CONFIG)
        return True
    except Exception:
        return False
