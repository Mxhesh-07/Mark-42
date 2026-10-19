"""Tier 4 W1 — proactivity with restraint.

The whole point of this module is the *suppression* pipeline, so these tests
pin the caps, the budgets and the cooldowns rather than the checks, which are
best-effort probes.
"""

import pytest

from agent import audit, initiative
from agent.initiative import (DIGEST, INTERRUPT, NOTIFY, SILENT, SPEAK, Candidate,
                              Initiative, Trigger)


class FakeClock:
    """A monotonic clock and a wall clock that only move when told to."""

    def __init__(self, now: float = 1000.0, wall: float = 12 * 3600.0):
        self.now = now
        self.wall = wall

    def monotonic(self) -> float:
        return self.now

    def wall_seconds(self) -> float:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Harness:
    def __init__(self, config: dict | None = None, **clock_kwargs):
        self.cfg = dict(initiative.DEFAULT_CONFIG)
        if config:
            self.cfg.update(config)
        self.clock = FakeClock(**clock_kwargs)
        self.engine = Initiative(clock=self.clock.monotonic,
                                 wall=self.clock.wall_seconds,
                                 config=lambda: self.cfg)

    def add(self, trigger_id="t", signal=True, urgency=3, cooldown_sec=0, **kwargs):
        calls = {"n": 0}

        def check():
            calls["n"] += 1
            return signal

        if callable(signal):
            check = signal
        self.engine.register(Trigger(trigger_id, check, urgency, cooldown_sec,
                                     kwargs.pop("description", trigger_id)))
        return calls


ALWAYS = True


# --- the urgency scale --------------------------------------------------------

def test_the_scale_is_the_documented_one():
    assert (SILENT, DIGEST, NOTIFY, SPEAK, INTERRUPT) == (0, 1, 2, 3, 4)
    assert initiative.LEVELS == ("SILENT", "DIGEST", "NOTIFY", "SPEAK", "INTERRUPT")


def test_a_trigger_rejects_an_urgency_outside_the_scale():
    with pytest.raises(ValueError):
        Trigger("bad", lambda: False, 5, 0, "out of range")
    with pytest.raises(ValueError):
        Trigger("bad", lambda: False, -1, 0, "out of range")


@pytest.mark.parametrize("urgency,action", list(enumerate(initiative.LEVELS)))
def test_a_candidate_reports_its_action(urgency, action):
    candidate = Candidate("t", urgency, {}, "why")
    assert candidate.action == action


def test_an_urgency_0_trigger_never_reaches_dispatch():
    harness = Harness()
    harness.add(urgency=SILENT)
    assert harness.engine.evaluate() == []


def test_a_candidate_below_min_urgency_is_dropped():
    harness = Harness({"min_urgency": 3})
    harness.add(urgency=2)
    assert harness.engine.evaluate() == []


def test_a_candidate_at_min_urgency_survives():
    harness = Harness({"min_urgency": 2})
    harness.add(urgency=2)
    assert [c.urgency for c in harness.engine.evaluate()] == [2]


# --- the check runs once, and only when it fires ------------------------------

def test_a_check_runs_exactly_once_per_tick():
    harness = Harness()
    calls = harness.add()
    harness.engine.evaluate()
    assert calls["n"] == 1


def test_a_silent_check_produces_nothing():
    harness = Harness()
    harness.add(signal=False)
    assert harness.engine.evaluate() == []


def test_a_raising_check_never_breaks_the_tick():
    def boom():
        raise RuntimeError("probe exploded")

    harness = Harness()
    harness.add(signal=boom)
    harness.add(trigger_id="fine")
    assert [c.trigger_id for c in harness.engine.evaluate()] == ["fine"]


def test_a_dict_signal_becomes_the_payload():
    harness = Harness()
    harness.add(signal={"message": "hello", "n": 2})
    candidate = harness.engine.evaluate()[0]
    assert candidate.payload == {"message": "hello", "n": 2}
    assert candidate.message == "hello"


def test_a_string_signal_becomes_the_message():
    harness = Harness()
    harness.add(signal="plain text")
    assert harness.engine.evaluate()[0].message == "plain text"


