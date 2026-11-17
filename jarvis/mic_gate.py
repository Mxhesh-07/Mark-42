"""Tier 1.6 — the microphone noise gate, out of main.py.

The gate keeps a chunk when the energy clearly rises above the recent ambient
level, or when webrtcvad hears speech *and* the energy clears the hold bar. The
energy bar is what makes webrtcvad safe to use: on a hot microphone it flags most
room noise as speech, so its verdict must never open the gate on its own.

The ambient level is an upper percentile of recent non-speech chunks (not a
running mean): a cough, a door or the keyboard is a brief burst a high percentile
ignores, while a sustained fan or air-conditioning is captured instead of being
mistaken for speech. It is learned even while the gate is open, so a gate that
opened on a burst can recover instead of latching open.
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
        percentile: float = 75,
        window: int = 90,
        min_floor: float = 65.0,
        max_floor: float = 180.0,
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
        # Do not lower the energy bar just because the gate is already open: a
        # hold multiple below the ambient p90 lets ordinary noise keep the gate
        # open forever. Word tails are covered by the hangover; the lower bar is
        # reserved for webrtcvad, whose verdict is independent evidence.
        rms_speech = rms > floor * threshold
        # webrtcvad may lower the bar for quiet speech, but never to zero
        # energy. On a hot microphone it calls most room noise "speech" (measured
        # here: 70-82% of silent frames at aggression 1), so its verdict alone
        # must not open the gate.
        had_vad = vad_speech is not None
        vad_speech = bool(vad_speech)
        vad_opens = vad_speech and rms > floor * self.hold_factor
        speak_now = rms_speech or vad_opens

        if speak_now:
            self.open = True
            self.last_speech = now
        elif not (self.open and now - self.last_speech <= self.hangover_s):
            self.open = False

        # Learn the ambient level from chunks webrtcvad says are not speech, even
        # while the gate is open. Otherwise a gate that opened on a burst latches
        # open forever: the floor is never corrected, and the hold threshold stays
        # below the room's own noise. Without webrtcvad, fall back to learning
        # whenever the chunk was not counted as speech.
        learn = (not vad_speech) if had_vad else (not speak_now)
        if learn:
            self.window.append(rms)
            if len(self.window) > self.window_size:
                del self.window[:-self.window_size]

        return self.open
