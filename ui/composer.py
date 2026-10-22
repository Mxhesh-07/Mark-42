"""Tier 3.7 — text composer model (voice-first is not voice-only).

Pure parts only: normalisation, history navigation and slash commands. The Tk
widget that wraps this can come and go without changing the behaviour that is
tested here.
"""

from __future__ import annotations

MAX_INPUT = 8000


def normalise(text: str) -> str:
    """Trim, cap and collapse the trailing whitespace a submit adds."""
    value = str(text or "").replace("\r\n", "\n").strip()
    if len(value) > MAX_INPUT:
        value = value[:MAX_INPUT]
    return value


class History:
    def __init__(self, limit: int = 100):
        self.limit = max(1, int(limit))
        self.items: list[str] = []
        self._cursor = 0

    def add(self, text: str) -> None:
        value = normalise(text)
        if not value:
            return
        if self.items and self.items[-1] == value:
            return
        self.items.append(value)
        if len(self.items) > self.limit:
            self.items = self.items[-self.limit:]
        self._cursor = len(self.items)

    def previous(self) -> str:
        if not self.items:
            return ""
        self._cursor = max(0, self._cursor - 1)
        return self.items[self._cursor]

    def next(self) -> str:
        if not self.items:
            return ""
        self._cursor = min(len(self.items), self._cursor + 1)
        return "" if self._cursor == len(self.items) else self.items[self._cursor]

    def reset(self) -> None:
        self._cursor = len(self.items)


def parse_command(text: str) -> tuple[str, str]:
    """`"/kill now"` -> `("kill", "now")`; plain text -> `("", text)`."""
    value = normalise(text)
    if not value.startswith("/"):
        return "", value
    name, _, rest = value[1:].partition(" ")
    return name.lower(), rest.strip()