def test_a_true_signal_uses_the_description():
    harness = Harness()
    harness.add(signal=True, description="the battery is low")
    assert harness.engine.evaluate()[0].message == "the battery is low"


# --- the suppression ladder ---------------------------------------------------

def test_quiet_hours_cap_to_digest():
    harness = Harness(wall=23.5 * 3600.0)
    harness.add(urgency=INTERRUPT)
    candidate = harness.engine.evaluate()[0]
    assert candidate.urgency == DIGEST
    assert candidate.action == "DIGEST"
    assert "quiet hours" in candidate.suppressed_by
    assert candidate.declared_urgency == INTERRUPT


def test_quiet_hours_that_wrap_midnight_are_handled():
    harness = Harness(wall=2 * 3600.0)        # 02:00, inside 23:00 -> 07:00
    harness.add(urgency=SPEAK)
    assert harness.engine.evaluate()[0].urgency == DIGEST


def test_a_daytime_candidate_is_untouched():
    harness = Harness(wall=12 * 3600.0)
    harness.add(urgency=SPEAK)
    assert harness.engine.evaluate()[0].urgency == SPEAK


def test_user_speaking_caps_to_notify():
    harness = Harness()
    harness.engine.set_user_speaking(True)
    harness.add(urgency=INTERRUPT)
    candidate = harness.engine.evaluate()[0]
    assert candidate.urgency == NOTIFY
    assert "user is speaking" in candidate.suppressed_by


def test_focus_mode_caps_to_notify():
    harness = Harness()
    harness.engine.set_focus(True)
    harness.add(urgency=INTERRUPT)
    assert harness.engine.evaluate()[0].suppressed_by == "focus mode"


def test_a_meeting_caps_to_notify():
    harness = Harness()
    harness.engine.set_meeting(True)
    harness.add(urgency=SPEAK)
    assert harness.engine.evaluate()[0].suppressed_by == "meeting in progress"


def test_the_lowest_cap_wins():
    harness = Harness(wall=23.5 * 3600.0)     # quiet hours -> DIGEST
    harness.engine.set_focus(True)            # focus -> NOTIFY
    harness.add(urgency=INTERRUPT)
    candidate = harness.engine.evaluate()[0]
    assert candidate.urgency == DIGEST        # the tighter of the two
    assert "quiet hours" in candidate.suppressed_by


def test_the_reason_names_the_declared_urgency():
    harness = Harness()
    harness.add(trigger_id="x", urgency=SPEAK, description="something")
    assert "urgency 3" in harness.engine.evaluate()[0].reason


# --- cooldowns ----------------------------------------------------------------

def test_a_cooldown_suppresses_a_repeat():
    harness = Harness()
    harness.add(cooldown_sec=600)
    assert len(harness.engine.evaluate()) == 1
    assert harness.engine.evaluate() == []
    harness.clock.advance(599)
    assert harness.engine.evaluate() == []
    harness.clock.advance(2)
    assert len(harness.engine.evaluate()) == 1


def test_a_cooldown_is_per_trigger():
    harness = Harness()
    harness.add(trigger_id="a", cooldown_sec=600)
    harness.add(trigger_id="b", cooldown_sec=600)
    assert {c.trigger_id for c in harness.engine.evaluate()} == {"a", "b"}
    assert harness.engine.evaluate() == []


def test_a_dropped_candidate_still_consumes_its_cooldown():
    """Otherwise a SILENT trigger would be re-probed loudly every tick."""
    harness = Harness({"min_urgency": 4})
    harness.add(urgency=1, cooldown_sec=600)
    assert harness.engine.evaluate() == []
    harness.add(trigger_id="loud", urgency=4)
    assert [c.trigger_id for c in harness.engine.evaluate()] == ["loud"]


# --- budgets -----------------------------------------------------------------

