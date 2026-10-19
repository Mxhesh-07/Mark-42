"""Structured logging (C1).

The contract that matters for the user experience: the console keeps printing
exactly the message it printed before (no timestamp, no level prefix unless the
record is a warning or worse), while the JSON file gets one object per record
with the fields needed to debug a turn.
"""

import json
import logging

import pytest

from agent import log


@pytest.fixture
def logging_state():
    """Save and restore the root logger around a test that reconfigures it."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield root
    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
    for handler in saved_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(saved_level)


@pytest.fixture(autouse=True)
def _fresh_config(monkeypatch):
    monkeypatch.setattr(log, "_configured", False)
    log.clear_turn()
    yield
    log.clear_turn()


def _flush(root):
    for handler in root.handlers:
        try:
            handler.flush()
        except Exception:
            pass


def _read_entries(path):
    text = path.read_text(encoding="utf-8").strip()
    return [json.loads(line) for line in text.splitlines() if line]


# --- turn correlation ---------------------------------------------------------

def test_turn_id_is_a_dash_outside_a_turn():
    assert log.turn_id() == "-"


def test_set_turn_generates_an_id_when_not_given_one():
    tid = log.set_turn()
    assert tid
    assert log.turn_id() == tid


def test_set_turn_honours_an_explicit_id():
    assert log.set_turn("turn-1") == "turn-1"
    assert log.turn_id() == "turn-1"


def test_turn_ids_are_unique():
    assert log.new_turn_id() != log.new_turn_id()


# --- JSON file handler --------------------------------------------------------

def test_a_record_becomes_one_json_object(tmp_path, logging_state):
    path = tmp_path / "jarvis.jsonl"
    log.configure(json_path=path, console=False)
    log.get_logger("executor").info(
        "[Executor] action done", extra={"fields": {"tool": "web_search"}}
    )
    _flush(logging_state)

    entry = _read_entries(path)[0]
    assert entry["msg"] == "[Executor] action done"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "executor"
    assert entry["tool"] == "web_search"
    assert entry["turn"] == "-"


def test_the_turn_id_is_recorded(tmp_path, logging_state):
    path = tmp_path / "jarvis.jsonl"
    log.configure(json_path=path, console=False)
    log.set_turn("abc123")
    log.get_logger("t").info("hello")
    _flush(logging_state)

    assert _read_entries(path)[0]["turn"] == "abc123"


def test_an_exception_is_recorded(tmp_path, logging_state):
    path = tmp_path / "jarvis.jsonl"
    log.configure(json_path=path, console=False)
    try:
        raise ValueError("boom")
    except ValueError:
        log.get_logger("t").exception("failed")
    _flush(logging_state)

    assert "ValueError: boom" in _read_entries(path)[0]["exc"]


def test_the_file_handler_creates_missing_directories(tmp_path, logging_state):
    path = tmp_path / "nested" / "deeper" / "jarvis.jsonl"
    log.configure(json_path=path, console=False)
    log.get_logger("t").info("hello")
    _flush(logging_state)

    assert path.exists()


# --- console handler ----------------------------------------------------------

def test_console_prints_only_the_message(capsys, logging_state):
    log.configure(json_path=None, console=True)
    log.get_logger("t").info("plain line")

    assert capsys.readouterr().out.strip() == "plain line"


def test_console_prefixes_warnings(capsys, logging_state):
    log.configure(json_path=None, console=True)
    log.get_logger("t").warning("careful")

    assert capsys.readouterr().out.strip() == "Warning: careful"


def test_console_does_not_double_a_level_prefix(capsys, logging_state):
    # Some libraries log "Warning: ..." themselves; the handler must not add a
    # second prefix.
    log.configure(json_path=None, console=True)
    log.get_logger("t").warning("Warning: there are non-data parts in the response")

    assert capsys.readouterr().out.strip() == (
        "Warning: there are non-data parts in the response"
    )


def test_console_output_for_an_error_is_prefixed(capsys, logging_state):
    log.configure(json_path=None, console=True)
    log.get_logger("t").error("broke")

    assert capsys.readouterr().out.strip() == "Error: broke"


# --- setup --------------------------------------------------------------------

def test_configure_is_idempotent(tmp_path, logging_state):
    log.configure(json_path=tmp_path / "first.jsonl", console=False)
    count = len(logging_state.handlers)

    log.configure(json_path=tmp_path / "second.jsonl", console=False)

    assert len(logging_state.handlers) == count
    assert not (tmp_path / "second.jsonl").exists()


def test_configure_from_config_maps_the_level(tmp_path, logging_state):
    log.configure_from_config({"logging": {"level": "warning"}})

    assert logging.getLogger().level == logging.WARNING


def test_configure_from_config_is_a_no_op_without_a_block(tmp_path, logging_state):
    log.configure_from_config({})

    assert log.get_logger("t") is not None
