"""Tier 3.8 — transcript viewer with search and export.

Reads the session transcript the HUD already records in `JarvisUI.write_log`.
Search filters in place; export writes `.txt` or `.json` next to the repo (the
dialog defaults to the user's home, not a hidden folder).
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path


def build(ui):
    try:
        from ui import theme
        colors = theme.palette()
    except Exception:
        colors = {"bg": "#000000", "panel": "#010c10", "text": "#8ffcff",
                  "pri": "#00d4ff", "dim": "#003344"}

    store = getattr(ui, "_transcript", None)
    if store is None:
        from ui.transcript import Transcript
        store = Transcript()
        ui._transcript = store

    win = tk.Toplevel(ui.root)
    win.title("Transcript")
    win.configure(bg=colors["bg"])
    win.transient(ui.root)
    win.geometry("720x460")

    top = tk.Frame(win, bg=colors["bg"])
    top.pack(fill="x", padx=10, pady=(10, 4))
    tk.Label(top, text="Search", fg=colors["text"], bg=colors["bg"],
             font=("Courier", 9)).pack(side="left")
    query = tk.Entry(top, bg=colors["panel"], fg=colors["text"],
                     insertbackground=colors["text"], relief="flat",
                     font=("Courier", 9))
    query.pack(side="left", fill="x", expand=True, padx=8)

    body = tk.Text(win, bg=colors["panel"], fg=colors["text"],
                   insertbackground=colors["text"], borderwidth=0,
                   wrap="word", font=("Courier", 9), padx=8, pady=6)
    body.pack(fill="both", expand=True, padx=10, pady=6)
    body.configure(state="disabled")

    def render(rows):
        body.configure(state="normal")
        body.delete("1.0", "end")
        lines = [f"[{row['time']}] {row['role']}: {row['text']}" for row in rows]
        if not lines:
            try:
                from ui.widgets import empty_state
                lines = [empty_state("recordings")]
            except Exception:
                lines = ["No transcript yet."]
        body.insert("1.0", "\n".join(lines))
        body.configure(state="disabled")

    def on_search(_event=None):
        term = query.get().strip()
        render(store.search(term, limit=500) if term else store.rows)

    query.bind("<KeyRelease>", on_search)

    buttons = tk.Frame(win, bg=colors["bg"])
    buttons.pack(fill="x", padx=10, pady=(0, 10))

    def export(fmt: str):
        try:
            base = Path.home() / f"jarvis-transcript.{fmt}"
            target = store.export(base, fmt=fmt)
            ui.jarvis_think("sys", f"transcript exported: {target}")
        except Exception as exc:
            ui.jarvis_think("err", f"transcript export failed: {exc}")

    tk.Button(buttons, text="Export .txt", command=lambda: export("txt"),
              bg=colors["panel"], fg=colors["pri"], relief="flat",
              font=("Courier", 9), cursor="hand2").pack(side="left")
    tk.Button(buttons, text="Export .json", command=lambda: export("json"),
              bg=colors["panel"], fg=colors["pri"], relief="flat",
              font=("Courier", 9), cursor="hand2").pack(side="left", padx=8)
    tk.Button(buttons, text="Close", command=win.destroy,
              bg=colors["panel"], fg=colors["text"], relief="flat",
              font=("Courier", 9), cursor="hand2").pack(side="right")

    render(store.rows)
    return win
