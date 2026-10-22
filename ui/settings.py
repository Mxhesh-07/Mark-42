"""Tier 3.2 — settings window.

A small Toplevel rather than another screen in the main window. It exposes only
things that are safe to change at runtime: theme, optional cues, the kill switch
and a read-only status view. API keys stay in the setup flow and config files;
this dialog never displays a secret.
"""

from __future__ import annotations

import tkinter as tk


def build(ui) -> tk.Toplevel:
    from ui import support, theme, widgets

    colors = theme.palette()
    win = tk.Toplevel(ui.root)
    win.title("Settings")
    win.configure(bg=colors["bg"])
    win.resizable(False, False)
    win.transient(ui.root)

    tk.Label(win, text="SETTINGS", fg=colors["pri"], bg=colors["bg"],
             font=theme.font(12, bold=True)).pack(anchor="w", padx=14, pady=(12, 6))

    # --- theme ---
    row = tk.Frame(win, bg=colors["bg"])
    row.pack(fill="x", padx=14, pady=4)
    tk.Label(row, text="Theme", fg=colors["text"], bg=colors["bg"],
             font=theme.font(9)).pack(side="left")
    choice = tk.StringVar(value=theme.configured_name())
    menu = tk.OptionMenu(row, choice, *theme.available(),
                         command=lambda _v: None)
    menu.configure(bg=colors["panel"], fg=colors["text"],
                   activebackground=colors["dim"], font=theme.font(9),
                   highlightthickness=0)
    menu.pack(side="right")

    def _save_theme() -> None:
        name = choice.get()
        if theme.save_theme(name):
            ui.jarvis_think("sys", f"theme saved: {name} (applies on restart)")
        else:
            ui.jarvis_think("err", f"theme not saved: {name}")

    tk.Button(win, text="Save theme", command=_save_theme,
              bg=colors["panel"], fg=colors["pri"], font=theme.font(9),
              relief="flat", cursor="hand2").pack(anchor="e", padx=14)

    # --- cues ---
    cues_var = tk.BooleanVar(value=_cues_enabled())
    tk.Checkbutton(win, text="Audio cues (off by default)",
                   variable=cues_var, command=lambda: _save_cues(cues_var.get()),
                   fg=colors["text"], bg=colors["bg"], selectcolor=colors["panel"],
                   activebackground=colors["bg"], activeforeground=colors["text"],
                   font=theme.font(9)).pack(anchor="w", padx=14, pady=(8, 2))

    # --- click-through (T3.19) ---
    ct_var = tk.BooleanVar(value=False)

    def _toggle_click_through() -> None:
        actual = ui.toggle_click_through()
        ct_var.set(bool(actual))

    tk.Checkbutton(win, text="Click-through (Windows only)",
                   variable=ct_var, command=_toggle_click_through,
                   fg=colors["text"], bg=colors["bg"], selectcolor=colors["panel"],
                   activebackground=colors["bg"], activeforeground=colors["text"],
                   font=theme.font(9)).pack(anchor="w", padx=14, pady=2)

    # --- kill switch ---
    kill = support.kill_state()
    tk.Label(win, text=kill.get("label", ""), fg=colors["red"] if kill.get("engaged") else colors["green"],
             bg=colors["bg"], font=theme.font(9, bold=True)).pack(anchor="w", padx=14, pady=(10, 2))
    buttons = tk.Frame(win, bg=colors["bg"])
    buttons.pack(anchor="w", padx=14, pady=(0, 8))
    tk.Button(buttons, text="Engage kill switch",
              command=lambda: (ui.engage_kill_switch("settings"),
                               win.destroy()),
              bg=colors["panel"], fg=colors["red"], font=theme.font(9),
              relief="flat", cursor="hand2").pack(side="left")
    tk.Button(buttons, text="Release…", command=ui.release_kill_switch,
              bg=colors["panel"], fg=colors["pri"], font=theme.font(9),
              relief="flat", cursor="hand2").pack(side="left", padx=8)

    # --- hologram (T3.20) ---
    try:
        from ui import hologram_control
        models = hologram_control.models()
        holo_row = tk.Frame(win, bg=colors["bg"])
        holo_row.pack(anchor="w", padx=14, pady=(4, 2))
        tk.Label(holo_row, text="Hologram", fg=colors["text"], bg=colors["bg"],
                 font=theme.font(9)).pack(side="left")
        holo_choice = tk.StringVar(value=models[0] if models else "")
        holo_menu = tk.OptionMenu(holo_row, holo_choice, *(models or [""]))
        holo_menu.configure(bg=colors["panel"], fg=colors["text"],
                           activebackground=colors["dim"], font=theme.font(9),
                           highlightthickness=0)
        holo_menu.pack(side="left", padx=8)
        tk.Label(win, text=hologram_control.status_line(), fg=colors["dim"],
                 bg=colors["bg"], font=theme.font(8)).pack(anchor="w", padx=14)

        def _launch() -> None:
            name = holo_choice.get()
            if name:
                ui.hologram_launch(name)

        holo_buttons = tk.Frame(win, bg=colors["bg"])
        holo_buttons.pack(anchor="w", padx=14, pady=(2, 8))
        tk.Button(holo_buttons, text="Launch", command=_launch,
                  bg=colors["panel"], fg=colors["pri"], font=theme.font(9),
                  relief="flat", cursor="hand2").pack(side="left")
        tk.Button(holo_buttons, text="Close", command=ui.hologram_close,
                  bg=colors["panel"], fg=colors["text"], font=theme.font(9),
                  relief="flat", cursor="hand2").pack(side="left", padx=8)
    except Exception:
        pass

    # --- status (read only) ---
    status = tk.Label(win, text=support.status_text(), fg=colors["dim"],
                      bg=colors["bg"], font=theme.font(8), justify="left",
                      wraplength=420)
    status.pack(anchor="w", padx=14, pady=(4, 12))

    try:
        widgets.Tooltip(menu, "Theme changes apply the next time the HUD opens.")
    except Exception:
        pass

    return win


def _cues_enabled() -> bool:
    try:
        from ui import cues
        return cues.enabled()
    except Exception:
        return False


def _save_cues(on: bool) -> bool:
    try:
        import json
        from ui import cues

        data = {}
        try:
            data = json.loads(cues.CONFIG.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        data["cues"] = bool(on)
        cues.CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = cues.CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(cues.CONFIG)
        return True
    except Exception:
        return False
