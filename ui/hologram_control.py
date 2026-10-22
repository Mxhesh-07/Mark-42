"""Tier 3.20 — hologram control surface.

`hologram.py` already knows how to list, launch and quit the projector (it is a
separate pygame window, never a browser). This module is the small, testable
adapter the HUD calls, so a missing pygame or a dead projector shows as a status
line instead of an exception in the middle of a paint.
"""

from __future__ import annotations


def models() -> list[str]:
    try:
        import hologram_models

        return list(hologram_models.list_models())
    except Exception:
        return []


def status() -> dict:
    running = False
    try:
        import hologram

        running = bool(hologram.is_running())
    except Exception:
        pass
    return {"running": running, "models": len(models())}


def launch(name: str | None = None, *, prompt: str | None = None) -> dict:
    """Ask the projector to show a model. Returns a result dict, never raises."""
    if not name and not prompt:
        return {"ok": False, "reason": "name or prompt required"}
    if name:
        available = models()
        if available and name not in available:
            return {"ok": False, "reason": f"unknown model: {name}"}
    try:
        import hologram

        hologram.launch(name=name, prompt=prompt)
        return {"ok": True, "name": name, "prompt": prompt}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def close() -> dict:
    try:
        import hologram

        hologram.send_command({"action": "quit"})
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def status_line() -> str:
    state = status()
    if state["running"]:
        return f"hologram: running ({state['models']} models)"
    return f"hologram: idle ({state['models']} models)"
