# Privacy/minimization helpers (H5)
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PRIVACY = BASE_DIR / "config" / "privacy.json"


def _load():
    try:
        if PRIVACY.exists():
            return json.loads(PRIVACY.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"store_raw_audio": False, "store_transcripts": True, "require_consent_for_recording": True}


def allow_raw_audio() -> bool:
    return bool(_load().get("store_raw_audio", False))


def store_transcripts() -> bool:
    return bool(_load().get("store_transcripts", True))
