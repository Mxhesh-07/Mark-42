"""Metrics (Tier 2 C2).

One process-wide registry of counters and gauges, written by the pieces that
already know what happened: the gate records decisions, the breaker records
trips, the executor records tool calls and failures, the approver records
grants and denials.

Nothing here is heavy: counters are a plain dict, snapshots are JSON-safe, and
``render()`` emits the Prometheus text format so any scraper can read it. The
module imports nothing from the rest of the package, so it can never take part
in an import cycle.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_counters: dict[str, float] = {}
_gauges: dict[str, float] = {}
_started_at = time.time()


def _key(name: str, labels: dict | None) -> str:
    name = str(name).strip()
    if not labels:
        return name
    parts = ",".join(f"{k}={labels[k]}" for k in sorted(labels) if labels[k] is not None)
    return f"{name}{{{parts}}}" if parts else name


def inc(name: str, value: float = 1.0, **labels) -> None:
    """Add to a counter."""
    key = _key(name, labels)
    with _lock:
        _counters[key] = _counters.get(key, 0.0) + float(value)


def set_gauge(name: str, value: float, **labels) -> None:
    key = _key(name, labels)
    with _lock:
        _gauges[key] = float(value)


def observe_ms(name: str, milliseconds: float, **labels) -> None:
    """Record a duration: count, total and max, so an average is derivable."""
    inc(f"{name}_count", 1.0, **labels)
    inc(f"{name}_ms_total", float(milliseconds), **labels)
    key = _key(f"{name}_ms_max", labels)
    with _lock:
        if float(milliseconds) > _gauges.get(key, 0.0):
            _gauges[key] = float(milliseconds)


def value(name: str, **labels) -> float:
    with _lock:
        return _counters.get(_key(name, labels), _gauges.get(_key(name, labels), 0.0))


def snapshot() -> dict:
    with _lock:
        return {
            "uptime_s": round(time.time() - _started_at, 3),
            "counters": dict(_counters),
            "gauges": dict(_gauges),
        }


def render() -> str:
    """Prometheus text exposition format."""
    lines: list[str] = []
    with _lock:
        for key in sorted(_counters):
            lines.append(f"{key} {_counters[key]:g}")
        for key in sorted(_gauges):
            lines.append(f"{key} {_gauges[key]:g}")
    return "\n".join(lines) + ("\n" if lines else "")


def reset() -> None:
    """Clear everything (tests, or a fresh turn-of-day rollover)."""
    global _started_at
    with _lock:
        _counters.clear()
        _gauges.clear()
        _started_at = time.time()
