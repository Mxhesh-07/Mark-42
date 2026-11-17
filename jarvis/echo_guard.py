"""Distinguish JARVIS's own voice at the microphone from a real barge-in.

Comparing loudness alone is not enough: Windows microphone AGC can turn a loud
speaker bleed into a clipped signal (level 1.0) while the playback block being
queued at that instant happens to be quiet. That false positive used to cut the
reply in the middle of a word.

The reliable signal is similarity. Speaker bleed is a delayed, filtered copy of
what we just sent to the speaker; user speech is not. This module resamples the
24 kHz playback reference to the 16 kHz microphone rate and returns the best
normalized cross-correlation over plausible acoustic delays.
"""

from __future__ import annotations

import numpy as np

MIC_RATE = 16000
PLAYBACK_RATE = 24000


def resample_24k_to_16k(pcm: bytes) -> bytes:
    """Downsample 16-bit mono 24 kHz PCM to 16-bit mono 16 kHz."""
    src = np.frombuffer(pcm, dtype=np.int16)
    if src.size < 2:
        return b""
    dst_len = int(src.size * MIC_RATE / PLAYBACK_RATE)
    if dst_len < 1:
        return b""
    positions = np.linspace(0, src.size - 1, dst_len, endpoint=False)
    dst = np.interp(positions, np.arange(src.size), src.astype(np.float32))
    return np.clip(dst, -32768, 32767).astype(np.int16).tobytes()


def echo_correlation(out_pcm: bytes, mic_pcm: bytes,
                     max_lag_s: float = 0.25,
                     min_match_s: float = 0.12,
                     sample_rate: int = MIC_RATE) -> float:
    """Return 0..1 similarity of mic audio to a recent playback reference.

    ``out_pcm`` and ``mic_pcm`` are 16-bit mono PCM at ``sample_rate``. The
    search covers delays from 0 to ``max_lag_s``; a high score means the loud
    microphone signal is the speaker's own voice, not the user.
    """
    max_lag = int(float(sample_rate) * max_lag_s)
    min_match = max(64, int(float(sample_rate) * min_match_s))
    window = max_lag + min_match

    out = np.frombuffer(out_pcm, dtype=np.int16)[-window:]
    mic = np.frombuffer(mic_pcm, dtype=np.int16)[-window:]
    if out.size < min_match or mic.size < min_match:
        return 0.0

    a = out.astype(np.float32)
    b = mic.astype(np.float32)
    a -= a.mean()
    b -= b.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 1e-6:
        return 0.0

    n = 1 << (a.size + b.size - 2).bit_length()
    full = np.fft.irfft(
        np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n
    )
    # np.correlate(a, b, 'full') starts at lag -(len(b)-1). That is exactly the
    # region where mic is a *delayed* copy of playback.
    full = np.roll(full, b.size - 1)
    corr = full[:a.size + b.size - 1]
    start = b.size - 1 - min(max_lag, b.size - 1)
    best = float(np.max(np.abs(corr[start:b.size]))) if start < b.size else 0.0
    return min(1.0, best / denom)
