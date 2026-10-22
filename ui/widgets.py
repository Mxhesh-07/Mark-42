"""Tier 3.26 / T3.27 / T3.28 / T3.24 — small shared widget helpers.

These are additive: nothing here is imported by the existing layout code until
a widget opts in. The goal is that the next UI change does not have to invent
another tooltip, empty state or font tuple.
"""

from __future__ import annotations

import tkinter as tk

try:
    from ui.theme import font as theme_font, palette
except Exception:  # pragma: no cover
    def theme_font(size=10, *, bold=False):
        return ("Courier", size, "bold") if bold else ("Courier", size)

    def palette():
        return {"pri": "#00d4ff", "dim": "#003344", "panel": "#010c10"}


EMPTY_STATES = {
    "tasks": "No tasks yet — ask JARVIS to do something.",
    "memory": "Memory is empty — it fills as you talk.",
    "thinking": "No activity yet.",
    "audit": "No audit entries yet.",
    "recordings": "No recordings yet.",
}


def empty_state(kind: str) -> str:
    return EMPTY_STATES.get(kind, "Nothing here yet.")


class Tooltip:
    """A one-widget tooltip. Tk has none built in, and the HUD labels need one.

    Deliberately tiny: a label in a Toplevel, shown after `delay` ms on enter and
    destroyed on leave. Exceptions are swallowed so a tooltip can never break the
    widget it decorates.
    """

    def __init__(self, widget, text: str, delay: int = 450):
        self.widget = widget
        self.text = str(text)
        self.delay = int(delay)
        self._job = None
        self._tip = None
        try:
            widget.bind("<Enter>", self._schedule, add="+")
            widget.bind("<Leave>", self._hide, add="+")
            widget.bind("<ButtonPress>", self._hide, add="+")
        except Exception:
            pass

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._job = self.widget.after(self.delay, self._show)
        except Exception:
            self._job = None

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tip = tk.Toplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(tip, text=self.text, justify="left",
                             background="#001520", foreground="#8ffcff",
                             relief="solid", borderwidth=1,
                             font=theme_font(9), padx=6, pady=3)
            label.pack()
            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


def enable_copy(text_widget) -> None:
    """T3.28: Ctrl+C / Ctrl+A that keep working on a read-only Text.

    A disabled Text still shows a selection but does not copy it on every
    platform; these bindings make the panes behave like logs should.
    """
    def _copy(_event=None):
        try:
            selected = text_widget.get("sel.first", "sel.last")
        except Exception:
            selected = ""
        if selected:
            try:
                text_widget.clipboard_clear()
                text_widget.clipboard_append(selected)
            except Exception:
                pass
        return "break"

    def _select_all(_event=None):
        try:
            text_widget.tag_add("sel", "1.0", "end-1c")
            return "break"
        except Exception:
            return None

    try:
        text_widget.bind("<Control-c>", _copy, add="+")
        text_widget.bind("<Control-C>", _copy, add="+")
        text_widget.bind("<Control-a>", _select_all, add="+")
        text_widget.bind("<Control-A>", _select_all, add="+")
    except Exception:
        pass
