# OCR cache keyed on (window, content hash, TTL) - F3
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "memory" / "ocr_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TTL_SEC = 3600  # 1 hour default


def _key(window: str, content_hash: str) -> str:
    h = hashlib.sha256(f"{window}|{content_hash}".encode("utf-8")).hexdigest()
    return h


def _path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get(window: str, content_hash: str, ttl: int = TTL_SEC) -> dict[str, Any] | None:
    try:
        k = _key(window, content_hash)
        p = _path(k)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0))
        if time.time() - ts > float(ttl):
            try:
                p.unlink()
            except Exception:
                pass
            return None
        return data.get("result")
    except Exception:
        return None


def put(window: str, content_hash: str, result: dict[str, Any]) -> None:
    try:
        k = _key(window, content_hash)
        p = _path(k)
        data = {"ts": time.time(), "window": window, "content_hash": content_hash, "result": result}
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def clear_expired(ttl: int = TTL_SEC) -> int:
    n = 0
    try:
        now = time.time()
        for p in CACHE_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if now - float(data.get("ts", 0)) > float(ttl):
                    p.unlink()
                    n += 1
            except Exception:
                try:
                    p.unlink()
                    n += 1
                except Exception:
                    pass
    except Exception:
        pass
    return n
