"""The small, thread-safe state board the web HUD reads.

``main.py`` and the Tk control surface run on their own threads; the browser
polls over HTTP. Everything that crosses that boundary is a plain dict of JSON
values, so neither side needs to know anything about the other.

One lock, one revision counter:

    state.update(status="LISTEN", mic=0.21)
    state.snapshot()          # {"rev": 7, "status": "LISTEN", ...}

The revision lets the page skip a repaint when nothing changed. It is not a
guarantee: a polling client asks for the newest board and gets it, coalesced.
"""

from __future__ import annotations

import threading
import time
from collections import deque

# Everything the page may read. Missing keys are simply absent from JSON; the
# client treats them as "unchanged", so adding a key here is backwards-safe.
_DEFAULTS = {
    "status": "STANDBY",     # STANDBY / LISTEN / THINK / SPEAK / ERROR / OFFLINE
    "mic": 0.0,              # 0..1 RMS of the live microphone
    "speaking": False,
    "thinking": False,
    "connected": False,
    "recording": False,
    "muted": False,
    "you": "",               # last user turn (transcript)
    "jarvis": "",            # live reply, streamed
    "turn": 0,
    "log": [],               # [{role, text, ts}] oldest first, capped
    "tasks": [],
    "memory": "",
    "agent": {"name": "Planner", "state": "IDLE"},
    "actions": [],           # action loop events [{name, status, detail, ts}]
    "confirm": None,         # pending approval modal: panel dict + id, expires
    "telemetry": {},
    "error": "",
}

_MAX_LOG = 120
_MAX_ACTIONS = 40


class WebState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rev = 0
        self._data = dict(_DEFAULTS)
        self._log = deque(maxlen=_MAX_LOG)
        self._actions = deque(maxlen=_MAX_ACTIONS)
        self._started = time.time()

    # -- writes ------------------------------------------------------------ #
    def update(self, **kw) -> None:
        """Merge keys into the board. Unknown keys are kept (forward-compat)."""
        with self._lock:
            for key, value in kw.items():
                self._data[key] = value
            self._rev += 1

    def log(self, text: str) -> None:
        """Append one transcript/log line, classifying it by its prefix.

        ``main.py`` already writes "You: ...", "Jarvis: ..." and free-form
        system lines to the Tk UI; the page gets the same stream, tagged.
        """
        body = (text or "").strip()
        if not body:
            return
        low = body.lower()
        if low.startswith("you:"):
            role, body = "you", body[4:].strip()
        elif low.startswith("jarvis:"):
            role, body = "jarvis", body[7:].strip()
        elif low.startswith("ai:"):
            role, body = "jarvis", body[3:].strip()
        else:
            role = "sys"
        with self._lock:
            self._log.append({"role": role, "text": body, "ts": time.time()})
            self._data["log"] = list(self._log)
            self._rev += 1

    def action(self, name: str, status: str = "RUN", detail: str = "") -> None:
        """Record one step of the action loop for the right-hand panel."""
        with self._lock:
            self._actions.append({
                "name": str(name)[:80],
                "status": str(status)[:16].upper(),
                "detail": str(detail)[:160],
                "ts": time.time(),
            })
            self._data["actions"] = list(self._actions)
            self._rev += 1

    # -- reads ------------------------------------------------------------- #
    def snapshot(self) -> dict:
        with self._lock:
            out = dict(self._data)
            out["rev"] = self._rev
            out["uptime"] = round(time.time() - self._started, 1)
            out["ts"] = time.time()
            return out

    @property
    def rev(self) -> int:
        with self._lock:
            return self._rev
