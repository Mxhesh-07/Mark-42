"""Tier 1.7 — refuse placeholder credentials at the door.

`.gitignore` stops an accidental commit; it does nothing about a key that is
literally the example text. The setup flow and the first-run wizard both call
this, so a template value can never become the active credential.
"""

from __future__ import annotations

import re

_PLACEHOLDER = re.compile(
    r"(your[_-]?api[_-]?key|your[_-]?key|insert[_-]?key|changeme|change_me|"
    r"placeholder|example|redacted|dummy|test[_-]?key|sk-xxx|\.\.\.)",
    re.IGNORECASE,
)


def is_placeholder(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if len(text) < 16:
        return True
    return bool(_PLACEHOLDER.search(text))


def check(value: object) -> tuple[bool, str]:
    """Returns (acceptable, reason). Reason is safe to show the user."""
    text = str(value or "").strip()
    if not text:
        return False, "empty"
    if len(text) < 16:
        return False, "too short to be a real key"
    if _PLACEHOLDER.search(text):
        return False, "looks like a placeholder/example value"
    return True, ""
