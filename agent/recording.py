# Recording consent + indicator (H3)
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CONSENT_FILE = BASE_DIR / "config" / "recording_consent.json"
CONSENT_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict[str, Any]:
    try:
        if CONSENT_FILE.exists():
            return json.loads(CONSENT_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"consented": False, "set_at": None}


def _save(data: dict[str, Any]) -> None:
    try:
        tmp = CONSENT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, CONSENT_FILE)
    except Exception:
        pass


def get_consent() -> dict[str, Any]:
    return _load()


def grant_consent() -> dict[str, Any]:
    from datetime import datetime

    data = {"consented": True, "set_at": datetime.now().isoformat()}
    _save(data)
    try:
        from agent import audit

        audit.record("recording_consent_granted", enabled=True)
    except Exception:
        pass
    return data


def revoke_consent() -> dict[str, Any]:
    from datetime import datetime

    data = {"consented": False, "set_at": datetime.now().isoformat()}
    _save(data)
    try:
        from agent import audit

        audit.record("recording_consent_revoked", enabled=False)
    except Exception:
        pass
    return data


def require_consent() -> bool:
    return bool(_load().get("consented"))


def indicator() -> dict[str, Any]:
    return {"consented": require_consent(), "visible": True}
