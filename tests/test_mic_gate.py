"""Tier 1.6 — the noise gate: energy/VAD agreement, floor learning, hangover."""

from __future__ import annotations

import numpy as np

from jarvis.mic_gate import MicGate


def _chunk(value: int, size: int = 320):
    # Alternating ±value: zero mean, so RMS == value and DC removal is exercised.
    return np.tile(np.array([value, -value], dtype=np.int16), size // 2)


def _gate(**kwargs):
    defaults = dict(open_factor=1.9, hold_factor=1.3, hangover_s=0.35,
                    percentile=75, window=6, min_floor=0, max_floor=1000)
    defaults.update(kwargs)
    return MicGate(**defaults)


def test_gate_off_always_forwards_even_silence():
    gate = _gate()
    assert gate.keeps(_chunk(0), False) is True
    assert gate.keeps(None, True) is True


def test_speech_opens_instantly_and_noise_does_not():
    gate = _gate()
    assert gate.keeps(_chunk(5), True, 1.9, now=0.0) is False
    assert gate.keeps(_chunk(5), True, 1.9, now=0.1) is False
    assert gate.keeps(_chunk(2000), True, 1.9, now=0.2) is True
    assert gate.open is True


def test_hangover_keeps_word_tails_then_closes():
    gate = _gate()
    gate.keeps(_chunk(5), True, 1.9, now=0.0)
    assert gate.keeps(_chunk(2000), True, 1.9, now=1.0) is True
    assert gate.keeps(_chunk(5), True, 1.9, now=1.1) is True   # tail
    assert gate.keeps(_chunk(5), True, 1.9, now=1.5) is False  # past hangover


def test_webrtcvad_cannot_open_on_energy_alone():
    """A VAD verdict lowers the bar for quiet speech, but not to zero energy."""
    gate = _gate()
    gate.keeps(_chunk(5), True, 1.9, now=0.0)          # floor = 5
    assert gate.keeps(_chunk(5), True, 1.9, vad_speech=True, now=0.1) is False
    assert gate.keeps(_chunk(50), True, 1.9, vad_speech=True, now=0.2) is True


def test_quiet_speech_does_not_lift_the_floor():
    gate = _gate()
    for i in range(10):
        gate.keeps(_chunk(5), True, 1.9, now=i * 0.01)
    learned = gate.floor
    gate.keeps(_chunk(5000), True, 1.9, now=1.0)
    for i in range(10):
        gate.keeps(_chunk(5), True, 1.9, now=2.0 + i * 0.5)
    assert gate.floor == learned


def test_floor_is_clamped_between_the_configured_bounds():
    gate = _gate(min_floor=100, max_floor=120)
    gate.keeps(_chunk(1), True, 1.9, now=0.0)
    assert gate.floor == 100
    loud = _gate(min_floor=100, max_floor=120)
    loud.keeps(_chunk(30000), True, 1.9, now=0.0)
    assert loud.floor <= 120


def test_floor_uses_a_low_percentile_of_muted_chunks():
    gate = _gate(window=10, percentile=25)
    for value in [10, 10, 10, 10, 11, 12, 13, 40, 50, 60]:
        gate.keeps(_chunk(value), True, 1.9, now=0.0)
    assert gate.floor < 20


def test_a_noisy_room_does_not_hold_the_gate_open():
    """Measured room noise here is RMS 79-162; it must not read as speech."""
    gate = _gate(window=30, percentile=75, min_floor=40, max_floor=140)
    for i in range(30):
        gate.keeps(_chunk(112), True, 1.6, now=i * 0.05)
    assert gate.open is False
    assert 100 < gate.floor <= 140


def test_without_webrtcvad_speech_does_not_lift_the_floor():
    gate = _gate()
    gate.keeps(_chunk(5), True, 1.9, now=0.0)
    for i in range(10):
        gate.keeps(_chunk(2000), True, 1.9, now=1.0 + i * 0.05)
    assert gate.floor <= 10


def test_noise_just_above_the_old_hold_bar_still_closes():
    """Ambient noise around p90 (176 here) must not keep the gate open."""
    gate = _gate(window=30, percentile=75, min_floor=40, max_floor=180)
    for i in range(20):
        gate.keeps(_chunk(135), True, 1.6, vad_speech=False, now=i * 0.05)
    assert gate.floor >= 130
    assert gate.keeps(_chunk(600), True, 1.6, now=1.2) is True
    t = 1.3
    for _ in range(20):
        gate.keeps(_chunk(176), True, 1.6, vad_speech=False, now=t)
        t += 0.05
    assert gate.open is False


def test_vad_still_opens_quiet_speech_below_the_rms_bar():
    gate = _gate(window=30, percentile=75, min_floor=40, max_floor=180,
                 hold_factor=1.25)
    for i in range(20):
        gate.keeps(_chunk(135), True, 1.6, vad_speech=False, now=i * 0.05)
    # 175 is below open (216) but above the VAD bar (169), and VAD says speech.
    assert gate.keeps(_chunk(175), True, 1.6, vad_speech=True, now=1.5) is True


def test_a_gate_that_opened_on_a_burst_recovers_and_closes():
    gate = _gate(window=30, percentile=75, min_floor=40, max_floor=140)
    for i in range(10):
        gate.keeps(_chunk(60), True, 1.6, now=i * 0.05)
    assert gate.keeps(_chunk(600), True, 1.6, now=0.6) is True
    # Sustained ambient noise: the floor is learned even while open, so the
    # hold threshold rises above it instead of pinning the gate open.
    t = 0.7
    for _ in range(40):
        gate.keeps(_chunk(112), True, 1.6, vad_speech=False, now=t)
        t += 0.05
    assert gate.floor > 100
    assert gate.open is False
