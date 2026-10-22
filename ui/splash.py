"""Tier 3.23 — boot splash and composed shutdown.

The splash is drawn, not an asset: a black window with the system name and a
progress line, destroyed after `ms`. It is optional (the HUD works without it)
and every failure is swallowed, because a splash must never be the reason the
app does not start.
"""

from __future__ import annotations

import time

STAGES = ("policy", "memory", "audio", "model", "hud")


def splash_text(version: str = "", stage: str = "starting") -> str:
    parts = ["J.A.R.V.I.S."]
    if version:
        parts.append(f"v{version}")
    if stage:
        parts.append(stage)
    return "   ".join(parts)


def show(root, *, ms: int = 900, version: str = "", colors: dict | None = None):
    """Show a borderless splash over `root`. Returns the Toplevel or None."""
    try:
        import tkinter as tk

        colors = colors or {"bg": "#000000", "pri": "#00d4ff", "dim": "#003344"}
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.configure(bg=colors["bg"])
        width, height = 420, 120
        try:
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            win.geometry(f"{width}x{height}+{(sw - width) // 2}+{(sh - height) // 2}")
        except Exception:
            pass
        tk.Label(win, text=splash_text(version, "starting"),
                 fg=colors["pri"], bg=colors["bg"],
                 font=("Courier", 14, "bold")).pack(pady=(28, 6))
        tk.Label(win, text="initialising subsystems", fg=colors["dim"],
                 bg=colors["bg"], font=("Courier", 9)).pack()
        win.after(max(0, int(ms)), win.destroy)
        return win
    except Exception:
        return None


def shutdown_steps() -> list[str]:
    """The order shutdown happens in. Useful for logs and tests."""
    return [
        "stop task queue",
        "clear recording indicator",
        "save window layout",
        "exit",
    ]


def shutdown(ui=None, *, save_layout: bool = True) -> list[str]:
    """Run the composed shutdown. Each step is independent and best-effort.

    Deliberately does not engage the kill switch: shutting down is not a policy
    decision, and leaving AUTONOMY_OFF behind would block the next start.
    """
    done: list[str] = []
    if ui is not None:
        try:
            from agent import task_queue
            task_queue.get_queue().stop()
            done.append("stop task queue")
        except Exception:
            pass
        try:
            from ui import JarvisUI
            JarvisUI.set_recording(False, "shutdown")
            done.append("clear recording indicator")
        except Exception:
            pass
        if save_layout:
            try:
                from ui.layout import save_window
                if save_window(ui.root):
                    done.append("save window layout")
            except Exception:
                pass
    return done


def log_line(stage: str, started: float) -> str:
    return f"[boot] {stage} in {(time.time() - started) * 1000:.0f} ms"
