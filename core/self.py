"""JARVIS's model of itself (Tier 4 W3).

Memory stores facts about the *user*. Nothing stored facts about JARVIS: which
capabilities actually work right now, how good it is in each domain, or a stable
identity that survives a restart. This module is that model, and it is what
makes continuity read as a self rather than a fresh process each run.

Two kinds of state live here, and the difference matters:

    identity     written **once**, then read-only. A system that rewrites "who
                 it is" every run has no continuity, so this block is never
                 auto-mutated. To change it, edit ``memory/self.json`` by hand.
    confidence   a per-domain exponential moving average fed from real
                 outcomes. It is the honest answer to "how good are you at
                 this?" and it is what ``judgement`` reads before it has an
                 opinion.

Everything is best-effort and stdlib-only: an unreadable file degrades to
defaults and the assistant keeps working.
"""

from __future__ import annotations

import copy
import json
import sys
import threading
import time
from pathlib import Path
from typing import Callable

DOMAINS = ("voice", "vision", "files", "browser", "code", "comms", "devices",
           "memory")
ALPHA = 0.1
DEFAULT_CONFIDENCE = 0.5
PROBE_TTL_S = 60.0
MAX_SNAPSHOT_LINES = 15


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
STATE_PATH = BASE_DIR / "memory" / "self.json"

# The identity block is created from these defaults the first time the model is
# used, then frozen. Nothing here is personal data.
_DEFAULT_IDENTITY = {
    "name": "JARVIS",
    "persona": ("A warm, quick-witted companion — capable, calm, and honest "
                "about its own limits."),
    "origin": "A desktop companion built for one user, living on their machine.",
    "limits": [
        "shell commands are classified; destructive ones are refused",
        "file access is confined to the sandbox roots",
        "no smart-home hardware is wired up yet",
    ],
}

# Which domain an outcome belongs to. Tools not listed here record nothing, so
# an unknown tool can never pollute a confidence score.
_TOOL_DOMAIN = {
    "web_search": "browser",
    "browser_control": "browser",
    "youtube_video": "browser",
    "flight_finder": "browser",
    "weather_report": "browser",
    "screen_process": "vision",
    "get_open_windows": "vision",
    "desktop_control": "vision",
    "computer_control": "vision",
    "file_controller": "files",
    "cmd_control": "code",
    "code_helper": "code",
    "dev_agent": "code",
    "generated_code": "code",
    "send_message": "comms",
    "reminder": "memory",
    "devices": "devices",
}

_lock = threading.RLock()
_provider: str | None = None
_quota: dict | None = None
_PROBES: dict[str, Callable[[], bool]] = {}
_PROBE_CACHE: dict[str, tuple[float, bool]] = {}


# --- storage ------------------------------------------------------------------

def _load() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(doc: dict) -> None:
    try:
        from agent import atomic

        atomic.write_json(STATE_PATH, doc)
    except Exception:
        pass


# --- identity (write once) ----------------------------------------------------

def identity() -> dict:
    """The stable identity block, creating it on first use and never rewriting."""
    with _lock:
        doc = _load()
        ident = doc.get("identity")
        if isinstance(ident, dict) and ident.get("name"):
            return copy.deepcopy(ident)
        doc["identity"] = copy.deepcopy(_DEFAULT_IDENTITY)
        doc.setdefault("confidence", {})
        doc["updated_at"] = time.time()
        _save(doc)
        return copy.deepcopy(doc["identity"])


# --- confidence (per-domain EMA) ---------------------------------------------

def confidence(domain: str) -> float:
    try:
        value = (_load().get("confidence") or {}).get(str(domain))
        return float(value) if value is not None else DEFAULT_CONFIDENCE
    except Exception:
        return DEFAULT_CONFIDENCE


def record_outcome(domain: str, ok: bool) -> float:
    """Fold one real outcome into a domain's confidence. Returns the new value."""
    name = str(domain or "").strip().lower()
    if not name:
        return DEFAULT_CONFIDENCE
    with _lock:
        doc = _load()
        conf = doc.setdefault("confidence", {})
        previous = float(conf.get(name, DEFAULT_CONFIDENCE))
        updated = previous + ALPHA * ((1.0 if ok else 0.0) - previous)
        conf[name] = round(updated, 4)
        counts = doc.setdefault("outcomes", {}).setdefault(name, {"ok": 0, "fail": 0})
        counts["ok" if ok else "fail"] = int(counts.get("ok" if ok else "fail", 0)) + 1
        doc.setdefault("identity", copy.deepcopy(_DEFAULT_IDENTITY))
        doc["updated_at"] = time.time()
        _save(doc)
        return conf[name]


def domain_for(tool: str) -> str | None:
    return _TOOL_DOMAIN.get(str(tool or "").strip())


# --- capabilities (lazy, probed) ---------------------------------------------

def register_probe(tool: str, check: Callable[[], bool]) -> None:
    """Attach a health probe to a tool (used by adapters and by the tests)."""
    _PROBES[str(tool)] = check
    _PROBE_CACHE.pop(str(tool), None)


