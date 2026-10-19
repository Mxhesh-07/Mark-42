"""Crash bundles (Tier 2 C6).

When the process dies the useful question is not "what was the traceback" — it
is "what was it doing, and can I send this to someone without leaking my keys?".
A crash bundle answers both: a JSON file with the traceback, the recent log
tail, the version and the health snapshot, with secrets and personal data
redacted on the way out.

Nothing here ever keeps a raw key: ``redact()`` runs over every string that
goes into the file, so a bundle is safe to attach to a bug report.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
import uuid
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CRASH_DIR = BASE_DIR / "memory" / "crashes"
KEEP = 20   # bundles to retain

MAX_TAIL_LINES = 200
MAX_TEXT = 8000

# --- redaction ----------------------------------------------------------------

_KEY_PATTERNS = (
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),                 # Google API key
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),                  # OpenAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),              # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),           # Slack
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # JWT
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)\b(api[_\- ]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*"
               r"[\"']?([^\s\"',}]{6,})[\"']?"),
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_WINDOWS_USER = re.compile(r"(?i)\b[Cc]:\\Users\\[^\\\s\"']+")
_POSIX_HOME = re.compile(r"/(?:home|Users)/[^/\s\"']+")
_PHONE = re.compile(r"\b(?:\+?\d[\s-]?){10,}\b")


def _redact_str(text: str) -> str:
    out = text
    for pattern in _KEY_PATTERNS:
        if pattern.groups >= 2:
            out = pattern.sub(lambda m: f"{m.group(1)}=<redacted>", out)
        elif pattern.groups == 1:
            out = pattern.sub(lambda m: f"{m.group(1)} <redacted>", out)
        else:
            out = pattern.sub("<redacted-key>", out)
    out = _EMAIL.sub("<email>", out)
    out = _WINDOWS_USER.sub(r"<home>", out)
    out = _POSIX_HOME.sub("<home>", out)
    out = _PHONE.sub("<number>", out)
    return out


def redact(value):
    """Recursively redact a JSON-safe value."""
    if isinstance(value, str):
        return _redact_str(value)
    if isinstance(value, dict):
        return {redact(k): redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


# --- capture ------------------------------------------------------------------

def _version() -> str:
    for candidate in ("VERSION", "version.txt"):
        path = BASE_DIR / candidate
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return "unknown"


def recent_logs(lines: int = MAX_TAIL_LINES) -> list[str]:
    """The tail of the structured log, redacted."""
    try:
        from agent import log

        log_path = log.json_log_path()
        if log_path and Path(log_path).exists():
            content = Path(log_path).read_text(encoding="utf-8", errors="replace")
            return [line for line in content.splitlines()[-lines:]]
    except Exception:
        pass
    return []


def _health() -> dict:
    try:
        from agent import health

        return health.status()
    except Exception as e:
        return {"error": str(e)}


def capture(exc: BaseException | None = None, *, extra: dict | None = None,
            include_health: bool = True) -> Path:
    """Write one crash bundle and return its path."""
    if exc is None:
        exc = sys.exc_info()[1]

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else "no exception"
    bundle = {
        "created_at": time.time(),
        "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "version": _version(),
        "exception": redact(tb)[:MAX_TEXT],
        "recent_logs": redact(recent_logs()),
    }
    if extra:
        bundle["extra"] = redact(extra)
    if include_health:
        bundle["health"] = redact(_health())

    CRASH_DIR.mkdir(parents=True, exist_ok=True)
    name = (f"crash-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-"
            f"{uuid.uuid4().hex[:6]}.json")
    path = CRASH_DIR / name
    path.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
    _prune()
    _notify(path, exc)
    return path


def _prune() -> None:
    try:
        bundles = sorted(CRASH_DIR.glob("crash-*.json"), key=lambda p: p.stat().st_mtime)
        for old in bundles[:-KEEP]:
            old.unlink(missing_ok=True)
    except Exception:
        pass


def _notify(path: Path, exc) -> None:
    try:
        from agent import audit

        audit.record("crash", outcome="captured",
                     detail=redact(str(exc))[:400] if exc else "captured",
                     parameters={"bundle": path.name})
    except Exception:
        pass


def install() -> None:
    """Route uncaught exceptions in the main thread through ``capture``."""
    previous = sys.excepthook

    def _hook(exc_type, exc, tb):
        try:
            capture(exc)
        finally:
            previous(exc_type, exc, tb)

    sys.excepthook = _hook


def list_crashes() -> list[dict]:
    out = []
    for path in sorted(CRASH_DIR.glob("crash-*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        out.append({"file": path.name, "created_iso": data.get("created_iso"),
                    "exception": (data.get("exception") or "").splitlines()[-1:]})
    return out


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "list":
        for item in list_crashes():
            print(f"{item['created_iso']}  {item['file']}  {''.join(item['exception'])}")
        return 0
    if argv and argv[0] == "test":
        try:
            raise RuntimeError("crash bundle self-test")
        except RuntimeError as e:
            path = capture(e)
        print(f"wrote {path}")
        return 0
    print("usage: python -m agent.crash list|test")
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
