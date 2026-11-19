"""The J.A.R.V.I.S. interface: the ULTRON-derived web HUD, driven from Python.

``main.py`` talks to ~70 methods on ``ui``; the Tk HUD still owns the
confirmation modal, the tray and the transcript history. This subclass keeps
all of that machinery, hides the Tk window, and puts the web page in front:

    microphone level  -> the globe swell, the VOICE meter, the waveform ring
    speaking          -> the SPEAK state, the ring, the status line
    your last words   -> the YOU line
    the live reply    -> the J.A.R.V.I.S. line, streaming
    tasks / memory    -> the side panels
    action loop       -> the action log
    confirmations     -> an approval modal, in place of the Tk dialog

The page is served by ``ui.web.bridge`` on loopback. If the port cannot bind or
no browser exists, the Tk window stays visible and the session is unchanged —
the HUD is never allowed to be a single point of failure. If the HUD is live,
``ui.confirm``'s presenter is swapped for the page's modal; if the page stops
answering, the wait times out and the request is denied, exactly as before.

Typed input and the stop/mute buttons come back through the same bridge as a
command queue, which this class drains on the Tk thread. Nothing from HTTP
touches the assistant directly.
"""

from __future__ import annotations

import os
import threading
import time

from ui import JarvisUI
from ui.hud_ui import (_WINDOW_H, _WINDOW_W, _close_stale_hud, _find_browser,
                       _open_app_window)
from ui.web.bridge import Bridge
from ui.web.state import WebState

DEFAULT_PORT = 8790

# main.py scales RMS by 1/5000; this is roughly room tone plus a little.
LISTEN_LEVEL = 0.07