def _declared_tools() -> list[str]:
    try:
        from agent import policy

        tools = policy.load_policy().get("tools")
        if isinstance(tools, dict) and tools:
            return sorted(tools.keys())
    except Exception:
        pass
    return sorted(_TOOL_DOMAIN.keys())


def _unavailable_by_policy() -> set[str]:
    try:
        from agent import policy

        pol = policy.load_policy()
        if pol.get("enabled") is False:
            return set()
        table = pol.get("tools") or {}
        return {name for name, level in table.items() if level == "block"}
    except Exception:
        return set()


def _probe_health(name: str, *, refresh: bool) -> bool:
    probe = _PROBES.get(name)
    if probe is None:
        return True
    now = time.monotonic()
    cached = _PROBE_CACHE.get(name)
    if not refresh and cached is not None and (now - cached[0]) < PROBE_TTL_S:
        return cached[1]
    try:
        healthy = bool(probe())
    except Exception:
        healthy = False
    _PROBE_CACHE[name] = (now, healthy)
    return healthy


def capabilities(tools=None, *, refresh: bool = False) -> dict:
    """tool -> healthy right now (policy-blocked, degraded and probed away)."""
    names = list(tools) if tools is not None else _declared_tools()
    blocked = _unavailable_by_policy()
    monitor = False
    read_only = False
    try:
        from agent import degrade

        level = degrade.level()
        monitor = level == "MONITOR"
        read_only = level == "READ_ONLY"
    except Exception:
        pass

    result: dict[str, bool] = {}
    for name in names:
        healthy = not monitor and name not in blocked
        if healthy and read_only:
            try:
                from agent import policy

                healthy = not policy.may_write(name)
            except Exception:
                pass
        if healthy:
            healthy = _probe_health(name, refresh=refresh)
        result[name] = bool(healthy)
    return result


# --- live state ---------------------------------------------------------------

def note_provider(name: str | None) -> None:
    """Record which provider answered last, for an honest self-report."""
    global _provider
    _provider = str(name) if name else None


def note_quota(remaining: int | None, limit: int | None = None) -> None:
    global _quota
    if remaining is None:
        _quota = None
        return
    _quota = {"remaining": int(remaining),
              "limit": int(limit) if limit is not None else None}


def state() -> dict:
    out: dict = {"mode": "FULL", "provider": _provider, "degraded": False,
                 "quota": _quota, "kill_switch": False}
    try:
        from agent import degrade, policy

        out["mode"] = degrade.level()
        out["degraded"] = out["mode"] != "FULL"
        out["kill_switch"] = policy.kill_requested()
    except Exception:
        pass
    return out


# --- views --------------------------------------------------------------------

def snapshot() -> dict:
    return {
        "identity": identity(),
        "state": state(),
        "confidence": {d: round(confidence(d), 2) for d in DOMAINS},
        "capabilities": capabilities(),
    }


def render() -> str:
    """A compact self-report safe to inject into the prompt (<= ~15 lines)."""
    snap = snapshot()
    st = snap["state"]
    conf = snap["confidence"]
    strongest = sorted(conf.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    weakest = sorted(conf.items(), key=lambda kv: (kv[1], kv[0]))[:3]
    unhealthy = [name for name, ok in snap["capabilities"].items() if not ok]

    quota = st.get("quota")
    if isinstance(quota, dict) and quota.get("limit"):
        quota_txt = f"{quota['remaining']}/{quota['limit']}"
    elif isinstance(quota, dict):
        quota_txt = str(quota.get("remaining"))
    else:
        quota_txt = "unknown"

    lines = [
        "[SELF]",
        f"name: {snap['identity'].get('name', 'JARVIS')}",
        (f"mode: {st['mode']} | provider: {st.get('provider') or 'unknown'} | "
         f"degraded: {'yes' if st['degraded'] else 'no'} | quota: {quota_txt}"),
        "confidence strongest: " + "  ".join(f"{k} {v:.2f}" for k, v in strongest),
        "confidence weakest:   " + "  ".join(f"{k} {v:.2f}" for k, v in weakest),
    ]
    if unhealthy:
        lines.append("unavailable right now: " + ", ".join(unhealthy[:8]))
    lines.append("limits:")
    for limit in snap["identity"].get("limits", [])[:3]:
        lines.append(f"- {limit}")
    return "\n".join(lines[:MAX_SNAPSHOT_LINES])


def prompt_block() -> str:
    """The self-report plus the one instruction that makes it useful."""
    return (render() + "\n"
            "Report this state honestly: name a blocked capability and its "
            "policy, and say so before attempting a task in a weak domain.")


# --- test helpers -------------------------------------------------------------

def reset_for_tests() -> None:
    global _provider, _quota
    with _lock:
        _provider = None
        _quota = None
        _PROBES.clear()
        _PROBE_CACHE.clear()
