"""Phase 2 — connect the modular runtime to the existing Gemini Live loop.

The voice loop in ``main.py`` already owns the microphone and the speaker. It
must keep owning them: Gemini's server-side VAD and barge-in depend on a single
low-latency stream, and two PyAudio capture streams on the same Windows endpoint
are a reliable way to get feedback or a device-busy error.

This bridge therefore runs the new subsystems in *fed* mode:

* ``main.py`` hands each captured 16 kHz chunk to :meth:`feed_mic`.
* :class:`~perception.audio_engine.AudioEngine` publishes it on the event bus
  and queues it for the VAD / wake-word detectors (without opening a device).
* The conversation milestones already known to the voice loop are mirrored as
  events, which drive :mod:`core.runtime`'s state machine.
* The state machine's result is mirrored back to the web HUD through
  ``ui.update_machine`` so the new layer is observable, not decorative.

Everything is behind ``config/audio.json`` flags and fails soft: an import or a
detector that cannot start leaves the voice session exactly as it was.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PerceptionBridge:
    """Thin, optional seam between the live voice loop and the new modules."""

    def __init__(self, config: Optional[dict] = None, ui=None) -> None:
        self._modules: dict = {}
        self._started = False
        self._on_state = None
        self.configure(config, ui)

    def configure(self, config: Optional[dict] = None, ui=None) -> "PerceptionBridge":
        """Rebind the process-wide bridge before the voice loop starts."""
        self.config = dict(config or {})
        self.ui = ui
        self.enabled = bool(self.config.get("perception", True))
        self.state_on = self.enabled and bool(
            self.config.get("perception_state", True))
        self.vad_on = self.enabled and bool(
            self.config.get("perception_vad", False))
        self.wake_on = self.enabled and bool(
            self.config.get("perception_wake_word", False))
        # Guards against double response_start/end from the two independent
        # triggers (output transcription and real playback) and across the
        # small playback pauses inside one reply.
        self._response_active = False
        return self

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        """Start the modular layer. Returns True only if it is actually live."""
        if not self.enabled or self._started:
            return False

        try:
            from core.event_bus import event_bus
            from core.lifecycle import lifecycle
            from core.runtime import runtime
            from perception.audio_engine import audio_engine
            from perception.vad import vad_detector
            from perception.wake_word import wake_word_detector

            self._modules = {
                "runtime": runtime,
                "audio_engine": audio_engine,
            }

            # Fed mode: no capture/playback streams. main.py supplies the audio.
            audio_engine.start(capture=False, playback=False)
            runtime.register_module("audio_engine", audio_engine)

            if self.vad_on:
                vad_detector.start()
                self._modules["vad"] = vad_detector
                runtime.register_module("vad", vad_detector)

            if self.wake_on:
                wake_word_detector.start()
                self._modules["wake_word"] = wake_word_detector
                runtime.register_module("wake_word", wake_word_detector)

            if self.state_on:
                self._on_state = self._publish_state
                event_bus.subscribe("state.changed", self._on_state)

            lifecycle.add_shutdown_hook(self.stop)
            lifecycle.startup()

            # Seed the HUD with the initial state: state_manager starts in
            # STANDBY and emits no transition until the first turn, so without
            # this /api/state would report `machine` as empty on a fresh boot.
            if self.state_on and self.ui is not None:
                from core.state_manager import state_manager

                update = getattr(self.ui, "update_machine", None)
                if callable(update):
                    update(state_manager.state.value)

            self._started = True
            print("[Runtime] modular layer active "
                  f"(state={'on' if self.state_on else 'off'}, "
                  f"vad={'on' if self.vad_on else 'off'}, "
                  f"wake={'on' if self.wake_on else 'off'})")
            return True
        except Exception as exc:
            # A missing optional dependency must never take the voice loop down.
            print(f"[Runtime] modular layer unavailable ({exc})")
            logger.exception("Perception bridge failed to start")
            self.stop()
            return False

    def stop(self) -> None:
        """Tear down only what this bridge started."""
        if self._on_state is not None:
            try:
                from core.event_bus import event_bus

                event_bus.unsubscribe("state.changed", self._on_state)
            except Exception:
                pass
            self._on_state = None

        if self._started:
            try:
                from core.lifecycle import lifecycle

                lifecycle.shutdown()
            except Exception as exc:
                logger.warning("lifecycle shutdown: %s", exc)
            self._started = False

        self._modules.clear()

    @property
    def running(self) -> bool:
        return self._started

    # -- audio --------------------------------------------------------------

    def feed_mic(self, data: bytes, level: float) -> None:
        """Hand a captured chunk to the perception modules (never blocks)."""
        if not self.enabled:
            return
        try:
            from perception.audio_engine import audio_engine

            audio_engine.feed_input(data, level)
        except Exception:
            pass

    # -- conversation milestones -------------------------------------------

    def _emit(self, name: str, data: Optional[dict] = None) -> None:
        if not self.state_on:
            return
        try:
            from core.event_bus import event_bus

            event_bus.publish(name, data or {}, source="voice_loop")
        except Exception:
            pass

    def user_speech_start(self) -> None:
        self._emit("audio.speech_start")

    def user_speech_end(self, text: str = "") -> None:
        self._emit("audio.speech_end", {"text": text})

    def response_start(self) -> None:
        """Mark a reply as started — at most once until :meth:`response_end`.

        Both ``output_transcription`` and real audio playback can announce the
        same reply; a mid-sentence playback pause can fire ``start_speaking``
        twice. The flag keeps the state machine from seeing a duplicate event.
        """
        if self._response_active:
            return
        self._response_active = True
        self._emit("gemini.response_start")

    def response_end(self) -> None:
        if not self._response_active:
            return
        self._response_active = False
        self._emit("gemini.response_end")

    def turn_complete(self) -> None:
        self._emit("gemini.turn_complete")

    def tool_start(self, name: str) -> None:
        self._emit("tool.execution_start", {"tool": name})

    def tool_end(self, name: str, ok: bool) -> None:
        self._emit("tool.execution_end", {"tool": name, "ok": ok})

    def interrupted(self) -> None:
        # main.py performs the real cancellation; this only drives the shadow
        # state machine and lets other subscribers stop their own playback.
        # Clear the latch silently: the interrupt event itself moves the state
        # machine out of RESPONDING, so a later response_end would be spurious.
        self._response_active = False
        self._emit("audio.interrupt")

    def error(self, where: str, exc: BaseException) -> None:
        self._emit("error.occurred", {"where": where, "error": str(exc)})

    # -- observability ------------------------------------------------------

    def _publish_state(self, event) -> None:
        if self.ui is None:
            return
        try:
            update = getattr(self.ui, "update_machine", None)
            if callable(update):
                update(str(event.data.get("current", "")))
        except Exception:
            pass

    def health(self) -> dict:
        out = {"enabled": self.enabled, "running": self._started}
        for name, module in self._modules.items():
            try:
                check = getattr(module, "health_check", None)
                out[name] = check() if callable(check) else "registered"
            except Exception as exc:
                out[name] = f"error: {exc}"
        return out


# One bridge per process; main.py constructs it with its config and UI.
perception_bridge = PerceptionBridge()
