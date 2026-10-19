"""Atomic writes (D6) - a failed write must never destroy the old file."""

import json

import pytest

from agent import atomic


def test_write_text_creates_missing_directories(tmp_path):
    target = tmp_path / "deep" / "nested" / "a.txt"
    atomic.write_text(target, "hello")
    assert target.read_text(encoding="utf-8") == "hello"


def test_write_text_overwrites_in_place(tmp_path):
    target = tmp_path / "a.txt"
    atomic.write_text(target, "one")
    atomic.write_text(target, "two")
    assert target.read_text(encoding="utf-8") == "two"


def test_write_json_round_trips(tmp_path):
    target = tmp_path / "a.json"
    atomic.write_json(target, {"a": [1, 2], "b": "x", "c": {"d": True}})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": [1, 2], "b": "x", "c": {"d": True}}


def test_write_json_keeps_unicode_readable(tmp_path):
    target = tmp_path / "a.json"
    atomic.write_json(target, {"note": "caf\u00e9 \u2014 ok"})
    assert "caf\u00e9" in target.read_text(encoding="utf-8")


def test_no_temporary_files_are_left_behind(tmp_path):
    atomic.write_json(tmp_path / "a.json", {"x": 1})
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_the_original_survives_a_failed_write(tmp_path):
    target = tmp_path / "a.json"
    atomic.write_json(target, {"ok": True})
    with pytest.raises(TypeError):
        atomic.write_json(target, {"bad": object()})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}
