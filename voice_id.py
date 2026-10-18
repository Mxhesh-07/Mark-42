"""
J.A.R.V.I.S. — Speaker Identification Module

Recognises known voices from short audio clips and remembers new ones.

Backends, in order of preference:
  1. resemblyzer  — GE2E d-vectors; ships its model, no download, fast enough
                    to run on the live mic stream (a few ms per clip).
  2. speechbrain  — ECAPA-TDNN; heavier, downloads a checkpoint on first use.
Whichever is installed is used. If neither is, speaker ID is disabled and the
rest of JARVIS carries on unchanged (fail open, never block a conversation).

Embeddings are stored in voice_profiles.json. That file is biometric data and
must stay out of version control.
"""

import importlib.util
import json
import numpy as np
from pathlib import Path
from threading import Lock

BASE_DIR = Path(__file__).resolve().parent
PROFILES_PATH = BASE_DIR / "voice_profiles.json"

# Cosine similarity above which two embeddings are judged the same speaker.
# resemblyzer/d-vectors separate speakers around 0.75; ECAPA (speechbrain) is
# a touch more generous, so the threshold is per-backend.
THRESHOLDS = {"resemblyzer": 0.75, "speechbrain": 0.70}
TARGET_RATE = 16000

# A clip must contain at least this share of speech frames before it is treated
# as a voice at all. Without it, room noise is embedded, "recognised" as a
# speaker and stored — which both pollutes the profile file and can make noise
# look like a match. webrtcvad is used when available; otherwise a plain energy
# test stands in.
MIN_SPEECH_FRACTION = 0.10

_lock = Lock()

# ── Backend detection (done once) ─────────────────────────────────────────
_AVAILABLE: bool | None = None
_AVAILABILITY_ERROR = ""
_BACKEND: str | None = None
_ENCODER = None                      # cached backend model (loaded once!)
_ENCODER_LOCK = Lock()
_warned = False


def _detect_backend() -> str | None:
    global _AVAILABILITY_ERROR
    if importlib.util.find_spec("resemblyzer") is not None:
        return "resemblyzer"
    if importlib.util.find_spec("speechbrain") is not None:
        return "speechbrain"
    _AVAILABILITY_ERROR = (
        "no speaker backend found — install resemblyzer "
        "(pip install resemblyzer) or speechbrain + torch"
    )
    return None


def is_available() -> bool:
    """True if a speaker-embedding backend is importable."""
    global _AVAILABLE, _BACKEND
    if _AVAILABLE is None:
        _BACKEND = _detect_backend()
        _AVAILABLE = _BACKEND is not None
    return _AVAILABLE


def backend() -> str | None:
    is_available()
    return _BACKEND


def _warn_unavailable_once() -> None:
    global _warned
    if not _warned:
        _warned = True
        print(f"[VoiceID] Speaker ID disabled — {_AVAILABILITY_ERROR}.")


def _get_encoder():
    """Return the cached embedding model, loading it on first use."""
    global _ENCODER
    if _ENCODER is not None:
        return _ENCODER
    with _ENCODER_LOCK:
        if _ENCODER is None:
            if _BACKEND == "resemblyzer":
                from resemblyzer import VoiceEncoder
                _ENCODER = ("resemblyzer", VoiceEncoder(verbose=False))
            else:
                from speechbrain.inference import SpeakerRecognition
                _ENCODER = ("speechbrain", SpeakerRecognition.from_hparams(
                    source="speechbrain/spkrec-ecapa-voxceleb",
                    savedir="pretrained_models/spkrec-ecapa-voxceleb",
                ))
    return _ENCODER


def warmup() -> bool:
    """Load the model and run one dummy embedding.

    The first inference is an order of magnitude slower than the rest (model
    load + torch warm-up), so call this from a background thread at startup —
    otherwise the first real recognition stalls the mic loop.
    """
    if not is_available():
        return False
    try:
        _get_encoder()
        tone = (0.1 * np.sin(2 * np.pi * 220 * np.arange(TARGET_RATE) / TARGET_RATE))
        _extract_embedding(tone.astype(np.float32), TARGET_RATE)
        print(f"[VoiceID] {_BACKEND} ready")
        return True
    except Exception as e:
        print(f"[VoiceID] warm-up failed: {e}")
        return False


# ── profiles ──────────────────────────────────────────────────────────────
def _load_profiles() -> dict:
    if not PROFILES_PATH.exists():
        return {"known": {}, "unknown": {}}
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("known", {})
        data.setdefault("unknown", {})
        return data
    except Exception:
        return {"known": {}, "unknown": {}}


def _save_profiles(profiles: dict) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = PROFILES_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)
        tmp.replace(PROFILES_PATH)


