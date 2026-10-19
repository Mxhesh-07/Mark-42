"""Tier 2 I1/I2 — the quota ledger and the budget guard.

The interesting half is I2: what happens when the ledger says "too much". The
answer has to be enforced by the *gate*, not by the accounting code, and it has
to survive the ladder's own recovery rule — a spend cap is lifted by the clock,
not by three calls going well.
"""

import time
from datetime import datetime

import pytest

from agent import degrade, quota


@pytest.fixture
def midday():
    """Local noon today: deterministic, and far from every window boundary.

    A rolling-hour test anchored at "now" goes wrong when the suite runs in the
    minute after midnight, so the tests anchor on a fixed point in the day.
    """
    today = datetime.now().date()
    return datetime(today.year, today.month, today.day, 12, 0, 0).timestamp()


@pytest.fixture
def budget_policy(write_policy):
    """A full, valid policy with a tightened `budget` block.

    `write_policy` replaces the file, so the base has to be the real default —
    otherwise the gate tests would be testing a policy with no tool table.
    """
    def _write(reads: dict | None = None, **budget) -> None:
        from agent import policy

        data = dict(policy.DEFAULT_POLICY)
        data["enabled"] = True
        data["budget"] = budget
        if reads:
            data["tools"] = {**data.get("tools", {}), **reads}
        write_policy(data)

    return _write


# --- the ledger ---------------------------------------------------------------

def test_a_fresh_ledger_is_empty():
    state = quota.usage()
    assert state["hour"]["calls"] == 0
    assert state["day"]["calls"] == 0
    assert state["breached"] is None


def test_a_recorded_call_is_counted():
    quota.record("gemini", "gemini-2.5-flash", now=100.0)
    state = quota.usage(now=100.0)
    assert state["hour"]["calls"] == 1
    assert state["hour"]["providers"] == {"gemini": 1}
    assert state["hour"]["models"] == {"gemini-2.5-flash": 1}


def test_the_ledger_is_written_to_disk():
    import json

    quota.record("gemini", "m", now=100.0)
    assert quota.LEDGER_PATH.exists()
    raw = json.loads(quota.LEDGER_PATH.read_text(encoding="utf-8"))
    assert len(raw["calls"]) == 1
    assert raw["calls"][0]["provider"] == "gemini"


def test_tokens_are_summed_when_reported():
    quota.record("gemini", "m", tokens=120, now=100.0)
    quota.record("gemini", "m", tokens=80, now=101.0)
    assert quota.usage(now=101.0)["hour"]["tokens"] == 200


def test_a_missing_provider_is_recorded_as_unknown():
    quota.record(None, None, now=100.0)
    assert quota.usage(now=100.0)["hour"]["providers"] == {"unknown": 1}


def test_a_corrupt_ledger_is_treated_as_empty():
    quota.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    quota.LEDGER_PATH.write_text("this is not json", encoding="utf-8")
    assert quota.usage()["hour"]["calls"] == 0


def test_recording_still_counts_after_a_corrupt_ledger():
    quota.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    quota.LEDGER_PATH.write_text("{", encoding="utf-8")
    quota.record("gemini", "m", now=100.0)
    assert quota.usage(now=100.0)["hour"]["calls"] == 1


# --- the windows ---------------------------------------------------------------

def test_the_hour_window_is_rolling_and_not_a_calendar_hour(midday):
    quota.record("gemini", "recent", now=midday - 100)
    quota.record("gemini", "old", now=midday - 3700)
    state = quota.usage(now=midday)
    assert state["hour"]["calls"] == 1
    assert state["hour"]["models"] == {"recent": 1}


def test_the_day_window_is_the_local_calendar_day(midday):
    quota.record("gemini", "today", now=midday)
    quota.record("gemini", "yesterday", now=midday - 86400)
    state = quota.usage(now=midday)
    assert state["day"]["calls"] == 1
    assert state["day"]["models"] == {"today": 1}
    assert state["hour"]["calls"] == 1


def test_a_burst_across_the_hour_boundary_still_counts(midday):
    """The point of a rolling window: 59 minutes ago is still "this hour"."""
    hour_start = datetime.fromtimestamp(midday).replace(minute=0, second=0).timestamp()
    quota.record("gemini", "m", now=hour_start - 60)     # 1 minute before the hour
    quota.record("gemini", "m", now=hour_start + 60)     # 1 minute after
    assert quota.usage(now=hour_start + 120)["hour"]["calls"] == 2


