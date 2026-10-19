"""Crash bundles (Tier 2 C6).

When the process dies the useful question is not "what was the traceback" — it
is "what was it doing, and can I send this to someone without leaking my keys?".
A crash bundle answers both: a JSON file with the traceback, the recent log
tail, the version and the health snapshot, with secrets and personal data
redacted on the way out.

Nothing here ever keeps a raw key: ``redact()`` runs over every string that
goes into the file, so a bundle is safe to attach to a bug report. The redactor
itself is `agent/redact.py`, which is also applied to text on its way out to a
model; crash.py keeps this name because the capture path has always used it.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

from agent.redact import redact      # the one redactor (see agent/redact.py)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CRASH_DIR = BASE_DIR / "memory" / "crashes"
KEEP = 20   # bundles to retain

MAX_TAIL_LINES = 200
MAX_TEXT = 8000

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
