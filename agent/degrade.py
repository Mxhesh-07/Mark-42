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

Recovery is driven by consecutive successes, which is right for a flaky network
and wrong for a spend cap: an hourly budget is lifted by the clock, not by three
calls going well. `set_floor()` covers the second case — the ladder may still
fall further, but it cannot climb above the floor until it is cleared.
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
# A floor is like an override that only works downwards: the ladder may fall
# further but may never climb above it. It exists for limits whose clock is not
# "a run of successes" — a spend cap is lifted by the hour, not by three calls
# going well, so recovery-by-success must not be able to climb out of it.
_floor: str | None = None
_floor_reason: str | None = None


def level() -> str:
    with _lock:
        current = _override or _level
        if _floor is not None and _INDEX[_floor] > _INDEX[current]:
            return _floor
        return current


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


def set_floor(name: str, why: str = "floor") -> str:
    """Hold the ladder at *or below* `name` until `clear_floor()`.

    Unlike an override this is not absolute: a real failure may still drop the
    system further down the ladder. Recovery, on the other hand, is clamped —
    the ladder cannot climb above the floor, so a budget guard that set
    READ_ONLY is not undone by three calls happening to succeed.

    The floor is a *view* constraint: it does not move the underlying level, so
    clearing it puts the ladder back exactly where it was.
    """
    global _floor, _floor_reason
    name = str(name).upper()
    if name not in _INDEX:
        raise ValueError(f"unknown level {name!r}; expected one of {LEVELS}")
    with _lock:
        _floor, _floor_reason = name, str(why)
        _reset_counters()
        return _floor


def clear_floor() -> str | None:
    """Lift the floor. Recovery then resumes from wherever the ladder sits."""
    global _floor, _floor_reason
    with _lock:
        previous = _floor
        _floor, _floor_reason = None, None
        return previous


def floor() -> tuple[str, str] | None:
    """The floor and why it was set, or None."""
    with _lock:
        if _floor is None:
            return None
        return (_floor, _floor_reason or "floor")


def _reset_counters() -> None:
    global _consecutive_failures, _consecutive_successes
    _consecutive_failures = 0
    _consecutive_successes = 0


def drop(why: str = "failure", steps: int = 1) -> str:
    """Step down the ladder."""
    global _level, _reason
    with _lock:
        current = _override or _level
        if _floor is not None and _INDEX[_floor] > _INDEX[current]:
            current = _floor
        index = min(len(LEVELS) - 1, _INDEX[current] + max(1, int(steps)))
        _level, _reason = LEVELS[index], str(why)
        _reset_counters()
        return _level


def recover(why: str = "recovered", steps: int = 1) -> str:
    """Step back up the ladder, never above the floor."""
    global _level, _reason
    with _lock:
        index = max(0, _INDEX[_level] - max(1, int(steps)))
        if _floor is not None:
            index = max(index, _INDEX[_floor])
        if index > _INDEX[_level]:
            # The clamp would push the underlying level *down* to the floor.
            # Leave it alone instead: the floor already does this via level(),
            # and moving it would strand the ladder where the floor was once
            # the floor is cleared.
            return _floor
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
        current = _override or _level
        if _floor is not None and _INDEX[_floor] > _INDEX[current]:
            current = _floor
        at_top = _INDEX[current] == 0
    if reached and not at_top:
        before = level()
        new = recover("successes")
        if new != before:
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
        if _floor is not None and _INDEX[_floor] > _INDEX[current]:
            current = _floor
        reason = _reason
        override = _override
        floor = _floor
        floor_reason = _floor_reason
    # Capabilities are derived from `current` directly: calling the allows_*()
    # helpers here would re-acquire the lock we are not holding any more, which
    # is fine, but keeping the derivation pure avoids any chance of nesting.
    index = _INDEX[current]
    return {
        "level": current,
        "reason": reason,
        "override": override,
        "floor": floor,
        "floor_reason": floor_reason,
        "ladder": list(LEVELS),
        "capabilities": {
            "audio": index < _INDEX["TEXT_ONLY"],
            "tools": index < _INDEX["MONITOR"],
            "writes": index < _INDEX["READ_ONLY"],
            "messages": index < _INDEX["READ_ONLY"],
        },
    }


def reset() -> None:
    global _level, _reason, _override, _floor, _floor_reason
    with _lock:
        _level, _reason, _override = "FULL", "startup", None
        _floor, _floor_reason = None, None
        _reset_counters()
