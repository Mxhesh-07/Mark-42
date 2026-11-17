"""Tier 1.7 - deciding when the user is talking over JARVIS.

The echo guard keeps listening while JARVIS speaks and compares the microphone
against the audio being played. Speech that is clearly louder than the expected
speaker bleed is a barge-in. A slow echo baseline is also maintained: the first
half-second of playback is the loudest (speaker cones and room reflections), so
learning that level prevents JARVIS from interrupting itself mid-word.

The decision is testable without a microphone, speaker or Live session:

    det = BargeInDetector(floor=0.14, ratio=1.45, hits=3)
    if det.check(mic_level, out_level, echo_level):
        interrupt()

``hits`` consecutive loud chunks are required so a door slam or a single
stressed syllable cannot stop a sentence by accident. A quiet chunk resets the
count; interruptions are deliberate, not cumulative noise.
"""

from __future__ import annotations


class BargeInDetector:
    def __init__(self, floor: float = 0.14, ratio: float = 1.45, hits: int = 3,
                 echo_factor: float = 1.25):
        self.floor = max(0.0, float(floor))
        self.ratio = max(1.0, float(ratio))
        self.hits = max(1, int(hits))
        self.echo_factor = max(1.0, float(echo_factor))
        self._count = 0

    def reset(self) -> None:
        self._count = 0

    def threshold(self, out_level: float, echo_level: float = 0.0) -> float:
        """How loud the microphone must be to count as speech over the speaker.

        ``echo_level`` is the learned level of JARVIS's own voice at the mic.
        Requiring a margin above it is what stops the model from treating its
        own sentence as a user interruption. The old two-argument form is still
        supported (echo_level defaults to zero).
        """
        return max(
            self.floor,
            max(0.0, float(out_level)) * self.ratio,
            max(0.0, float(echo_level)) * self.echo_factor,
        )

    def check(self, mic_level: float, out_level: float,
              echo_level: float = 0.0) -> bool:
        """Feed one chunk. True exactly once, when the interrupt is confirmed."""
        if float(mic_level) >= self.threshold(out_level, echo_level):
            self._count += 1
        else:
            self._count = 0
        if self._count < self.hits:
            return False
        self._count = 0
        return True
