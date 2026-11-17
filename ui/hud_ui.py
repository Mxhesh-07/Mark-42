"""Tier 4 - drive the MK-LXXXV web HUD from the assistant.

The Tkinter HUD in :mod:`ui` is the control surface: it owns the transcript, the
typed-input box, the confirmation dialogs and the tray icon. This subclass keeps
all of that, hides the Tk window, and mirrors the parts a viewer should see onto
the cinematic web HUD in ``hud_mk85/``:

    microphone level  -> the reactor bloom and the VOICE meter
    speaking          -> SPEAK, plus the subtitle glow
    your last words   -> the YOU line
    the live reply    -> the J.A.R.V.I.S line, streaming

Nothing here is required for JARVIS to work. If the bridge cannot bind or no
browser can be found, the base class is left visible and the session runs
exactly as before.

Why a subclass: ``main.py`` talks to ~70 methods on ``ui``. Re-implementing that
surface against a web page would be a rewrite with no upside, and the Tk widgets
still have to exist for the confirmation modal and the tray.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ui import JarvisUI

HUD_DIR = Path(__file__).resolve().parent.parent / "hud_mk85"
DEFAULT_PORT = 8787

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Where the app-mode window goes. Chrome/Edge accept these only in app mode.
_WINDOW_W, _WINDOW_H = 1536, 960

# Microphone RMS above this reads as "someone is talking". main.py scales the
# level by 1/5000, so this is roughly room tone + a little.
LISTEN_LEVEL = 0.07

_BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _find_browser() -> str | None:
    """Chrome first, then Edge; PATH lookup last. None means 'no HUD window'."""
    for path in _BROWSERS:
        if os.path.isfile(path):
            return path
    for name in ("chrome", "msedge", "chromium", "brave"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _open_app_window(browser: str, url: str, w: int, h: int) -> subprocess.Popen | None:
    """Open the HUD as a chromeless window and return the process handle."""
    profile = Path(os.environ.get("TEMP", ".")) / "jarvis-hud-profile"
    args = [
        browser,
        f"--app={url}",
        f"--window-size={w},{h}",
        "--window-position=0,0",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--autoplay-policy=no-user-gesture-required",
    ]
    try:
        return subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:  # pragma: no cover - depends on the machine
        print(f"[HUD] could not open the browser: {e}")
        return None


def _close_stale_hud(port: int) -> int:
    """Close HUD windows left over from a previous run on the same port.

    Chrome hands a second ``--app`` launch to the already-running instance for
    that profile, which opens *another* window instead of replacing the old one.
    The old window is bound to a bridge that no longer exists (it shows a dead
    board), so a restart would otherwise leave two HUDs stacked at 0,0.
    """
    marker = f"--app=http://127.0.0.1:{port}"
    closed = 0
    try:
        import psutil
    except Exception:
        return 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if marker in cmd and proc.info["pid"] != os.getpid():
                proc.terminate()
                closed += 1
        except Exception:
            continue
    return closed


class HudUI(JarvisUI):
    """JarvisUI that publishes to ``hud_mk85`` and hides the Tk window."""

    def __init__(self, face_path, size=None, *, port: int = DEFAULT_PORT,
                 open_window: bool = True):
        super().__init__(face_path, size)
        self._bridge = None
        self._port = port
        self._browser_proc = None
        self._hud_live = False
        self._last_mic_push = 0.0
        self._reply_buf = ""
        self._turn = 0
        self._thinking = False
        self._awaiting_reply = False
        self._last_status = "IDLE"
        self._lock = threading.Lock()

        self._start_bridge()
        if open_window:
            self._open_hud()
        # Hide the Tk window only once something else is on screen; otherwise
        # the user would be staring at the desktop wondering what happened.
        if self._hud_live:
            self._withdraw()

    # -- plumbing ---------------------------------------------------------- #
    def _start_bridge(self) -> None:
        """Serve the HUD and /state from this process, on loopback only."""
        try:
            sys.path.insert(0, str(HUD_DIR))
            import telemetry  # noqa: WPS433 - local import keeps startup cheap

            httpd, sampler = telemetry.start(self._port)
            self._bridge = (httpd, sampler)
            # Announced only once the bridge is actually listening; until then
            # the page must be able to tell "no bridge" from "quiet room".
            telemetry.publish(status="IDLE", mic=0.0, you="", jarvis="", turn=0)
            print(f"[HUD] bridge on http://127.0.0.1:{self._port}/")
        except OSError as e:
            # Another bridge already owns the port. The page still gets live
            # telemetry from it, but voice state would be split across two
            # processes - so say so instead of silently showing a dead meter.
            print(f"[HUD] port {self._port} already in use ({e}); "
                  "the HUD will not receive voice state")
            self._bridge = None
        except Exception as e:
            print(f"[HUD] bridge unavailable: {e}")
            self._bridge = None

    def _open_hud(self) -> None:
        browser = _find_browser()
        url = f"http://127.0.0.1:{self._port}/"
        if not browser:
            print("[HUD] no Chrome/Edge found; keeping the native window")
            return
        # A window from a previous run would be handed the new URL by Chrome and
        # end up stacked on top of the new one, pointing at a dead board.
        stale = _close_stale_hud(self._port)
        if stale:
            print(f"[HUD] closed {stale} stale HUD window(s) from a previous run")
            time.sleep(0.4)          # let the old process release the profile
        # Give the sampler a beat so the first paint is not all placeholders.
        proc = _open_app_window(browser, url, _WINDOW_W, _WINDOW_H)
        if proc is None:
            return
        self._browser_proc = proc
        self._hud_live = True

    def _withdraw(self) -> None:
        try:
            self.root.withdraw()
        except Exception:
            pass

    def _publish(self, **kw) -> None:
        """Best-effort; the HUD must never break a turn."""
        if self._bridge is None:
            return
        try:
            import telemetry

            telemetry.publish(**kw)
        except Exception:
            pass

    def _push_mic(self, level: float) -> None:
        # Called per audio chunk (~20-60 ms). The page reads at ~8 Hz, so
        # throttle the write instead of taking the lock on every chunk.
        now = time.time()
        if now - self._last_mic_push < 0.06:
            return
        self._last_mic_push = now
        level = max(0.0, min(1.0, level))

        # LISTEN is not a separate signal from main.py: it is simply "there is
        # speech energy and the assistant is not busy", which the microphone
        # level already answers. Below the threshold the room is quiet.
        if not self.speaking and not self._thinking:
            status = "LISTEN" if level >= LISTEN_LEVEL else "IDLE"
            if status != self._last_status:
                self._last_status = status
                self._publish(mic=round(level, 3), status=status)
                return
        self._publish(mic=round(level, 3))

    # -- display methods overridden --------------------------------------- #
    def set_persona(self, name: str) -> str:
        """Switch protocol on the HUD; the palette transition does the rest."""
        key = super().set_persona(name)
        if key:
            self._publish(persona=key)
        return key

    def update_mic_level(self, level):
        super().update_mic_level(level)
        self._push_mic(level)

    def start_speaking(self):
        super().start_speaking()
        self._thinking = False
        self._last_status = "SPEAK"
        self._publish(status="SPEAK", speaking=True, thinking=False, mic=0.0)

    def stop_speaking(self):
        super().stop_speaking()
        self._thinking = False
        self._last_status = "IDLE"
        self._publish(status="IDLE", speaking=False, thinking=False)

    def write_log(self, text: str):
        super().write_log(text)
        body = (text or "").strip()
        low = body.lower()
        if low.startswith("you:"):
            said = body[4:].strip()
            if said:
                self._awaiting_reply = bool(said)
                self._thinking = True
                self._last_status = "THINK"
                self._publish(you=said, status="THINK", thinking=True)
        elif low.startswith("jarvis:"):
            said = body[7:].strip()
            if said:
                if self._awaiting_reply:
                    self._awaiting_reply = False
                    self._turn += 1
                self._publish(jarvis=said, turn=self._turn)

    def stream_jarvis_text(self, text: str):
        super().stream_jarvis_text(text)
        frag = (text or "").strip()
        if not frag:
            return
        with self._lock:
            # The first fragment of a reply starts a new sentence; anything
            # after that is the same thought still arriving.
            if not self._reply_buf:
                self._reply_buf = frag
            else:
                self._reply_buf = (self._reply_buf + " " + frag)[-240:]
            line = self._reply_buf
        self._publish(jarvis=line)

    def jarvis_think(self, kind: str, text: str):
        super().jarvis_think(kind, text)
        # A user turn lands here once Gemini commits it; the reply is on its way.
        if kind == "in":
            self._reply_buf = ""
            self._thinking = True
            self._last_status = "THINK"
            self._publish(you=(text or "").strip(), status="THINK", thinking=True)

    # -- lifecycle --------------------------------------------------------- #
    def close_hud(self) -> None:
        proc = self._browser_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        httpd, sampler = self._bridge or (None, None)
        try:
            if sampler is not None:
                sampler.stop()
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
        except Exception:
            pass
        self._bridge = None

    def _on_close(self):  # noqa: D401 - mirrors the base hook
        self.close_hud()
        super()._on_close()
