"""Tier 4 W6 — the confirmation modal, and the narrow rules it writes.

The dialog itself needs a display, so the tested half is the decision logic: what
the panel says, what Deny does by default, what counts as "narrow", and that
every decision is audited exactly once and can never approve by accident.
"""

import json
import threading

import pytest

from agent import approval_rules, audit
from agent.judgement import assess
from agent.policy import Decision, Level
from ui import confirm


DELETE = {"action": "delete", "path": "C:/x/y.txt"}
SEND = {"recipient": "a@example.com", "message": "hi"}


@pytest.fixture(autouse=True)
def _rules_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(approval_rules, "RULES_PATH", tmp_path / "approval_rules.json")


@pytest.fixture
def sandboxed_delete(tmp_path):
    """A delete whose target is inside the sandbox root, so policy reaches the gate."""
    return {"action": "delete", "path": str(tmp_path / "y.txt")}


# --- the panel ----------------------------------------------------------------

def test_deny_holds_the_focus():
    panel = confirm.content("file_controller", DELETE)
    defaults = [b for b in panel["buttons"] if b["default"]]
    assert [b["id"] for b in defaults] == [confirm.DENY]


def test_the_panel_shows_the_effect_not_the_tool_name():
    panel = confirm.content("file_controller", DELETE)
    assert "y.txt" in panel["summary"]
    assert "file_controller" not in panel["summary"]


def test_the_panel_shows_the_risk_and_the_opinion():
    assessment = assess("file_controller", DELETE, decision=Decision(Level.CONFIRM, "x"))
    panel = confirm.content("file_controller", DELETE, assessment)
    assert panel["risk"] == assessment.risk
    assert panel["reversibility"] == "permanent"
    assert panel["blast_radius"] == "local"
    assert panel["opinion"] == assessment.opinion


def test_the_panel_resolves_the_target():
    panel = confirm.content("send_message", SEND)
    assert panel["target"] == "a@example.com"


def test_the_panel_has_a_countdown():
    assert confirm.content("file_controller", DELETE)["timeout_s"] == 30.0


def test_the_buttons_are_deny_approve_then_always():
    ids = [b["id"] for b in confirm.content("file_controller", DELETE)["buttons"]]
    assert ids == [confirm.DENY, confirm.APPROVE, confirm.ALWAYS]


def test_always_allow_is_offered_only_when_the_call_is_narrowable():
    panel = confirm.content("generated_code", {"code": "print(1)"})
    assert [b["id"] for b in panel["buttons"]] == [confirm.DENY, confirm.APPROVE]
    assert panel["narrowable"] is False


# --- the narrow rule ----------------------------------------------------------

def test_a_narrow_rule_keeps_the_target():
    rule = approval_rules.build("file_controller", DELETE)
    assert rule["tool"] == "file_controller"
    assert rule["action"] == "delete"
    assert rule["target_key"] == "path"
    assert rule["target"].endswith("y.txt")


def test_a_narrow_rule_is_not_tool_wide():
    """It must not cover a different file, a different action, or a bare tool."""
    approval_rules.add(approval_rules.build("file_controller", DELETE))
    assert approval_rules.matches("file_controller", DELETE) is not None
    assert approval_rules.matches("file_controller",
                                  {"action": "delete", "path": "C:/x/other.txt"}) is None
    assert approval_rules.matches("file_controller",
                                  {"action": "remove", "path": "C:/x/y.txt"}) is None
    assert approval_rules.matches("file_controller", {}) is None
    assert approval_rules.matches("send_message", SEND) is None


def test_a_relative_path_and_an_absolute_one_are_the_same_target():
    approval_rules.add(approval_rules.build("file_controller",
                                           {"action": "delete", "path": "./notes.txt"}))
    import os

    absolute = os.path.abspath("./notes.txt")
    assert approval_rules.matches("file_controller",
                                  {"action": "delete", "path": absolute}) is not None


def test_a_path_target_is_case_folded_only_as_a_path():
    """A recipient is compared as text; a path is resolved as a path."""
    rule = approval_rules.build("send_message", {"recipient": "A@Example.com"})
    assert rule["target"] == "a@example.com"


def test_a_tool_without_a_target_has_no_rule():
    for tool, params in (("cmd_control", {"command": "dir"}),
                         ("generated_code", {"code": "print(1)"}),
                         ("dev_agent", {"goal": "refactor"})):
        assert approval_rules.build(tool, params) is None


def test_adding_the_same_rule_twice_keeps_one():
    rule = approval_rules.build("file_controller", DELETE)
    approval_rules.add(rule)
    approval_rules.add(rule)
    assert len(approval_rules.rules()) == 1