def test_old_entries_are_trimmed_on_write(midday):
    import json

    quota.record("gemini", "ancient", now=midday - quota.RETENTION_DAYS * 86400 - 60)
    quota.record("gemini", "now", now=midday)
    raw = json.loads(quota.LEDGER_PATH.read_text(encoding="utf-8"))
    assert len(raw["calls"]) == 1


# --- configuration --------------------------------------------------------------

def test_the_defaults_are_generous_but_real():
    cfg = quota.config()
    assert cfg["enabled"] is True
    assert cfg["max_calls_per_hour"] > 0
    assert cfg["max_calls_per_day"] > cfg["max_calls_per_hour"]


def test_the_config_can_tighten_the_caps(budget_policy):
    budget_policy(max_calls_per_hour=5, max_calls_per_day=50)
    limits = quota.usage()["limits"]
    assert limits["calls_per_hour"] == 5
    assert limits["calls_per_day"] == 50


def test_an_unknown_budget_key_is_ignored(budget_policy):
    budget_policy(max_calls_per_minute=1)
    assert quota.usage()["limits"]["calls_per_hour"] == quota.DEFAULTS["max_calls_per_hour"]


def test_a_zero_cap_means_unlimited(budget_policy):
    budget_policy(max_calls_per_hour=0, max_calls_per_day=0)
    for moment in range(5):
        quota.record("gemini", "m", now=100.0 + moment)
    assert quota.usage(now=104.0)["breached"] is None


def test_the_guard_can_be_switched_off(budget_policy):
    budget_policy(enabled=False, max_calls_per_hour=1)
    for moment in range(3):
        quota.record("gemini", "m", now=100.0 + moment)
    assert quota.usage(now=102.0)["breached"] is None
    assert degrade.level() == "FULL"


# --- the guard ------------------------------------------------------------------

def test_the_hour_cap_floors_the_ladder_at_read_only(budget_policy, midday):
    budget_policy(max_calls_per_hour=3, max_calls_per_day=100)
    for moment in range(3):
        quota.record("gemini", "m", now=midday + moment)
    assert degrade.level() == "READ_ONLY"
    assert degrade.floor() == ("READ_ONLY", "budget: hour call cap reached")


def test_the_floor_survives_the_ladders_own_recovery_rule(budget_policy, midday):
    """Three successes normally climb a step; a spend cap must not be climbed."""
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)
    assert degrade.level() == "READ_ONLY"
    for _ in range(9):
        degrade.note_success()
    assert degrade.level() == "READ_ONLY"


def test_a_failure_may_still_drop_below_the_floor(budget_policy, midday):
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)
    degrade.set_level("MONITOR", "infrastructure")
    assert degrade.level() == "MONITOR"


def test_the_day_cap_is_reported_before_the_hour_cap(budget_policy, midday):
    budget_policy(max_calls_per_hour=100, max_calls_per_day=3)
    for moment in range(3):
        quota.record("gemini", "m", now=midday + moment)
    assert quota.breached(now=midday + 2) == "day"


def test_the_floor_is_lifted_when_the_hour_rolls_over(budget_policy, midday):
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)
    assert degrade.level() == "READ_ONLY"
    quota.enforce(now=midday + 3700)
    assert degrade.floor() is None
    assert degrade.level() == "FULL"


def test_the_floor_is_lifted_when_the_day_rolls_over(budget_policy, midday):
    budget_policy(max_calls_per_hour=0, max_calls_per_day=1)
    quota.record("gemini", "m", now=midday)
    assert degrade.level() == "READ_ONLY"
    quota.enforce(now=midday + 86400)
    assert degrade.floor() is None
    assert degrade.level() == "FULL"


def test_release_does_not_clear_a_floor_it_did_not_set():
    degrade.set_floor("READ_ONLY", "infrastructure on fire")
    assert quota.release() is False
    assert degrade.floor() == ("READ_ONLY", "infrastructure on fire")


def test_release_lifts_its_own_floor():
    degrade.set_floor("READ_ONLY", "budget: hour call cap reached")
    assert quota.release() is True
    assert degrade.floor() is None


def test_an_unknown_on_breach_value_still_floors_the_ladder(budget_policy, midday):
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100, on_breach="shout")
    quota.record("gemini", "m", now=midday)
    assert degrade.level() == "READ_ONLY"


def test_the_breach_is_announced_once_per_window(budget_policy, midday, capsys):
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "a", now=midday)
    quota.record("gemini", "b", now=midday + 1)
    quota.record("gemini", "c", now=midday + 2)
    assert capsys.readouterr().out.count("[Budget]") == 1


def test_the_breach_is_announced_again_in_the_next_window(budget_policy, midday, capsys):
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "a", now=midday)
    quota.record("gemini", "b", now=midday + 3700)
    assert capsys.readouterr().out.count("[Budget]") == 2


