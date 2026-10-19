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
    """A gate decision.

    ``hard`` marks a safety invariant (kill switch, sandbox escape, refused
    command, denied egress, non-owner speaker) that can never be approved away.
    A soft decision comes from the policy table and expresses *autonomy* — what
    the assistant may do unattended — which an attended request may satisfy.
    """

    __slots__ = ("level", "reason", "hard")

    def __init__(self, level: Level, reason: str, hard: bool = False):
        self.level  = level
        self.reason = reason
        self.hard   = bool(hard)

    def __repr__(self) -> str:
        tag = " [hard]" if self.hard else ""
        return f"Decision({self.level.value}, {self.reason!r}{tag})"


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
    # A2: filesystem sandbox. Roots are resolved (symlinks and "..") before a
    # path is compared; "~" expands to the user's home directory.
    "sandbox": {
        "enabled": True,
        "roots": ["~"],
    },
    # A9: per-tool token buckets, enforced inside evaluate().
    "rate_limits": {
        "default": {"per_minute": 30, "burst": 12},
        "global":  {"per_minute": 120, "burst": 40},
        "tools":   {},
    },
    # A4: network egress control. Private/loopback destinations are refused by
    # default; add hosts to "allow" to reach them deliberately.
    "egress": {
        "enabled": True,
        "block_private": True,
        "allow": [],
        "deny": [],
        "log_allowed": True,
    },
    # A8: speaker authorisation. Enrollment is authorisation, so a recognised
    # voice is the owner unless the config maps it elsewhere. Set
    # enforce_on_unknown to true once your own voice is enrolled.
    "roles": {
        "enforce": True,
        "enforce_on_unknown": False,
        "default": "owner",
        "map": {"owner": [], "guest": []},
        "extra_tools": {"guest": [], "unknown": []},
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


# Tools whose parameters carry filesystem paths that must stay inside the roots.
_SANDBOX_TOOLS = frozenset({"file_controller"})

# Tools that can name a network destination (A4).
_EGRESS_TOOLS = frozenset({
    "browser_control", "web_search", "send_message", "flight_finder",
    "youtube_video", "dev_agent", "code_helper", "generated_code",
})

# Tools that change the world away from the machine: B2 stops these first when
# the system is degraded to READ_ONLY. `file_controller` is handled by action,
# because reads must keep working at READ_ONLY.
_WRITE_TOOLS = frozenset({
    "send_message", "cmd_control", "generated_code", "dev_agent",
    "code_helper", "computer_control", "desktop_control", "computer_settings",
})

_MUTATING_ACTIONS = frozenset({
    "write", "create", "create_file", "append", "save", "copy", "move",
    "rename", "delete", "mkdir", "mkdirs",
})


def is_write(tool: str, params: dict) -> bool:
    """Would this call change the world rather than observe it?

    Used by the degradation ladder and the self-model as well as the gate, so it
    is public.
    """
    if tool in _WRITE_TOOLS:
        return True
    if tool == "file_controller":
        return str((params or {}).get("action") or "").strip().lower() in _MUTATING_ACTIONS
    return False


def may_write(tool: str) -> bool:
    """True when this tool can change the world for *some* argument.

    ``is_write`` answers for one specific call; a capability report needs the
    general answer, because it has no arguments to look at.
    """
    name = str(tool)
    return name in _WRITE_TOOLS or name in _SANDBOX_TOOLS

_ORDER = {Level.ALLOW: 0, Level.CONFIRM: 1, Level.BLOCK: 2}


def _strictest(a: Decision, b: Decision) -> Decision:
    return a if _ORDER.get(a.level, 1) >= _ORDER.get(b.level, 1) else b


# --- the gate -----------------------------------------------------------------

def evaluate(tool: str, parameters: dict | None = None) -> Decision:
    """Decide whether `tool` may run, given its parameters."""
    pol = load_policy()
    if not pol.get("enabled", True):
        return Decision(Level.ALLOW, "policy disabled")

    tool   = str(tool or "")
    params = parameters or {}
    action = str(params.get("action") or "").strip().lower()
    if tool == "devices":
        # W4 spells the per-device capability "cmd" and wraps it in an action of
        # list/status/run, but the policy table is keyed by the capability itself
        # (notify, ring, sms, ...), so normalise it here rather than in callers.
        capability = str(params.get("cmd") or params.get("capability") or "").strip().lower()
        action = capability or action or "list"

    action_map = (pol.get("actions") or {}).get(tool) or {}
    if action and action in action_map:
        lvl = _level(action_map[action])
        base = Decision(lvl, f"{tool}.{action} is '{lvl.value}' by policy")
    elif tool in (pol.get("tools") or {}):
        lvl = _level(pol["tools"][tool])
        base = Decision(lvl, f"{tool} is '{lvl.value}' by policy")
    else:
        lvl = _level(pol.get("default_level", "confirm"))
        base = Decision(lvl, f"{tool} not listed → default '{lvl.value}'")

    decision = _guards(tool, params, base)
    _count(decision, tool)
    return decision


def _count(decision: Decision, tool: str) -> None:
    """Record the outcome for C2, never letting a metric break a decision."""
    try:
        from agent import metrics

        metrics.inc("policy.decision", level=decision.level.value)
        if decision.level is not Level.ALLOW:
            metrics.inc("policy.blocked", tool=tool)
    except Exception:
        pass


def evaluate_live(tool: str, parameters: dict | None = None) -> Decision:
    """Gate an *attended* call — the user is present and asked for it.

    The background agent is unattended, so a `confirm` there must be answered by
    an approver or it fails closed. In the live voice path there is no separate
    approval channel, and the spoken request *is* the authorisation, so a soft
    ``confirm`` — and a soft ``block`` from the policy *table* — is satisfied by
    attendance.

    Nothing that is a safety invariant is relaxed. A ``hard`` block — the kill
    switch, a refused shell command, a sandbox escape, a denied network
    destination, a rate-limit guard, or a non-owner speaker (A8 downgrades
    those to a hard block, never to ``confirm``) — is still refused, because it
    can never be approved away.
    """
    decision = evaluate(tool, parameters)
    if not decision.hard and decision.level in (Level.CONFIRM, Level.BLOCK):
        try:
            from agent import metrics

            metrics.inc("policy.attended", tool=tool)
        except Exception:
            pass
        return Decision(Level.ALLOW, f"{decision.reason} (attended request)")
    return decision


def _guards(tool: str, params: dict, base: Decision) -> Decision:
    """Apply the extra guards, so every caller inherits them (A2/A3/A4/A8/A9).

    Every BLOCK raised here is ``hard``: these are safety invariants, not
    autonomy preferences, so even an attended request cannot lift them.
    """
    # Kill switch - enforced here so even a caller that forgets to check it stops.
    if kill_requested():
        return Decision(Level.BLOCK, "kill switch engaged", hard=True)

    # B2 - degradation ladder: a degraded system stops the riskiest work first.
    # READ_ONLY is "observe only" (reads still pass, writes do not) and MONITOR
    # stops tools entirely. Both are hard: a system that believes it is broken
    # must not be talked past by an attended request.
    from agent import degrade
    current_mode = degrade.level()
    if current_mode == "MONITOR":
        return Decision(Level.BLOCK, "degraded to MONITOR: tools are stopped",
                        hard=True)
    if current_mode == "READ_ONLY" and is_write(tool, params):
        return Decision(Level.BLOCK, "degraded to READ_ONLY: writes are stopped",
                        hard=True)

    # A2 - filesystem sandbox: deny outright; this never reaches the model.
    if tool in _SANDBOX_TOOLS:
        from agent import sandbox
        for path in sandbox.paths_in(params):
            ok, why = sandbox.check(path)
            if not ok:
                return Decision(Level.BLOCK, f"path sandbox blocked {path!r}: {why}",
                                hard=True)

    # A3 - shell command analysis: read-only runs, destructive is refused.
    if tool == "cmd_control" and base.level is not Level.BLOCK:
        from agent import command_policy
        cmd = str(params.get("command") or params.get("cmd") or "")
        category, why = command_policy.classify(cmd)
        if category == command_policy.CATEGORY_BLOCK:
            return Decision(Level.BLOCK, f"shell command blocked: {why}", hard=True)
        if category == command_policy.CATEGORY_ALLOW:
            base = Decision(Level.ALLOW, f"shell command allowed: {why}")
        else:
            base = Decision(Level.CONFIRM, f"shell command needs confirmation: {why}")

    # A4 - network egress: refuse denied or private destinations outright.
    if tool in _EGRESS_TOOLS:
        from agent import egress
        ok, why = egress.guard(tool, params)
        if not ok:
            return Decision(Level.BLOCK, f"egress blocked: {why}", hard=True)

    # W4 - two device rules cannot be configured away, so they are enforced here
    # rather than trusted to the table: a capability that reaches other people can
    # never be silent, and the shell capability can never be enabled.
    if tool == "devices" and base.level is not Level.BLOCK:
        from agent import devices
        capability = devices.canonical(params.get("cmd") or params.get("capability"))
        if capability in devices.ALWAYS_BLOCKED:
            return Decision(Level.BLOCK,
                            f"the {capability!r} device capability is always blocked",
                            hard=True)
        if capability in devices.OTHER_PEOPLE and base.level is Level.ALLOW:
            base = Decision(Level.CONFIRM,
                            f"{capability!r} reaches other people: it can never be silent")

    # A9 - per-tool rate limits, enforced centrally so no caller can skip them.
    from agent import ratelimit
    allowed, why = ratelimit.check(tool)
    if not allowed:
        return Decision(Level.BLOCK, why, hard=True)

    # A8 - speaker authorisation: a guest can never approve anything, so only
    # read-only actions survive for a non-owner.
    from agent import roles
    base = roles.cap(tool, params, base)

    # W6 - a narrow, user-authored approval rule turns this exact CONFIRM into an
    # ALLOW. Three things keep that from being a hole: it runs *after* every hard
    # guard above (a rule can never lift a kill switch, a sandbox escape or a
    # refused command), it only applies to the owner, and the rule itself is
    # bound to one tool + action + resolved target.
    if base.level is Level.CONFIRM and roles.current() == roles.OWNER:
        try:
            from agent import approval_rules

            if approval_rules.matches(tool, params) is not None:
                base = Decision(Level.ALLOW, "approved once by a saved narrow rule")
        except Exception:
            pass

    return base


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
    out = {
        "enabled":        bool(pol.get("enabled", True)),
        "default_level":  pol.get("default_level", "confirm"),
        "kill_switch":    kill_requested(),
        "kill_file":      str(KILL_FILE),
        "policy_file":    str(POLICY_PATH),
        "limits":         limits(),
    }
    from agent import egress, roles
    out["egress"] = egress.status()
    out["roles"] = roles.status()
    return out


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
