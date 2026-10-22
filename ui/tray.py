"""T3.1 — the system tray icon.

Optional by design. JARVIS is a voice-first assistant and the HUD is the real
interface; the tray only makes the window closable and re-openable without
digging through the taskbar. Nothing here is allowed to break start-up:

* missing ``pystray``/Pillow, a non-Windows session or ``JARVIS_NO_TRAY=1``
  simply means no tray,
* the icon runs on its own thread, and every callback is marshalled back to the
  Tk thread with ``root.after`` (Tk is not thread-safe),
* stopping the icon never raises.

The icon is drawn, not loaded from an asset, so a frozen build has no extra file
to miss.
"""

from __future__ import annotations

import os
import sys
import threading

NAME = "J.A.R.V.I.S."


def available() -> bool:
    """True when a tray icon can actually be shown on this machine."""
    if sys.platform != "win32":
        return False
    if os.environ.get("JARVIS_NO_TRAY"):
        return False
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def icon_image(size: int = 64):
    """A small arc-reactor mark, drawn at any size (T3.25: no asset file)."""
    from PIL import Image, ImageDraw

    size = max(16, int(size))
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(2, size // 12)
    cyan = (0, 229, 255, 255)
    dim = (0, 130, 160, 255)

    draw.ellipse((pad, pad, size - pad, size - pad), outline=cyan,
                 width=max(1, size // 16))
    inner = size // 4
    draw.ellipse((inner, inner, size - inner, size - inner), outline=dim,
                 width=max(1, size // 24))
    core = size // 2
    r = max(2, size // 10)
    draw.ellipse((core - r, core - r, core + r, core + r), fill=cyan)
    return img


class Tray:
    """A tray icon bound to a :class:`ui.JarvisUI` instance."""

    def __init__(self, ui):
        self.ui = ui
        self._icon = None
        self._thread = None

    def start(self) -> bool:
        if not available():
            return False
        try:
            import pystray

            menu = pystray.Menu(
                pystray.MenuItem("Show J.A.R.V.I.S.", self._show, default=True),
                pystray.MenuItem("Hide", self._hide),
                pystray.MenuItem("Settings…", self._settings),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            )
            self._icon = pystray.Icon(NAME, icon_image(), NAME, menu)
            self._thread = threading.Thread(
                target=self._run, name="JarvisTray", daemon=True
            )
            self._thread.start()
            return True
        except Exception:
            self._icon = None
            return False

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:
            pass

    def stop(self) -> None:
        try:
            if self._icon is not None:
                self._icon.stop()
        except Exception:
            pass
        self._icon = None

    # --- callbacks: tray thread -> Tk thread --------------------------------

    def _call(self, fn) -> None:
        try:
            self.ui.root.after(0, fn)
        except Exception:
            pass

    def _show(self, *_args) -> None:
        self._call(self.ui.show_from_tray)

    def _hide(self, *_args) -> None:
        self._call(self.ui.hide_to_tray)

    def _settings(self, *_args) -> None:
        self._call(self.ui.open_settings)

    def _quit(self, *_args) -> None:
        self._call(self.ui._on_close)


def start(ui) -> Tray:
    """Create and start a tray when possible; always return a usable object."""
    tray = Tray(ui)
    tray.start()
    return tray
