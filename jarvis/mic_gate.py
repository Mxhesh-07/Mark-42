"""Tier 1.6 — the microphone noise gate, out of main.py.

The gate keeps a chunk if *either* detector says speech: webrtcvad's verdict or
the chunk RMS relative to a tracked room-noise floor. The union means real speech
is never dropped because one detector was unsure, while both stay quiet on pure
noise.

The floor is a low percentile of recent *muted* chunk levels (not a running
mean): a cough, a door or the keyboard are brief bursts and must not drag the
floor up, and the clamp stops a genuinely loud room from raising the threshold
beyond normal speech. Opening is instant so the first word is never lost, and the
gate stays open `hangover_s` past the last speech frame so word tails are never
clipped.
"""

from __future__ import annotations

import time

import numpy as np


class MicGate:
    def __init__(
        self,
        *,
        open_factor: float = 1.9,
        hold_factor: float = 1.3,
        hangover_s: float = 0.35,
        percentile: float = 25,
        window: int = 90,
        min_floor: float = 65.0,
        max_floor: float = 125.0,
        clock=time.time,
    ):
        self.open_factor = float(open_factor)
        self.hold_factor = float(hold_factor)
        self.hangover_s = float(hangover_s)
        self.percentile = float(percentile)
        self.window_size = max(1, int(window))
        self.min_floor = float(min_floor)
        self.max_floor = float(max_floor)
        self.clock = clock

        self.window: list[float] = []
        self.floor = 0.0
        self.open = False
        self.last_speech = 0.0

    def keeps(self, samples, gate_on: bool, gate_factor: float | None = None,
              vad_speech=None, *, now: float | None = None) -> bool:
        """True when the chunk should be forwarded (or the gate is off)."""
        if not gate_on or samples is None or not samples.size:
            return True

        x = samples.astype(np.float32)
        x -= x.mean()                              # ignore any DC offset
        rms = float(np.sqrt(np.mean(x * x)))
        now = float(self.clock() if now is None else now)

        floor = (float(np.percentile(self.window, self.percentile))
                 if self.window else rms)
        floor = min(max(floor, self.min_floor), self.max_floor)
        self.floor = floor

        threshold = gate_factor if gate_factor is not None else self.open_factor
        rms_speech = rms > floor * (self.hold_factor if self.open else threshold)
        speak_now = rms_speech or bool(vad_speech)

        if speak_now:
            self.open = True
            self.last_speech = now
        elif not (self.open and now - self.last_speech <= self.hangover_s):
            self.open = False

        if not self.open:
            # Learn the floor only while muted, so speech cannot lift it.
            self.window.append(rms)
            if len(self.window) > self.window_size:
                del self.window[:-self.window_size]

        return self.open
