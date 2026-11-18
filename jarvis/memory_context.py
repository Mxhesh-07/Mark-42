"""Persistent memory that actually reaches the live voice prompt.

`memory_manager.format_memory_for_prompt()` only carries the small
`long_term.json` fact store. The richer stores — AIMemory notes/projects,
SQLite memories and the audit trail of what JARVIS has done — were written but
never injected. This module collects them into one compact, scrubbed block and
records each finished voice exchange as a durable episodic memory.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIT_PATH = BASE_DIR / "memory" / "audit_log.jsonl"

MAX_CONTEXT_CHARS = 1800
MAX_ITEMS = 12
MAX_LINE = 180

_SECRET = re.compile(
    r"(AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)


def _scrub(text: str) -> str:
    """Keep secrets and personal contact details out of the model prompt."""
    return _SECRET.sub("[redacted]", str(text or ""))


def _clip(text: str, limit: int = MAX_LINE) -> str:
    text = " ".join(_scrub(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _ai_context() -> str:
    try:
        from memory.ai_memory import AIMemory

        return AIMemory().get_context() or ""
    except Exception:
        return ""


def _sql_context() -> str:
    try:
        from memory import sql_memory

        rows = sql_memory.all_records(limit=80)
    except Exception:
        return ""

    wanted = {"fact", "event", "exchange", "note", "task", "action"}
    kept = []
    for row in rows:
        kind = str(row.get("kind") or "fact")
        if kind not in wanted:
            continue
        value = str(row.get("value") or "").strip()
        if not value:
            continue
        created = float(row.get("created_at") or 0.0)
        when = datetime.fromtimestamp(created or time.time()).strftime("%b %d")
        kept.append((created, f"- [{kind}] {_clip(value)} ({when})"))

    kept.sort(key=lambda pair: pair[0], reverse=True)
    return "\n".join(line for _, line in kept[:MAX_ITEMS])


def _audit_context() -> str:
    try:
        lines = AUDIT_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return ""

    out = []
    for line in reversed(lines[-50:]):
        try:
            entry = json.loads(line)
        except Exception:
            continue
        action = _clip(str(entry.get("tool") or entry.get("event") or "action"), 40)
        detail = _clip(str(entry.get("detail") or entry.get("outcome") or ""), 100)
        text = f"- {action}: {detail}" if detail else f"- {action}"
        if text not in out:
            out.append(text)
        if len(out) >= 6:
            break
    return "\n".join(out)


def build_context() -> str:
    """The compact ``[LONG-TERM MEMORY]`` block for the Live system prompt."""
    parts = []
    ai = _ai_context()
    if ai:
        parts.append(_scrub(ai))
    sql = _sql_context()
    if sql:
        parts.append("[MEMORIES & EVENTS]\n" + sql)
    audit = _audit_context()
    if audit:
        parts.append("[RECENT ACTIONS]\n" + audit)

    text = "\n\n".join(parts)
    if len(text) > MAX_CONTEXT_CHARS:
        text = text[: MAX_CONTEXT_CHARS - 1].rstrip() + "…"
    return text


def _remember_explicit(user_text: str) -> None:
    """Turn 'remember that X' into durable notes in both stores."""
    note = user_text.strip()
    lowered = note.lower()
    starters = (
        "remember that ",
        "remember ",
        "don't forget that ",
        "don't forget ",
        "keep in mind that ",
        "keep in mind ",
    )
    for starter in starters:
        if lowered.startswith(starter):
            note = note[len(starter):]
            break
    note = note.strip(" .")
    if not note:
        return

    try:
        from memory.ai_memory import AIMemory

        AIMemory().remember(note)
    except Exception:
        pass
    try:
        from memory import sql_memory

        sql_memory.remember(
            f"note:{int(time.time() * 1000)}",
            note,
            kind="note",
            source="user",
            confidence=0.9,
            tags=["remember"],
        )
    except Exception:
        pass


def record_exchange(user_text: str, jarvis_text: str = "") -> None:
    """Persist a finished user turn so later sessions can recall it."""
    user_text = (user_text or "").strip()
    if len(user_text) < 4:
        return
    reply = (jarvis_text or "").strip()[:300]
    value = f"User: {user_text[:300]}"
    if reply:
        value += f" | JARVIS: {reply}"

    try:
        from memory import sql_memory

        sql_memory.remember(
            f"exchange:{int(time.time() * 1000)}",
            value,
            kind="exchange",
            source="voice",
            confidence=0.6,
            tags=["conversation"],
        )
    except Exception:
        pass

    lowered = user_text.lower()
    if any(
        phrase in lowered
        for phrase in ("remember", "don't forget", "keep in mind")
    ):
        _remember_explicit(user_text)
