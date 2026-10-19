"""Narrow, user-authored approval rules (Tier 4 W6).

"Always allow this" is the most dangerous button in the UI, so it does **not**
write what it says. It writes the narrowest rule that still covers the decision
the user actually made: a tool, the discriminating action, and exactly one
resolved target — a path, a recipient, a host. A rule that would also cover a
different path, a different recipient or a different action simply cannot be
expressed here, so the button can never quietly become a tool-wide permission.

Rules live in ``config/approval_rules.json`` (gitignored, like every other piece
of runtime state) and are consulted only where the permission gate has already
decided CONFIRM and every hard guard has already passed — see
``policy._guards``. A rule never lifts a block, and never widens a guest.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

MAX_RULES = 200


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
RULES_PATH = BASE_DIR / "config" / "approval_rules.json"

# The one thing that makes a rule narrow: the value the user was shown. Ordered
# by preference — the first key present in the parameters is used.
_TARGET_KEYS = {
    "file_controller":   ("path", "destination", "source"),
    "send_message":      ("recipient", "to", "phone"),
    "computer_settings": ("action",),
    "computer_control":  ("action",),
    "desktop_control":   ("action",),
    "open_app":          ("app_name", "app", "name"),
    "browser_control":   ("url",),
    "spotify_control":   ("action",),
    "reminder":          ("action",),
    "screen_process":    ("action",),
}

# Keys whose value is a filesystem path, so it can be resolved to one canonical
# spelling before it is compared or stored.
_PATH_KEYS = frozenset({"path", "destination", "source"})

_lock = threading.RLock()


def _action(params: dict) -> str:
    return str((params or {}).get("action") or "").strip().lower()


def _normalise(key: str, value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if key in _PATH_KEYS:
        try:
            return str(Path(text).expanduser().resolve())
        except Exception:
            pass
    return " ".join(text.split()).casefold()


def target_of(tool: str, params: dict | None = None) -> tuple[str, str] | None:
    """``(key, normalised value)`` for the narrowest target, or ``None``.

    ``None`` means the call has nothing narrow to bind to — a shell command, a
    generated script — so "always allow" must not be offered for it.
    """
    params = params or {}
    for key in _TARGET_KEYS.get(tool, ()):
        value = params.get(key)
        if value in (None, ""):
            continue
        normalised = _normalise(key, value)
        if normalised:
            return key, normalised
    return None


def narrowable(tool: str, params: dict | None = None) -> bool:
    return target_of(tool, params) is not None


def build(tool: str, params: dict | None = None) -> dict | None:
    """The rule that "always allow" would write, or ``None`` if it cannot be narrow."""
    found = target_of(tool, params)
    if found is None:
        return None
    key, value = found
    return {
        "tool": str(tool),
        "action": _action(params or {}),
        "target_key": key,
        "target": value,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# --- the store ----------------------------------------------------------------

def rules() -> list[dict]:
    with _lock:
        try:
            raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


def _save(items: list[dict]) -> None:
    try:
        from agent import atomic

        atomic.write_json(RULES_PATH, items, indent=2)
    except Exception:
        try:
            RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
            RULES_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[ApprovalRules] ⚠️ Could not save rules: {e}")


def add(rule: dict) -> dict:
    """Store a rule. Re-adding the same one is a no-op, not a duplicate."""
    with _lock:
        items = rules()
        for existing in items:
            if _same(existing, rule):
                return existing
        items.append(rule)
        _save(items[-MAX_RULES:])
        return rule


def forget(tool: str, params: dict | None = None) -> bool:
    """Remove the rule that covers this exact call. True if one was removed."""
    found = build(tool, params)
    if found is None:
        return False
    with _lock:
        items = rules()
        kept = [r for r in items if not _same(r, found)]
        if len(kept) == len(items):
            return False
        _save(kept)
        return True


def clear() -> None:
    with _lock:
        _save([])


def reset_for_tests() -> None:
    with _lock:
        try:
            RULES_PATH.unlink(missing_ok=True)
        except Exception:
            pass


def _same(left: dict, right: dict) -> bool:
    return (str(left.get("tool")) == str(right.get("tool"))
            and str(left.get("action") or "") == str(right.get("action") or "")
            and str(left.get("target_key") or "") == str(right.get("target_key") or "")
            and str(left.get("target") or "") == str(right.get("target") or ""))


def matches(tool: str, params: dict | None = None) -> dict | None:
    """The rule covering this exact call, or ``None``."""
    found = build(tool, params)
    if found is None:
        return None
    for rule in rules():
        if _same(rule, found):
            return rule
    return None


def status() -> dict:
    return {"path": str(RULES_PATH), "count": len(rules()),
            "rules": rules()[-10:]}


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "clear":
        clear()
        print("approval rules cleared")
        return 0
    print(json.dumps(status(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
