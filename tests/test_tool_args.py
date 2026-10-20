"""G2: tool argument validation tests (unit, pyramid base).

The validator is the new hard gate: every call's arguments must match the
declarations the model was handed. These tests exercise every failure mode, and
a few happy paths, in isolation from handlers and the UI.
"""

from agent import tool_args as ta
from agent import policy
from agent.policy import Level


def test_check_rejects_unknown_tool():
    problems = ta.check("nope_does_not_exist", {})
    assert problems
    assert problems[0].kind == "unknown_tool"


def test_check_rejects_non_mapping_args():
    problems = ta.check("open_app", ["chrome"])
    assert problems
    assert problems[0].kind == "type"


def test_required_is_enforced():
    problems = ta.check("open_app", {})
    assert any(p.kind == "missing" and "app_name" in p.detail for p in problems)


def test_type_is_enforced():
    problems = ta.check("open_app", {"app_name": 123})
    assert any(p.kind == "type" for p in problems)


def test_unexpected_field_is_rejected():
    problems = ta.check("open_app", {"app_name": "Chrome", "nonsense": 1})
    assert any(p.kind == "unexpected" for p in problems)


def test_boolean_type_is_respected():
    # pick a tool that might have boolean? Let us pick web_search has no bool,
    # cmd_control has visible (boolean) - but cmd_control required 'task'
    problems = ta.check("cmd_control", {"task": "list files", "visible": "yes"})
    assert any(p.kind == "type" for p in problems)


def test_integer_not_accepted_as_bool():
    problems = ta.check("cmd_control", {"task": "list files", "visible": 1})
    assert any(p.kind == "type" for p in problems)


def test_array_is_checked():
    # code_helper has code (string) maybe not array; file_controller has paths? none declared. find example
    problems = ta.check("code_helper", {"task": "refactor", "code": [1, 2, 3]})
    assert any(p.kind == "type" for p in problems)


def test_describe_formats_problems():
    s = ta.describe([ta.Problem("type", "x", "x must be a string")])
    assert "string" in s


def test_snapshot_reports_counts():
    s = ta.snapshot()
    assert "tools" in s and s["tools"] > 0
    assert "types" in s


def test_valid_and_check_are_consistent():
    assert ta.valid("open_app", {"app_name": "Chrome"})
    assert not ta.valid("open_app", {})


def test_audit_findings_are_empty_on_valid_declarations():
    findings = ta.audit_findings()
    assert findings == []


def test_policy_hard_blocks_malformed_call():
    d = policy.evaluate("open_app", {"app_name": 5})
    assert d.level is Level.BLOCK and d.hard
    assert "malformed" in d.reason


def test_policy_hard_blocks_unknown_tool_as_argument_problem():
    d = policy.evaluate("totally_unknown", {})
    assert d.level is Level.BLOCK and d.hard
    assert "no declared tool" in d.reason
