"""Opinions and risk (Tier 4 W2).

``policy.py`` answers "may I?". It is deliberately binary — allow, confirm,
block — so it cannot answer "is this *wise*?", and it has no way to say so.
That is the gap this module fills.

For a proposed call it produces an explainable risk score, a plain-language
classification (is it undoable? whom does it affect?), the assistant's own
confidence in that domain, and — only when all of that says it matters — one
sentence of pushback with a concrete safer alternative.

The score is a weighted sum, not a model:

    risk = 0.45*irreversibility + 0.35*blast_radius + 0.20*(1 - confidence)

with every component on a 0..1 scale, so a person can read the number and
disagree with it. Pushback is rarer than the score suggests: it needs risk above
the threshold *and* a concrete alternative *and* it never repeats for the same
action in a session. Nagging is the failure mode; one interruption costs trust.

``assess()`` takes the ``policy.Decision`` the caller already computed rather
than evaluating again, because a second ``policy.evaluate()`` would spend a
second rate-limit token for the same call.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

REVERSIBILITY = ("reversible", "recoverable", "permanent")
BLAST_RADIUS = ("self", "local", "network", "other_people")

# How much each label contributes, 0..1. These two tables are the whole model.
_IRREVERSIBILITY = {"reversible": 0.0, "recoverable": 0.5, "permanent": 1.0}
_BLAST = {"self": 0.0, "local": 0.35, "network": 0.6, "other_people": 1.0}

DEFAULT_CONFIG = {
    "enabled": True,
    "weights": {"irreversibility": 0.45, "blast_radius": 0.35, "confidence": 0.20},
    "pushback_threshold": 0.6,
    "pushback_on_allow": True,
    "never_pushback_tools": ["weather_report", "reminder"],
}


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "judgement.json"

# tool -> (reversibility, blast_radius). Refined for some tools below.
_TOOL_PROFILE = {
    "web_search":        ("reversible", "network"),
    "weather_report":    ("reversible", "network"),
    "youtube_video":     ("reversible", "network"),
    "flight_finder":     ("reversible", "network"),
    "spotify_control":   ("reversible", "self"),
    "reminder":          ("reversible", "self"),
    "open_app":          ("reversible", "self"),
    "get_open_windows":  ("reversible", "self"),
    "screen_process":    ("reversible", "local"),
    "browser_control":   ("recoverable", "network"),
    "computer_control":  ("recoverable", "self"),
    "desktop_control":   ("recoverable", "local"),
    "computer_settings": ("recoverable", "self"),
    "file_controller":   ("reversible", "local"),      # refined by action
    "cmd_control":       ("recoverable", "local"),
    "code_helper":       ("recoverable", "self"),
    "dev_agent":         ("permanent", "local"),
    "generated_code":    ("permanent", "local"),
    "send_message":      ("permanent", "other_people"),
}

# Refinements: (tool, action) -> (reversibility, blast_radius).
_FILE_READ_ACTIONS = frozenset({
    "read", "read_file", "list", "list_dir", "ls", "find", "search", "info",
    "exists", "disk_usage", "tree", "stat", "get",
})
_FILE_DELETE_ACTIONS = frozenset({
    "delete", "remove", "rmdir", "remove_dir", "unlink", "trash", "rmtree",
})
_POWER_ACTIONS = frozenset({
    "shutdown", "shut_down", "power_off", "turn_off_computer",
    "restart", "restart_computer", "reboot", "reboot_computer",
    "sleep", "hibernate", "logoff", "logout",
})

# The concrete safer alternative that justifies raising a concern. A pushback
# without one is just an objection, so a missing entry means no pushback.
_ALTERNATIVES = {
    ("file_controller", "delete"):
        "I can move it to the Recycle Bin instead, which is undoable.",
    ("file_controller", "rmdir"):
        "I can move the folder to the Recycle Bin instead, which is undoable.",
    ("file_controller", "write"):
        "I can show you the change before it is written.",
    ("send_message", None):
        "I can show you the draft first, so nothing goes out unchecked.",
    ("cmd_control", None):
        "I can run the read-only part first and show you what it finds.",
    ("generated_code", None):
        "I can save the script and let you read it before it runs.",
    ("dev_agent", None):
        "I can plan the changes and show them to you before touching anything.",
    ("computer_settings", "shutdown"):
        "I can lock the screen instead, if you are stepping away.",
    ("computer_settings", "restart"):
        "I can lock the screen instead, if you are stepping away.",
    ("browser_control", None):
        "I can read the page and tell you what is there instead of acting on it.",
}

_lock = threading.RLock()
_pushed: set[str] = set()


@dataclass(frozen=True)
class Assessment:
    """What the assistant thinks about one proposed call.

    ``allowed``        policy did not refuse it outright (a ``confirm`` is still
                       "allowed" in this sense — see ``needs_confirmation``).
    ``risk``           0..1, from the weighted sum.
    ``confidence``     the self-model's confidence in this tool's domain.
    ``opinion``        one sentence, or ``None``. Present only when it would
                       change the outcome.
    ``should_pushback``whether that opinion should actually be voiced.
    """

    allowed: bool
    risk: float
    reversibility: str
    blast_radius: str
    confidence: float
    opinion: str | None
    should_pushback: bool
    tool: str = ""
    effect: str = ""
    level: str = "allow"
    needs_confirmation: bool = False

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "risk": self.risk,
            "reversibility": self.reversibility,
            "blast_radius": self.blast_radius,
            "confidence": self.confidence,
            "opinion": self.opinion,
            "should_pushback": self.should_pushback,
            "tool": self.tool,
            "effect": self.effect,
            "level": self.level,
            "needs_confirmation": self.needs_confirmation,
        }


# --- config -------------------------------------------------------------------

def load_config() -> dict:
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _setting(config: dict, key: str, default):
    value = config.get(key, default)
    return default if value is None else value


def _weights(config: dict) -> dict:
    weights = dict(DEFAULT_CONFIG["weights"])
    given = config.get("weights")
    if isinstance(given, dict):
        for key in weights:
            try:
                weights[key] = float(given.get(key, weights[key]))
            except (TypeError, ValueError):
                pass
    return weights


# --- classification -----------------------------------------------------------

def _action(params: dict) -> str:
    return str((params or {}).get("action") or "").strip().lower()


def classify(tool: str, params: dict | None = None) -> tuple[str, str]:
    """Return ``(reversibility, blast_radius)`` for a proposed call."""
    params = params or {}
    action = _action(params)

    if tool == "file_controller":
        if action in _FILE_READ_ACTIONS:
            return "reversible", "self"
        if action in _FILE_DELETE_ACTIONS:
            return "permanent", "local"
        return "recoverable", "local"

    if tool == "computer_settings" and action in _POWER_ACTIONS:
        return "recoverable", "self"

    return _TOOL_PROFILE.get(tool, ("recoverable", "network"))


def _alternative(tool: str, params: dict) -> str | None:
    action = _action(params)
    if (tool, action) in _ALTERNATIVES:
        return _ALTERNATIVES[(tool, action)]
    return _ALTERNATIVES.get((tool, None))


def action_key(tool: str, params: dict | None = None) -> str:
    """A stable id for one effect, for the once-per-session rule."""
    blob = json.dumps({"tool": tool, "params": params or {}},
                      sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _confidence(tool: str) -> float:
    try:
        from core import self as self_model

        return float(self_model.confidence(self_model.domain_for(tool) or ""))
    except Exception:
        return 0.5


def _effect(tool: str, params: dict) -> str:
    try:
        from agent import approval

        return str(approval.effect_for(tool, params))
    except Exception:
        return ""


def _risk(reversibility: str, blast_radius: str, confidence: float, weights: dict) -> float:
    irreversibility = _IRREVERSIBILITY.get(reversibility, 0.5)
    blast = _BLAST.get(blast_radius, 0.35)
    score = (weights["irreversibility"] * irreversibility
             + weights["blast_radius"] * blast
             + weights["confidence"] * (1.0 - max(0.0, min(1.0, confidence))))
    return round(max(0.0, min(1.0, score)), 4)


# --- the judgement ------------------------------------------------------------

def assess(
    tool: str,
    params: dict | None = None,
    *,
    decision=None,
    safety: bool = False,
    remember: bool = True,
) -> Assessment:
    """Score one proposed call and decide whether to say something about it.

    ``decision``  the ``policy.Decision`` the caller already has. Pass it: a
                  second ``policy.evaluate()`` would spend a second rate-limit
                  token on the same call. Without it, one is computed.
    ``safety``    set for a safety-critical path (the W1 urgency-4 case), where
                  pushback is never appropriate.
    ``remember``  whether a pushback consumes the once-per-session slot.
    """
    params = params or {}
    config = load_config()

    level = "allow"
    reason = ""
    if decision is None:
        try:
            from agent import policy

            decision = policy.evaluate(tool, params)
        except Exception:
            decision = None
    if decision is not None:
        level_value = getattr(getattr(decision, "level", None), "value", "allow")
        level = str(level_value)
        reason = str(getattr(decision, "reason", "") or "")

    allowed = level != "block"
    needs_confirmation = level == "confirm"

    reversibility, blast_radius = classify(tool, params)
    confidence = _confidence(tool)
    weights = _weights(config)
    risk = _risk(reversibility, blast_radius, confidence, weights)

    should = False
    opinion = None
    if bool(_setting(config, "enabled", True)) and allowed and not safety:
        threshold = float(_setting(config, "pushback_threshold", 0.6))
        never = set(_setting(config, "never_pushback_tools", []))
        if needs_confirmation or bool(_setting(config, "pushback_on_allow", True)):
            alternative = _alternative(tool, params)
            key = action_key(tool, params)
            with _lock:
                unseen = key not in _pushed
            should = (
                risk > threshold
                and alternative is not None
                and tool not in never
                and unseen
            )
            if should:
                opinion = alternative
                if remember:
                    with _lock:
                        _pushed.add(key)

    return Assessment(
        allowed=allowed,
        risk=risk,
        reversibility=reversibility,
        blast_radius=blast_radius,
        confidence=round(confidence, 4),
        opinion=opinion,
        should_pushback=should,
        tool=str(tool),
        effect=_effect(tool, params),
        level=level,
        needs_confirmation=needs_confirmation,
    )


def explain(advice: Assessment) -> str:
    """A one-line, log-safe summary of an assessment."""
    denied = "" if advice.allowed else "  (refused by policy)"
    return (f"risk {advice.risk:.2f} = {advice.reversibility}/{advice.blast_radius}, "
            f"confidence {advice.confidence:.2f}{denied}")


def pushed_this_session() -> int:
    with _lock:
        return len(_pushed)


def reset_session() -> None:
    """Forget which effects have already been pushed back on."""
    with _lock:
        _pushed.clear()
