"""One serialized door for PortAudio.

Regression: the background startup self-check calling ``PyAudio()`` while
``main`` built its own module-level instance killed the process with an access
violation (0xC0000005). Construction must never overlap.
"""

import sys
import threading
import time

from agent import audio


class _FakeInstance:
    def __init__(self, on_build=None):
        if on_build:
            on_build()
        self.terminated = False

    def terminate(self):
        self.terminated = True


def _fake_pyaudio(monkeypatch, on_build=None):
    """Install a stub `pyaudio` module whose PyAudio() records construction."""

    class _Fake:
        @staticmethod
        def PyAudio():
            return _FakeInstance(on_build)

    monkeypatch.setitem(sys.modules, "pyaudio", _Fake)
    monkeypatch.setattr(audio, "_INSTANCES", 0)


def test_open_returns_an_instance_and_close_terminates_it(monkeypatch):
    _fake_pyaudio(monkeypatch)
    instance = audio.open_pyaudio()
    assert isinstance(instance, _FakeInstance)
    assert audio.live_instances() == 1

    audio.close(instance)
    assert instance.terminated is True
    assert audio.live_instances() == 0


def test_construction_never_overlaps(monkeypatch):
    """The whole point of the module."""
    depth = 0
    peak = 0
    guard = threading.Lock()

    def enter():
        nonlocal depth, peak
        with guard:
            depth += 1
            peak = max(peak, depth)

    def leave():
        nonlocal depth
        with guard:
            depth -= 1

    def build():
        enter()
        time.sleep(0.05)      # widen the race window
        leave()

    _fake_pyaudio(monkeypatch, on_build=build)

    results = []

    def worker():
        instance = audio.open_pyaudio()
        results.append(instance)
        audio.close(instance)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 8
    assert peak == 1


def test_close_tolerates_none_and_a_broken_terminate(monkeypatch):
    _fake_pyaudio(monkeypatch)
    audio.close(None)                       # must not raise

    class Exploding(_FakeInstance):
        def terminate(self):
            raise RuntimeError("device already gone")

    audio.close(Exploding())                # must not raise


def test_session_closes_on_the_way_out(monkeypatch):
    _fake_pyaudio(monkeypatch)
    with audio.session() as instance:
        assert audio.live_instances() == 1
    assert instance.terminated is True
    assert audio.live_instances() == 0


def test_session_closes_even_when_the_body_raises(monkeypatch):
    _fake_pyaudio(monkeypatch)
    instance = None
    try:
        with audio.session() as instance:
            raise ValueError("boom")
    except ValueError:
        pass
    assert instance.terminated is True
    assert audio.live_instances() == 0
