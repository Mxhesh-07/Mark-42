"""Voice-authorization roles (A8).

`voice_id.py` can already tell who is speaking. Until now that identity changed
nothing: anyone in the room could drive the assistant, and an enrolled
voiceprint was only a label. This module turns the label into authority.

Three roles:

    owner    full policy - the machine's owner, as before
    guest    read-only actions only; can never approve anything
    unknown  an unenrolled voice; read-only only when enforcement is opted in

Enrollment *is* the authorisation: a recognised voice is you unless the config
maps it elsewhere, and it is never locked out for being missing from a list.

Config lives in ``config/autonomy.json`` -> ``"roles"``::

    "roles": {
      "enforce": true,
      "enforce_on_unknown": false,        # true once your own voice is enrolled
      "default": "owner",                 # role when no speaker was identified
      "map": {"owner": ["Mahesh"], "guest": ["Sam"]},
      "extra_tools": {"guest": [], "unknown": []}
    }

``enforce_on_unknown`` defaults to ``false`` so that enabling this cannot lock
the owner out before their voice is enrolled.
"""

import threading

OWNER = "owner"
GUEST = "guest"
UNKNOWN = "unknown"
_ROLES = (OWNER, GUEST, UNKNOWN)

DEFAULT_ROLES: dict = {
    "enforce": True,
    "enforce_on_unknown": False,
    "default": OWNER,
    "map": {"owner": [], "guest": []},
    "extra_tools": {"guest": [], "unknown": []},
}

# Tools that only read.
_READ_ONLY_TOOLS = frozenset({
    "web_search", "weather_report", "youtube_video", "reminder", "flight_finder",
})
# Tools whose business is decided by their "action" field.
_ACTION_SCOPED_TOOLS = frozenset({"file_controller", "computer_settings"})
_READ_ONLY_ACTIONS = frozenset({
    "read", "list", "find", "disk_usage", "search", "info", "status", "get", "show",
})

# The current role is process-wide, not thread-local: speaker identification runs
# on a background thread and the tool call that must respect it runs on another.
_current_role: str | None = None
_current_lock = threading.Lock()


def _cfg() -> dict:
    from agent import policy

    cfg = {
        "enforce": DEFAULT_ROLES["enforce"],
        "enforce_on_unknown": DEFAULT_ROLES["enforce_on_unknown"],
        "default": DEFAULT_ROLES["default"],
        "map": {"owner": [], "guest": []},
        "extra_tools": {"guest": [], "unknown": []},
    }
    block = policy.load_policy().get("roles")
    if isinstance(block, dict):
        for key in ("enforce", "enforce_on_unknown", "default"):
            if key in block:
                cfg[key] = block[key]
        for key in ("map", "extra_tools"):
            value = block.get(key)
            if isinstance(value, dict):
                for role, items in value.items():
                    if isinstance(items, str):
                        items = [items]
                    if isinstance(items, (list, tuple, set)):
                        cfg[key][str(role)] = [str(i) for i in items if str(i).strip()]
    return cfg


# --- speaker -> role ----------------------------------------------------------

def mapped_role(label) -> str | None:
    """The explicitly configured role for a speaker label, if any."""
    name = str(label or "").strip().lower()
    if not name:
        return None
    for role, names in _cfg()["map"].items():
        if any(name == str(n).strip().lower() for n in names):
            return role if role in _ROLES else None
    return None


def role_for_label(label) -> str:
    """Configured role for a label, else ``unknown``."""
    return mapped_role(label) or UNKNOWN


def set_from_speaker(label, *, status: str = "known") -> str:
    """Set the current role from a speaker-identification result.

    ``status`` is voice_id's status: ``known``, ``unknown``, ``noise``,
    ``unavailable``. Noise and unavailable leave the role untouched (a door
    slamming is not a person); an unrecognised voice is only restricted when
    ``enforce_on_unknown`` is on. If enforcement is disabled, this always resets
    to the configured default (owner) so that the process never "remembers" a
    non-owner role once enforcement goes off.
    """
    cfg = _cfg()
    if not cfg.get("enforce", True):
        return set_current(str(cfg.get("default") or OWNER))
    status = str(status or "").strip().lower()
    if status in ("noise", "unavailable", "error"):
        return current()
    if status == "unknown":
        if cfg.get("enforce_on_unknown", False):
            return set_current(UNKNOWN)
        return set_current(str(cfg.get("default") or OWNER))
    return set_current(mapped_role(label) or str(cfg.get("default") or OWNER))


# --- the current role ---------------------------------------------------------

def current() -> str:
    cfg = _cfg()
    if not cfg.get("enforce", True):
        d = str(cfg.get("default") or OWNER).lower()
        return d if d in _ROLES else OWNER
    with _current_lock:
        role = _current_role
    if role:
        return role
    d = str(cfg.get("default") or OWNER).lower()
    return d if d in _ROLES else OWNER


def set_current(role) -> str:
    global _current_role
    role = str(role or "").strip().lower()
    with _current_lock:
        _current_role = role if role in _ROLES else UNKNOWN
        return _current_role


def clear() -> None:
    global _current_role
    with _current_lock:
        _current_role = None


# --- capability check ---------------------------------------------------------

def is_read_only(tool, params=None) -> bool:
    """True when this call only reads (no mutation, no network effect)."""
    tool = str(tool or "")
    params = params or {}
    if tool == "cmd_control":
        from agent import command_policy

        command = str(params.get("command") or params.get("cmd") or "")
        category, _ = command_policy.classify(command)
        return category == command_policy.CATEGORY_ALLOW
    if tool in _READ_ONLY_TOOLS:
        return True
    if tool in _ACTION_SCOPED_TOOLS:
        action = str(params.get("action") or "").strip().lower()
        return action in _READ_ONLY_ACTIONS
    return False


def cap(tool, params, decision):
    """Downgrade a policy decision to fit the current speaker's role.

    Only read-only, already-allowed calls survive for a non-owner: a guest can
    never approve anything, so a ``confirm`` becomes a refusal.
    """
    cfg = _cfg()
    if not cfg.get("enforce", True):
        return decision
    role = current()
    if role == OWNER:
        return decision

    from agent.policy import Decision, Level

    if decision.level is Level.BLOCK:
        return decision
    if decision.level is Level.ALLOW:
        extra = {str(t) for t in (cfg["extra_tools"].get(role) or [])}
        if str(tool) in extra or is_read_only(tool, params):
            return decision
    return Decision(
        Level.BLOCK,
        f"{role} speaker is not authorised for {tool!r} (owner-only)",
        hard=True,
    )


def status() -> dict:
    cfg = _cfg()
    return {
        "enforce": bool(cfg.get("enforce", True)),
        "enforce_on_unknown": bool(cfg.get("enforce_on_unknown", False)),
        "default": cfg.get("default"),
        "current": current(),
        "map": {k: list(v) for k, v in cfg["map"].items()},
    }
