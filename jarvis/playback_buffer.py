"""Jitter buffer for Gemini Live speech audio.

The Live API delivers PCM in socket-sized packets, not in evenly spaced blocks.
Writing each packet straight to PortAudio makes a late packet audible as a gap
in the middle of a word. This buffer coalesces packets into fixed-size blocks
and deliberately keeps a short partial block across small network gaps instead
of flushing it immediately.

    buf = PlaybackBuffer(block_bytes=5760, max_bytes=24000)
    for packet in packets:
        for block in buf.add(packet):
            stream.write(block)
    stream.write(buf.flush())       # only when the turn is really over

Every byte that goes in comes back out exactly once — in order. Dropping or
reordering PCM is what sounds like "the voice skipped to another word", so this
class never does either.
"""

from __future__ import annotations


class PlaybackBuffer:
    """Lossless byte buffer that emits whole playback blocks."""

    def __init__(self, block_bytes: int, max_bytes: int | None = None):
        self.block_bytes = max(1, int(block_bytes))
        self.max_bytes = max(self.block_bytes, int(max_bytes or self.block_bytes * 8))
        self._buf = bytearray()

    def __len__(self) -> int:
        return len(self._buf)

    def clear(self) -> None:
        self._buf.clear()

    def add(self, data: bytes) -> list[bytes]:
        """Append a packet; return zero or more complete blocks to play."""
        if not data:
            return []
        self._buf.extend(data)
        blocks: list[bytes] = []
        while len(self._buf) >= self.block_bytes:
            blocks.append(bytes(self._buf[:self.block_bytes]))
            del self._buf[:self.block_bytes]
        # Safety valve: a long socket burst must not grow latency without bound.
        # This flushes early, but still never discards audio.
        while len(self._buf) > self.max_bytes:
            blocks.append(bytes(self._buf[:self.block_bytes]))
            del self._buf[:self.block_bytes]
        return blocks

    def ready(self, idle_s: float, tail_s: float, source_done: bool) -> bool:
        """Whether the partial tail should be written now.

        ``source_done`` means the model reported turn_complete; that is the
        authoritative signal. Before that, only a long gap (or an oversized
        cushion) flushes. A small gap is normal jitter and must not create a
        silent hole between words.
        """
        if not self._buf:
            return False
        return bool(source_done or idle_s >= tail_s or len(self._buf) > self.max_bytes)

    def flush(self) -> bytes:
        """Return and remove every remaining byte."""
        data = bytes(self._buf)
        self._buf.clear()
        return data
