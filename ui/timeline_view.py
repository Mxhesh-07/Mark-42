"""Tier 3.11 — activity timeline window: per-step status and cancel.

The model already lives in `ui.timeline`; this is the read-only-plus-cancel view.
Steps that are pending or running get a Cancel button; finished steps do not.
"""

from __future__ import annotations

import tkinter as tk

from ui import timeline as timeline_model


def build(ui) -> tk.Toplevel:
    try:
        from ui import theme
        colors = theme.palette()
    except Exception:
        colors = {"bg": "#000000", "panel": "#010c10", "text": "#8ffcff",
                  "pri": "#00d4ff", "dim": "#003344", "red": "#ff3333"}

    store = getattr(ui, "timeline", None)
    if store is None:
        store = timeline_model.Timeline()
        ui.timeline = store

    win = tk.Toplevel(ui.root)
    win.title("Activity")
    win.configure(bg=colors["bg"])
    win.transient(ui.root)
    win.geometry("460x320")

    tk.Label(win, text="ACTIVITY", fg=colors["pri"], bg=colors["bg"],
             font=("Courier", 11, "bold")).pack(anchor="w", padx=12,
                                                pady=(10, 4))

    body = tk.Frame(win, bg=colors["bg"])
    body.pack(fill="both", expand=True, padx=8, pady=4)

    empty = tk.Label(body, text="No activity yet.", fg=colors["dim"],
                     bg=colors["bg"], font=("Courier", 9))
    empty.pack(anchor="w", padx=8, pady=8)

    def refresh() -> None:
        for child in body.winfo_children():
            child.destroy()
        if not store.steps:
            tk.Label(body, text="No activity yet.", fg=colors["dim"],
                     bg=colors["bg"], font=("Courier", 9)).pack(
                anchor="w", padx=8, pady=8)
            return
        for step, line in zip(store.steps, store.lines()):
            row = tk.Frame(body, bg=colors["bg"])
            row.pack(fill="x", pady=1)
            tk.Label(row, text=line, fg=colors["text"], bg=colors["bg"],
                     anchor="w", font=("Courier", 9),
                     justify="left").pack(side="left", fill="x", expand=True)
            if step["status"] in (timeline_model.PENDING,
                                  timeline_model.RUNNING):
                tk.Button(
                    row, text="Cancel",
                    command=lambda s=step: (store.cancel(s["id"]),
                                            refresh()),
                    bg=colors["panel"], fg=colors["red"],
                    relief="flat", font=("Courier", 8), cursor="hand2",
                ).pack(side="right", padx=4)

    buttons = tk.Frame(win, bg=colors["bg"])
    buttons.pack(fill="x", padx=12, pady=(0, 10))
    tk.Button(buttons, text="Clear finished",
              command=lambda: (store.clear_finished(), refresh()),
              bg=colors["panel"], fg=colors["text"], relief="flat",
              font=("Courier", 9), cursor="hand2").pack(side="left")
    tk.Button(buttons, text="Close", command=win.destroy,
              bg=colors["panel"], fg=colors["text"], relief="flat",
              font=("Courier", 9), cursor="hand2").pack(side="right")

    refresh()
    return win