def test_a_rule_survives_a_reload():
    approval_rules.add(approval_rules.build("file_controller", DELETE))
    assert approval_rules.matches("file_controller", DELETE) is not None


def test_forget_removes_only_the_matching_rule():
    approval_rules.add(approval_rules.build("file_controller", DELETE))
    other = approval_rules.build("file_controller",
                                 {"action": "delete", "path": "C:/x/other.txt"})
    approval_rules.add(other)
    assert approval_rules.forget("file_controller", DELETE) is True
    assert approval_rules.matches("file_controller", DELETE) is None
    assert approval_rules.matches(
        "file_controller", {"action": "delete", "path": "C:/x/other.txt"}) is not None


def test_rules_are_capped():
    for index in range(approval_rules.MAX_RULES + 25):
        approval_rules.add({"tool": "t", "action": "", "target_key": "path",
                            "target": f"c:/x/{index}.txt"})
    assert len(approval_rules.rules()) == approval_rules.MAX_RULES


def test_a_corrupt_rules_file_reads_as_empty():
    approval_rules.RULES_PATH.write_text("{not json", encoding="utf-8")
    assert approval_rules.rules() == []
    assert approval_rules.matches("file_controller", DELETE) is None


# --- the policy hook ----------------------------------------------------------

def test_a_saved_rule_turns_the_confirm_into_an_allow(write_policy, sandboxed_delete):
    write_policy({"enabled": True, "tools": {"file_controller": "confirm"},
                  "actions": {"file_controller": {"delete": "confirm"}}})
    from agent import policy

    assert policy.evaluate("file_controller", sandboxed_delete).level is Level.CONFIRM
    approval_rules.add(approval_rules.build("file_controller", sandboxed_delete))
    assert policy.evaluate("file_controller", sandboxed_delete).level is Level.ALLOW


def test_a_saved_rule_cannot_override_a_block(write_policy, sandboxed_delete):
    write_policy({"enabled": True, "tools": {"file_controller": "block"}})
    approval_rules.add(approval_rules.build("file_controller", sandboxed_delete))
    from agent import policy

    assert policy.evaluate("file_controller", sandboxed_delete).level is Level.BLOCK


def test_a_saved_rule_does_not_widen_a_guest(write_policy, monkeypatch, sandboxed_delete):
    write_policy({"enabled": True, "tools": {"file_controller": "confirm"},
                  "actions": {"file_controller": {"delete": "confirm"}}})
    from agent import policy, roles

    approval_rules.add(approval_rules.build("file_controller", sandboxed_delete))
    monkeypatch.setattr(roles, "current", lambda: roles.GUEST)
    assert policy.evaluate("file_controller", sandboxed_delete).level is not Level.ALLOW


def test_a_saved_rule_cannot_lift_the_kill_switch(write_policy, sandboxed_delete):
    write_policy({"enabled": True, "tools": {"file_controller": "confirm"}})
    from agent import policy

    approval_rules.add(approval_rules.build("file_controller", sandboxed_delete))
    policy.engage_kill_switch("test")
    try:
        assert policy.evaluate("file_controller", sandboxed_delete).level is Level.BLOCK
    finally:
        policy.disengage_kill_switch()


# --- consult / ask ------------------------------------------------------------

def test_ask_with_no_ui_denies():
    assert confirm.ask("file_controller", DELETE) == confirm.DENY


def test_a_headless_deny_is_audited_once(monkeypatch):
    entries = []
    monkeypatch.setattr(audit, "record", lambda *a, **kw: entries.append((a, kw)))
    confirm.ask("file_controller", DELETE)
    assert len(entries) == 1
    assert entries[0][0][0] == "approval_ui"
    assert entries[0][1]["outcome"] == confirm.DENY


def test_an_approval_is_audited_once(monkeypatch):
    entries = []
    monkeypatch.setattr(audit, "record", lambda *a, **kw: entries.append((a, kw)))
    confirm.ask("file_controller", DELETE,
                show=lambda panel, done: done(confirm.APPROVE))
    assert len(entries) == 1
    assert entries[0][1]["outcome"] == confirm.APPROVE


def test_the_user_can_approve():
    answer = confirm.consult("file_controller", DELETE,
                             show=lambda panel, done: done(confirm.APPROVE))
    assert answer.decision == confirm.APPROVE
    assert answer.approved is True
    assert answer.reason == "chosen"


def test_the_user_can_deny():
    answer = confirm.consult("file_controller", DELETE,
                             show=lambda panel, done: done(confirm.DENY))
    assert answer.decision == confirm.DENY
    assert answer.approved is False


