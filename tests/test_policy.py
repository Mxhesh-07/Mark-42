"""The permission gate is the safety net, so it is tested hardest."""

import json

from agent import policy
from agent.policy import Level


def test_known_read_only_tool_is_allowed(policy_file):
    assert policy.evaluate("web_search", {"query": "x"}).level is Level.ALLOW


def test_side_effecting_tool_needs_confirmation(policy_file):
    assert policy.evaluate("send_message", {"to": "a", "body": "b"}).level is Level.CONFIRM


def test_unlisted_tool_falls_back_to_the_default(policy_file):
    assert policy.evaluate("brand_new_tool", {}).level is Level.CONFIRM


def test_action_override_allows_a_read(policy_file):
    d = policy.evaluate("file_controller", {"action": "read", "path": "x.txt"})
    assert d.level is Level.ALLOW


def test_action_override_keeps_delete_at_confirm(policy_file):
    d = policy.evaluate("file_controller", {"action": "delete", "path": "x.txt"})
    assert d.level is Level.CONFIRM


def test_config_can_block_an_action(policy_file):
    assert policy.evaluate("computer_settings", {"action": "shutdown"}).level is Level.BLOCK


def test_disabling_policy_allows_everything(policy_file, write_policy):
    data = json.loads(json.dumps(policy.DEFAULT_POLICY))
    data["enabled"] = False
    write_policy(data)
    assert policy.evaluate("cmd_control", {"command": "rm -rf /"}).level is Level.ALLOW


def test_kill_switch_blocks_everything(policy_file):
    policy.engage_kill_switch("test")
    try:
        assert policy.evaluate("web_search", {}).level is Level.BLOCK
    finally:
        policy.disengage_kill_switch()


def test_invalid_level_string_falls_back_to_confirm(policy_file, write_policy):
    data = json.loads(json.dumps(policy.DEFAULT_POLICY))
    data["tools"] = {"weird": "banana"}
    write_policy(data)
    assert policy.evaluate("weird", {}).level is Level.CONFIRM


def test_unreadable_policy_falls_back_to_safe_defaults(policy_file):
    policy_file.write_text("{ not json", encoding="utf-8")
    policy._cache = None
    policy._cache_mtime = -1.0
    assert policy.evaluate("file_controller", {"action": "delete"}).level is Level.CONFIRM


def test_limits_have_defaults(policy_file):
    lim = policy.limits()
    assert lim["max_actions_per_task"] >= 1
    assert lim["max_tasks_per_hour"] >= 1


def test_status_reports_kill_and_limits(policy_file):
    s = policy.status()
    assert s["enabled"] is True
    assert s["kill_switch"] is False
    assert "limits" in s


# --- A3 shell-command analysis is enforced through the gate -------------------

def test_cmd_control_read_only_command_is_allowed(policy_file):
    assert policy.evaluate("cmd_control", {"command": "dir"}).level is Level.ALLOW


def test_cmd_control_destructive_command_is_blocked(policy_file):
    assert policy.evaluate("cmd_control", {"command": "rm -rf /"}).level is Level.BLOCK


def test_cmd_control_unknown_command_needs_confirmation(policy_file):
    assert policy.evaluate("cmd_control", {"command": "mkdir newdir"}).level is Level.CONFIRM


# --- A2 path sandboxing is enforced through the gate --------------------------

def test_file_controller_outside_the_roots_is_blocked(policy_file):
    from pathlib import Path
    outside = str(Path.home().parent / "escaped.txt")
    assert policy.evaluate("file_controller", {"action": "read", "path": outside}).level is Level.BLOCK


# --- attended (live voice) vs unattended (background agent) gate --------------

def test_a_soft_confirmation_is_satisfied_by_attendance(policy_file):
    assert policy.evaluate("send_message", {"to": "a@b.com"}).level is Level.CONFIRM
    assert policy.evaluate_live("send_message", {"to": "a@b.com"}).level is Level.ALLOW


def test_a_soft_policy_block_is_satisfied_by_attendance(policy_file):
    decision = policy.evaluate("computer_settings", {"action": "shutdown"})
    assert decision.level is Level.BLOCK and not decision.hard
    assert policy.evaluate_live("computer_settings", {"action": "shutdown"}).level is Level.ALLOW


def test_a_hard_block_survives_attendance(policy_file):
    from pathlib import Path
    outside = str(Path.home().parent / "escaped.txt")
    decision = policy.evaluate_live("file_controller", {"action": "read", "path": outside})
    assert decision.level is Level.BLOCK and decision.hard


def test_the_kill_switch_is_hard_for_the_live_gate(policy_file):
    policy.engage_kill_switch("test")
    try:
        decision = policy.evaluate_live("web_search", {})
        assert decision.level is Level.BLOCK and decision.hard
    finally:
        policy.disengage_kill_switch()


def test_status_reports_the_new_guards(policy_file):
    status = policy.status()
    assert "egress" in status
    assert "roles" in status