def test_the_breach_is_written_to_the_audit_log(budget_policy, midday):
    from agent import audit

    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)
    assert any(entry.get("event") == "budget" for entry in audit.tail(20))


# --- the payoff: the gate -------------------------------------------------------

def test_the_gate_blocks_writes_after_a_budget_breach(budget_policy, midday):
    from agent import policy

    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)

    decision = policy.evaluate("cmd_control", {"command": "echo hi"})
    assert decision.level is policy.Level.BLOCK
    assert decision.hard is True
    assert "READ_ONLY" in decision.reason


def test_the_gate_still_allows_reads_after_a_budget_breach(budget_policy, midday):
    from agent import policy

    budget_policy(reads={"get_open_windows": "allow"},
                  max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)

    decision = policy.evaluate("get_open_windows", {})
    assert decision.level is policy.Level.ALLOW


# --- reporting ------------------------------------------------------------------

def test_describe_names_both_caps(budget_policy):
    budget_policy(max_calls_per_hour=7, max_calls_per_day=70)
    text = quota.describe()
    assert "cap 7" in text
    assert "cap 70" in text


def test_describe_says_when_it_is_over(budget_policy, midday):
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)
    assert "OVER" in quota.describe(now=midday)


def test_status_reports_the_ledger_and_the_ladder(budget_policy):
    budget_policy()
    out = quota.status()
    assert out["ledger"].endswith("quota_ledger.json")
    assert out["enabled"] is True
    assert out["degradation"]["level"] == "FULL"


def test_clear_wipes_the_ledger(midday):
    quota.record("gemini", "m", now=midday)
    assert quota.clear() == 1
    assert quota.usage(now=midday)["hour"]["calls"] == 0


def test_clear_lifts_a_budget_floor(budget_policy, midday):
    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=midday)
    assert degrade.level() == "READ_ONLY"
    quota.clear()
    assert degrade.level() == "FULL"


# --- the CLI --------------------------------------------------------------------

def test_the_cli_prints_json_status(budget_policy, capsys):
    budget_policy()
    assert quota._cli([]) == 0
    assert "quota_ledger.json" in capsys.readouterr().out


def test_the_cli_prints_a_human_line(budget_policy, capsys):
    budget_policy()
    assert quota._cli(["--text"]) == 0
    assert "calls this hour" in capsys.readouterr().out


def test_the_cli_refuses_to_clear_without_yes(capsys):
    assert quota._cli(["clear"]) == 2
    assert "refusing" in capsys.readouterr().out


def test_the_cli_clears_with_yes(capsys):
    assert quota._cli(["clear", "--yes"]) == 0
    assert "cleared" in capsys.readouterr().out


def test_the_cli_rejects_a_stray_argument(capsys):
    assert quota._cli(["nonsense"]) == 2
    assert "usage" in capsys.readouterr().out


# --- the wiring -----------------------------------------------------------------

def test_gemini_calls_are_recorded():
    import gemini_util

    gemini_util._record_success("gemini-2.5-flash", "gemini-2.5-flash")
    state = quota.usage()
    assert state["hour"]["providers"].get("gemini") == 1
    assert "gemini-2.5-flash" in state["hour"]["models"]


def test_tier2_calls_are_recorded_against_their_provider():
    import gemini_util

    gemini_util._record_success("groq:llama-3.3-70b", None)
    state = quota.usage()
    assert state["hour"]["providers"] == {"groq": 1}
    assert state["hour"]["models"] == {"llama-3.3-70b": 1}


def test_accounting_never_breaks_a_conversation(monkeypatch):
    import gemini_util

    def explode(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(quota, "record", explode)
    gemini_util._record_success("gemini-2.5-flash", None)     # must not raise


def test_health_reports_the_budget(budget_policy):
    from agent import health

    budget_policy()
    check = health.check_budget()
    assert check["ok"] is True
    assert "calls this hour" in check["detail"]


def test_health_flags_an_exceeded_budget(budget_policy):
    from agent import health

    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=time.time())      # this hour, as health sees it
    check = health.check_budget()
    assert check["ok"] is False
    assert "budget" in check["detail"]


def test_health_status_does_not_act_on_the_budget(budget_policy):
    """`status` reports; it must not be the thing that flips the ladder."""
    from agent import health

    budget_policy(max_calls_per_hour=1, max_calls_per_day=100)
    quota.record("gemini", "m", now=time.time())
    assert degrade.level() == "READ_ONLY"
    degrade.reset()                                   # as if the guard had not run

    out = health.status()
    assert out["quota"]["breached"] == "hour"
    assert degrade.level() == "FULL"
