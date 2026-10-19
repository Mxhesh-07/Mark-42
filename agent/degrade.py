"""Graceful degradation ladder (Tier 2 B2).

The assistant has four modes. When a capability fails it steps DOWN, and when
the underlying problem clears it steps back UP — one step at a time, so a flaky
network cannot make it flap between full and crippled.

    FULL        voice in, voice out, tools, writes
    TEXT_ONLY   no audio either way; the HUD still works, tools still run
    READ_ONLY   no writes, no shell, no messages — observation only
    MONITOR     nothing but logging and alerts

Drops are driven by infrastructure failures — a provider circuit breaker tripping,
or an audio device disappearing — and recovery by consecutive successes, so a
flaky network cannot make it flap between full and crippled. Ordinary tool
errors do not move the ladder; they are recorded as metrics only.

The policy gate is what enforces READ_ONLY and MONITOR — this module only
decides the mode and exposes the predicates. TEXT_ONLY is advisory: it reports
that audio output should fall back to the HUD, but nothing here ever switches
the microphone off on its own.
"""

from __future__ import annotations

import threading

LEVELS = ("FULL", "TEXT_ONLY", "READ_ONLY", "MONITOR")
_INDEX = {name: i for i, name in enumerate(LEVELS)}

# Consecutive successes needed to climb one step back up.
RECOVER_AFTER = 3
# Consecutive failures needed to drop one step.
DROP_AFTER = 2

_lock = threading.Lock()
_level = "FULL"
_reason = "startup"
_consecutive_failures = 0
_consecutive_successes = 0
_override: str | None = None


def level() -> str:
    with _lock:
        return _override or _level


def reason() -> str:
    with _lock:
        return _reason


def set_level(name: str, why: str = "manual") -> str:
    """Force a level (config or a human). Clears the override with None."""
    global _level, _reason
    name = str(name).upper()
    if name not in _INDEX:
        raise ValueError(f"unknown level {name!r}; expected one of {LEVELS}")
    with _lock:
        _level, _reason = name, str(why)
        _reset_counters()
    return name


def set_override(name: str | None) -> str | None:
    global _override
    with _lock:
        if name is None:
            _override = None
        else:
            name = str(name).upper()
            if name not in _INDEX:
                raise ValueError(f"unknown level {name!r}")
            _override = name
        return _override


def _reset_counters() -> None:
    global _consecutive_failures, _consecutive_successes
    _consecutive_failures = 0
    _consecutive_successes = 0


def drop(why: str = "failure", steps: int = 1) -> str:
    """Step down the ladder."""
    global _level, _reason
    with _lock:
        index = min(len(LEVELS) - 1, _INDEX[_level] + max(1, int(steps)))
        _level, _reason = LEVELS[index], str(why)
        _reset_counters()
        return _level


def recover(why: str = "recovered", steps: int = 1) -> str:
    """Step back up the ladder."""
    global _level, _reason
    with _lock:
        index = max(0, _INDEX[_level] - max(1, int(steps)))
        _level, _reason = LEVELS[index], str(why)
        _reset_counters()
        return _level


def note_failure(why: str = "failure") -> str:
    """Record a failure; drop a step once the threshold is reached."""
    global _consecutive_failures, _consecutive_successes
    with _lock:
        _consecutive_failures += 1
        _consecutive_successes = 0
        reached = _consecutive_failures >= DROP_AFTER
    if reached:
        new = drop(why)
        _audit("degraded", why, new)
        return new
    return level()


def note_success() -> str:
    """Record a success; climb a step after enough of them."""
    global _consecutive_failures, _consecutive_successes
    with _lock:
        _consecutive_successes += 1
        _consecutive_failures = 0
        reached = _consecutive_successes >= RECOVER_AFTER
        at_top = _level == LEVELS[0]
    if reached and not at_top:
        new = recover("successes")
        _audit("recovered", "successes", new)
        return new
    return level()


def _audit(event: str, why: str, new_level: str) -> None:
    try:
        from agent import audit

        audit.record("degradation", outcome=event,
                     detail=f"{why} -> {new_level}")
    except Exception:
        pass
    try:
        from agent import metrics

        metrics.inc("degrade", event=event, level=new_level)
    except Exception:
        pass


# --- capability predicates ----------------------------------------------------

def allows_audio() -> bool:
    return _INDEX[level()] < _INDEX["TEXT_ONLY"]


def allows_tools() -> bool:
    return _INDEX[level()] < _INDEX["MONITOR"]


def allows_writes() -> bool:
    return _INDEX[level()] < _INDEX["READ_ONLY"]


def allows_messages() -> bool:
    return _INDEX[level()] < _INDEX["READ_ONLY"]


def describe() -> str:
    """A short spoken line, for when the mode changes."""
    current = level()
    if current == "FULL":
        return "running normally"
    if current == "TEXT_ONLY":
        return "running without audio"
    if current == "READ_ONLY":
        return "running read-only"
    return "monitoring only"


def status() -> dict:
    with _lock:
        current = _override or _level
        reason = _reason
        override = _override
    # Capabilities are derived from `current` directly: calling the allows_*()
    # helpers here would re-acquire the lock we are not holding any more, which
    # is fine, but keeping the derivation pure avoids any chance of nesting.
    index = _INDEX[current]
    return {
        "level": current,
        "reason": reason,
        "override": override,
        "ladder": list(LEVELS),
        "capabilities": {
            "audio": index < _INDEX["TEXT_ONLY"],
            "tools": index < _INDEX["MONITOR"],
            "writes": index < _INDEX["READ_ONLY"],
            "messages": index < _INDEX["READ_ONLY"],
        },
    }


def reset() -> None:
    global _level, _reason, _override
    with _lock:
        _level, _reason, _override = "FULL", "startup", None
        _reset_counters()
