"""Per-turn tracing (Tier 2 C3).

A turn is: microphone -> speech-to-text -> planning -> tool calls -> text out.
When something is slow or wrong, the question is always "which stage?", and a
log line per stage answers it. This module keeps the spans of the current turn
in memory, tagged with the turn id from ``agent.log``, so a slow turn can be
dumped exactly as it happened.

Spans are cheap: a dict per stage, appended to a list. Nothing is written to
disk unless a caller asks for ``snapshot()``.
"""

from __future__ import annotations

import threading
import time

from agent import metrics

_lock = threading.Lock()
_turns: dict[str, list[dict]] = {}
_order: list[str] = []

MAX_TURNS = 20


def _turn_id() -> str:
    try:
        from agent import log

        return log.turn_id() or "no-turn"
    except Exception:
        return "no-turn"


class Span:
    """Timing for one stage of a turn; usable as a context manager."""

    __slots__ = ("name", "data", "started", "finished", "ok", "detail", "turn",
                 "override_ms")

    def __init__(self, name: str, **data):
        self.name = str(name)
        self.data = {k: v for k, v in data.items() if v is not None}
        self.started = 0.0
        self.finished = 0.0
        self.ok = True
        self.detail = ""
        self.turn = ""
        self.override_ms: float | None = None

    @property
    def duration_ms(self) -> float:
        if self.override_ms is not None:
            return float(self.override_ms)
        if not self.started:
            return 0.0
        end = self.finished or time.perf_counter()
        return (end - self.started) * 1000.0

    def __enter__(self) -> "Span":
        self.turn = _turn_id()
        self.started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.finished = time.perf_counter()
        self.ok = exc_type is None
        if exc is not None and not self.detail:
            self.detail = str(exc)
        _record(self)
        return False   # never swallow the exception

    def __repr__(self) -> str:
        state = "ok" if self.ok else "fail"
        return f"Span({self.name}, {self.duration_ms:.0f}ms, {state})"


def _record(span: Span) -> None:
    entry = {
        "name": span.name,
        "ms": round(span.duration_ms, 3),
        "ok": span.ok,
        "detail": span.detail,
        **span.data,
    }
    with _lock:
        bucket = _turns.setdefault(span.turn, [])
        bucket.append(entry)
        if span.turn not in _order:
            _order.append(span.turn)
        while len(_order) > MAX_TURNS:
            _turns.pop(_order.pop(0), None)

    metrics.observe_ms("turn.stage", entry["ms"], stage=span.name)
    if not span.ok:
        metrics.inc("turn.stage_error", stage=span.name)


def span(name: str, **data) -> Span:
    """``with trace.span("tts"): ...``"""
    return Span(name, **data)


def record(name: str, *, ms: float, ok: bool = True, detail: str = "", **data) -> None:
    """Record a stage that was timed elsewhere."""
    _record(_Synthetic(name, ms, ok, detail, data))


class _Synthetic(Span):
    def __init__(self, name, ms, ok, detail, data):
        super().__init__(name, **data)
        self.override_ms = float(ms)
        self.ok = bool(ok)
        self.detail = detail
        self.turn = _turn_id()


def current_turn() -> dict:
    turn = _turn_id()
    with _lock:
        spans = list(_turns.get(turn, []))
    total = round(sum(s["ms"] for s in spans), 3)
    return {"turn_id": turn, "total_ms": total, "spans": spans}


def snapshot(limit: int = 5) -> dict:
    with _lock:
        turns = list(_order)[-limit:]
        data = {t: list(_turns.get(t, [])) for t in turns}
    return {"turns": data}


def reset() -> None:
    with _lock:
        _turns.clear()
        _order.clear()
