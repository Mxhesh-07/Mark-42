"""Fed-mode audio: no second device, and both detectors see the same chunk."""

from __future__ import annotations

import importlib

import pytest

from core.event_bus import Event


class Recorder:
    def __init__(self):
        self.events = []

    def publish(self, name, data=None, source="test"):
        self.events.append((name, dict(data or {}), source))

    def subscribe(self, *args, **kwargs):
        pass

    def unsubscribe(self, *args, **kwargs):
        pass


def test_fed_engine_publishes_chunk_without_opening_devices(monkeypatch):
    portaudio = importlib.import_module("agent.audio")
    ae = importlib.import_module("perception.audio_engine")

    bus = Recorder()
    monkeypatch.setattr(portaudio, "open_pyaudio", lambda: object())
    monkeypatch.setattr(ae, "event_bus", bus)

    engine = ae.AudioEngine()
    engine.start(capture=False, playback=False)
    assert engine.fed_mode is True
    assert engine.input_stream is None and engine.output_stream is None
    assert engine._input_thread is None and engine._output_thread is None
    assert engine.health_check()["mode"] == "fed"

    data = b"\x01\x00" * 512
    engine.feed_input(data, 0.42)
    assert bus.events[0][0] == "audio.mic_level"
    assert bus.events[0][1]["level"] == 0.42
    assert bus.events[0][1]["chunk"] is data
    assert engine.input_queue.get_nowait() is data
    assert engine.fed_chunks == 1

    engine.stop()
    engine.feed_input(b"after-stop", 0.9)
    assert engine.fed_chunks == 1


def test_vad_uses_the_event_chunk_instead_of_draining_the_queue(monkeypatch):
    v = importlib.import_module("perception.vad")

    bus = Recorder()
    d = v.VoiceActivityDetector()
    d.running = True
    d.model = object()
    d.speech_active = False
    seen = []

    class Iterator:
        def __call__(self, tensor, return_seconds=False):
            seen.append(tensor)
            return {"start": 12}

        def reset_states(self):
            pass

    d.vad_iterator = Iterator()
    monkeypatch.setattr(v, "event_bus", bus)
    monkeypatch.setattr(
        v.audio_engine, "get_audio_chunk",
        lambda **kw: pytest.fail("the shared queue must not be drained"))

    chunk = b"\x00" * 2048
    d._on_audio(Event("audio.mic_level", {"level": 0.5, "chunk": chunk}))
    assert len(seen) == 1
    assert d.speech_active is True
    assert bus.events[0][0] == "audio.speech_start"


def test_wake_word_uses_the_event_chunk(monkeypatch):
    w = importlib.import_module("perception.wake_word")

    bus = Recorder()
    d = w.wake_word_detector
    d.running = True
    d.last_detection = 0
    seen = []

    class Model:
        def predict(self, array):
            seen.append(array)
            return {"hey_jarvis": 0.91}

    d.model = Model()
    monkeypatch.setattr(w, "event_bus", bus)
    monkeypatch.setattr(
        w.audio_engine, "get_audio_chunk",
        lambda **kw: pytest.fail("the shared queue must not be drained"))

    chunk = b"\x00" * 2560
    d._on_mic_audio(Event("audio.mic_level", {"level": 0.5, "chunk": chunk}))
    assert len(seen) == 1
    assert bus.events[0][0] == "audio.wake_word_detected"
    assert bus.events[0][1]["wakeword"] == "hey_jarvis"
