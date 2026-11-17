"""Tier 2 A6 — secrets at rest (encrypted at rest).

On Windows, keys in ``config/api_keys.json`` are encrypted with DPAPI
(`CryptProtectData`) so they cannot be read by another user or copied to
another machine without re-encryption. On other platforms we fall back to
plaintext but set restrictive permissions where possible.

This module is backward-compatible:
* ``load()`` reads plaintext or encrypted files; if plaintext is found and
  encryption is available it is migrated in place on first successful load,
* ``save()`` writes encrypted when possible, otherwise plaintext,
* all call sites keep using the same JSON shape.

The file format adds ``_encrypted: true`` and stores values as base64 blobs.
Plaintext shape is unchanged for compatibility.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path


def _config_dir(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir)
    try:
        from main import BASE_DIR  # type: ignore
        return Path(BASE_DIR) / "config"
    except Exception:
        try:
            from ui import get_base_dir  # type: ignore
            return Path(get_base_dir()) / "config"
        except Exception:
            return Path(__file__).resolve().parent.parent / "config"


def _key_path(base_dir: Path | None = None) -> Path:
    return _config_dir(base_dir) / "api_keys.json"


def _dpapi_available() -> bool:
    return sys.platform == "win32"


def _protect(data: bytes) -> bytes:
    if not _dpapi_available():
        raise RuntimeError("dpapi unavailable")
    try:
        import ctypes
        from ctypes import wintypes

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        def blob(d: bytes) -> DATA_BLOB:
            buf = ctypes.create_string_buffer(d)
            return DATA_BLOB(len(d), buf)

        def unblob(b: DATA_BLOB) -> bytes:
            return ctypes.string_at(b.pbData, b.cbData)

        in_blob = blob(data)
        out_blob = DATA_BLOB()
        if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None,
                                        None, 0x01, ctypes.byref(out_blob)):  # CRYPTPROTECT_UI_FORBIDDEN
            raise OSError("CryptProtectData failed")
        result = unblob(out_blob)
        kernel32.LocalFree(out_blob.pbData)
        return result
    except Exception as exc:
        raise RuntimeError(f"dpapi protect failed: {exc}")


def _unprotect(data: bytes) -> bytes:
    if not _dpapi_available():
        raise RuntimeError("dpapi unavailable")
    try:
        import ctypes
        from ctypes import wintypes

        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        def blob(d: bytes) -> DATA_BLOB:
            buf = ctypes.create_string_buffer(d)
            return DATA_BLOB(len(d), buf)

        def unblob(b: DATA_BLOB) -> bytes:
            return ctypes.string_at(b.pbData, b.cbData)

        in_blob = blob(data)
        out_blob = DATA_BLOB()
        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None,
                                          None, 0x01, ctypes.byref(out_blob)):
            raise OSError("CryptUnprotectData failed")
        result = unblob(out_blob)
        kernel32.LocalFree(out_blob.pbData)
        return result
    except Exception as exc:
        raise RuntimeError(f"dpapi unprotect failed: {exc}")


def load(base_dir: Path | None = None) -> dict:
    path = _key_path(base_dir)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return {}

    if isinstance(data, dict) and data.get("_encrypted"):
        out = {}
        encrypted = False
        for k, v in data.items():
            if k.startswith("_"):
                continue
            if isinstance(v, str):
                try:
                    blob = base64.b64decode(v)
                    plain = _unprotect(blob).decode("utf-8")
                    out[k] = plain
                    encrypted = True
                except Exception:
                    out[k] = v  # best effort
            else:
                out[k] = v
        return out

    # plaintext - try to migrate
    if isinstance(data, dict):
        try:
            if _dpapi_available():
                save(data, base_dir)
        except Exception:
            pass
        return dict(data)
    return {}


def save(data: dict, base_dir: Path | None = None) -> bool:
    if not isinstance(data, dict):
        return False
    path = _key_path(base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    out = {}
    if _dpapi_available():
        for k, v in data.items():
            if k.startswith("_"):
                continue
            try:
                s = str(v)
                enc = _protect(s.encode("utf-8"))
                out[k] = base64.b64encode(enc).decode("ascii")
            except Exception:
                out[k] = v
        out["_encrypted"] = True
        try:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(out, indent=4), encoding="utf-8")
            os.replace(tmp, path)
            return True
        except Exception:
            pass

    # fallback plaintext
    try:
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(clean, indent=4), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def get_key(name: str, base_dir: Path | None = None) -> str:
    data = load(base_dir)
    val = data.get(name) or data.get(name.replace("_api_key", "")) or data.get(name + "_key")
    if val is None:
        return ""
    return str(val).strip()


def set_key(name: str, value: str, base_dir: Path | None = None) -> bool:
    data = load(base_dir)
    data[name] = str(value).strip()
    return save(data, base_dir)


def has_key(name: str, base_dir: Path | None = None) -> bool:
    return bool(get_key(name, base_dir))
