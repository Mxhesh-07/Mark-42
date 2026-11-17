"""Phase 2 seam — the modular runtime rides the existing voice loop.

No test here opens a microphone or a speaker. Optional imports and the event
bus are replaced with fakes so the wiring itself can be verified.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

from core.event_bus import Event
from jarvis.perception_bridge import PerceptionBridge


class FakeBus:
    def __init__(self):
        self.events = []
        self.subs = []

    def publish(self, name, data=None, source="test"):
        self.events.append((name, dict(data or {}), source))

    def subscribe(self, name, handler):
        self.subs.append((name, handler))

    def unsubscribe(self, name, handler):
        self.subs = [s for s in self.subs if s != (name, handler)]


class FakeEngine:
    def __init__(self):
        self.fed = []
        self.started_with = None
        self.stopped = False

    def start(self, **kw):
        self.started_with = kw

    def stop(self):
        self.stopped = True

    def feed_input(self, data, level):
        self.fed.append((data, level))

    def health_check(self):
        return {"status": "ok"}


class FakeDetector:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def health_check(self):
        return {"status": "ok"}


class FakeRuntime:
    def __init__(self):
        self.modules = {}

    def register_module(self, name, module):
        self.modules[name] = module

    def health_check(self):
        return {"status": "ok"}


class FakeLifecycle:
    instances = []

    def __init__(self):
        self.hooks = []
        self.started = 0
        self.stopped = 0
        FakeLifecycle.instances.append(self)

    def add_shutdown_hook(self, hook):
        self.hooks.append(hook)

    def startup(self):
        self.started += 1

    def shutdown(self):
        self.stopped += 1


@pytest.fixture
def modular(monkeypatch):
    """Install fake versions of every lazily imported Phase 2 module."""
    # core/__init__ re-exports the bus instance under the submodule's name, so
    # a plain `import core.event_bus as x` would hand us the instance, not the
    # module. Go through importlib to get the module object itself.
    bus_mod = importlib.import_module("core.event_bus")

    bus = FakeBus()
    engine = FakeEngine()
    vad = FakeDetector()
    wake = FakeDetector()
    runtime = FakeRuntime()
    FakeLifecycle.instances.clear()
    lifecycle = FakeLifecycle()

    monkeypatch.setattr(bus_mod, "event_bus", bus)
    modules = {
        "core.lifecycle": types.SimpleNamespace(lifecycle=lifecycle),
        "core.runtime": types.SimpleNamespace(runtime=runtime),
        "perception.audio_engine": types.SimpleNamespace(audio_engine=engine),
        "perception.vad": types.SimpleNamespace(vad_detector=vad),
        "perception.wake_word": types.SimpleNamespace(wake_word_detector=wake),
    }
    for name, fake in modules.items():
        monkeypatch.setitem(sys.modules, name, fake)
    return types.SimpleNamespace(bus=bus, engine=engine, vad=vad, wake=wake,
                                 runtime=runtime, lifecycle=lifecycle)


def test_flags_default_to_state_only(modular):
    bridge = PerceptionBridge({}, ui=None)
    assert bridge.enabled is True
    assert bridge.state_on is True
    assert bridge.vad_on is False
    assert bridge.wake_on is False


def test_disabled_bridge_is_inert(modular):
    bridge = PerceptionBridge({"perception": False})
    assert bridge.start() is False
    bridge.feed_mic(b"\x00" * 32, 0.4)
    assert modular.engine.fed == []
    assert modular.lifecycle.started == 0


def test_start_registers_modules_and_uses_fed_audio(modular):
    cfg = {"perception_vad": True, "perception_wake_word": True}
    bridge = PerceptionBridge(cfg)
    assert bridge.start() is True
    assert bridge.running is True
    assert modular.engine.started_with == {"capture": False, "playback": False}
    assert set(modular.runtime.modules) == {
        "audio_engine", "vad", "wake_word"}
    assert set(bridge._modules) == {
        "runtime", "audio_engine", "vad", "wake_word"}
    assert modular.vad.started and modular.wake.started
    assert modular.lifecycle.started == 1
    assert any(name == "state.changed" for name, _ in modular.bus.subs)

    bridge.feed_mic(b"\x01" * 32, 0.25)
    assert modular.engine.fed == [(b"\x01" * 32, 0.25)]
    assert "running" in bridge.health()
    assert bridge.health()["audio_engine"] == {"status": "ok"}

    bridge.stop()
    assert bridge.running is False
    assert modular.lifecycle.stopped == 1
    assert modular.bus.subs == []


def test_conversation_milestones_publish_the_expected_events(modular):
    bridge = PerceptionBridge()
    bridge.user_speech_start()
    bridge.user_speech_end("hello")
    bridge.response_start()
    bridge.response_end()
    bridge.turn_complete()
    bridge.tool_start("open_app")
    bridge.tool_end("open_app", True)
    bridge.interrupted()
    bridge.error("connection", RuntimeError("offline"))

    assert [name for name, _, _ in modular.bus.events] == [
        "audio.speech_start", "audio.speech_end", "gemini.response_start",
        "gemini.response_end", "gemini.turn_complete",
        "tool.execution_start", "tool.execution_end", "audio.interrupt",
        "error.occurred",
    ]
    assert modular.bus.events[1][1] == {"text": "hello"}
    assert all(src == "voice_loop" for _, _, src in modular.bus.events)


def test_response_milestones_are_idempotent(modular):
    """Transcription and playback both announce a reply; emit it only once."""
    bridge = PerceptionBridge()
    bridge.response_start()
    bridge.response_start()                 # duplicate from the other source
    assert [name for name, _, _ in modular.bus.events] == [
        "gemini.response_start"]

    bridge.response_end()
    bridge.response_end()                   # duplicate at idle timeout
    assert [name for name, _, _ in modular.bus.events] == [
        "gemini.response_start", "gemini.response_end"]

    # A new reply after the previous one ended is a fresh event.
    bridge.response_start()
    assert len(modular.bus.events) == 3

    # An interrupt clears the latch silently; a later response_end is dropped.
    bridge.interrupted()
    bridge.response_end()
    assert [name for name, _, _ in modular.bus.events][-2:] == [
        "gemini.response_start", "audio.interrupt"]


def test_state_milestones_can_be_silenced(modular):
    bridge = PerceptionBridge({"perception_state": False})
    bridge.user_speech_start()
    assert modular.bus.events == []


def test_state_changes_are_mirrored_to_the_ui(modular):
    seen = []

    class UI:
        def update_machine(self, value):
            seen.append(value)

    bridge = PerceptionBridge(ui=UI())
    bridge.start()
    assert any(name == "state.changed" for name, _ in modular.bus.subs)
    # start() seeds the current state; a fresh state_manager is in STANDBY.
    assert seen == ["standby"]
    bridge._publish_state(Event("state.changed", {"current": "listening"}))
    assert seen == ["standby", "listening"]
