"""Path sandboxing (A2) - deny by default, and no way to climb out with .."""

import json
from pathlib import Path

from agent import policy, sandbox


def test_path_inside_home_is_allowed(policy_file):
    ok, why = sandbox.check(str(Path.home() / "sandbox-probe.txt"))
    assert ok, why


def test_path_outside_home_is_denied(policy_file):
    outside = Path.home().parent / "outside-sandbox-probe"
    ok, why = sandbox.check(str(outside))
    assert not ok and "outside" in why


def test_dotdot_cannot_escape_a_root(policy_file):
    escape = Path.home() / ".." / "escaped-probe"
    assert sandbox.check(str(escape))[0] is False


def test_empty_path_is_denied(policy_file):
    assert sandbox.check("")[0] is False
    assert sandbox.check("   ")[0] is False
    assert sandbox.check(None)[0] is False


def test_disabled_sandbox_allows_outside_paths(policy_file, write_policy):
    data = json.loads(json.dumps(policy.DEFAULT_POLICY))
    data["sandbox"]["enabled"] = False
    write_policy(data)
    outside = Path.home().parent / "outside-probe"
    assert sandbox.check(str(outside))[0] is True


def test_custom_roots_are_honoured(policy_file, write_policy, tmp_path):
    data = json.loads(json.dumps(policy.DEFAULT_POLICY))
    data["sandbox"]["roots"] = [str(tmp_path)]
    write_policy(data)
    assert sandbox.check(str(tmp_path / "inside.txt"))[0] is True
    assert sandbox.check(str(Path.home()))[0] is False


def test_root_itself_is_allowed(policy_file, write_policy, tmp_path):
    data = json.loads(json.dumps(policy.DEFAULT_POLICY))
    data["sandbox"]["roots"] = [str(tmp_path)]
    write_policy(data)
    assert sandbox.check(str(tmp_path))[0] is True


def test_paths_in_extracts_only_path_like_keys():
    got = sandbox.paths_in({"path": "a", "action": "read", "source": "b", "query": "c"})
    assert set(got) == {"a", "b"}


def test_paths_in_ignores_non_strings_and_empty():
    assert sandbox.paths_in({"path": 3, "file": None, "dir": "  "}) == []
    assert sandbox.paths_in(None) == []
