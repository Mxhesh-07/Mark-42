"""Circuit breakers for external services (upgrade list B1).

Today `gemini_util` walks models on 429/503, but a *dead* provider is re-tried on
every turn and made to pay a full timeout each time. A breaker fixes that: it
tracks consecutive failures and moves through three states.

    closed     healthy - calls pass through. N consecutive failures -> open.
    open       skipping calls until the cooldown elapses, then -> half-open.
    half-open  let a bounded number of trial calls through. Success -> closed,
               failure -> open again.

State is in-process and uses the monotonic clock, so a wall-clock change (or a
laptop waking from sleep) cannot strand a breaker in the open state.

Example::

    from agent import breaker
    b = breaker.breaker("provider:groq")
    if b.allow():
        try:
            result = call()
        except Exception:
            b.record_failure()
        else:
            b.record_success()
"""

import threading
import time

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


def _metric(name: str, breaker_name: str) -> None:
    try:
        from agent import metrics

        metrics.inc(name, breaker=breaker_name)
    except Exception:
        pass


def _on_trip(breaker_name: str) -> None:
    """Infrastructure failure: let the degradation ladder (B2) know."""
    try:
        from agent import degrade

        degrade.note_failure(f"breaker {breaker_name} open")
    except Exception:
        pass


def _on_success(breaker_name: str) -> None:
    try:
        from agent import degrade

        degrade.note_success()
    except Exception:
        pass


class Breaker:
    """A three-state circuit breaker for one named dependency."""

    def __init__(self, name: str, *, failure_threshold: int = 3,
                 recovery_timeout: float = 60.0, half_open_trials: int = 1):
        self.name = str(name)
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_timeout = max(0.0, float(recovery_timeout))
        self.half_open_trials = max(1, int(half_open_trials))

        self._lock = threading.Lock()
        self._state = CLOSED
        self._failures = 0
        self._trials = 0
        self._opened_at = 0.0
        self._total_ok = 0
        self._total_failed = 0
        self._trips = 0

    # -- state ------------------------------------------------------------
    def _state_locked(self) -> str:
        """Current state, promoting open -> half-open once the cooldown elapsed."""
        if self._state == OPEN and (time.monotonic() - self._opened_at) >= self.recovery_timeout:
            self._state = HALF_OPEN
            self._trials = 0
        return self._state

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_locked()

    # -- decisions --------------------------------------------------------
    def allow(self) -> bool:
        """May a call go through right now?"""
        with self._lock:
            state = self._state_locked()
            if state == CLOSED:
                return True
            if state == OPEN:
                return False
            if self._trials < self.half_open_trials:     # half-open probe
                self._trials += 1
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._trials = 0
            self._state = CLOSED
            self._total_ok += 1
        _metric("breaker.success", self.name)
        _on_success(self.name)

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._total_failed += 1
            # A failed probe means the service is still down: re-open at once.
            if self._state == HALF_OPEN or self._failures >= self.failure_threshold:
                self._trip_locked()

    def _trip_locked(self) -> None:
        first = self._state != OPEN
        if first:
            self._trips += 1
        self._state = OPEN
        self._opened_at = time.monotonic()
        self._trials = 0
        if first:
            _metric("breaker.trip", self.name)
            _on_trip(self.name)

    def reset(self) -> None:
        with self._lock:
            self._state = CLOSED
            self._failures = 0
            self._trials = 0
            self._opened_at = 0.0

    def snapshot(self) -> dict:
        with self._lock:
            state = self._state_locked()
            retry_in = 0.0
            if state == OPEN:
                elapsed = time.monotonic() - self._opened_at
                retry_in = round(max(0.0, self.recovery_timeout - elapsed), 1)
            return {
                "name": self.name,
                "state": state,
                "failures": self._failures,
                "trips": self._trips,
                "ok": self._total_ok,
                "failed": self._total_failed,
                "retry_in": retry_in,
            }


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
_breakers: dict[str, Breaker] = {}
_registry_lock = threading.Lock()


def breaker(name: str, **options) -> Breaker:
    """The breaker for `name`, created on first use. Options apply on creation."""
    key = str(name)
    with _registry_lock:
        found = _breakers.get(key)
        if found is None:
            found = _breakers[key] = Breaker(key, **options)
        return found


def snapshot() -> list[dict]:
    """State of every breaker created so far (for /status and diagnostics)."""
    with _registry_lock:
        items = list(_breakers.values())
    return [b.snapshot() for b in items]


def open_names() -> list[str]:
    return [s["name"] for s in snapshot() if s["state"] == OPEN]


def reset() -> None:
    """Forget every breaker (tests / diagnostics)."""
    with _registry_lock:
        _breakers.clear()
