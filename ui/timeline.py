"""Tier 3.11 — activity timeline model.

Each step has a status and an optional cancel hook. The model is pure: rendering
and cancellation are the caller's job, which keeps it testable and means a slow
UI cannot block a task.
"""

from __future__ import annotations

import time

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

_SYMBOLS = {PENDING: "□", RUNNING: "⟳", DONE: "✓", FAILED: "✗", CANCELLED: "⊘"}


class Timeline:
    def __init__(self):
        self.steps: list[dict] = []

    def add(self, name: str, *, detail: str = "", status: str = PENDING,
            cancel=None) -> dict:
        step = {"id": len(self.steps) + 1, "name": str(name),
                "detail": str(detail), "status": status,
                "started": time.time(), "ended": None, "cancel": cancel}
        self.steps.append(step)
        return step

    def set_status(self, name_or_id, status: str) -> bool:
        step = self._find(name_or_id)
        if step is None:
            return False
        step["status"] = status
        if status in (DONE, FAILED, CANCELLED):
            step["ended"] = time.time()
        return True

    def cancel(self, name_or_id) -> bool:
        step = self._find(name_or_id)
        if step is None or step["status"] in (DONE, CANCELLED):
            return False
        hook = step.get("cancel")
        try:
            if callable(hook):
                hook()
        except Exception:
            pass
        step["status"] = CANCELLED
        step["ended"] = time.time()
        return True

    def _find(self, name_or_id):
        for step in self.steps:
            if step["id"] == name_or_id or step["name"] == name_or_id:
                return step
        return None

    def lines(self) -> list[str]:
        out = []
        for step in self.steps:
            elapsed = (step["ended"] or time.time()) - step["started"]
            mark = _SYMBOLS.get(step["status"], "·")
            line = f"{mark} {step['name']}  {elapsed:4.1f}s"
            if step["detail"]:
                line += f"  — {step['detail']}"
            out.append(line)
        return out

    def clear_finished(self) -> int:
        before = len(self.steps)
        self.steps = [s for s in self.steps
                      if s["status"] in (PENDING, RUNNING)]
        return before - len(self.steps)
