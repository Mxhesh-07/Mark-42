"""The audit log: append-only, tamper-evident (A7)."""

import json

import pytest

from agent import audit


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "LOG_PATH", tmp_path / "audit_log.jsonl")
    audit._LAST_HASH = ""
    yield audit.LOG_PATH
    audit._LAST_HASH = ""


def _entries(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_appends_an_entry_with_a_hash(log):
    audit.record("task_start", goal="do a thing")
    entries = _entries(log)
    assert len(entries) == 1
    assert entries[0]["event"] == "task_start"
    assert entries[0]["goal"] == "do a thing"
    assert entries[0]["hash"] and entries[0]["prev"] == ""


def test_each_entry_links_to_the_one_before_it(log):
    audit.record("task_start")
    audit.record("action", tool="web_search")
    first, second = _entries(log)
    assert second["prev"] == first["hash"]
    assert second["hash"] != first["hash"]


def test_verify_accepts_an_intact_chain(log):
    for i in range(3):
        audit.record("action", tool=f"t{i}")
    ok, msg = audit.verify()
    assert ok and "3 entries verified" in msg


def test_verify_accepts_a_missing_log(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "LOG_PATH", tmp_path / "does-not-exist.jsonl")
    audit._LAST_HASH = ""
    ok, msg = audit.verify()
    assert ok and "no audit log" in msg


def test_editing_an_entry_is_detected(log):
    audit.record("action", tool="web_search")
    audit.record("action", tool="send_message")
    lines = log.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["tool"] = "something_else"
    lines[0] = json.dumps(entry)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, msg = audit.verify()
    assert not ok and "line 1" in msg


def test_deleting_a_middle_entry_is_detected(log):
    for i in range(3):
        audit.record("action", tool=f"t{i}")
    lines = log.read_text(encoding="utf-8").splitlines()
    del lines[1]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, _ = audit.verify()
    assert not ok


def test_reordering_entries_is_detected(log):
    for i in range(3):
        audit.record("action", tool=f"t{i}")
    lines = log.read_text(encoding="utf-8").splitlines()
    lines[0], lines[2] = lines[2], lines[0]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, _ = audit.verify()
    assert not ok


def test_tail_reads_the_most_recent_entries(log):
    audit.record("first")
    audit.record("second")
    assert [e["event"] for e in audit.tail(2)] == ["first", "second"]


def test_clear_empties_the_log_and_restarts_the_chain(log):
    audit.record("first")
    audit.clear()
    assert log.read_text(encoding="utf-8") == ""
    audit.record("second")
    entry = _entries(log)[0]
    assert entry["prev"] == ""
