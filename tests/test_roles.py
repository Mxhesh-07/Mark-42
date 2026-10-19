"""A8 - voice-authorization roles."""

from agent import policy, roles
from agent.policy import Level


def test_enrolled_voice_is_the_owner(policy_file):
    roles.set_from_speaker("Mahesh", status="known")
    assert roles.current() == "owner"


def test_a_mapped_label_gets_its_role(policy_file, write_policy):
    write_policy(policy.DEFAULT_POLICY | {"roles": {"map": {"guest": ["Sam"]}}})
    assert roles.set_from_speaker("Sam", status="known") == "guest"


def test_an_unrecognised_voice_is_only_restricted_when_opted_in(policy_file):
    assert roles.set_from_speaker("someone", status="unknown") == "owner"


def test_enforce_on_unknown_blocks_an_unenrolled_voice(policy_file, write_policy):
    write_policy(policy.DEFAULT_POLICY | {"roles": {"enforce_on_unknown": True}})
    assert roles.set_from_speaker("someone", status="unknown") == "unknown"


def test_noise_leaves_the_role_untouched(policy_file):
    roles.set_current("owner")
    assert roles.set_from_speaker("Unknown", status="noise") == "owner"


def test_disabling_enforcement_always_yields_owner(policy_file, write_policy):
    write_policy(policy.DEFAULT_POLICY | {"roles": {"enforce": False}})
    roles.clear()
    roles.set_current("unknown")
    assert roles.current() == "owner"


def test_disabling_enforcement_forces_the_default(policy_file, write_policy):
    write_policy(policy.DEFAULT_POLICY | {"roles": {"enforce": False, "default": "owner"}})
    roles.clear()
    roles.set_current("unknown")
    assert roles.current() == "owner"


def test_read_only_detection(policy_file):
    assert roles.is_read_only("web_search", {})
    assert roles.is_read_only("file_controller", {"action": "read"})
    assert not roles.is_read_only("file_controller", {"action": "write"})
    assert roles.is_read_only("cmd_control", {"command": "dir"})
    assert not roles.is_read_only("cmd_control", {"command": "del x.txt"})


def test_owner_keeps_the_full_policy(policy_file):
    roles.set_current("owner")
    decision = policy.evaluate("file_controller", {"action": "delete", "path": "x.txt"})
    assert decision.level is Level.CONFIRM


def test_guest_cannot_use_a_mutating_tool(policy_file):
    from pathlib import Path

    roles.set_current("guest")
    target = str(Path.home() / "note.txt")
    decision = policy.evaluate("file_controller", {"action": "write", "path": target})
    assert decision.level is Level.BLOCK
    assert decision.hard


def test_guest_can_use_a_read_only_tool(policy_file):
    roles.set_current("guest")
    assert policy.evaluate("web_search", {"query": "x"}).level is Level.ALLOW


def test_guest_is_not_given_an_attended_pass(policy_file):
    # A guest block is hard, so the live (attended) gate must not lift it.
    roles.set_current("guest")
    assert policy.evaluate_live("send_message", {"to": "a@b.com"}).level is Level.BLOCK


def test_an_allowed_level_tool_is_refused_to_a_guest_without_a_grant(policy_file):
    roles.set_current("guest")
    assert policy.evaluate("open_app", {"app_name": "notepad"}).level is Level.BLOCK


def test_extra_tools_can_widen_a_guest(policy_file, write_policy):
    write_policy(policy.DEFAULT_POLICY | {"roles": {"extra_tools": {"guest": ["open_app"]}}})
    roles.set_current("guest")
    assert policy.evaluate("open_app", {"app_name": "notepad"}).level is Level.ALLOW
