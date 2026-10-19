"""Structured logging (upgrade list C1).

Everything in this project is `print()`ed, which means no levels, no timestamps,
no fields, and no way to correlate the lines belonging to one turn. This module
wires up the standard `logging` module with two handlers:

  * a **console** handler that prints just the message, so the on-screen output
    looks exactly as it did before; and
  * a **JSON-lines** file handler, so a bad turn can be grepped by turn id and
    by field instead of by eyeballing a wall of text.

Every record carries the current turn id. Call `configure()` once at startup and
`get_logger(__name__)` everywhere else::

    from agent import log
    log.configure(json_path=BASE_DIR / "logs" / "jarvis.jsonl")
    logger = log.get_logger(__name__)
    logger.info("[Executor] action done", extra={"fields": {"tool": tool}})

Use `set_turn()` at the start of a turn so every line it produces shares one id.
"""

import json
import logging
import sys
import threading
import time
import uuid
from pathlib import Path

_state = threading.local()
_configured = False

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


# --- turn correlation ---------------------------------------------------------
def new_turn_id() -> str:
    return uuid.uuid4().hex[:12]


def turn_id() -> str:
    """The id of the turn being logged, or '-' outside a turn."""
    return getattr(_state, "turn_id", "-")


def set_turn(tid: str | None = None) -> str:
    """Mark the start of a turn; every later record carries this id."""
    _state.turn_id = tid or new_turn_id()
    return _state.turn_id


def clear_turn() -> None:
    _state.turn_id = "-"


# --- formatters ---------------------------------------------------------------
class _TurnFilter(logging.Filter):
    """Attach the current turn id to any record that does not have one."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "turn_id"):
            record.turn_id = turn_id()
        return True


class _ConsoleFormatter(logging.Formatter):
    """Exactly the message - the console output must not change."""

    def format(self, record: logging.LogRecord) -> str:
        text = record.getMessage()
        if record.levelno >= logging.WARNING:
            return f"{record.levelname.title()}: {text}"
        return text


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(record.created, 3),
            "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "turn": getattr(record, "turn_id", "-"),
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for key, value in fields.items():
                payload.setdefault(str(key), value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        try:
            return json.dumps(payload, ensure_ascii=False, default=str)
        except Exception:  # pragma: no cover - a log line must never raise
            return json.dumps({"level": record.levelname, "msg": record.getMessage()})


# --- setup --------------------------------------------------------------------
def configure(*, level=logging.INFO, json_path=None, console: bool = True,
              force: bool = False) -> None:
    """Install the handlers once. Safe to call more than once."""
    global _configured
    if _configured and not force:
        return

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(_ConsoleFormatter())
        stream.addFilter(_TurnFilter())
        root.addHandler(stream)

    if json_path:
        path = Path(json_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            to_file = logging.FileHandler(path, encoding="utf-8")
        except Exception:
            to_file = None
        if to_file is not None:
            to_file.setFormatter(_JsonFormatter())
            to_file.addFilter(_TurnFilter())
            root.addHandler(to_file)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def configure_from_config(config: dict | None = None) -> None:
    """Configure from a `logging` block in config, e.g. {"level": "info"}."""
    block = (config or {}).get("logging") or {}
    level = _LEVELS.get(str(block.get("level", "info")).lower(), logging.INFO)
    json_path = block.get("json_path")
    configure(level=level, json_path=json_path or None)
