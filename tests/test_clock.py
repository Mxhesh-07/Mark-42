"""Tier 2 B7 - clock discipline."""

import time
from datetime import datetime, timedelta, timezone

from agent import clock


def test_utc_now_is_timezone_aware():
    assert clock.utc_now().tzinfo is timezone.utc


def test_iso_round_trips():
    text = clock.iso_utc()
    assert text.endswith("Z")
    parsed = clock.from_iso(text)
    assert abs(clock.epoch(parsed) - time.time()) < 5


def test_a_naive_datetime_is_read_as_utc():
    naive = datetime(2026, 1, 2, 3, 4, 5)
    assert clock.to_utc(naive) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def test_epoch_accepts_numbers_and_strings():
    assert clock.epoch(0) == 0
    assert clock.epoch("1970-01-01T00:00:00Z") == 0


def test_local_conversion_changes_only_the_zone():
    when = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    assert clock.to_local(when) == when


def test_in_window_handles_a_normal_window():
    assert clock.in_window("09:30", "09:00", "17:00") is True
    assert clock.in_window("08:59", "09:00", "17:00") is False
    assert clock.in_window("17:00", "09:00", "17:00") is False


def test_in_window_handles_a_window_past_midnight():
    assert clock.in_window("23:30", "22:00", "07:00") is True
    assert clock.in_window("03:00", "22:00", "07:00") is True
    assert clock.in_window("12:00", "22:00", "07:00") is False


def test_deadlines_use_the_monotonic_clock():
    soon = clock.deadline(0.05)
    assert clock.due(soon) is False
    assert clock.remaining(soon) > 0
    time.sleep(0.06)
    assert clock.due(soon) is True
    assert clock.remaining(soon) <= 0


def test_humanize_is_short():
    assert clock.humanize(30) == "30s"
    assert clock.humanize(90) == "1m"
    assert clock.humanize(3600) == "1h"
    assert clock.humanize(5400) == "1h 30m"
    assert clock.humanize(90000) == "1d"


def test_add_days_returns_utc():
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert clock.add_days(2, when) == datetime(2026, 1, 3, tzinfo=timezone.utc)
    assert clock.add_days(-1, when) == datetime(2025, 12, 31, tzinfo=timezone.utc)


def test_local_day_format():
    assert len(clock.local_day()) == 10