def test_invalid_answers_are_coerced_to_deny():
    answer = confirm.consult("file_controller", DELETE,
                             show=lambda panel, done: done("maybe"))
    assert answer.decision == confirm.DENY


def test_always_is_never_accepted_when_it_was_not_offered():
    """A stale 'always' for a call with no narrow target is a deny."""
    answer = confirm.consult("generated_code", {"code": "print(1)"},
                             show=lambda panel, done: done(confirm.ALWAYS))
    assert answer.decision == confirm.DENY
    assert "not offered" in answer.reason
    assert approval_rules.rules() == []


def test_a_timeout_denies():
    """The dialog never answers, so the decision is Deny — not a hang."""
    def never(panel, done):
        pass

    answer = confirm.consult("file_controller", DELETE, timeout_s=0.05, show=never)
    assert answer.decision == confirm.DENY
    assert answer.reason == "timeout"


def test_a_failing_dialog_denies(capsys):
    def explode(panel, done):
        raise RuntimeError("no display")

    answer = confirm.consult("file_controller", DELETE, show=explode)
    assert answer.decision == confirm.DENY
    assert answer.reason == "dialog failed"
    assert "dialog failed" in capsys.readouterr().out


def test_a_late_answer_after_the_timeout_is_ignored():
    """The first answer wins; a second one cannot flip a deny into an approve."""
    answers = []

    def slow(panel, done):
        done(confirm.DENY)
        done(confirm.APPROVE)          # a stray double-click
        answers.append(True)

    answer = confirm.consult("file_controller", DELETE, timeout_s=1.0, show=slow)
    assert answer.decision == confirm.DENY
    assert answers == [True]


def test_always_writes_a_narrow_rule():
    confirm.ask("file_controller", DELETE, show=lambda panel, done: done(confirm.ALWAYS))
    rules = approval_rules.rules()
    assert len(rules) == 1
    assert rules[0]["target"].endswith("y.txt")
    assert approval_rules.matches("file_controller", DELETE) is not None


def test_approve_once_does_not_write_a_rule():
    confirm.ask("file_controller", DELETE, show=lambda panel, done: done(confirm.APPROVE))
    assert approval_rules.rules() == []


def test_the_dialog_does_not_block_the_caller():
    """The modal is built elsewhere; the caller waits on an event, not a spin."""
    thread_names = []

    def slow(panel, done):
        thread_names.append(threading.current_thread().name)

        def later():
            done(confirm.APPROVE)

        threading.Timer(0.02, later).start()

    answer = confirm.consult("file_controller", DELETE, timeout_s=2.0, show=slow)
    assert answer.decision == confirm.APPROVE
    assert thread_names == [threading.current_thread().name]


def test_reset_gates_nothing_after_the_fact():
    approval_rules.add(approval_rules.build("file_controller", DELETE))
    approval_rules.clear()
    assert approval_rules.matches("file_controller", DELETE) is None


# --- the executor's approver --------------------------------------------------

def test_the_ui_approver_returns_a_bool():
    approver = confirm.ui_approver(None)
    assert approver("file_controller", DELETE, "delete C:/x/y.txt") in (True, False)


def test_the_ui_approver_fails_closed_without_a_root():
    """No root means no modal, and no modal means no approval."""
    approver = confirm.ui_approver(None)
    assert approver("file_controller", DELETE, "delete C:/x/y.txt") is False


def test_the_ui_approver_accepts_an_assessment():
    approver = confirm.ui_approver(None)
    assessment = assess("file_controller", DELETE, decision=Decision(Level.CONFIRM, "x"))
    assert approver("file_controller", DELETE, "delete", assessment=assessment) is False


# --- the pure bits ------------------------------------------------------------

def test_status_reports_the_rules():
    approval_rules.add(approval_rules.build("file_controller", DELETE))
    state = approval_rules.status()
    assert state["count"] == 1
    assert state["rules"][0]["tool"] == "file_controller"


def test_the_cli_prints_the_panel(capsys):
    assert confirm._cli(["file_controller",
                         json.dumps({"action": "delete", "path": "C:/x/y.txt"})]) == 0
    out = capsys.readouterr().out
    assert "buttons" in out
    assert "narrow_rule" in out


def test_the_rules_cli_prints_state(capsys):
    assert approval_rules._cli([]) == 0
    assert "count" in capsys.readouterr().out


def test_the_rules_cli_can_clear(capsys):
    approval_rules.add(approval_rules.build("file_controller", DELETE))
    assert approval_rules._cli(["clear"]) == 0
    assert approval_rules.rules() == []
