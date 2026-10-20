"""F2: lightweight latency budget measurement.

Tracks time from a marker to first audio out or to completion, stored in
memory/metrics.json style via agent.metrics. Keeps it simple and best-effort.
"""

from __future__ import annotations

import time
from typing import Any


class Timer:
    def __init__(self, name: str = "turn", **tags: Any):
        self.name = name
        self.tags = tags
        self.start = time.perf_counter()
        self.first_out = None
        self.end = None

    def mark_first_out(self):
        if self.first_out is None:
            self.first_out = time.perf_counter()
        return self

    def stop(self):
        if self.end is None:
            self.end = time.perf_counter()
        self.record()
        return self

    @property
    def mic_to_first_ms(self):
        if self.first_out is None:
            return None
        return (self.first_out - self.start) * 1000.0

    @property
    def total_ms(self):
        if self.end is None:
            return None
        return (self.end - self.start) * 1000.0

    def record(self):
        try:
            from agent import metrics
            if self.first_out is not None:
                metrics.observe("latency.mic_to_first_audio_ms", self.mic_to_first_ms, **self.tags)
            if self.end is not None:
                metrics.observe("latency.turn_total_ms", self.total_ms, **self.tags)
        except Exception:
            pass

    def as_dict(self):
        return {
            "name": self.name,
            "tags": self.tags,
            "mic_to_first_ms": self.mic_to_first_ms,
            "total_ms": self.total_ms,
        }


def now():
    return time.perf_counter()
