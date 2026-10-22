"""Tier 2 E2 — first-run wizard.

The installer finishes, the app starts, and this asks the two questions that
cannot be guessed: the API key, and which microphone to listen on (with a live
level meter so "nothing is happening" is visible immediately instead of being
debugged later).

It is deliberately console-first and import-safe: everything the GUI/tray needs
is a plain function, and no device is opened until the user asks for the meter.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
API_KEYS = CONFIG_DIR / "api_keys.json"
FIRST_RUN = CONFIG_DIR / "first_run.json"
AUDIO = CONFIG_DIR / "audio.json"


def is_complete() -> bool:
    """True when both answers exist and the marker was written."""
    try:
        if not FIRST_RUN.exists():
            return False
        marker = json.loads(FIRST_RUN.read_text(encoding="utf-8"))
        if not marker.get("complete"):
            return False
        keys = json.loads(API_KEYS.read_text(encoding="utf-8"))
        return bool(str(keys.get("gemini_api_key", "")).strip())
    except Exception:
        return False


def mark_complete() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FIRST_RUN.with_suffix(".tmp")
    tmp.write_text(json.dumps({"complete": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}),
                   encoding="utf-8")
    os.replace(tmp, FIRST_RUN)


def save_api_key(key: str) -> None:
    key = (key or "").strip()
    if not key:
        raise ValueError("empty API key")
    try:
        from agent.secrets_guard import check

        ok, reason = check(key)
        if not ok:
            raise ValueError(reason)
    except ValueError:
        raise
    except Exception:
        pass
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    try:
        existing = json.loads(API_KEYS.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except Exception:
        existing = {}
    existing["gemini_api_key"] = key
    tmp = API_KEYS.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, API_KEYS)


def list_input_devices() -> list[dict]:
    try:
        import pyaudio

        pa = pyaudio.PyAudio()
        try:
            out = []
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if int(info.get("maxInputChannels", 0)) > 0:
                    out.append({
                        "index": i,
                        "name": str(info.get("name", "")),
                        "channels": int(info.get("maxInputChannels", 0)),
                        "rate": int(float(info.get("defaultSampleRate", 0) or 0)),
                    })
            return out
        finally:
            pa.terminate()
    except Exception:
        return []


def choose_device(name_part: str, devices: list[dict]) -> dict | None:
    """Case-insensitive substring match, the same rule main.py uses."""
    needle = (name_part or "").strip().lower()
    if not needle:
        return None
    for dev in devices:
        if needle in dev["name"].lower():
            return dev
    return None


def save_input_device(value) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    try:
        existing = json.loads(AUDIO.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}
    except Exception:
        existing = {}
    if isinstance(value, int):
        existing["input_device"] = int(value)
    else:
        existing["input_device"] = str(value)
    tmp = AUDIO.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    os.replace(tmp, AUDIO)


def meter_seconds(index: int, seconds: float = 3.0) -> list[int]:
    """Sample peaks from one input device. Returns the peaks it saw.

    Kept free of printing so tests can drive it with a fake; `run()` renders.
    """
    peaks: list[int] = []
    try:
        import pyaudio

        pa = pyaudio.PyAudio()
        try:
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                             input=True, input_device_index=index,
                             frames_per_buffer=1024)
            try:
                deadline = time.time() + max(0.1, float(seconds))
                while time.time() < deadline:
                    raw = stream.read(1024, exception_on_overflow=False)
                    peak = 0
                    for i in range(0, len(raw) - 1, 2):
                        sample = int.from_bytes(raw[i:i + 2], "little", signed=True)
                        peak = max(peak, abs(sample))
                    peaks.append(peak)
            finally:
                stream.stop_stream()
                stream.close()
        finally:
            pa.terminate()
    except Exception:
        return peaks
    return peaks


def _bar(peak: int, width: int = 24) -> str:
    filled = min(width, max(0, int(peak / 32768 * width)))
    return "#" * filled + "." * (width - filled)


def run(input_fn=input, print_fn=print) -> int:
    print_fn("JARVIS first run")
    print_fn("----------------")

    if not is_complete():
        key = input_fn("Gemini API key: ").strip()
        if key:
            save_api_key(key)
            print_fn("Saved to config/api_keys.json (gitignored).")
        else:
            print_fn("No key entered; you can add it later in config/api_keys.json.")

        devices = list_input_devices()
        if devices:
            print_fn("")
            print_fn("Microphones:")
            for dev in devices:
                print_fn(f"  [{dev['index']}] {dev['name']}")
            choice = input_fn(
                "Microphone (number, or part of the name; blank = auto): "
            ).strip()
            selected = None
            if choice.isdigit():
                selected = next((d for d in devices if d["index"] == int(choice)), None)
            elif choice:
                selected = choose_device(choice, devices)
            if selected:
                print_fn(f"Speak now — measuring {selected['name']} for 3 seconds...")
                peaks = meter_seconds(selected["index"], 3.0)
                for peak in peaks[::3]:
                    print_fn(f"  {_bar(peak)}  {peak}")
                best = max(peaks) if peaks else 0
                if best <= 0:
                    print_fn("No signal. Check the device and Windows microphone "
                             "permissions; nothing was saved.")
                else:
                    save_input_device(selected["index"])
                    print_fn(f"Saved microphone '{selected['name']}' (peak {best}).")
            else:
                print_fn("No device selected; the app will auto-detect on first run.")
        else:
            print_fn("No microphones found (pyaudio not installed or no device).")
            print_fn("The app will auto-detect once a microphone is available.")

        mark_complete()

    print_fn("")
    print_fn("Ready. Start with: python main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
