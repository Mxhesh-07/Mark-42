"""Tier 3.3/3.4 — the dashboard panels, out of the HUD class.

`JarvisUI` keeps the behaviour; this module owns the four side panels and the
status strip. Geometry comes from `ui.layout_spec.Metrics` where it exists, so a
panel cannot drift away from the status strip again.
"""

from __future__ import annotations

PANEL_BG = "#05141c"


def _panel(tk, hud, x: int, y: int, width: int = 180, height: int = 140):
    frame = tk.Frame(hud.root, bg=PANEL_BG, highlightbackground="#00d4ff",
                     highlightthickness=2)
    frame.place(x=x, y=y, width=width, height=height)
    return frame


def _title(tk, frame, text: str, font) -> None:
    tk.Label(frame, text=text, fg="#00d4ff", bg=PANEL_BG,
             font=font(11, bold=True)).pack(anchor="w", padx=10, pady=5)


def _body(tk, frame, text: str, font):
    label = tk.Label(frame, text=text, fg="#8ffcff", bg=PANEL_BG,
                     justify="left", font=font(9))
    label.pack(anchor="w", padx=10)
    return label


def build(hud) -> None:
    import tkinter as tk

    from ui import theme, widgets

    font = theme.font
    margin = 15
    width = 180
    height = 140
    right_x = hud.W - width - margin

    hud.task_frame = _panel(tk, hud, margin, 80, width, height)
    _title(tk, hud.task_frame, "TASKS", font)
    hud.task_label = _body(tk, hud.task_frame, "Waiting...", font)

    hud.memory_frame = _panel(tk, hud, right_x, 80, width, height)
    _title(tk, hud.memory_frame, "MEMORY", font)
    hud.memory_label = _body(tk, hud.memory_frame, "No Context", font)

    hud.agent_frame = _panel(tk, hud, margin, 240, width, height)
    _title(tk, hud.agent_frame, "AGENTS", font)
    hud.agent_label = _body(
        tk, hud.agent_frame,
        "Planner : ACTIVE\nMemory  : ACTIVE\n"
        "Browser : IDLE\nExecutor: IDLE",
        font,
    )

    hud.system_frame = _panel(tk, hud, right_x, 240, width, height)
    _title(tk, hud.system_frame, "SYSTEM", font)
    hud.system_label = _body(tk, hud.system_frame, "Loading...", font)

    # T3.13: provider/model/mode/queue strip. Users otherwise blame a fallback
    # model for slowness without seeing that it happened.
    hud.status_strip_label = tk.Label(
        hud.root, text="", fg="#003344", bg="#000000",
        font=font(8), anchor="w",
    )
    geo = (hud.metrics.pane("status") if getattr(hud, "metrics", None) is not None
           else {"x": margin, "y": hud.H - 20,
                 "width": hud.W - 2 * margin, "height": 14})
    hud.status_strip_label.place(**geo)
    hud._refresh_status_strip()

    hud.update_dashboard()
    hud.refresh_memory_panel()
    hud.update_agent_panel()

    # T3.26: the dashboard labels are terse on purpose; tooltips carry the
    # explanation without adding permanent chrome.
    try:
        widgets.Tooltip(hud.task_label,
                        "Current plan steps. Cancelled steps are marked ⊘.")
        widgets.Tooltip(hud.memory_label,
                        "What JARVIS remembers. Stored locally in memory/.")
        if hasattr(hud, "agent_label"):
            widgets.Tooltip(hud.agent_label,
                            "Per-agent state: ○ idle, ◉ active, ◈ thinking.")
    except Exception:
        pass
