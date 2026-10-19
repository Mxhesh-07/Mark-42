"""A1 - signed task manifests and intent binding."""

import time

from agent import approval


def test_digest_depends_on_the_arguments():
    a = approval.digest("file_controller", {"action": "delete", "path": "a.txt"})
    b = approval.digest("file_controller", {"action": "delete", "path": "b.txt"})
    c = approval.digest("file_controller", {"path": "a.txt", "action": "delete"})
    assert a != b
    assert a == c  # key order must not matter


def test_manifest_describes_the_effect_not_the_tool():
    man = approval.manifest("file_controller", {"action": "delete", "path": "a.txt"})
    assert "delete" in man["effect"]
    assert "a.txt" in man["effect"]
    assert man["token"]


def test_a_fresh_manifest_verifies():
    man = approval.manifest("cmd_control", {"command": "mkdir x"})
    ok, why = approval.verify(man["token"], "cmd_control", man["args"])
    assert ok, why


def test_a_token_does_not_verify_for_different_arguments():
    man = approval.manifest("file_controller", {"action": "delete", "path": "a.txt"})
    ok, _ = approval.verify(man["token"], "file_controller",
                            {"action": "delete", "path": "b.txt"})
    assert not ok


def test_a_token_does_not_verify_for_a_different_tool():
    man = approval.manifest("cmd_control", {"command": "dir"})
    ok, _ = approval.verify(man["token"], "file_controller", man["args"])
    assert not ok


def test_an_expired_token_does_not_verify():
    man = approval.manifest("cmd_control", {"command": "dir"}, ttl_s=1.0)
    parts = man["token"].split(".", 2)
    # The expiry field is integer milliseconds, as a float would contain a ".",
    # which is also the token's field separator.
    expired = f"{int((time.time() - 5) * 1000)}.{parts[1]}.{parts[2]}"
    ok, why = approval.verify(expired, "cmd_control", man["args"])
    assert not ok and "expired" in why


def test_a_garbage_token_does_not_verify():
    assert not approval.verify("nonsense", "cmd_control", {})[0]
    assert not approval.verify("1.2", "cmd_control", {})[0]


def test_authorize_refuses_when_the_user_says_no():
    man = approval.manifest("cmd_control", {"command": "dir"})
    ok, why = approval.authorize(man, False)
    assert not ok and "approved" in why


def test_authorize_passes_and_consumes_the_token():
    man = approval.manifest("cmd_control", {"command": "dir"})
    ok, _ = approval.authorize(man, True)
    assert ok
    # The token is single-use: a replay is rejected.
    again, why = approval.verify(man["token"], "cmd_control", man["args"])
    assert not again and "replay" in why


def test_a_different_key_cannot_forge_a_token(monkeypatch):
    man = approval.manifest("cmd_control", {"command": "dir"})
    monkeypatch.setenv("JARVIS_APPROVAL_KEY", "0" * 64)
    approval.reset_for_tests()
    ok, why = approval.verify(man["token"], "cmd_control", man["args"])
    assert not ok and "match" in why


def test_effect_names_the_command_for_cmd_control():
    man = approval.manifest("cmd_control", {"command": "del important.txt"})
    assert "del important.txt" in man["effect"]


def test_effect_names_the_recipient_for_a_message():
    man = approval.manifest("send_message", {"to": "sam@example.com", "message": "hi"})
    assert "sam@example.com" in man["effect"]


# --- C2: approvals are observable --------------------------------------------

def test_a_grant_is_counted():
    from agent import metrics

    man = approval.manifest("cmd_control", {"command": "dir"})
    assert approval.authorize(man, True)[0] is True
    assert metrics.value("approval", outcome="granted") == 1


def test_a_refusal_is_counted():
    from agent import metrics

    man = approval.manifest("cmd_control", {"command": "dir"})
    assert approval.authorize(man, False)[0] is False
    assert metrics.value("approval", outcome="denied") == 1


def test_a_forged_token_is_counted_as_invalid():
    from agent import metrics

    man = approval.manifest("cmd_control", {"command": "dir"})
    man["args_digest"] = "0" * 64
    assert approval.authorize(man, True)[0] is False
    assert metrics.value("approval", outcome="invalid") == 1