def test_the_hourly_interrupt_budget_is_enforced():
    harness = Harness({"max_interrupts_per_hour": 1})
    harness.add(trigger_id="first", urgency=INTERRUPT, cooldown_sec=0)
    engine = harness.engine
    assert engine.tick() == [("first", "INTERRUPT")]

    harness.add(trigger_id="second", urgency=INTERRUPT, cooldown_sec=0)
    candidate = [c for c in engine.evaluate() if c.trigger_id == "second"][0]
    assert candidate.urgency == NOTIFY
    assert candidate.suppressed_by == "interrupt budget exhausted"


def test_the_speak_budget_is_enforced():
    harness = Harness({"max_speaks_per_hour": 1})
    harness.add(trigger_id="first", urgency=SPEAK)
    assert harness.engine.tick() == [("first", "SPEAK")]

    harness.add(trigger_id="second", urgency=SPEAK)
    assert harness.engine.evaluate()[0].urgency == NOTIFY


def test_a_digest_does_not_spend_the_speak_budget():
    harness = Harness({"max_speaks_per_hour": 1})
    harness.add(trigger_id="quiet_one", urgency=NOTIFY)
    harness.engine.tick()
    harness.add(trigger_id="loud", urgency=SPEAK)
    assert harness.engine.evaluate()[0].urgency == SPEAK


def test_the_budget_window_slides():
    harness = Harness({"max_interrupts_per_hour": 1})
    harness.add(trigger_id="first", urgency=INTERRUPT)
    harness.engine.tick()
    harness.clock.advance(3601)
    harness.add(trigger_id="second", urgency=INTERRUPT)
    assert harness.engine.evaluate()[0].urgency == INTERRUPT


def test_budget_state_reports_usage():
    harness = Harness({"max_interrupts_per_hour": 2, "max_speaks_per_hour": 5})
    harness.add(urgency=SPEAK)
    harness.engine.tick()
    state = harness.engine.budget_state()
    assert state["speaks"] == {"used": 1, "max": 5}
    assert state["interrupts"] == {"used": 0, "max": 2}
    assert state["window_sec"] == initiative.WINDOW_S
    assert state["quiet"] is False


# --- dispatch -----------------------------------------------------------------

def test_dispatch_writes_exactly_one_audit_entry(monkeypatch):
    entries = []
    monkeypatch.setattr(audit, "record", lambda *a, **kw: entries.append((a, kw)))

    harness = Harness()
    candidate = Candidate("battery_low", SPEAK, {"message": "low"}, "why",
                          declared_urgency=SPEAK)
    assert harness.engine.dispatch(candidate) == "SPEAK"
    assert len(entries) == 1
    assert entries[0][0][0] == "initiative"
    assert entries[0][1]["tool"] == "battery_low"
    assert entries[0][1]["urgency"] == SPEAK


def test_a_speaking_candidate_reaches_the_speaker():
    spoken = []
    harness = Harness()
    harness.engine.configure(speaker=spoken.append)
    harness.add(urgency=SPEAK, signal={"message": "Battery at 12%."})
    harness.engine.tick()
    assert spoken == ["Battery at 12%."]


def test_a_notification_reaches_the_notifier():
    seen = []
    harness = Harness()
    harness.engine.configure(notifier=lambda title, text: seen.append((title, text)))
    harness.add(urgency=NOTIFY, signal={"message": "heads up"})
    harness.engine.tick()
    assert seen == [("JARVIS", "heads up")]


def test_a_broken_sink_does_not_break_the_tick(capsys):
    def explode(_text):
        raise RuntimeError("the UI is gone")

    harness = Harness()
    harness.engine.configure(speaker=explode)
    harness.add(urgency=SPEAK)
    assert harness.engine.tick() == [("t", "SPEAK")]
    assert "dispatch sink failed" in capsys.readouterr().out


def test_digest_candidates_are_collected_not_spoken():
    spoken = []
    harness = Harness()
    harness.engine.configure(speaker=spoken.append)
    harness.add(urgency=DIGEST, signal={"message": "fyi"})
    harness.engine.tick()
    assert spoken == []
    assert [c.message for c in harness.engine.take_digest()] == ["fyi"]
    assert harness.engine.take_digest() == []


