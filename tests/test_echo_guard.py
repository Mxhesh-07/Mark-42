"""Speaker-echo detection must not be fooled by clipped microphone levels."""

import numpy as np

from jarvis.echo_guard import echo_correlation, resample_24k_to_16k


def test_delayed_speaker_bleed_is_detected():
    rng = np.random.default_rng(7)
    out = rng.normal(0, 6000, 16000).astype(np.int16)
    mic = np.zeros(16000, dtype=np.int16)
    delay = 2400
    mic[delay:] = out[:16000 - delay]

    score = echo_correlation(out.tobytes(), mic.tobytes())

    assert score > 0.45


def test_unrelated_microphone_audio_is_not_echo():
    rng = np.random.default_rng(11)
    out = rng.normal(0, 6000, 16000).astype(np.int16)
    mic = rng.normal(0, 6000, 16000).astype(np.int16)

    score = echo_correlation(out.tobytes(), mic.tobytes())

    assert score < 0.15


def test_short_buffers_do_not_crash():
    assert echo_correlation(b"", b"") == 0.0
    assert echo_correlation(b"\x01\x00" * 4, b"\x02\x00" * 4) == 0.0


def test_resample_24k_to_16k_keeps_sample_count_and_scale():
    rng = np.random.default_rng(3)
    src = rng.normal(0, 5000, 24000).astype(np.int16)

    dst = np.frombuffer(resample_24k_to_16k(src.tobytes()), dtype=np.int16)

    assert dst.size == 16000
    assert np.abs(dst).mean() > 1000
