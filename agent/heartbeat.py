"""The companion's pulse — proactive ticks on their own scheduler.

These ticks used to ride ``TaskQueue._worker_loop``. That loop waits on a
condition while a task runs, and a long background task could stop it iterating
for minutes: reminders, initiative and the brain all went quiet exactly when
JARVIS was busiest. A tiny dedicated daemon thread fixes that without touching
the worker's cancellation semantics.

Two speeds, both best-effort:

* ``initiative`` every 30 s — sensor triggers, budgets, speaking.
* ``brain`` every 60 s — observe, form intentions, decide what to do next.

A failed tick is swallowed and the next one still happens. ``stop()`` is used by
the runtime shutdown path; the thread is a daemon either way, so a crash cannot
keep the process alive.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

INITIATIVE_INTERVAL_S = 30.0
BRAIN_INTERVAL_S = 60.0
TICK_S = 1.0

_thread: threading.Thread | None = None
_stop: threading.Event | None = None
_lock = threading.Lock()
_SKIP = object()


def tick_once(*, initiative_fn=None, brain_fn=None) -> dict:
    """Run one pass of each layer. Every failure is isolated to its own layer.

    Pass ``heartbeat.SKIP`` for a layer to leave it out of this pass.
    """
    out: dict = {}
    if initiative_fn is not _SKIP:
        if initiative_fn is None:
            try:
                from agent import initiative as _initiative

                initiative_fn = _initiative.tick
            except Exception:
                initiative_fn = None
        if initiative_fn is not None:
            try:
                out["initiative"] = initiative_fn()
            except Exception as exc:
                out["initiative_error"] = str(exc)

    if brain_fn is not _SKIP:
        if brain_fn is None:
            try:
                from agent import brain as _brain

                brain_fn = _brain.tick
            except Exception:
                brain_fn = None
        if brain_fn is not None:
            try:
                out["brain"] = brain_fn()
            except Exception as exc:
                out["brain_error"] = str(exc)
    return out


SKIP = _SKIP


def _run(stop: threading.Event) -> None:
    next_initiative = 0.0
    next_brain = 0.0
    while not stop.is_set():
        now = time.monotonic()
        if now >= next_initiative:
            next_initiative = now + INITIATIVE_INTERVAL_S
            tick_once(initiative_fn=_initiative_only, brain_fn=SKIP)
        if now >= next_brain:
            next_brain = now + BRAIN_INTERVAL_S
            tick_once(initiative_fn=SKIP, brain_fn=_brain_only)
        stop.wait(TICK_S)


def _initiative_only():
    from agent import initiative

    return initiative.tick()


def _brain_only():
    from agent import brain

    return brain.tick()


def start() -> bool:
    """Start the scheduler once. Returns True if it is now running."""
    global _thread, _stop
    with _lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop = threading.Event()
        _thread = threading.Thread(
            target=_run, args=(_stop,), daemon=True, name="JarvisHeartbeat",
        )
        _thread.start()
        return True


def stop() -> None:
    global _thread, _stop
    with _lock:
        event, thread = _stop, _thread
        _thread, _stop = None, None
    if event is not None:
        event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)


def status() -> dict:
    return {
        "running": bool(_thread is not None and _thread.is_alive()),
        "initiative_interval_s": INITIATIVE_INTERVAL_S,
        "brain_interval_s": BRAIN_INTERVAL_S,
    }
