"""Tier 1.7 — placeholder credentials are refused before they are saved."""

from __future__ import annotations

import pytest

from agent import secrets_guard


@pytest.mark.parametrize("value", [
    "", "   ", "short", "your_api_key_here", "YOUR_API_KEY", "changeme",
    "placeholder-key-123", "example-value-1234567890", "sk-xxx",
])
def test_placeholders_are_rejected(value):
    ok, reason = secrets_guard.check(value)
    assert ok is False
    assert reason


def test_a_realistic_key_is_accepted():
    ok, reason = secrets_guard.check("AIza" + "x" * 35)
    assert ok is True
    assert reason == ""


def test_is_placeholder_never_raises_on_odd_types():
    assert secrets_guard.is_placeholder(None) is True
    assert secrets_guard.is_placeholder(12345) is True
