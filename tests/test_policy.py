"""The permission gate is the safety net, so it is tested hardest."""

import json

from agent import policy
from agent.policy import Level


def test_known_read_only_tool_is_allowed(policy_file):
    assert policy.evaluate("web_search", {"query": "x"}).level is Level.ALLOW


def test_side_effecting_tool_needs_confirmation(policy_file):
    assert policy.evaluate("send_message", {"receiver": "a", "message_text": "b", "platform": "whatsapp"}).level is Level.CONFIRM


def test_unlisted_tool_falls_back_to_the_default(policy_file):
    """An unknown tool has no schema: fail closed (hard block), never 'no constraints'."""
    d = policy.evaluate("brand_new_tool", {})
    assert d.level is Level.BLOCK and d.hard
    assert "no declared tool" in d.reason


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
    # "weird" has no declared schema -> hard block regardless of policy table.
    # The policy-table fallback still exists, but schema validation runs first.
    write_policy(data)
    d = policy.evaluate("weird", {})
    assert d.level is Level.BLOCK and d.hard
    assert "no declared tool" in d.reason


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
    assert policy.evaluate("cmd_control", {"task": "dir"}).level is Level.ALLOW


def test_cmd_control_destructive_command_is_blocked(policy_file):
    assert policy.evaluate("cmd_control", {"task": "rm -rf /"}).level is Level.BLOCK


def test_cmd_control_unknown_command_needs_confirmation(policy_file):
    assert policy.evaluate("cmd_control", {"task": "mkdir newdir"}).level is Level.CONFIRM


# --- A2 path sandboxing is enforced through the gate --------------------------

def test_file_controller_outside_the_roots_is_blocked(policy_file):
    from pathlib import Path
    outside = str(Path.home().parent / "escaped.txt")
    assert policy.evaluate("file_controller", {"action": "read", "path": outside}).level is Level.BLOCK


# --- attended (live voice) vs unattended (background agent) gate --------------

def test_a_soft_confirmation_is_satisfied_by_attendance(policy_file):
    assert policy.evaluate("send_message", {"receiver": "a", "message_text": "b", "platform": "whatsapp"}).level is Level.CONFIRM
    assert policy.evaluate_live("send_message", {"receiver": "a", "message_text": "b", "platform": "whatsapp"}).level is Level.ALLOW


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
        decision = policy.evaluate_live("web_search", {"query": "x"})
        assert decision.level is Level.BLOCK and decision.hard
    finally:
        policy.disengage_kill_switch()


def test_status_reports_the_new_guards(policy_file):
    status = policy.status()
    assert "egress" in status
    assert "roles" in status


# --- B2: the degradation ladder is enforced in the gate -----------------------

def test_read_only_blocks_a_file_write(policy_file):
    from agent import degrade

    degrade.set_level("READ_ONLY")
    decision = policy.evaluate("file_controller", {"action": "write", "path": "x.txt"})
    assert decision.level is Level.BLOCK and decision.hard


def test_read_only_still_allows_a_file_read(policy_file):
    from agent import degrade

    degrade.set_level("READ_ONLY")
    assert policy.evaluate("file_controller", {"action": "read", "path": "x.txt"}).level is Level.ALLOW


def test_read_only_blocks_messages_and_shell(policy_file):
    from agent import degrade

    degrade.set_level("READ_ONLY")
    assert policy.evaluate("send_message", {"receiver": "a", "message_text": "b", "platform": "whatsapp"}).level is Level.BLOCK
    assert policy.evaluate("cmd_control", {"task": "dir"}).level is Level.BLOCK


def test_monitor_stops_every_tool(policy_file):
    from agent import degrade

    degrade.set_level("MONITOR")
    assert policy.evaluate("web_search", {}).level is Level.BLOCK


def test_a_degraded_block_is_not_liftable_by_attendance(policy_file):
    from agent import degrade

    degrade.set_level("READ_ONLY")
    decision = policy.evaluate_live("send_message", {"receiver": "a", "message_text": "b", "platform": "whatsapp"})
    assert decision.level is Level.BLOCK and decision.hard


# --- C2: the gate records what it decided -------------------------------------

def test_evaluate_records_a_metric(policy_file):
    from agent import metrics

    policy.evaluate("web_search", {"query": "x"})
    assert metrics.value("policy.decision", level="allow") >= 1


def test_attendance_is_recorded(policy_file):
    from agent import metrics

    policy.evaluate_live("send_message", {"receiver": "a", "message_text": "b", "platform": "whatsapp"})
    assert metrics.value("policy.attended", tool="send_message") == 1