# ── embeddings ────────────────────────────────────────────────────────────
def _to_mono_float(audio_data, sample_rate: int) -> np.ndarray:
    """Normalise any mic input to mono float32 in [-1, 1] at TARGET_RATE."""
    arr = np.asarray(audio_data)
    if arr.dtype == np.int16:
        arr = arr.astype(np.float32) / 32768.0
    elif arr.dtype == np.int32:
        arr = arr.astype(np.float32) / 2147483648.0
    else:
        arr = arr.astype(np.float32)
    arr = np.ascontiguousarray(arr.reshape(-1))

    if sample_rate != TARGET_RATE:
        try:
            import librosa
            arr = librosa.resample(arr, orig_sr=sample_rate, target_sr=TARGET_RATE)
        except Exception:
            pass

    peak = float(np.max(np.abs(arr))) if arr.size else 0.0
    if peak > 1.0:
        arr = arr / peak
    return arr


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def _speech_fraction(wav: np.ndarray, rate: int = TARGET_RATE) -> float:
    """Share of 20 ms frames that look like speech (0..1).

    Uses webrtcvad when present, else a simple energy-above-median test.
    """
    try:
        import webrtcvad
    except Exception:
        rms = float(np.sqrt(np.mean(wav * wav))) if wav.size else 0.0
        return 1.0 if rms > 0.01 else 0.0

    frame = int(rate * 0.02)
    if frame == 0 or wav.size < frame:
        return 0.0
    raw = (np.clip(wav, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    fb = frame * 2
    n = len(raw) // fb
    if n == 0:
        return 0.0
    vad = webrtcvad.Vad(3)
    hits = sum(1 for k in range(n)
               if vad.is_speech(raw[k * fb:(k + 1) * fb], rate))
    return hits / n


def _extract_embedding(audio_data, sample_rate: int = TARGET_RATE) -> np.ndarray:
    if not is_available():
        raise RuntimeError(_AVAILABILITY_ERROR or "speaker backend unavailable")

    wav = _to_mono_float(audio_data, sample_rate)
    if wav.size < int(0.4 * TARGET_RATE):
        raise ValueError("clip too short for speaker recognition")

    kind, model = _get_encoder()
    if kind == "resemblyzer":
        emb = model.embed_utterance(wav)
        return np.asarray(emb, dtype=np.float64)

    import torch
    waveform = torch.tensor(wav, dtype=torch.float32).unsqueeze(0)
    embedding = model.encode_batch(waveform)
    return embedding.squeeze().detach().cpu().numpy().astype(np.float64)


def _threshold() -> float:
    return THRESHOLDS.get(_BACKEND or "", 0.75)


def _best_match(embedding, candidates: dict):
    """Best (name, score) among candidates, skipping incompatible embeddings.

    Voiceprints written by a *different* backend have a different vector length
    (e.g. speechbrain's 192-d ECAPA vs resemblyzer's 256-d d-vectors) and cannot
    be compared, so they are skipped rather than allowed to raise. A stale print
    then simply reads as "no match" and the owner can re-enrol to replace it.
    """
    query = np.asarray(embedding, dtype=np.float64)
    best_name, best_score = None, 0.0
    for name, data in candidates.items():
        emb = data.get("embedding")
        if not emb:
            continue
        emb = np.asarray(emb, dtype=np.float64)
        if emb.shape != query.shape:
            continue
        score = _cosine_similarity(query, emb)
        if score > best_score:
            best_score, best_name = score, name
    return best_name, best_score


def _next_unknown_id(unknown: dict) -> str:
    """Lowest unused `UNK-nnn` id.

    Ids are freed when a voice is named via assign_name_to_unknown(), so keying
    off len() alone would hand out an id that already exists and overwrite it.
    """
    used = {int(k[4:]) for k in unknown
            if k.startswith("UNK-") and k[4:].isdigit()}
    n = 1
    while n in used:
        n += 1
    return f"UNK-{n:03d}"


# ── public API ────────────────────────────────────────────────────────────
def identify_speaker(audio_data, sample_rate: int = TARGET_RATE) -> dict:
    """Identify the speaker in `audio_data`.

    Returns {"status": "known"|"unknown"|"unavailable"|"error",
             "name": str, "confidence": float}
    An unrecognised voice is remembered under profiles["unknown"] so it can be
    named later with assign_name_to_unknown().
    """
    if not is_available():
        _warn_unavailable_once()
        return {"status": "unavailable", "name": "Unknown", "confidence": 0.0}

    try:
        embedding = _extract_embedding(audio_data, sample_rate)
    except Exception as e:
        print(f"[VoiceID] Embedding failed: {e}")
        return {"status": "error", "name": "Unknown", "confidence": 0.0}

    wav = _to_mono_float(audio_data, sample_rate)
    if _speech_fraction(wav) < MIN_SPEECH_FRACTION:
        # Noise, a door, JARVIS's own tail — not a voice worth remembering.
        return {"status": "noise", "name": "Unknown", "confidence": 0.0}

    profiles = _load_profiles()
    threshold = _threshold()

    name, score = _best_match(embedding, profiles["known"])
    if name and score >= threshold:
        print(f"[VoiceID] Recognised: {name} ({score:.2f})")
        return {"status": "known", "name": name, "confidence": score}

    uid, uscore = _best_match(embedding, profiles["unknown"])
    if uid and uscore >= threshold:
        profiles["unknown"][uid]["last_seen"] = str(np.datetime64("now"))
        profiles["unknown"][uid]["sample_count"] = \
            profiles["unknown"][uid].get("sample_count", 1) + 1
        _save_profiles(profiles)
        print(f"[VoiceID] Known unknown voice: {uid} ({uscore:.2f})")
        return {"status": "unknown", "name": f"Unknown-{uid}", "confidence": uscore}

    new_id = _next_unknown_id(profiles["unknown"])
    profiles["unknown"][new_id] = {
        "embedding": embedding.tolist(),
        "first_seen": str(np.datetime64("now")),
        "last_seen": str(np.datetime64("now")),
        "sample_count": 1,
    }
    _save_profiles(profiles)
    print(f"[VoiceID] New unknown voice stored: {new_id}")
    return {"status": "unknown", "name": f"Unknown-{new_id}", "confidence": 0.0}


def verify_speaker(name: str, audio_data, sample_rate: int = TARGET_RATE) -> dict:
    """Compare `audio_data` against one stored voice only (no side effects).

    Returns {"status": "match"|"no_match"|"missing"|"unavailable"|"error",
             "name": str, "confidence": float}
    """
    if not is_available():
        return {"status": "unavailable", "name": name, "confidence": 0.0}

    profiles = _load_profiles()
    data = profiles["known"].get(name)
    if not data or not data.get("embedding"):
        return {"status": "missing", "name": name, "confidence": 0.0}

    try:
        embedding = _extract_embedding(audio_data, sample_rate)
    except Exception as e:
        print(f"[VoiceID] Verification failed: {e}")
        return {"status": "error", "name": name, "confidence": 0.0}

    stored = np.asarray(data["embedding"], dtype=np.float64)
    query = np.asarray(embedding, dtype=np.float64)
    if stored.shape != query.shape:
        print(f"[VoiceID] Stored print for '{name}' is {stored.shape[0]}-d but the "
              f"current backend produces {query.shape[0]}-d — re-enrol to fix it.")
        return {"status": "missing", "name": name, "confidence": 0.0}
    score = _cosine_similarity(query, stored)
    status = "match" if score >= _threshold() else "no_match"
    return {"status": status, "name": name, "confidence": score}


def register_speaker(name: str, audio_data, sample_rate: int = TARGET_RATE) -> bool:
    """Register (or refine) a known speaker from a clip of their voice."""
    if not is_available():
        _warn_unavailable_once()
        return False

    try:
        embedding = _extract_embedding(audio_data, sample_rate)
    except Exception as e:
        print(f"[VoiceID] Registration failed: {e}")
        return False

    wav = _to_mono_float(audio_data, sample_rate)
    frac = _speech_fraction(wav)
    if frac < MIN_SPEECH_FRACTION:
        print(f"[VoiceID] Not enough speech to enrol (only {frac * 100:.0f}% "
              f"voiced) — speak longer, closer to the mic.")
        return False

    profiles = _load_profiles()
    existing = profiles["known"].get(name)

    if existing and existing.get("embedding"):
        old = np.asarray(existing["embedding"], dtype=np.float64)
        if old.shape == embedding.shape:
            # Running average keeps the voiceprint stable as more samples arrive.
            n = existing.get("sample_count", 1)
            merged = (old * n + embedding) / (n + 1)
            existing["embedding"] = merged.tolist()
            existing["sample_count"] = n + 1
        else:
            # A print from a different backend cannot be averaged with this one,
            # so replace it instead of raising on the shape mismatch.
            print(f"[VoiceID] Existing print for '{name}' was {old.shape[0]}-d but "
                  f"the current backend produces {embedding.shape[0]}-d — replacing it.")
            existing["embedding"] = embedding.tolist()
            existing["sample_count"] = 1
        existing["updated_at"] = str(np.datetime64("now"))
    else:
        profiles["known"][name] = {
            "embedding": embedding.tolist(),
            "registered_at": str(np.datetime64("now")),
            "sample_count": 1,
        }

    _save_profiles(profiles)
    print(f"[VoiceID] Registered: {name}")
    return True


def assign_name_to_unknown(unknown_id: str, name: str) -> bool:
    """Give a name to a previously stored unknown voice."""
    profiles = _load_profiles()
    key = unknown_id.replace("Unknown-", "").strip()
    if key not in profiles["unknown"]:
        return False
    data = profiles["unknown"].pop(key)
    data["name"] = name
    data["assigned_at"] = str(np.datetime64("now"))
    profiles["known"][name] = data
    _save_profiles(profiles)
    print(f"[VoiceID] {key} is now {name}")
    return True


def list_speakers() -> dict:
    profiles = _load_profiles()
    return {
        "known": list(profiles["known"].keys()),
        "unknown": list(profiles["unknown"].keys()),
        "backend": backend(),
    }


def get_speaker_info(name: str) -> dict | None:
    profiles = _load_profiles()
    if name in profiles["known"]:
        data = dict(profiles["known"][name])
        data.pop("embedding", None)
        return data
    return None
