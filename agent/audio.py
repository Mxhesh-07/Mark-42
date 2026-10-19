"""One door for PortAudio.

PortAudio (the C library behind PyAudio) keeps global initialisation state, and
two threads calling ``pyaudio.PyAudio()`` at the same time on Windows can take
the whole process down with an access violation (0xC0000005) instead of raising
a Python exception. That is not hypothetical: the background startup self-check
probing the microphone while ``main`` built its own module-level instance
crashed every single time.

Every PyAudio instance in this project is therefore created through
``open_pyaudio()``, which serializes construction behind one process-wide lock.

The lock is held only for construction, never for a stream's lifetime, so a
long recording can never block a health probe.

    pa = audio.open_pyaudio()
    try:
        ...
    finally:
        audio.close(pa)

    with audio.session() as pa:      # same thing, shorter
        ...
"""

from __future__ import annotations

import contextlib
import threading

_LOCK = threading.RLock()
_INSTANCES = 0


def open_pyaudio():
    """Create a PyAudio instance, serialized against every other one."""
    global _INSTANCES

    import pyaudio

    with _LOCK:
        instance = pyaudio.PyAudio()
        _INSTANCES += 1
        return instance


def close(instance) -> None:
    """Terminate a PyAudio instance. Never raises, safe to call twice."""
    global _INSTANCES

    if instance is None:
        return
    with _LOCK:
        try:
            instance.terminate()
        except Exception:
            pass
        finally:
            _INSTANCES = max(0, _INSTANCES - 1)


@contextlib.contextmanager
def session():
    instance = open_pyaudio()
    try:
        yield instance
    finally:
        close(instance)


def live_instances() -> int:
    """How many instances this module created and has not closed (for tests)."""
    return _INSTANCES
