"""Phase 2 — the shadow state machine must track what the speaker is doing.

Regression: the HUD reported ``status=SPEAK`` while ``/api/state`` said
``machine=listening``, because ``response_start`` was only emitted from an
output transcription the Live model frequently omits, and the transition table
did not even permit LISTENING → RESPONDING. These tests drive the *real*
StateManager and JARVISRuntime handlers through a synchronous event bus so the
whole chain is covered without audio or Gemini.
"""

from __future__ import annotations

import importlib
from collections import defaultdict

from core.event_bus import Event
from core.state_manager import JARVISState, StateManager

# core/__init__ re-exports the runtime singleton under the submodule's name, so
# `import core.runtime as rt` would give us the instance, not the module.
rt = importlib.import_module("core.runtime")
sm_mod = importlib.import_module("core.state_manager")


class SyncBus:
    """Deliver events to subscribers on the publishing thread, immediately."""

    def __init__(self):
        self._subs = defaultdict(list)
        self.published = []

    def subscribe(self, name, handler):
        self._subs[name].append(handler)

    def unsubscribe(self, name, handler):
        self._subs[name] = [h for h in self._subs[name] if h is not handler]

    def publish(self, name, data=None, source="test"):
        self.published.append(name)
        ev = Event(name, dict(data or {}), source)
        for handler in list(self._subs.get(name, [])):
            handler(ev)


def _runtime(monkeypatch):
    bus = SyncBus()
    sm = StateManager()
    monkeypatch.setattr(rt, "event_bus", bus)
    monkeypatch.setattr(rt, "state_manager", sm)
    # state_manager publishes state.changed through its own module reference.
    monkeypatch.setattr(sm_mod, "event_bus", bus)
    rt.JARVISRuntime()  # registers handlers on the fresh bus
    seen = []
    bus.subscribe("state.changed", lambda e: seen.append(e.data["current"]))
    return bus, sm, seen


def test_transition_table_allows_playback_from_listening_and_standby():
    sm = StateManager()
    assert sm.transition_to(JARVISState.LISTENING) is True
    assert sm.transition_to(JARVISState.RESPONDING) is True
    assert sm.transition_to(JARVISState.STANDBY) is True

    # A proactive reminder speaks from standby with no user turn at all.
    assert sm.transition_to(JARVISState.RESPONDING) is True
    assert sm.transition_to(JARVISState.STANDBY) is True


def test_playback_driven_turn_tracks_listening_responding_standby(monkeypatch):
    bus, sm, seen = _runtime(monkeypatch)

    bus.publish("audio.speech_start")       # first input transcript fragment
    assert sm.state is JARVISState.LISTENING
    bus.publish("gemini.response_start")    # real audio hits the speaker
    assert sm.state is JARVISState.RESPONDING
    bus.publish("gemini.response_end")      # playback guard expired
    assert sm.state is JARVISState.STANDBY

    assert seen == ["listening", "responding", "standby"]


def test_turn_complete_still_clears_a_silent_listening_state(monkeypatch):
    """No audio reply (e.g. a denied tool) must not leave the machine hot."""
    bus, sm, _ = _runtime(monkeypatch)

    bus.publish("audio.speech_start")
    bus.publish("audio.speech_end", {"text": "stop"})
    assert sm.state is JARVISState.UNDERSTANDING
    bus.publish("gemini.turn_complete")
    assert sm.state is JARVISState.STANDBY


def test_proactive_speech_from_standby(monkeypatch):
    bus, sm, _ = _runtime(monkeypatch)
    bus.publish("gemini.response_start")
    assert sm.state is JARVISState.RESPONDING
    bus.publish("gemini.response_end")
    assert sm.state is JARVISState.STANDBY


def test_tool_turn_reaches_responding_before_standby(monkeypatch):
    bus, sm, seen = _runtime(monkeypatch)
    bus.publish("audio.speech_start")
    bus.publish("audio.speech_end", {"text": "open notepad"})
    bus.publish("tool.execution_start", {"tool": "open_app"})
    assert sm.state is JARVISState.EXECUTING
    bus.publish("tool.execution_end", {"tool": "open_app", "ok": True})
    assert sm.state is JARVISState.UNDERSTANDING
    bus.publish("gemini.response_start")
    bus.publish("gemini.response_end")
    assert sm.state is JARVISState.STANDBY
    assert "executing" in seen and "responding" in seen


def test_interrupt_moves_responding_back_to_listening(monkeypatch):
    bus, sm, _ = _runtime(monkeypatch)
    bus.publish("gemini.response_start")
    assert sm.state is JARVISState.RESPONDING
    bus.publish("audio.interrupt")
    assert sm.state is JARVISState.LISTENING
    assert "gemini.cancel" in bus.published
    assert "audio.stop_playback" in bus.published
