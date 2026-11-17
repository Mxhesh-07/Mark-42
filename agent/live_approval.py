"""Approval for consequential tool calls in the attended (voice) path.

Attendance is a reason to *ask*, not an approval. The live path used to let a
soft ``confirm`` through because the user had spoken the request; that made
"send this message" and "delete this" run on the strength of voice alone.

Three layers, in order:

  A. **Screen prompt.** When a Tk root exists, :mod:`ui.confirm` shows the
     effect and the user clicks approve. Deny is the default and a timeout
     denies.
  B. **Spoken two-step.** Only when no screen is available *and* the action
     reaches another person: this module issues a signed, single-use code. The
     model must ask aloud and re-call with it. The code is bound to the tool and
     its full arguments, expires, and cannot be replayed.
  C. **Refuse.** Destructive file or system changes without a screen, a denied
     prompt, a timeout, a stale or replayed code: all fail closed.

The token is the same primitive the background agent uses (HMAC over the tool
and arguments). It is *explicit* confirmation, not authentication: it proves the
second call is the one the user was asked about, not that a voice is the owner.
"""

from __future__ import annotations

from agent import approval

# Long enough to ask a question and answer it, short enough that a stale "yes"
# cannot be used later. The background agent's default is five minutes; voice is
# a live conversation, so it does not need that.
SPOKEN_TTL_S = 90.0

# Actions that reach another person. Only these may be confirmed by voice when
# the screen prompt cannot be shown. Anything else needs the prompt.
_COMMS_ACTIONS = {
    "devices": {"sms", "call"},
    "enterprise": {"send_email"},
    "smart_alert": {"test_alert"},
}


def spoken_allowed(tool: str, params: dict | None = None) -> bool:
    """True when a spoken confirmation is an acceptable channel for this action."""
    params = params or {}
    if tool == "send_message":
        return True
    actions = _COMMS_ACTIONS.get(tool)
    if not actions:
        return False
    said = {
        str(params.get("action") or "").strip().lower(),
        str(params.get("cmd") or "").strip().lower(),
    }
    return bool(said & actions)


def decide(ui_verdict: str, tool: str, params: dict | None = None) -> str:
    """Map the screen result to ``allow`` | ``challenge`` | ``deny``.

    Deny is the default: any verdict this function does not recognise refuses.
    """
    if ui_verdict == "approved":
        return "allow"
    if ui_verdict == "no-ui" and spoken_allowed(tool, params):
        return "challenge"
    return "deny"


def ask_ui(root, tool: str, params: dict | None, reason: str, *,
           timeout_s: float = 30.0) -> str:
    """Show the screen prompt. Returns approved | denied | timeout | no-ui."""
    if root is None or not hasattr(root, "after"):
        return "no-ui"
    try:
        from ui import confirm

        answer = confirm.consult_on(root, tool, params, effect=reason,
                                    timeout_s=timeout_s)
    except Exception as e:
        print(f"[Approval] the screen prompt failed: {e}")
        return "no-ui"
    if answer.approved:
        return "approved"
    if answer.reason in ("no UI available", "dialog failed"):
        return "no-ui"
    if answer.reason == "timeout":
        return "timeout"
    return "denied"


def issue(tool: str, params: dict | None) -> str:
    """A signed, single-use code bound to this exact action."""
    return approval.manifest(tool, params, ttl_s=SPOKEN_TTL_S)["token"]


def consume(token, tool: str, params: dict | None) -> tuple[bool, str]:
    """Verify and spend a code. Wrong action, expiry and replay all fail."""
    if not token:
        return False, "no approval code"
    manifest = {
        "token": str(token),
        "tool": str(tool),
        "args_digest": approval.digest(tool, params),
    }
    ok, why = approval.authorize(manifest, True)
    if not ok:
        return False, f"approval refused: {why}"
    return True, "approved"


def challenge_text(tool: str, token: str, ttl_s: float = SPOKEN_TTL_S) -> str:
    """What the model is told when it must ask aloud instead of on screen."""
    return (
        f"NOT EXECUTED. '{tool}' needs explicit confirmation and no approval "
        "prompt is available. Ask the user out loud whether to go ahead. Only if "
        f"they agree, call {tool} again with the same arguments and add "
        f"\"approval\": \"{token}\". The code expires in {int(ttl_s)} seconds and "
        "works once. Do not claim the action happened."
    )