def test_notifications_are_collected():
    harness = Harness()
    harness.add(urgency=NOTIFY, signal={"message": "heads up"})
    harness.engine.tick()
    assert [c.trigger_id for c in harness.engine.take_notifications()] == ["t"]


def test_silent_candidates_are_logged_only():
    harness = Harness()
    candidate = Candidate("t", SILENT, {"message": "nothing"}, "why")
    assert harness.engine.dispatch(candidate) == "SILENT"
    assert harness.engine.take_digest() == []


# --- ordering and enablement --------------------------------------------------

def test_candidates_are_ordered_by_urgency_then_id():
    harness = Harness()
    harness.add(trigger_id="a", urgency=1)
    harness.add(trigger_id="b", urgency=3)
    harness.add(trigger_id="c", urgency=3)
    assert [c.trigger_id for c in harness.engine.evaluate()] == ["b", "c", "a"]


def test_the_engine_can_be_switched_off():
    harness = Harness({"enabled": False})
    harness.add(urgency=INTERRUPT)
    assert harness.engine.evaluate() == []
    assert harness.engine.tick() == []


# --- the kill switch ----------------------------------------------------------

def test_the_kill_switch_drops_all_candidates(monkeypatch):
    from agent import policy

    monkeypatch.setattr(policy, "kill_requested", lambda: True)
    harness = Harness()
    harness.add(urgency=INTERRUPT)
    assert harness.engine.evaluate() == []
    assert harness.engine.tick() == []


def test_the_kill_switch_drops_a_dispatch(monkeypatch):
    from agent import policy

    monkeypatch.setattr(policy, "kill_requested", lambda: True)
    harness = Harness()
    candidate = Candidate("t", INTERRUPT, {}, "why")
    assert harness.engine.dispatch(candidate) == "DROPPED"


# --- the config can only lower an urgency -------------------------------------

def test_the_config_lowers_an_urgency():
    harness = Harness({"triggers": {"loud": "digest"}})
    harness.add(trigger_id="loud", urgency=INTERRUPT)
    assert harness.engine.evaluate()[0].urgency == DIGEST


def test_the_config_cannot_raise_an_urgency():
    """Urgency is a fixed trigger property; only a human may lower it."""
    harness = Harness({"triggers": {"quiet": "interrupt"}})
    harness.add(trigger_id="quiet", urgency=NOTIFY)
    assert harness.engine.evaluate()[0].urgency == NOTIFY


def test_an_unknown_configured_action_is_ignored():
    harness = Harness({"triggers": {"t": "shout"}})
    harness.add(urgency=SPEAK)
    assert harness.engine.evaluate()[0].urgency == SPEAK


def test_unregistering_a_trigger_clears_its_cooldown():
    harness = Harness()
    harness.add(trigger_id="t", cooldown_sec=600)
    harness.engine.evaluate()
    harness.engine.unregister("t")
    assert harness.engine.triggers() == []
    harness.add(trigger_id="t", cooldown_sec=600)
    assert len(harness.engine.evaluate()) == 1


# --- the focus clock ----------------------------------------------------------

def test_the_focus_stretch_starts_at_zero():
    harness = Harness()
    assert harness.engine.focus_stretch_sec() == 0.0


def test_the_focus_stretch_grows_with_activity():
    harness = Harness()
    harness.engine.note_activity()
    for _ in range(60):                       # a minute at a time, never idle
        harness.clock.advance(60)
        harness.engine.note_activity()
    assert harness.engine.focus_stretch_sec() == pytest.approx(3600.0)


def test_a_long_idle_gap_restarts_the_focus_stretch():
    harness = Harness()
    harness.engine.note_activity()
    harness.clock.advance(initiative.IDLE_RESET_S + 1)
    harness.engine.note_activity()
    assert harness.engine.focus_stretch_sec() == pytest.approx(0.0)


def test_the_focus_break_trigger_fires_after_two_hours():
    harness = Harness()
    check = initiative.check_focus_stretch(harness.engine.focus_stretch_sec)
    assert check() is None
    harness.engine.note_activity()
    harness.clock.advance(7201)
    assert "two hours" in check()["message"]


