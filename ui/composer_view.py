"""Tier 3.7 — a text composer floating over the HUD.

Voice-first is not voice-only: dictation fails in a noisy room, and some commands
are easier to type. The composer is a small Toplevel with history navigation and
slash commands; it hands the final text to whatever `on_text_input` the app
connected (main.py points it at `JarvisLive.speak`).
"""

from __future__ import annotations

import tkinter as tk

from ui import composer as composer_model


def build(ui):
    try:
        from ui import theme
        colors = theme.palette()
    except Exception:
        colors = {"bg": "#000000", "panel": "#010c10", "text": "#8ffcff",
                  "pri": "#00d4ff", "dim": "#003344"}

    win = tk.Toplevel(ui.root)
    win.title("Command")
    win.configure(bg=colors["bg"])
    win.transient(ui.root)
    win.resizable(True, False)
    history = composer_model.History()

    entry = tk.Entry(win, bg=colors["panel"], fg=colors["text"],
                     insertbackground=colors["text"], relief="flat",
                     font=("Courier", 11), width=60)
    entry.pack(fill="x", padx=12, pady=(12, 6))
    try:
        entry.focus_set()
    except Exception:
        pass

    hint = tk.Label(win, text="Enter to send · ↑/↓ history · Esc to close",
                    fg=colors["dim"], bg=colors["bg"], font=("Courier", 8))
    hint.pack(anchor="w", padx=12, pady=(0, 10))

    def submit(_event=None):
        text = composer_model.normalise(entry.get())
        if not text:
            return "break"
        name, rest = composer_model.parse_command(text)
        if name == "kill":
            ui.engage_kill_switch(rest or "text command")
            win.destroy()
            return "break"
        if name == "quit":
            win.destroy()
            return "break"
        history.add(text)
        entry.delete(0, "end")
        try:
            ui.submit_text(text)
        except Exception as exc:
            ui.jarvis_think("err", f"text input failed: {exc}")
        win.destroy()
        return "break"

    def previous(_event=None):
        entry.delete(0, "end")
        entry.insert(0, history.previous())
        return "break"

    def following(_event=None):
        entry.delete(0, "end")
        entry.insert(0, history.next())
        return "break"

    def close(_event=None):
        win.destroy()
        return "break"

    entry.bind("<Return>", submit)
    entry.bind("<Up>", previous)
    entry.bind("<Down>", following)
    win.bind("<Escape>", close)
    return win
