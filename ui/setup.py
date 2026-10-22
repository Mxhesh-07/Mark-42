"""Tier 3.3 — the API-key setup panel, out of the main HUD class.

Kept separate so `JarvisUI` is not the place every dialog is born. The panel
still uses the HUD's palette, and saving is the only side effect.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
API_FILE = CONFIG_DIR / "api_keys.json"


def save_key(key: str) -> bool:
    key = (key or "").strip()
    if not key:
        return False
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = API_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"gemini_api_key": key}, indent=4),
                   encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, API_FILE)
    return True


def build(ui):
    """Create the panel on `ui.root`; returns the frame it placed."""
    import tkinter as tk

    frame = tk.Frame(ui.root, bg="#00080d",
                     highlightbackground="#00d4ff", highlightthickness=1)
    frame.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(frame, text="◈  INITIALISATION REQUIRED",
             fg="#00d4ff", bg="#00080d",
             font=("Courier", 13, "bold")).pack(pady=(18, 4))
    tk.Label(frame, text="Enter your Gemini API key to boot J.A.R.V.I.S.",
             fg="#007a99", bg="#00080d",
             font=("Courier", 9)).pack(pady=(0, 10))
    tk.Label(frame, text="GEMINI API KEY", fg="#003344", bg="#00080d",
             font=("Courier", 9)).pack(pady=(8, 2))

    entry = tk.Entry(frame, width=52, fg="#8ffcff", bg="#000d12",
                     insertbackground="#8ffcff", borderwidth=0,
                     font=("Courier", 10), show="*")
    entry.pack(pady=(0, 4))

    def submit():
        if save_key(entry.get()):
            ui.setup_frame.destroy()
            ui._api_key_ready = True
            ui.status_text = "ONLINE"
            ui.write_log("SYS: Systems initialised. JARVIS online.")

    tk.Button(frame, text="▸  INITIALISE SYSTEMS", command=submit,
              bg="#000000", fg="#00d4ff", activebackground="#003344",
              font=("Courier", 10), borderwidth=0, pady=8).pack(pady=14)

    return frame, entry
