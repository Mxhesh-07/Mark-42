"""Playback jitter buffer: never drop or reorder spoken PCM."""

from jarvis.playback_buffer import PlaybackBuffer


def test_playback_buffer_preserves_every_byte_in_order():
    buf = PlaybackBuffer(block_bytes=8, max_bytes=24)
    data = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = []
    for i in range(0, len(data), 5):
        out.extend(buf.add(data[i:i + 5]))
    out.append(buf.flush())

    assert b"".join(out) == data
    assert all(len(block) == 8 for block in out[:-1])
    assert buf.flush() == b""


def test_short_gap_does_not_flush_partial_block():
    buf = PlaybackBuffer(block_bytes=8, max_bytes=32)

    assert buf.add(b"12345") == []
    assert len(buf) == 5
    # 80 ms is normal socket jitter, not the end of a phrase.
    assert buf.ready(idle_s=0.08, tail_s=0.45, source_done=False) is False

    assert buf.add(b"678") == [b"12345678"]
    assert buf.add(b"9") == []
    # A long gap with no turn_complete still releases the tail.
    assert buf.ready(idle_s=0.50, tail_s=0.45, source_done=False) is True
    assert buf.flush() == b"9"


def test_turn_complete_flushes_immediately():
    buf = PlaybackBuffer(block_bytes=8, max_bytes=32)
    assert buf.add(b"abc") == []
    assert buf.ready(idle_s=0.0, tail_s=0.45, source_done=True) is True
    assert buf.flush() == b"abc"


def test_large_burst_flushes_early_without_loss():
    buf = PlaybackBuffer(block_bytes=8, max_bytes=16)
    data = b"ABCDEFGHIJKLMNOPQRST"

    blocks = buf.add(data)
    tail = buf.flush()

    assert b"".join(blocks) + tail == data
    assert len(buf) == 0
