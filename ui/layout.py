"""Tier 3.18 / T3.21 — window persistence and DPI/multi-monitor hygiene.

The window remembers size, position, on-top and opacity in ``config/ui.json``.
Geometry is clamped to the visible desktop on load, so unplugging a monitor
cannot leave the HUD off-screen (the classic "the app opens but I can't see it"
bug).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG = BASE_DIR / "config" / "ui.json"


def _read() -> dict:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(data: dict) -> bool:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(CONFIG)
        return True
    except Exception:
        return False


def dpi_awareness() -> bool:
    """Tell Windows the process handles DPI itself; no-op elsewhere."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def clamp_geometry(x: int, y: int, w: int, h: int,
                   screen_w: int, screen_h: int, margin: int = 40) -> tuple:
    """Keep at least `margin` px of the window on screen."""
    w = max(320, min(int(w), max(320, int(screen_w))))
    h = max(240, min(int(h), max(240, int(screen_h))))
    x = max(-(w - margin), min(int(x), int(screen_w) - margin))
    y = max(0, min(int(y), int(screen_h) - margin))
    return x, y, w, h


def load_window() -> dict:
    data = _read().get("window") or {}
    return data if isinstance(data, dict) else {}


def save_window(root, *, extra: dict | None = None) -> bool:
    """Store geometry/opacity/on-top. Errors never block shutdown."""
    try:
        data = _read()
        geometry = root.winfo_geometry()          # WxH+X+Y
        window = {"geometry": geometry}
        try:
            window["on_top"] = bool(root.attributes("-topmost"))
        except Exception:
            pass
        try:
            window["opacity"] = float(root.attributes("-alpha"))
        except Exception:
            pass
        if extra:
            window.update(extra)
        data["window"] = window
        return _write(data)
    except Exception:
        return False


def apply_window(root, screen_w: int | None = None,
                 screen_h: int | None = None) -> dict:
    """Apply a saved geometry, clamped. Returns the window dict it used."""
    saved = load_window()
    if not saved:
        return {}
    raw = str(saved.get("geometry") or "")
    try:
        size, _, pos = raw.partition("+")
        w, _, h = size.partition("x")
        x, _, y = pos.partition("+")
        sw = screen_w or root.winfo_screenwidth()
        sh = screen_h or root.winfo_screenheight()
        cx, cy, cw, ch = clamp_geometry(int(x), int(y), int(w), int(h), sw, sh)
        root.geometry(f"{cw}x{ch}+{cx}+{cy}")
    except Exception:
        pass
    try:
        if "on_top" in saved:
            root.attributes("-topmost", bool(saved["on_top"]))
        if "opacity" in saved:
            root.attributes("-alpha", max(0.2, min(1.0, float(saved["opacity"]))))
    except Exception:
        pass
    return saved