# --- helpers ------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("23:00", 23 * 3600),
    ("07:30", 7 * 3600 + 1800),
    ("00:00", 0),
    ("nonsense", None),
    ("25:00", None),
    ("12:99", None),
    (None, None),
])
def test_parse_hhmm(text, expected):
    assert initiative.parse_hhmm(text) == expected


def test_reset_clears_the_engine():
    harness = Harness()
    harness.add(urgency=INTERRUPT)
    harness.engine.tick()
    harness.engine.reset_for_tests()
    assert harness.engine.triggers() == []
    assert harness.engine.budget_state()["speaks"]["used"] == 0


# --- the starter triggers -----------------------------------------------------

def test_the_starter_triggers_are_well_formed():
    engine = Initiative(clock=lambda: 0.0, wall=lambda: 0.0, config=lambda: {})
    triggers = initiative.default_triggers(engine)
    ids = [t.id for t in triggers]
    assert len(ids) == len(set(ids))
    for trigger in triggers:
        assert callable(trigger.check)
        assert SILENT <= trigger.urgency <= INTERRUPT
        assert trigger.cooldown_sec >= 0
        assert trigger.description


def test_the_starter_triggers_do_not_include_an_urgency_4():
    """Nagging is the failure mode; nothing ships as an interruption."""
    engine = Initiative(clock=lambda: 0.0, wall=lambda: 0.0, config=lambda: {})
    assert all(t.urgency < INTERRUPT
               for t in initiative.default_triggers(engine))


@pytest.mark.parametrize("name", ["email_important", "quota_exhausted", "device_offline"])
def test_a_seam_trigger_is_silent_until_a_source_is_provided(name):
    check = initiative._seam(name)
    initiative._SOURCES.pop(name, None)
    assert check() is None
    initiative.provide(name, lambda: {"message": "from the source"})
    try:
        assert check()["message"] == "from the source"
    finally:
        initiative._SOURCES.pop(name, None)


def test_a_failing_source_is_swallowed():
    def boom():
        raise RuntimeError("source down")

    initiative.provide("device_offline", boom)
    try:
        assert initiative._seam("device_offline")() is None
    finally:
        initiative._SOURCES.pop("device_offline", None)


def test_the_self_contained_checks_survive_this_machine():
    """They are probes: on any machine they must answer, never raise."""
    for check in (initiative.check_battery_low, initiative.check_disk_full,
                  initiative.check_calendar_conflict, initiative.check_deadline_near):
        assert check() is None or isinstance(check(), dict)


# --- the shared engine and the CLI --------------------------------------------

@pytest.fixture
def quiet_starter_checks(monkeypatch):
    """Neutralise the real probes so a shared-engine tick touches nothing."""
    for name in ("check_battery_low", "check_disk_full", "check_calendar_conflict",
                 "check_deadline_near"):
        monkeypatch.setattr(initiative, name, lambda: None)


def test_the_shared_engine_registers_the_starter_triggers(quiet_starter_checks):
    try:
        engine = initiative.get()
        assert "battery_low" in engine.triggers()
        assert engine is initiative.get()
    finally:
        initiative.reset()


def test_a_tick_returns_pairs_and_never_raises(quiet_starter_checks):
    try:
        result = initiative.tick()
        assert isinstance(result, list)
        for entry in result:
            assert len(entry) == 2
    finally:
        initiative.reset()


def test_the_cli_prints_state(quiet_starter_checks, capsys):
    try:
        assert initiative._cli([]) == 0
        assert "triggers" in capsys.readouterr().out
    finally:
        initiative.reset()


def test_the_cli_can_send_a_notification(quiet_starter_checks, capsys):
    try:
        assert initiative._cli(["send", "hello there"]) == 0
        assert initiative.get().take_notifications()
    finally:
        initiative.reset()


def test_the_cli_tick_is_idempotent(quiet_starter_checks, capsys):
    try:
        assert initiative._cli(["tick"]) == 0
        capsys.readouterr()
    finally:
        initiative.reset()