class WebUI(JarvisUI):
    """JarvisUI that publishes to the web HUD and hides the Tk window."""

    def __init__(self, face_path, size=None, *, port: int = DEFAULT_PORT,
                 open_window: bool = True):
        super().__init__(face_path, size)

        self._state = WebState()
        self._bridge: Bridge | None = None
        self._browser_proc = None
        self._hud_live = False
        self._port = port
        self._last_mic_push = 0.0
        self._last_status = "STANDBY"
        self._reply_buf = ""
        self._awaiting_reply = False
        self._thinking = False

        # Pending confirmations, keyed by a short id the page echoes back. The
        # worker thread that asked is parked on an Event inside ui.confirm; this
        # class only moves the answer across.
        self._confirm_lock = threading.Lock()
        self._confirms: dict[str, tuple] = {}
        self._confirm_seq = 0
        self._confirm_current = None

        # main.py wires these two to the live session; if it does not, the
        # buttons degrade to no-ops instead of raising.
        self.on_interrupt = None      # () -> None
        self.on_mute = None           # (bool) -> None
        self.on_quit = None           # () -> None
        self.muted = False
        self._quitting = False

        self._start_bridge()
        if open_window and not os.environ.get("JARVIS_NO_HUD_WINDOW") \
                and self._bridge is not None:
            self._open_hud()
        if self._hud_live:
            self._withdraw()
            self._install_confirm()
        self.root.after(120, self._pump_commands)

    # -- plumbing ---------------------------------------------------------- #
    def _start_bridge(self) -> None:
        try:
            self._bridge = Bridge(self._state, port=self._port).start()
            self._port = self._bridge.port
            self._publish(status="STANDBY", mic=0.0, you="", jarvis="", turn=0,
                          connected=False)
            print(f"[HUD] web interface on {self._bridge.url}")
        except OSError as e:
            print(f"[HUD] port {self._port} unavailable ({e}); "
                  "keeping the native window")
            self._bridge = None
        except Exception as e:
            print(f"[HUD] bridge unavailable: {e}")
            self._bridge = None

    def _open_hud(self) -> None:
        browser = _find_browser()
        if not browser or self._bridge is None:
            print("[HUD] no Chrome/Edge found; keeping the native window")
            return
        stale = _close_stale_hud(self._port)
        if stale:
            print(f"[HUD] closed {stale} stale HUD window(s) from a previous run")
            time.sleep(0.4)          # let the old process release the profile
        proc = _open_app_window(browser, self._bridge.url, _WINDOW_W, _WINDOW_H)
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
            self._state.update(**kw)
        except Exception:
            pass

    def update_machine(self, state: str) -> None:
        """Expose the Phase 2 state machine on ``/api/state``.

        The page keeps using its own status word (it drives the animation),
        so this is additive: older clients simply ignore the extra field.

        It also sweeps up a stale THINK: ``write_log("You: ...")`` publishes
        THINK at turn completion, but a turn with no spoken reply never calls
        ``stop_speaking`` to clear it. Without this, the HUD showed THINK while
        the machine was already ``standby``, and kept showing it over a new
        user turn. The machine is the source of truth for turn boundaries.
        """
        value = str(state or "").lower()
        self._publish(machine=value)
        if self._thinking and not self.speaking and value in ("standby", "listening"):
            self._thinking = False
            shown = "LISTEN" if value == "listening" else "STANDBY"
            self._last_status = shown
            self._publish(status=shown, thinking=False)

    # -- approvals ---------------------------------------------------------- #
    def _install_confirm(self) -> None:
        """Route ui.confirm's modal into the page instead of a Tk Toplevel."""
        try:
            from ui import confirm

            confirm.set_shower(self._web_confirm)
        except Exception as e:
            print(f"[HUD] web confirmation unavailable: {e}")

    def _web_confirm(self, panel: dict, done) -> None:
        """Publish an approval panel; the page answers with its button id.

        Called from the executor's worker thread, so it must not touch Tk. The
        worker is already parked on an Event inside ui.confirm; the answer comes
        back through the bridge queue and is delivered by ``_pump_commands``.
        """
        with self._confirm_lock:
            self._confirm_seq += 1
            cid = f"c{self._confirm_seq}"
            deadline = time.time() + float(panel.get("timeout_s") or 30.0)
            self._confirms[cid] = (done, deadline)
            self._confirm_current = cid
        payload = dict(panel)
        payload["id"] = cid
        payload["expires"] = deadline
        self._publish(confirm=payload)

    def _resolve_confirm(self, cid, decision: str) -> None:
        with self._confirm_lock:
            entry = self._confirms.pop(str(cid or ""), None)
            if self._confirm_current == str(cid or ""):
                self._confirm_current = None
        if entry is None:
            return                     # unknown or already expired: fail closed
        done, _deadline = entry
        self._publish(confirm=None)
        try:
            done(decision)
        except Exception as e:
            print(f"[HUD] confirmation callback failed: {e}")

    def _expire_confirms(self) -> None:
        """Clear a modal the page never answered; ui.confirm denies on timeout."""
        now = time.time()
        cleared = False
        with self._confirm_lock:
            for cid, (_done, deadline) in list(self._confirms.items()):
                if deadline > now:
                    continue
                self._confirms.pop(cid, None)
                if self._confirm_current == cid:
                    self._confirm_current = None
                    cleared = True
        if cleared:
            self._publish(confirm=None)

    def _deny_pending_confirms(self) -> None:
        with self._confirm_lock:
            pending = list(self._confirms.items())
            self._confirms.clear()
            self._confirm_current = None
        for _cid, (done, _deadline) in pending:
            try:
                done("deny")
            except Exception:
                pass

    # -- commands from the page ------------------------------------------- #
    def _pump_commands(self) -> None:
        bridge = self._bridge
        if bridge is not None:
            for cmd in bridge.commands.drain():
                try:
                    self._handle_command(cmd)
                except Exception as e:
                    print(f"[HUD] command failed: {e}")
        try:
            self._expire_confirms()
        except Exception:
            pass
        if self._quitting:
            return
        # A closed/crashed HUD stops polling. Quit from here, never from the
        # HTTP thread, so audio and state are still touched on the Tk thread.
        if bridge is not None:
            try:
                if bridge.hud_lost():
                    self.quit_from_hud()
                    return
            except Exception:
                pass
        try:
            self.root.after(120, self._pump_commands)
        except Exception:
            pass

    def _handle_command(self, cmd: dict) -> None:
        kind = cmd.get("kind")
        if kind == "text":
            text = str(cmd.get("text", ""))
            if text:
                self._publish(you=text, thinking=True, status="THINK")
                self._thinking = True
                self.submit_text(text)
        elif kind == "stop":
            cb = getattr(self, "on_interrupt", None)
            if callable(cb):
                cb()
            self._thinking = False
            self._reply_buf = ""
            self._publish(status="STANDBY", thinking=False, speaking=False,
                          jarvis="")
        elif kind == "mute":
            on = bool(cmd.get("on"))
            self.muted = on
            cb = getattr(self, "on_mute", None)
            if callable(cb):
                cb(on)
            self._publish(muted=on, mic=0.0 if on else self.mic_level)
        elif kind == "confirm":
            self._resolve_confirm(cmd.get("id"), str(cmd.get("decision") or "deny"))
        elif kind == "quit":
            self.quit_from_hud()

    # -- display methods overridden ---------------------------------------- #
    def update_mic_level(self, level):
        super().update_mic_level(level)
        if self.muted:
            level = 0.0
        # Called per audio chunk (~20-60 ms); the page polls at 20 Hz, so
        # throttle the write instead of taking the lock on every chunk.
        now = time.time()
        if now - self._last_mic_push < 0.06:
            return
        self._last_mic_push = now
        level = max(0.0, min(1.0, float(level)))

        if not self.speaking and not self._thinking:
            status = "LISTEN" if level >= LISTEN_LEVEL else "STANDBY"
            if status != self._last_status:
                self._last_status = status
                self._publish(mic=round(level, 3), status=status)
                return
        self._publish(mic=round(level, 3))

    def start_speaking(self):
        super().start_speaking()
        self._thinking = False
        self._last_status = "SPEAK"
        self._publish(status="SPEAK", speaking=True, thinking=False, mic=0.0)

    def stop_speaking(self):
        super().stop_speaking()
        self._thinking = False
        self._last_status = "STANDBY"
        self._publish(status="STANDBY", speaking=False, thinking=False)

    def write_log(self, text: str):
        super().write_log(text)
        self._state.log(text)
        low = (text or "").strip().lower()
        if low.startswith("you:"):
            self._awaiting_reply = True
            self._thinking = True
            self._last_status = "THINK"
            self._publish(you=text[4:].strip(), status="THINK", thinking=True)
        elif low.startswith("[audio]"):
            self._publish(error=text.strip())
        if "jarvis online" in low:
            self.set_connected(True)

    def stream_jarvis_text(self, text: str):
        super().stream_jarvis_text(text)
        frag = (text or "").strip()
        if not frag:
            return
        if not self._reply_buf:
            self._reply_buf = frag
        else:
            self._reply_buf = (self._reply_buf + " " + frag)[-240:]
        self._publish(jarvis=self._reply_buf)

    def jarvis_think(self, kind: str, text: str):
        super().jarvis_think(kind, text)
        if kind == "in":
            self._reply_buf = ""
            self._thinking = True
            self._last_status = "THINK"
            self._publish(you=(text or "").strip(), status="THINK", thinking=True)
        elif kind == "err" and text and "connection" in text.lower():
            self.set_connected(False)

    def set_persona(self, name: str) -> str:
        key = super().set_persona(name)
        if key:
            self._publish(persona=key)
        return key

    def set_tasks(self, tasks):
        super().set_tasks(tasks)
        try:
            self._publish(tasks=[str(t) for t in (tasks or [])])
        except Exception:
            pass

    def set_memory(self, text):
        super().set_memory(text)
        try:
            self._publish(memory=str(text or ""))
        except Exception:
            pass

    def set_agent(self, name, state):
        super().set_agent(name, state)
        try:
            self._publish(agent={"name": str(name), "state": str(state)})
        except Exception:
            pass

    def set_agent_status(self, text):
        # Base method writes a single status line; the agent panel wants the
        # structured form, so keep the panel in sync when the name is known.
        super().set_agent_status(text)
        try:
            self._publish(agent={"name": getattr(self, "_agent_name", "Planner"),
                                 "state": str(text or "IDLE")})
        except Exception:
            pass

    def action(self, name: str, status: str = "RUN", detail: str = "") -> None:
        """Called by the action loop (and available to main.py) to record a step."""
        try:
            self._state.action(name, status, detail)
        except Exception:
            pass

    def set_connected(self, on: bool) -> None:
        self._publish(connected=bool(on))

    # -- lifecycle --------------------------------------------------------- #
    def quit_from_hud(self) -> None:
        """Shut the runtime down when the page is closed or Quit is pressed.

        The HTTP thread never calls this: it runs on the Tk command pump, the
        same place that handles stop/mute. ``root.quit()`` lets main() finish
        its cleanup (perception, heartbeat, queue) instead of the hard
        ``os._exit`` used by the native window close.
        """
        if self._quitting:
            return
        self._quitting = True
        print("[HUD] closed — shutting J.A.R.V.I.S. down", flush=True)
        cb = getattr(self, "on_quit", None)
        if callable(cb):
            try:
                cb()
            except Exception as e:
                print(f"[HUD] quit callback failed: {e}")
        self.close_hud()
        try:
            self.root.quit()
        except Exception:
            pass

    def close_hud(self) -> None:
        self._deny_pending_confirms()
        try:
            from ui import confirm

            confirm.set_shower(None)
        except Exception:
            pass
        proc = self._browser_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        if self._bridge is not None:
            try:
                self._bridge.stop()
            except Exception:
                pass
        self._bridge = None

    def _on_close(self):  # noqa: D401 - mirrors the base hook
        self.close_hud()
        super()._on_close()
