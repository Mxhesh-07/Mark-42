"""
J.A.R.V.I.S. — enrol a voice

Records from the same microphone JARVIS listens on and stores a voiceprint in
voice_profiles.json, so JARVIS can recognise the speaker later.

    python enroll_voice.py                       # enrol as the owner name
    python enroll_voice.py --name Alex           # explicit name
    python enroll_voice.py --list                # show enrolled voices
    python enroll_voice.py --delete Alex         # forget a voice

Just start talking once it says "speak now" — it keeps listening until it has
heard enough real speech (up to --timeout seconds), so you do not have to time
anything. Run it a couple of times to refine the voiceprint; runs are averaged.
"""

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import voice_id  # noqa: E402

RATE = 16000
CHUNK = 1024
FRAME_MS = 20
FRAME = int(RATE * FRAME_MS / 1000)


def _default_name() -> str:
    """The same default label JARVIS uses, else a neutral fallback.

    Kept in sync with main._owner_name(): the memory identity is consulted
    first, so enrolling from the CLI and saying "remember my voice" to JARVIS
    label the same person identically.
    """
    try:
        from memory.memory_manager import load_memory
        entry = (load_memory().get("identity", {}) or {}).get("name")
        name = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass

    for path in (BASE_DIR / "config" / "email_config.json",
                 BASE_DIR / "config" / "life_data.json",
                 BASE_DIR / "life_data.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for key in ("user_name", "name", "owner"):
            if isinstance(data.get(key), str) and data[key].strip():
                return data[key].strip()
    return "Owner"


def _pick_device():
    """Reuse JARVIS's own microphone picker so we record the same input."""
    try:
        from main import _pick_input_device, _apply_mic_level, _device_name, AUDIO_CONFIG
        dev = _pick_input_device()
        lvl = AUDIO_CONFIG.get("mic_level")
        if lvl is not None:
            _apply_mic_level(_device_name(dev), float(lvl))
        return dev
    except Exception as e:
        print(f"[enrol] could not use JARVIS picker ({e}); using default device")
        return None


def _record_until_speech(device, target_speech: float, timeout: float):
    """Record until `target_speech` seconds of speech or `timeout` elapses.

    Speech is scored as the union of an adaptive noise floor (webrtcvad
    under-reports on quiet far-field mics) and webrtcvad, and a live meter is
    drawn so you can see the microphone responding as you talk.
    """
    import pyaudio
    try:
        import webrtcvad
        vad = webrtcvad.Vad(3)
    except Exception:
        vad = None

    pa = pyaudio.PyAudio()
    try:
        kwargs = dict(format=pyaudio.paInt16, channels=1, rate=RATE,
                      input=True, frames_per_buffer=CHUNK)
        if device is not None:
            kwargs["input_device_index"] = device
        stream = pa.open(**kwargs)
    except Exception:
        pa.terminate()
        raise

    frames, recent = [], []
    carry = b""
    speech_s = 0.0
    t0 = time.time()
    tick, width = 0.0, 0
    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            x = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(x * x))) if x.size else 0.0

            recent.append(rms)
            if len(recent) > 160:                 # ~10 s of 64 ms chunks
                recent.pop(0)
            floor = float(np.percentile(recent, 20)) if len(recent) >= 8 else 0.0
            loud = rms > max(2.5 * floor, 70.0)   # clearly above the room

            vad_hit = False
            if vad is not None:                   # webrtcvad agrees on clear speech
                buf = carry + data
                step = FRAME * 2
                n = len(buf) // step
                vad_hit = any(vad.is_speech(buf[k * step:(k + 1) * step], RATE)
                              for k in range(n))
                carry = buf[n * step:]

            if loud or vad_hit:
                speech_s += len(x) / RATE

            elapsed = time.time() - t0
            if elapsed - tick >= 0.5:
                tick = elapsed
                msg = (f"  {elapsed:4.1f}s  rms {rms:5.0f}  floor {floor:4.0f}  "
                       f"speech {speech_s:4.1f}s  {'#' * min(28, int(rms / 25))}")
                print(msg + " " * max(0, width - len(msg)), end="\r", flush=True)
                width = len(msg)

            if speech_s >= target_speech or elapsed >= timeout:
                break
    finally:
        if width:
            print(" " * width, end="\r", flush=True)
        stream.close()
        pa.terminate()

    samples = np.frombuffer(b"".join(frames), dtype=np.int16)
    return samples, speech_s


def main() -> int:
    ap = argparse.ArgumentParser(description="Enrol a voice with JARVIS")
    ap.add_argument("--name", default=os.environ.get("JARVIS_OWNER") or _default_name())
    ap.add_argument("--speech", type=float, default=6.0,
                    help="seconds of speech to collect (default 6)")
    ap.add_argument("--timeout", type=float, default=45.0,
                    help="give up after this many seconds (default 45)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--delete", metavar="NAME")
    ap.add_argument("--save", metavar="PATH", help="also write the raw WAV")
    args = ap.parse_args()

    if args.list:
        print(json.dumps(voice_id.list_speakers(), indent=2))
        return 0

    if args.delete:
        profiles = voice_id._load_profiles()
        removed = (profiles["known"].pop(args.delete, None)
                   or profiles["unknown"].pop(args.delete, None))
        if removed:
            voice_id._save_profiles(profiles)
            print(f"Forgot {args.delete}.")
            return 0
        print(f"No voice named {args.delete}.")
        return 1

    if not voice_id.is_available():
        print("Speaker recognition is unavailable — install resemblyzer "
              "(pip install resemblyzer).")
        return 2

    print(f"Backend: {voice_id.backend()}")

    device = _pick_device()
    if device is None:
        print("No usable microphone was found — check that it is plugged in, "
              "unmuted, and that Windows is not blocking mic access.")
        return 6
    print(f"Microphone ready (device {device}). START TALKING NOW — read this out "
          f"loud:\n    \"JARVIS, this is my voice. I am recording a voiceprint so "
          f"you can recognise me.\"\n"
          f"  Repeat / keep talking for ~10 seconds. A live meter below shows the "
          f"mic hearing you\n  (rms rises and 'speech' climbs as you speak).")

    # Warm the model up while the user is talking, so start-up cost is hidden.
    warm = threading.Thread(target=voice_id.warmup, daemon=True)
    warm.start()

    samples, speech_s = _record_until_speech(device, args.speech, args.timeout)
    warm.join(timeout=60)

    if samples.size == 0:
        print("Nothing captured — check the microphone.")
        return 3

    rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
    print(f"Captured {samples.size / RATE:.1f}s  |  speech {speech_s:.1f}s  |  "
          f"RMS {rms:.0f}")

    if args.save:
        try:
            import soundfile as sf
            sf.write(args.save, samples, RATE)
            print(f"Saved raw audio to {args.save}")
        except Exception as e:
            print(f"(could not save WAV: {e})")

    if speech_s < 2.0:
        print("Too little speech detected — was the wrong microphone used?")
        return 4

    if voice_id.register_speaker(args.name, samples, sample_rate=RATE):
        print(f"Done — JARVIS will recognise '{args.name}' now.")
        return 0
    print("Enrolment failed.")
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
