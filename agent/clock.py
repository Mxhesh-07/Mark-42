"""Clock discipline (Tier 2 B7).

Everything the assistant stores is UTC; everything it shows is local. Elapsed
time — cooldowns, timeouts, watchdog deadlines — always uses the monotonic
clock, so a laptop sleeping or an NTP correction can never make a timer fire
early, late, or (with a backwards jump) never.

This module is the single place that decides which clock is which.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    """Timezone-aware current time in UTC."""
    return datetime.now(timezone.utc)


def to_utc(when) -> datetime:
    """Coerce anything date-ish into an aware UTC datetime."""
    if when is None:
        return utc_now()
    if isinstance(when, (int, float)):
        return datetime.fromtimestamp(float(when), tz=timezone.utc)
    if isinstance(when, str):
        return from_iso(when)
    if isinstance(when, datetime):
        if when.tzinfo is None:
            return when.replace(tzinfo=timezone.utc)
        return when.astimezone(timezone.utc)
    raise TypeError(f"cannot interpret {when!r} as a time")


def to_local(when) -> datetime:
    """Aware UTC -> local timezone, for display only."""
    return to_utc(when).astimezone()


def iso_utc(when=None) -> str:
    """RFC-3339 UTC with a trailing Z; the storage format."""
    return to_utc(when).isoformat(timespec="seconds").replace("+00:00", "Z")


def from_iso(text: str) -> datetime:
    """Parse a stored timestamp, tolerating a missing timezone."""
    value = str(text).strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def epoch(when=None) -> float:
    """UTC as a POSIX timestamp."""
    return to_utc(when).timestamp()


def local_hhmm(when=None) -> str:
    """``"HH:MM"`` in local time — what a quiet-hours window compares against."""
    return to_local(when).strftime("%H:%M")


def in_window(now_hhmm: str, start: str, end: str) -> bool:
    """Is ``now_hhmm`` inside the local window that may wrap past midnight?"""
    start, end, now_hhmm = str(start), str(end), str(now_hhmm)
    if start <= end:
        return start <= now_hhmm < end
    return now_hhmm >= start or now_hhmm < end


# --- elapsed time (never wall-clock) ------------------------------------------

def monotonic() -> float:
    return time.monotonic()


def deadline(seconds: float) -> float:
    """A monotonic instant ``seconds`` from now."""
    return time.monotonic() + float(seconds)


def remaining(deadline_value: float) -> float:
    """Seconds left before a monotonic deadline (may be negative)."""
    return float(deadline_value) - time.monotonic()


def due(deadline_value: float) -> bool:
    return time.monotonic() >= float(deadline_value)


def sleep(seconds: float) -> None:
    time.sleep(max(0.0, float(seconds)))


def humanize(seconds: float) -> str:
    """A short, spoken-friendly duration."""
    seconds = max(0, int(round(float(seconds))))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        hours, minutes = divmod(seconds // 60, 60)
        return f"{hours}h" + (f" {minutes}m" if minutes else "")
    return f"{seconds // 86400}d"


def local_day(when=None) -> str:
    return to_local(when).strftime("%Y-%m-%d")


def add_days(days: int, when=None) -> datetime:
    return to_utc(when) + timedelta(days=int(days))
