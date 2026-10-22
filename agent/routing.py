"""Tier 2 I3/I4 — cost-aware routing and prompt budgeting.

I3 asks *which model should answer this*: a "what time is it" does not need the
largest model in the chain, and a multi-step design question should not be sent
to the cheapest one first. The classifier is deliberately small and
deterministic: no extra model call to decide which model to call.

I4 asks *what should the prompt look like when the context window is small*.
`compact()` is a lossy, deterministic reduction used only when the caller says
the budget is tight; the full prompt remains the default so behaviour does not
silently change.
"""

from __future__ import annotations

import re

# Ordered cheapest → most capable. Names are looked up in `gemini_util._chain`
# so a model missing from the configured chain is simply skipped by the router.
CHEAP = ("gemini-2.5-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash")
STRONG = (
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
)

_REASONING = re.compile(
    r"\b(why|analyse|analyze|compare|design|architect|debug|diagnose|strategy|"
    r"plan|step by step|trade-?off|root cause|prove|derive|refactor|review|"
    r"explain in detail|summari[sz]e|recommend|decide|evaluate)\b",
    re.IGNORECASE,
)
_TRIVIAL = re.compile(
    r"^(hi|hey|hello|yo|thanks|thank you|ok|okay|cool|nice|stop|cancel|"
    r"yes|no|what time|what'?s the time|open |launch |close )\b",
    re.IGNORECASE,
)


def classify(text: str) -> str:
    """`"trivial"`, `"reasoning"`, or `"standard"`.

    Short, single-purpose utterances and greeting/short-command shapes are
    trivial. Explicit multi-step or analytical language is reasoning. Anything
    unclear stays standard, which keeps the current chain order — the safe
    default.
    """
    t = (text or "").strip()
    if not t:
        return "standard"
    if len(t) <= 40 and _TRIVIAL.search(t):
        return "trivial"
    if len(t) > 400 or _REASONING.search(t):
        return "reasoning"
    if len(t) <= 40 and "?" not in t:
        return "trivial"
    return "standard"


def order(chain, text: str) -> list[str]:
    """Reorder an existing chain for the classified intent.

    Members not in the intent's preference list keep their relative order after
    the preferred ones, so a misclassification can cost a call but never a
    model: the chain is always the same set, just reordered.
    """
    base = [str(m) for m in chain]
    kind = classify(text)
    if kind == "reasoning":
        preferred = STRONG
    elif kind == "trivial":
        preferred = CHEAP
    else:
        return base
    head = [m for m in preferred if m in base]
    tail = [m for m in base if m not in head]
    return head + tail


def compact(text: str, limit: int = 1200) -> str:
    """I4: a smaller prompt for small-context fallbacks.

    Keeps the first and last part (the instruction and the most recent turn),
    drops duplicate blank lines and trims each line. It never invents content
    and never returns more than `limit` characters.
    """
    t = (text or "").replace("\r\n", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    lines = [line.rstrip() for line in t.split("\n")]
    t = "\n".join(lines).strip()
    if len(t) <= limit:
        return t
    marker = "\n\n[...trimmed for a smaller context...]\n\n"
    budget = max(0, limit - len(marker))
    keep = max(1, budget // 2)
    head, tail = t[:keep], t[-(budget - keep):]
    return f"{head}{marker}{tail}"
