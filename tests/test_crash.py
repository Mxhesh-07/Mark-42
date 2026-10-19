"""Tier 2 C6 - crash bundles."""

import json
import sys

from agent import crash


def test_an_api_key_is_redacted():
    text = "using AIzaSyD-1234567890abcdefghijklmnop now"
    out = crash.redact(text)
    assert "AIzaSyD" not in out
    assert "<redacted-key>" in out


def test_an_openai_style_key_is_redacted():
    out = crash.redact("sk-" + "a" * 32)
    assert "sk-aaaa" not in out


def test_a_labelled_secret_is_redacted():
    out = crash.redact('api_key = "abcdef1234567890"')
    assert "abcdef1234567890" not in out


def test_emails_and_home_paths_are_redacted():
    out = crash.redact(r"mail bob@example.com from C:\Users\bob\secrets.txt")
    assert "bob@example.com" not in out
    assert r"C:\Users\bob" not in out


def test_redact_walks_nested_structures():
    out = crash.redact({"a": ["x@y.com", {"token": "sk-" + "b" * 20}]})
    assert out["a"][0] == "<email>"
    assert "sk-bbbb" not in json.dumps(out)


def test_capture_writes_a_redacted_bundle():
    try:
        raise ValueError("bad thing with AIzaSyD-1234567890abcdefghijklmnop")
    except ValueError as e:
        path = crash.capture(e, extra={"note": "bob@example.com"}, include_health=False)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "bad thing" in data["exception"]
    assert "AIzaSyD" not in data["exception"]
    assert data["extra"]["note"] == "<email>"
    assert data["python"]


def test_capture_includes_health_when_asked(policy_file):
    path = crash.capture(ValueError("x"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "health" in data


def test_capture_is_audited():
    from agent import audit

    crash.capture(ValueError("x"), include_health=False)
    assert any(e.get("event") == "crash" for e in audit.tail(20))


def test_recent_logs_reads_the_json_log(monkeypatch, tmp_path):
    from agent import log

    log_file = tmp_path / "jarvis.jsonl"
    log_file.write_text("\n".join(f'{{"i": {i}}}' for i in range(5)), encoding="utf-8")
    monkeypatch.setattr(log, "json_log_path", lambda: log_file)
    assert len(crash.recent_logs(lines=3)) == 3


def test_recent_logs_is_empty_without_a_log(monkeypatch):
    from agent import log

    monkeypatch.setattr(log, "json_log_path", lambda: None)
    assert crash.recent_logs() == []


def test_old_bundles_are_pruned(monkeypatch):
    monkeypatch.setattr(crash, "KEEP", 2)
    for i in range(4):
        try:
            raise ValueError(f"boom {i}")
        except ValueError as e:
            crash.capture(e, include_health=False)
    assert len(list(crash.CRASH_DIR.glob("crash-*.json"))) == 2


def test_list_crashes_reports_the_tail_of_the_traceback():
    try:
        raise ValueError("the last line")
    except ValueError as e:
        crash.capture(e, include_health=False)
    listed = crash.list_crashes()
    assert listed
    assert "the last line" in "".join(listed[0]["exception"])


def test_cli_list_prints_the_bundles(capsys):
    try:
        raise ValueError("cli test")
    except ValueError as e:
        crash.capture(e, include_health=False)
    assert crash._cli(["list"]) == 0
    assert "crash-" in capsys.readouterr().out


def test_install_routes_uncaught_exceptions(monkeypatch):
    calls = []
    monkeypatch.setattr(crash, "capture", lambda exc, **kw: calls.append(exc))
    previous = sys.excepthook
    try:
        crash.install()
        sys.excepthook(ValueError, ValueError("uncaught"), None)
        assert calls and str(calls[0]) == "uncaught"
    finally:
        sys.excepthook = previous
