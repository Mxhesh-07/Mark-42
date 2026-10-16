"""
J.A.R.V.I.S. — Speaker Identification Module
Uses SpeechBrain ECAPA-TDNN for voice embeddings.
Recognizes known users and remembers unknown speakers.
"""

import json
import importlib.util
import numpy as np
from pathlib import Path
from threading import Lock

BASE_DIR = Path(__file__).resolve().parent
PROFILES_PATH = BASE_DIR / "voice_profiles.json"
SIMILARITY_THRESHOLD = 0.70

_lock = Lock()

# ── Backend availability (detected once) ──────────────────────────────────
# Speaker ID needs speechbrain + torch. When they are missing we must fail
# fast and silently — not import torch or print on every audio chunk.
_AVAILABLE: bool | None = None
_AVAILABILITY_ERROR = ""
_warned = False


def is_available() -> bool:
    """True if the embedding backend (speechbrain + torch) is importable."""
    global _AVAILABLE, _AVAILABILITY_ERROR
    if _AVAILABLE is None:
        missing = [
            mod
            for mod in ("speechbrain", "torch")
            if importlib.util.find_spec(mod) is None
        ]
        _AVAILABLE = not missing
        if missing:
            _AVAILABILITY_ERROR = (
                "missing dependency: " + ", ".join(missing)
                + " (pip install speechbrain torch)"
            )
    return _AVAILABLE


def _warn_unavailable_once() -> None:
    global _warned
    if not _warned:
        _warned = True
        print(
            f"[VoiceID] Speaker ID disabled — {_AVAILABILITY_ERROR}. "
            "Install with: pip install speechbrain torch"
        )


def _load_profiles() -> dict:
    if not PROFILES_PATH.exists():
        return {"known": {}, "unknown": {}}
    try:
        with open(PROFILES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"known": {}, "unknown": {}}


def _save_profiles(profiles: dict) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with open(PROFILES_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2)


def _get_embedder():
    from speechbrain.inference import SpeakerRecognition
    return SpeakerRecognition.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="pretrained_models/spkrec-ecapa-voxceleb",
    )


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


def _extract_embedding(audio_data: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    if not is_available():
        raise RuntimeError(_AVAILABILITY_ERROR or "speaker backend unavailable")
    import torch
    embedder = _get_embedder()
    waveform = torch.tensor(audio_data, dtype=torch.float32).unsqueeze(0)
    embedding = embedder.encode_batch(waveform)
    return embedding.squeeze().numpy()


def identify_speaker(audio_data: np.ndarray, sample_rate: int = 16000) -> dict:
    """
    Identify speaker from audio data.
    Returns: {"status": "known"|"unknown"|"error", "name": str, "confidence": float}
    """
    if not is_available():
        _warn_unavailable_once()
        return {"status": "unavailable", "name": "Unknown", "confidence": 0.0}

    try:
        embedding = _extract_embedding(audio_data, sample_rate)
    except Exception as e:
        print(f"[VoiceID] Embedding failed: {e}")
        return {"status": "error", "name": "Unknown", "confidence": 0.0}

    profiles = _load_profiles()

    best_match = None
    best_score = 0.0

    for name, data in profiles["known"].items():
        stored_embedding = np.array(data["embedding"])
        score = _cosine_similarity(embedding, stored_embedding)
        if score > best_score:
            best_score = score
            best_match = name

    if best_match and best_score >= SIMILARITY_THRESHOLD:
        print(f"[VoiceID] Recognized: {best_match} ({best_score:.2f})")
        return {"status": "known", "name": best_match, "confidence": best_score}

    for uid, data in profiles["unknown"].items():
        stored_embedding = np.array(data["embedding"])
        score = _cosine_similarity(embedding, stored_embedding)
        if score > best_score:
            best_score = score
            best_match = uid

    if best_match and best_score >= SIMILARITY_THRESHOLD:
        print(f"[VoiceID] Unknown speaker recognized (ID: {best_match}, {best_score:.2f})")
        return {"status": "unknown", "name": f"Unknown-{best_match}", "confidence": best_score}

    new_id = f"UNK-{len(profiles['unknown']) + 1:03d}"
    profiles["unknown"][new_id] = {
        "embedding": embedding.tolist(),
        "first_seen": str(np.datetime64("now")),
        "last_seen": str(np.datetime64("now")),
        "sample_count": 1,
    }
    _save_profiles(profiles)
    print(f"[VoiceID] New unknown speaker saved: {new_id}")
    return {"status": "unknown", "name": f"Unknown-{new_id}", "confidence": 0.0}


def register_speaker(name: str, audio_data: np.ndarray, sample_rate: int = 16000) -> bool:
    """Register a known speaker with their name."""
    if not is_available():
        _warn_unavailable_once()
        return False

    try:
        embedding = _extract_embedding(audio_data, sample_rate)
    except Exception as e:
        print(f"[VoiceID] Registration failed: {e}")
        return False

    profiles = _load_profiles()

    if name in profiles["known"]:
        old = np.array(profiles["known"][name]["embedding"])
        new = (old + embedding) / 2
        profiles["known"][name]["embedding"] = new.tolist()
        profiles["known"][name]["sample_count"] = profiles["known"][name].get("sample_count", 1) + 1
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
    """Give a name to a previously unknown speaker."""
    profiles = _load_profiles()

    if unknown_id not in profiles["unknown"]:
        return False

    data = profiles["unknown"].pop(unknown_id)
    data["name"] = name
    data["assigned_at"] = str(np.datetime64("now"))
    profiles["known"][name] = data
    _save_profiles(profiles)
    print(f"[VoiceID] {unknown_id} is now {name}")
    return True


def list_speakers() -> dict:
    profiles = _load_profiles()
    return {
        "known": list(profiles["known"].keys()),
        "unknown": list(profiles["unknown"].keys()),
    }


def get_speaker_info(name: str) -> dict | None:
    profiles = _load_profiles()
    if name in profiles["known"]:
        data = profiles["known"][name].copy()
        data.pop("embedding", None)
        return data
    return None
