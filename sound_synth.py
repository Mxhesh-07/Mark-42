"""Procedural movie-grade SFX for MCU HUD morphs - zero external files."""
from __future__ import annotations

import math
import random
from typing import Optional

import numpy as np
import pygame
from pygame import sndarray


class SoundSynth:
    def __init__(self, sample_rate: int = 44100):
        self.sample_rate = sample_rate
        self.enabled = True
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=sample_rate, size=-16, channels=2, buffer=512)
        except Exception:
            self.enabled = False

    def _make(self, wave: np.ndarray, volume: float = 0.4):
        if not self.enabled:
            return None
        try:
            wave = np.clip(wave * volume, -1.0, 1.0)
            stereo = np.column_stack((wave, wave))
            arr = (stereo * 32767).astype(np.int16)
            s = sndarray.make_sound(arr)
            return s
        except Exception:
            return None

    def disconnect_snap(self):
        if not self.enabled:
            return
        t = np.linspace(0, 0.16, int(self.sample_rate * 0.16), False)
        freq = np.linspace(2200, 900, len(t))
        wave = np.sign(np.sin(2 * np.pi * freq * t)) * 0.25
        noise = np.random.randn(len(t)) * 0.12
        wave = (wave + noise)
        env = np.exp(-18 * t / 0.16)
        wave *= env
        s = self._make(wave, 0.35)
        if s: s.play()

    def magnetic_recoil(self):
        if not self.enabled:
            return
        t = np.linspace(0, 0.28, int(self.sample_rate * 0.28), False)
        freq = np.linspace(650, 320, len(t))
        wave = np.sin(2 * np.pi * freq * t) * 0.22
        wave += np.sin(2 * np.pi * freq * 0.5 * t) * 0.16
        env = np.exp(-10 * t / 0.28)
        wave *= env
        s = self._make(wave, 0.32)
        if s: s.play()

    def nanite_stream(self):
        if not self.enabled:
            return
        t = np.linspace(0, 0.42, int(self.sample_rate * 0.42), False)
        freq = np.linspace(950, 1850, len(t))
        wave = (np.sin(2 * np.pi * freq * t) * 0.16)
        clicks = (np.random.rand(len(t)) > 0.88).astype(float) * 0.24
        wave += clicks
        env = np.exp(-7 * t / 0.42)
        wave *= env
        s = self._make(wave, 0.34)
        if s: s.play()

    def neural_tear(self):
        if not self.enabled:
            return
        t = np.linspace(0, 0.58, int(self.sample_rate * 0.58), False)
        sub = np.sin(2 * np.pi * 38 * t) * 0.36
        mod = np.sin(2 * np.pi * 27 * t + np.pi/4) * 0.28
        wave = sub * (1.0 + mod)
        noise = np.random.randn(len(t)) * 0.22
        wave = (wave + noise)
        env = np.exp(-4.2 * t / 0.58)
        wave *= env
        s = self._make(wave, 0.38)
        if s: s.play()

    def jarvis_lock(self):
        if not self.enabled:
            return
        t = np.linspace(0, 0.64, int(self.sample_rate * 0.64), False)
        f1 = np.linspace(420, 780, len(t))
        f2 = np.linspace(640, 520, len(t))
        wave = np.sin(2 * np.pi * f1 * t) * 0.2
        wave += np.sin(2 * np.pi * f2 * t) * 0.16
        wave += np.sin(2 * np.pi * f1 * 2 * t) * 0.09
        env = np.exp(-5.5 * t / 0.64)
        wave *= env
        s = self._make(wave, 0.34)
        if s: s.play()

    def friday_lock(self):
        if not self.enabled:
            return
        t = np.linspace(0, 0.58, int(self.sample_rate * 0.58), False)
        f = np.linspace(780, 1320, len(t))
        wave = np.sign(np.sin(2 * np.pi * f * t)) * 0.18
        wave += np.sin(2 * np.pi * f * 1.6 * t) * 0.14
        chirp = (np.random.rand(len(t)) > 0.9).astype(float) * 0.16
        wave += chirp
        env = np.exp(-6.2 * t / 0.58)
        wave *= env
        s = self._make(wave, 0.36)
        if s: s.play()

    def ultron_lock(self):
        if not self.enabled:
            return
        t = np.linspace(0, 0.76, int(self.sample_rate * 0.76), False)
        f = np.linspace(58, 164, len(t))
        wave = np.sin(2 * np.pi * f * t) * 0.42
        mod = np.sin(2 * np.pi * 19 * t) * 0.34
        wave = wave * (1.0 + mod)
        noise = np.random.randn(len(t)) * 0.26
        wave += noise
        env = np.exp(-3.4 * t / 0.76)
        wave *= env
        s = self._make(wave, 0.4)
        if s: s.play()


_SYNTH = None


def get_synth() -> SoundSynth:
    global _SYNTH
    if _SYNTH is None:
        _SYNTH = SoundSynth()
    return _SYNTH
