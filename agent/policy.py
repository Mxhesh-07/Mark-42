"""
Permission boundary and kill switch for the agent.

The agent can chain up to several tool calls from a single request, and some of
those tools can do irreversible things (delete files, run shell commands, send
messages as the user). This module is the single place that decides whether a
tool call is allowed to run.

Three levels:

  allow    run it
  confirm  run it ONLY with explicit approval; otherwise refuse (fail-closed).
           When the agent is unattended there is nobody to approve, so the
           action is denied and written to the audit log.
  block    never run — not even with approval.

Policy lives in config/autonomy.json (created with sensible defaults on first
use). The kill switch is a sentinel file (memory/AUTONOMY_OFF) and/or an
in-process event, so an in-flight agent can be stopped immediately.
"""

import copy
import json
import sys
import threading
import time
from enum import Enum
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR    = get_base_dir()
POLICY_PATH = BASE_DIR / "config" / "autonomy.json"
KILL_FILE   = BASE_DIR / "memory" / "AUTONOMY_OFF"


class Level(Enum):
    ALLOW   = "allow"
    CONFIRM = "confirm"
    BLOCK   = "block"


class Decision:
    __slots__ = ("level", "reason")

    def __init__(self, level: Level, reason: str):
        self.level  = level
        self.reason = reason

    def __repr__(self) -> str:
        return f"Decision({self.level.value}, {self.reason!r})"


# Default policy — conservative. Anything not listed falls back to `confirm`.
DEFAULT_POLICY: dict = {
    "enabled": True,
    "default_level": "confirm",
    "limits": {
        "max_actions_per_task": 8,
        "max_minutes_per_task": 10,
        "max_tasks_per_hour": 20,
    },
    "tools": {
        # read-only / harmless
        "web_search":       "allow",
        "weather_report":   "allow",
        "youtube_video":    "allow",
        "spotify_control":  "allow",
        "reminder":         "allow",
        "flight_finder":    "allow",
        "open_app":         "allow",
        "browser_control":  "allow",
        # can change or expose the machine / reach other people
        "file_controller":  "confirm",
        "computer_settings": "confirm",
        "computer_control": "confirm",
        "desktop_control":  "confirm",
        "screen_process":   "confirm",
        "send_message":     "confirm",
        "cmd_control":      "confirm",
        "code_helper":      "confirm",
        "dev_agent":        "confirm",
        "generated_code":   "confirm",
    },
    # Per-action overrides win over the tool-level level.
    "actions": {
        "file_controller": {
            "read":       "allow",
            "list":       "allow",
            "find":       "allow",
            "disk_usage": "allow",
            "write":      "allow",
            "create_file": "allow",
            "copy":       "confirm",
            "move":       "confirm",
            "delete":     "confirm",
        },
        "computer_settings": {
            "shutdown": "block",
            "restart":  "block",
            "lock":     "confirm",
        },
    },
}

_lock         = threading.Lock()
_killed       = threading.Event()
_cache: dict | None = None
_cache_mtime: float = -1.0


# --- policy loading -----------------------------------------------------------

def _write_default() -> None:
    try:
        POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
        POLICY_PATH.write_text(
            json.dumps(DEFAULT_POLICY, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[Policy] 🆕 Wrote default policy to {POLICY_PATH.name}")
    except Exception as e:
        print(f"[Policy] ⚠️ Could not write default policy: {e}")


def load_policy() -> dict:
    """Read config/autonomy.json, creating it with defaults on first use."""
    global _cache, _cache_mtime
    try:
        mtime = POLICY_PATH.stat().st_mtime
    except OSError:
        _write_default()
        try:
            mtime = POLICY_PATH.stat().st_mtime
        except OSError:
            return copy.deepcopy(DEFAULT_POLICY)

    with _lock:
        if _cache is not None and mtime == _cache_mtime:
            return _cache
    try:
        data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("policy root must be an object")
    except Exception as e:
        print(f"[Policy] ⚠️ autonomy.json unreadable ({e}) — using safe defaults")
        data = copy.deepcopy(DEFAULT_POLICY)

    with _lock:
        _cache, _cache_mtime = data, mtime
    return data


def _level(value, fallback: Level = Level.CONFIRM) -> Level:
    try:
        return Level(str(value).strip().lower())
    except Exception:
        return fallback


# --- the gate -----------------------------------------------------------------

def evaluate(tool: str, parameters: dict | None = None) -> Decision:
    """Decide whether `tool` may run, given its parameters."""
    pol = load_policy()
    if not pol.get("enabled", True):
        return Decision(Level.ALLOW, "policy disabled")

    tool   = str(tool or "")
    params = parameters or {}
    action = str(params.get("action") or "").strip().lower()

    action_map = (pol.get("actions") or {}).get(tool) or {}
    if action and action in action_map:
        lvl = _level(action_map[action])
        return Decision(lvl, f"{tool}.{action} is '{lvl.value}' by policy")

    tools = pol.get("tools") or {}
    if tool in tools:
        lvl = _level(tools[tool])
        return Decision(lvl, f"{tool} is '{lvl.value}' by policy")

    lvl = _level(pol.get("default_level", "confirm"))
    return Decision(lvl, f"{tool} not listed → default '{lvl.value}'")


# --- kill switch --------------------------------------------------------------

def kill_requested() -> bool:
    """True if the kill switch is engaged (in-process flag or sentinel file)."""
    if _killed.is_set():
        return True
    try:
        return KILL_FILE.exists()
    except Exception:
        return False


def engage_kill_switch(reason: str = "manual") -> None:
    _killed.set()
    try:
        KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
        KILL_FILE.write_text(
            f"engaged {time.strftime('%Y-%m-%d %H:%M:%S')} ({reason})\n",
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[Policy] ⚠️ Could not write kill file: {e}")
    print(f"[Policy] 🛑 KILL SWITCH ENGAGED ({reason}) — agent runs will stop")


def disengage_kill_switch() -> None:
    _killed.clear()
    try:
        KILL_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    print("[Policy] ✅ Kill switch released")


# --- limits / status ----------------------------------------------------------

def limits() -> dict:
    d = dict(DEFAULT_POLICY["limits"])
    d.update(load_policy().get("limits") or {})
    return d


def status() -> dict:
    pol = load_policy()
    return {
        "enabled":        bool(pol.get("enabled", True)),
        "default_level":  pol.get("default_level", "confirm"),
        "kill_switch":    kill_requested(),
        "kill_file":      str(KILL_FILE),
        "policy_file":    str(POLICY_PATH),
        "limits":         limits(),
    }


# --- tiny CLI: python -m agent.policy [status|kill|resume] --------------------

def _cli(argv: list[str]) -> int:
    cmd = (argv[0] if argv else "status").lower()
    if cmd == "kill":
        engage_kill_switch("cli")
    elif cmd in ("resume", "release", "off"):
        disengage_kill_switch()
    elif cmd == "status":
        for k, v in status().items():
            print(f"  {k:15s} {v}")
    else:
        print("usage: python -m agent.policy [status|kill|resume]")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
