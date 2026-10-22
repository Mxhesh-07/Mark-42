"""Tier 1.6 — microphone discovery and gain, out of main.py.

These were 200 lines in the middle of the app entry point, which made them
impossible to test without PyAudio devices. The behaviour is unchanged; the
constants are passed in a `CaptureSpec` so the module has no import-time
dependency on the app's tuning block.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

VIRTUAL_HINTS = (
    "stereo mix", "what u hear", "loopback", "sound mapper", "primary sound",
    "wave out", "output",
)


@dataclass(frozen=True)
class CaptureSpec:
    format: int = 8              # pyaudio.paInt16
    channels: int = 1
    rate: int = 16000
    chunk: int = 1024
    dead_peak: int = 40
    alive_peak: int = 90
    bad_peak: int = 30000
    virtual_hints: tuple = field(default=VIRTUAL_HINTS)


def load_audio_config(base_dir) -> dict:
    """Optional user overrides (input device, noise gate). Never fatal."""
    try:
        with open(Path(base_dir) / "config" / "audio.json", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def device_peak(pa, index: int, spec: CaptureSpec, seconds: float = 0.6) -> int:
    """Peak sample magnitude captured from `index` (-1 if unusable)."""
    try:
        stream = pa.open(
            format=spec.format, channels=spec.channels, rate=spec.rate,
            input=True, input_device_index=index,
            frames_per_buffer=spec.chunk,
        )
    except Exception:
        return -1
    peak = 0
    broken = False
    try:
        t0 = time.time()
        while time.time() - t0 < seconds:
            data = stream.read(spec.chunk, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16)
            if samples.size > spec.chunk:      # host returned more than asked
                broken = True
                break
            if samples.size:
                peak = max(peak, int(np.abs(samples).max()))
    except Exception:
        return -1
    finally:
        try:
            stream.close()
        except Exception:
            pass
    if broken or peak >= spec.bad_peak:
        return -1
    return peak


def pick_input_device(config: dict, spec: CaptureSpec, audio_module, *,
                      printer=print):
    """Return the PyAudio index of the microphone to listen on (or None)."""
    pref = (config or {}).get("input_device")

    try:
        pa = audio_module.open_pyaudio()
    except Exception:
        return None

    try:
        candidates = []
        for i in range(pa.get_device_count()):
            try:
                d = pa.get_device_info_by_index(i)
            except Exception:
                continue
            name = str(d.get("name", ""))
            low = name.lower()
            if not d.get("maxInputChannels") or any(
                    h in low for h in spec.virtual_hints):
                continue
            candidates.append((i, name, int(d.get("hostApi", 99))))

        candidates.sort(key=lambda t: (t[2], t[0]))     # MME first, then index
        inputs, seen = [], set()
        for i, name, _api in candidates:
            key = name.lower()[:28]
            if key in seen:
                continue
            seen.add(key)
            inputs.append((i, name))

        if isinstance(pref, int):
            printer(f"[JARVIS] 🎙️ Input device (from config): [{pref}]")
            return pref
        if isinstance(pref, str) and pref.strip():
            needle = pref.strip().lower()
            for i, nm in inputs:
                if needle in nm.lower():
                    printer(f"[JARVIS] 🎙️ Input device (from config): [{i}] {nm}")
                    return i
            printer(f"[JARVIS] ⚠️ config input_device '{pref}' not found — auto-detecting")

        try:
            default_index = pa.get_default_input_device_info()["index"]
        except Exception:
            default_index = None

        default_name = next((nm for i, nm in inputs if i == default_index),
                            "system default")
        if default_index is not None:
            p = device_peak(pa, default_index, spec)
            printer(f"[JARVIS] 🎙️ Default input [{default_index}] {default_name} "
                    f"peak={p}")
            if p >= spec.dead_peak:
                return default_index
            printer("[JARVIS] ⚠️ Default microphone appears silent "
                    "(3.5mm jack with nothing plugged in?) — searching for a live mic")

        best, best_peak, best_name = None, -1, ""
        for i, nm in inputs:
            if i == default_index:
                continue
            p = device_peak(pa, i, spec)
            if p > best_peak:
                best, best_peak, best_name = i, p, nm
            if p >= spec.alive_peak:
                break

        if best is not None and best_peak > 0:
            if best_peak >= spec.dead_peak:
                printer(f"[JARVIS] 🎙️ Using input [{best}] {best_name}  (peak={best_peak})")
            else:
                printer(f"[JARVIS] ⚠️ Every microphone looks quiet — using the "
                        f"best, [{best}] {best_name} (peak={best_peak}); check the "
                        f"Windows mic level or mute if JARVIS cannot hear you")
            return best

        printer("[JARVIS] ⚠️ No microphone produced any signal — using system default")
        return None
    finally:
        audio_module.close(pa)


def device_name(index, audio_module) -> str:
    """Friendly name of a PyAudio input device index ('' if unknown)."""
    if index is None:
        return ""
    try:
        pa = audio_module.open_pyaudio()
        try:
            return str(pa.get_device_info_by_index(index).get("name", ""))
        finally:
            audio_module.close(pa)
    except Exception:
        return ""


def apply_mic_level(device_name_value: str, level: float, *, printer=print) -> bool:
    """Set the Windows capture level for `device_name_value` (0.0 .. 1.0)."""
    try:
        from core import platform as platform_adapter

        if platform_adapter.set_mic_level(device_name_value, level):
            printer(f"[JARVIS] 🔉 Mic level -> {level:.2f} on {device_name_value}")
            return True
        printer(f"[JARVIS] ⚠️ could not set mic level for '{device_name_value}' "
                f"(unsupported platform or device not found)")
        return False
    except Exception as exc:
        printer(f"[JARVIS] ⚠️ could not set mic level: {exc}")
        return False
