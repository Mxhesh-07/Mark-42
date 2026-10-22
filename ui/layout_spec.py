"""Tier 3.4 — one description of the HUD's geometry.

Positions used to be arithmetic buried in `JarvisUI.__init__` and in
`create_dashboard_panels`, which meant the log pane and the status strip could
drift apart. `Metrics.from_size()` is now the single source for the main panes;
new widgets should take their coordinates from it instead of adding more
percentages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metrics:
    width: int
    height: int
    content_frac: float = 0.72
    gap: int = 10
    log_frac: float = 0.52
    log_height: int = 138
    bottom_margin: int = 36
    status_height: int = 14
    panel_margin: int = 15

    @classmethod
    def from_size(cls, width: int, height: int) -> "Metrics":
        return cls(max(640, int(width)), max(480, int(height)))

    @property
    def content_width(self) -> int:
        return int(self.width * self.content_frac)

    @property
    def left_x(self) -> int:
        return (self.width - self.content_width) // 2

    @property
    def log_width(self) -> int:
        return int(self.content_width * self.log_frac)

    @property
    def think_width(self) -> int:
        return self.content_width - self.log_width - self.gap

    @property
    def panes_y(self) -> int:
        return self.height - self.log_height - self.bottom_margin

    @property
    def think_x(self) -> int:
        return self.left_x + self.log_width + self.gap

    @property
    def status_y(self) -> int:
        return self.height - 20

    @property
    def status_width(self) -> int:
        return self.width - 30

    def pane(self, which: str) -> dict:
        if which == "log":
            return {"x": self.left_x, "y": self.panes_y,
                    "width": self.log_width, "height": self.log_height}
        if which == "think":
            return {"x": self.think_x, "y": self.panes_y,
                    "width": self.think_width, "height": self.log_height}
        if which == "status":
            return {"x": self.panel_margin, "y": self.status_y,
                    "width": self.status_width, "height": self.status_height}
        raise ValueError(f"unknown pane: {which}")
