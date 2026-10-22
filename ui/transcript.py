"""Tier 3.8 — transcript store with timestamps, search and export.

Voice-first should not mean voice-only: what was said must be reviewable. The
store is in memory during a session and exported on demand as JSON or plain
text. It never writes audio, and it never leaves the machine by itself.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class Transcript:
    def __init__(self, limit: int = 2000):
        self.limit = max(1, int(limit))
        self.rows: list[dict] = []

    def add(self, role: str, text: str, *, at: float | None = None) -> dict:
        row = {"ts": float(time.time() if at is None else at),
               "time": time.strftime("%H:%M:%S", time.localtime(float(time.time() if at is None else at))),
               "role": str(role or "sys"),
               "text": str(text or "")}
        self.rows.append(row)
        if len(self.rows) > self.limit:
            self.rows = self.rows[-self.limit:]
        return row

    def search(self, query: str, limit: int = 50) -> list[dict]:
        needle = str(query or "").strip().lower()
        if not needle:
            return []
        hits = [row for row in self.rows if needle in row["text"].lower()]
        return hits[-max(1, int(limit)):]

    def lines(self) -> list[str]:
        return [f"[{row['time']}] {row['role']}: {row['text']}" for row in self.rows]

    def export(self, path, fmt: str = "txt") -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            target.write_text(json.dumps(self.rows, indent=2, ensure_ascii=False),
                              encoding="utf-8")
        else:
            target.write_text("\n".join(self.lines()), encoding="utf-8")
        return target

    def clear(self) -> int:
        removed = len(self.rows)
        self.rows = []
        return removed


def split_speaker(line: str) -> tuple[str, str]:
    """`"You: hi"` -> `("you", "hi")`; anything else is a system line."""
    text = str(line or "")
    low = text.lower()
    if low.startswith("you:"):
        return "you", text[4:].strip()
    if low.startswith("ai:"):
        return "ai", text[3:].strip()
    if low.startswith("sys:"):
        return "sys", text[4:].strip()
    return "sys", text.strip()
