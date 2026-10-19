"""Circuit breakers (B1)."""

import time

from agent import breaker


def test_a_new_breaker_is_closed_and_allows_calls():
    b = breaker.Breaker("x")
    assert b.state == breaker.CLOSED
    assert b.allow() is True


def test_it_opens_only_after_the_failure_threshold():
    b = breaker.Breaker("x", failure_threshold=3)
    b.record_failure()
    b.record_failure()
    assert b.state == breaker.CLOSED
    assert b.allow() is True
    b.record_failure()
    assert b.state == breaker.OPEN
    assert b.allow() is False


def test_a_success_resets_the_failure_streak():
    b = breaker.Breaker("x", failure_threshold=3)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.state == breaker.CLOSED


def test_it_goes_half_open_after_the_cooldown_then_closed_on_success():
    b = breaker.Breaker("x", failure_threshold=1, recovery_timeout=0.05)
    b.record_failure()
    assert b.allow() is False
    time.sleep(0.06)
    assert b.state == breaker.HALF_OPEN
    assert b.allow() is True          # one trial call
    assert b.allow() is False         # but only one
    b.record_success()
    assert b.state == breaker.CLOSED


def test_a_failed_probe_reopens_immediately():
    b = breaker.Breaker("x", failure_threshold=1, recovery_timeout=0.05)
    b.record_failure()
    time.sleep(0.06)
    assert b.allow() is True
    b.record_failure()
    assert b.state == breaker.OPEN
    assert b.allow() is False


def test_half_open_trials_are_bounded():
    b = breaker.Breaker("x", failure_threshold=1, recovery_timeout=0.0,
                        half_open_trials=2)
    b.record_failure()
    assert b.allow() is True
    assert b.allow() is True
    assert b.allow() is False


def test_breakers_are_independent():
    a = breaker.Breaker("a", failure_threshold=1)
    c = breaker.Breaker("c", failure_threshold=1)
    a.record_failure()
    assert a.state == breaker.OPEN
    assert c.state == breaker.CLOSED


# --- registry -----------------------------------------------------------------

def test_the_registry_hands_back_the_same_instance():
    assert breaker.breaker("same") is breaker.breaker("same")


def test_options_apply_only_on_creation():
    first = breaker.breaker("opts", failure_threshold=1)
    again = breaker.breaker("opts", failure_threshold=99)
    assert again is first
    assert again.failure_threshold == 1


def test_snapshot_reports_counters():
    b = breaker.breaker("snap")
    b.record_failure()
    entry = {s["name"]: s for s in breaker.snapshot()}["snap"]
    assert entry["state"] == breaker.CLOSED
    assert entry["failed"] == 1
    assert entry["ok"] == 0


def test_snapshot_reports_the_time_until_a_retry_while_open():
    b = breaker.Breaker("x", failure_threshold=1, recovery_timeout=60.0)
    b.record_failure()
    entry = b.snapshot()
    assert entry["state"] == breaker.OPEN
    assert 0 < entry["retry_in"] <= 60.0
    assert entry["trips"] == 1


def test_open_names_lists_only_tripped_breakers():
    breaker.breaker("down", failure_threshold=1).record_failure()
    breaker.breaker("up")
    assert breaker.open_names() == ["down"]


def test_reset_clears_the_registry():
    breaker.breaker("gone").record_failure()
    assert any(s["name"] == "gone" for s in breaker.snapshot())
    breaker.reset()
    assert breaker.snapshot() == []


# --- C2 / B2: a trip is observable and feeds the degradation ladder -----------

def test_a_trip_is_counted_as_a_metric():
    from agent import metrics

    breaker.Breaker("down", failure_threshold=1).record_failure()
    assert metrics.value("breaker.trip", breaker="down") == 1


def test_a_trip_feeds_the_degradation_ladder():
    from agent import degrade

    breaker.Breaker("down", failure_threshold=1).record_failure()
    breaker.Breaker("worse", failure_threshold=1).record_failure()
    assert degrade.level() != "FULL"


def test_repeated_failures_while_open_count_the_trip_once():
    from agent import metrics

    b = breaker.Breaker("down", failure_threshold=1)
    b.record_failure()
    b.record_failure()
    b.record_failure()
    assert metrics.value("breaker.trip", breaker="down") == 1

