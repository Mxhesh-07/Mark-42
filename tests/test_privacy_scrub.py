"""No hardcoded personal name, and no \"sir\": the greeting must work without one.

The name is learned from conversation and kept in gitignored memory. Source code
must not seed it, and the greeting must read naturally when it is unknown.
"""

import inspect
from pathlib import Path

import companion

ROOT = Path(__file__).resolve().parents[1]


def test_check_in_does_not_default_to_a_hardcoded_name():
    default = inspect.signature(companion.check_in).parameters["user_name"].default
    assert default is None


def test_check_in_without_a_name_reads_naturally(monkeypatch):
    monkeypatch.setattr(companion.random, "choice", lambda seq: seq[0])
    text = companion.check_in()
    assert text
    assert "Mahesh" not in text
    assert "None" not in text
    assert "sir" not in text.lower()
    assert ", ." not in text


def test_check_in_uses_a_name_when_one_is_known(monkeypatch):
    monkeypatch.setattr(companion.random, "choice", lambda seq: seq[0])
    assert "Alex" in companion.check_in("Alex")


def test_companion_response_without_a_name_has_no_dangling_address(monkeypatch):
    monkeypatch.setattr(companion.random, "choice", lambda seq: seq[0])
    text = companion.companion_response({"text": "how are you"})
    assert ", ?" not in text
    assert "None" not in text
    assert "Mahesh" not in text


def test_no_personal_name_is_hardcoded_in_source_or_prompts():
    files = [
        "main.py",
        "companion.py",
        "jarvis/tools_schema.py",
        "agent/roles.py",
        "core/prompt.txt",
        "prompts/jarvis_personality.txt",
    ]
    for name in files:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "Mahesh" not in text, f"personal name still hardcoded in {name}"


def test_both_prompts_forbid_titles():
    for name in ("core/prompt.txt", "prompts/jarvis_personality.txt"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert '"sir"' in text, f"no-sir rule missing from {name}"
