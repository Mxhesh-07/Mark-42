"""Tier 3.1 — window management for the HUD.

The HUD is borderless and floating; without these helpers the only way to move
or pin it was to edit code. All functions take a Tk root and are best-effort:
an unsupported window manager returns False instead of raising.
"""

from __future__ import annotations


def minimize(root) -> bool:
    try:
        root.iconify()
        return True
    except Exception:
        return False


def hide_to_tray(root) -> bool:
    """T3.1: remove the HUD from the taskbar without ending the session."""
    try:
        root.withdraw()
        return True
    except Exception:
        return False


def show_from_tray(root) -> bool:
    try:
        root.deiconify()
        try:
            root.state("normal")
        except Exception:
            pass
        root.lift()
        try:
            root.focus_force()
        except Exception:
            pass
        return True
    except Exception:
        return False


def maximize(root) -> bool:
    try:
        if root.state() == "zoomed":
            root.state("normal")
        else:
            root.state("zoomed")
        return True
    except Exception:
        try:
            root.attributes("-fullscreen", not bool(root.attributes("-fullscreen")))
            return True
        except Exception:
            return False


def toggle_always_on_top(root) -> bool:
    try:
        current = bool(root.attributes("-topmost"))
        root.attributes("-topmost", not current)
        return not current
    except Exception:
        return False


def toggle_fullscreen(root) -> bool:
    try:
        current = bool(root.attributes("-fullscreen"))
        root.attributes("-fullscreen", not current)
        return not current
    except Exception:
        return False


def center(root, width: int | None = None, height: int | None = None) -> bool:
    try:
        w = int(width or root.winfo_width())
        h = int(height or root.winfo_height())
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        return True
    except Exception:
        return False


def move_to(root, corner: str, margin: int = 24, width: int | None = None,
            height: int | None = None) -> bool:
    """Snap to a corner: tl, tr, bl, br, or center."""
    try:
        w = int(width or root.winfo_width())
        h = int(height or root.winfo_height())
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        xs = {"tl": margin, "tr": sw - w - margin, "bl": margin,
              "br": sw - w - margin, "center": (sw - w) // 2}
        ys = {"tl": margin, "tr": margin, "bl": sh - h - margin,
              "br": sh - h - margin, "center": (sh - h) // 2}
        if corner not in xs:
            return False
        root.geometry(f"{w}x{h}+{int(xs[corner])}+{int(ys[corner])}")
        return True
    except Exception:
        return False


def state(root) -> dict:
    try:
        return {
            "geometry": root.winfo_geometry(),
            "state": root.state(),
            "on_top": bool(root.attributes("-topmost")),
            "fullscreen": bool(root.attributes("-fullscreen")),
        }
    except Exception:
        return {}
