"""Tier 2 B2 - the degradation ladder."""

import pytest

from agent import degrade


def test_it_starts_at_the_top():
    assert degrade.level() == "FULL"
    assert degrade.allows_audio() and degrade.allows_tools() and degrade.allows_writes()


def test_two_failures_drop_one_step():
    degrade.note_failure("breaker trip")
    assert degrade.level() == "FULL"
    degrade.note_failure("breaker trip")
    assert degrade.level() == "TEXT_ONLY"


def test_text_only_still_allows_tools_and_writes():
    degrade.set_level("TEXT_ONLY")
    assert degrade.allows_audio() is False
    assert degrade.allows_tools() is True
    assert degrade.allows_writes() is True


def test_read_only_forbids_writes_and_messages():
    degrade.set_level("READ_ONLY")
    assert degrade.allows_tools() is True
    assert degrade.allows_writes() is False
    assert degrade.allows_messages() is False


def test_monitor_forbids_tools():
    degrade.set_level("MONITOR")
    assert degrade.allows_tools() is False


def test_a_success_resets_the_failure_streak():
    degrade.note_failure("x")
    degrade.note_success()
    degrade.note_failure("x")
    assert degrade.level() == "FULL"


def test_three_successes_climb_one_step():
    degrade.set_level("READ_ONLY")
    degrade.note_success()
    degrade.note_success()
    assert degrade.level() == "READ_ONLY"
    degrade.note_success()
    assert degrade.level() == "TEXT_ONLY"


def test_recovery_never_overshoots():
    degrade.set_level("TEXT_ONLY")
    for _ in range(10):
        degrade.note_success()
    assert degrade.level() == "FULL"


def test_drop_can_skip_steps():
    assert degrade.drop("catastrophic", steps=3) == "MONITOR"


def test_the_drop_is_audited():
    from agent import audit

    degrade.note_failure("disk gone")
    degrade.note_failure("disk gone")
    events = [e for e in audit.tail(20) if e.get("event") == "degradation"]
    assert events and "disk gone" in events[-1].get("detail", "")


def test_an_unknown_level_is_rejected():
    with pytest.raises(ValueError):
        degrade.set_level("NOPE")


def test_an_override_wins_but_can_be_cleared():
    degrade.set_override("MONITOR")
    assert degrade.level() == "MONITOR"
    degrade.set_override(None)
    assert degrade.level() == "FULL"


def test_describe_speaks_plainly():
    assert degrade.describe() == "running normally"
    degrade.set_level("READ_ONLY")
    assert "read-only" in degrade.describe()


def test_status_reports_capabilities():
    status = degrade.status()
    assert status["level"] == "FULL"
    assert status["capabilities"]["audio"] is True
    assert status["ladder"][0] == "FULL"
