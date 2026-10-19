"""Tier 2 H2 — redaction, in one place.

Before this module existed, redaction lived inside `agent/crash.py`, applied
where crash bundles were written. That is one of the places a string leaves the
process, not the last one, and it is not the most important one.

There are two levels, because "leaves the machine" is not one situation:

``secrets``
    Credentials that are **never** the content: API keys, tokens, private-key
    blocks, `password=...`, bearer tokens, URL-embedded passwords, AWS keys, and
    card-like numbers (13-19 digits that pass the Luhn check). Safe to apply to
    anything that goes out — masking a credential cannot break a task, because
    no task legitimately needs to *send* one to a model.

``personal``
    Adds what a person looks like: email addresses, phone numbers, and the user
    name inside home paths. Right for logs, crash bundles and audit entries.
    Wrong for an outbound prompt, where the address is usually the thing the
    user is working on — "email Sam about Thursday" — and masking it would
    silently break the task it was meant to protect.

So: logs default to ``personal``, outbound model text defaults to ``secrets``.
Both are configurable in `config/autonomy.json` → `privacy`, and both are
idempotent, so applying them twice is harmless.

`python -m agent.redact` shows what a given text would lose, level by level.
"""

from __future__ import annotations

import json
import re
import sys

LEVELS = ("off", "secrets", "personal")

# --- credential patterns (the `secrets` level) --------------------------------

_KEY_PATTERNS = (
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"),                 # Google API key
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),                  # OpenAI-style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),              # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),           # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                        # AWS access key
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # JWT
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)\b(api[_\- ]?key|api[_\- ]?secret|access[_\- ]?key|token|secret"
               r"|password|passwd|pwd)\b\s*[:=]\s*"
               r"[\"']?([^\s\"',}]{6,})[\"']?"),
)

# A whole private-key block, whatever its flavour.
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
    r"[\s\S]*?"
    r"-----END (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")

# https://user:password@host — the password is the one part nobody wants sent.
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.\-]*://)(?P<user>[^:@/\s]+):(?P<pw>[^@/\s]+)@")

# 13-19 digits, optionally grouped, kept only when they pass the Luhn check:
# an arbitrary long number almost always fails it, a card number never does.
_CARD_CANDIDATE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

# --- personal patterns (added by the `personal` level) ------------------------

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_WINDOWS_USER = re.compile(r"(?i)\b[Cc]:\\Users\\[^\\\s\"']+")
_POSIX_HOME = re.compile(r"/(?:home|Users)/[^/\s\"']+")
_PHONE = re.compile(r"\b(?:\+?\d[\s-]?){10,}\b")

MARK_KEY = "<redacted-key>"
MARK_CARD = "<card>"


def _luhn_ok(digits: str) -> bool:
    total = 0
    for position, character in enumerate(reversed(digits)):
        value = int(character)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _mask_cards(text: str) -> str:
    def replace(match: re.Match) -> str:
        digits = re.sub(r"[^\d]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return MARK_CARD
        return match.group(0)

    return _CARD_CANDIDATE.sub(replace, text)


def secrets(text: str) -> str:
    """Mask credentials only. Idempotent; safe on anything outbound."""
    out = str(text)
    out = _PRIVATE_KEY.sub("<redacted-private-key>", out)
    out = _URL_CREDENTIALS.sub(lambda m: f"{m.group('scheme')}{m.group('user')}:<redacted>@", out)
    out = _mask_cards(out)
    for pattern in _KEY_PATTERNS:
        if pattern.groups >= 2:
            out = pattern.sub(lambda m: f"{m.group(1)}=<redacted>", out)
        elif pattern.groups == 1:
            out = pattern.sub(lambda m: f"{m.group(1)} <redacted>", out)
        else:
            out = pattern.sub(MARK_KEY, out)
    return out


def personal(text: str) -> str:
    """Mask credentials and personal data. For logs, bundles and audit entries."""
    out = secrets(text)
    out = _EMAIL.sub("<email>", out)
    out = _WINDOWS_USER.sub("<home>", out)
    out = _POSIX_HOME.sub("<home>", out)
    out = _PHONE.sub("<number>", out)
    return out


# --- levels -------------------------------------------------------------------

def _level(name, fallback: str = "personal") -> str:
    """A level, or the fallback if the configured one is unknown."""
    name = str(name or "").strip().lower()
    if name in LEVELS:
        return name
    fallback = str(fallback or "").strip().lower()
    return fallback if fallback in LEVELS else "personal"


def load_config() -> dict:
    from agent import policy

    try:
        cfg = policy.load_policy().get("privacy")
    except Exception:
        cfg = None
    return cfg if isinstance(cfg, dict) else {}


def level_for(context: str) -> str:
    """The configured level for `"log"` or `"egress"`.

    A value that is not one of LEVELS falls back to that context's default, so a
    typo cannot silently turn redaction off.
    """
    cfg = load_config()
    key = "log_redaction" if context == "log" else "egress_redaction"
    default = "personal" if context == "log" else "secrets"
    return _level(cfg.get(key, default), default)


def redact(value, *, level: str | None = None):
    """Recursively redact a JSON-safe value. `level` defaults to the log level."""
    level = _level(level if level is not None else level_for("log"))
    if level == "off":
        return value
    return _apply(value, personal if level == "personal" else secrets)


def _apply(value, fn):
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {_apply(k, fn): _apply(v, fn) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_apply(v, fn) for v in value]
    return value


def outbound(contents):
    """The `contents` of a model request, with credentials removed.

    Only walks the built-in containers and strings, so SDK objects pass through
    untouched — this must never mangle a `types.Content` the SDK needs.
    """
    return _apply(contents, secrets)


def findings(text: str) -> dict:
    """What each level would mask, for `python -m agent.redact`."""
    out = {"secrets": secrets(text), "personal": personal(text)}
    return {k: v for k, v in out.items() if v != text}


# --- CLI ----------------------------------------------------------------------

def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        if sys.stdin.isatty():
            print("usage: python -m agent.redact \"<text>\"   (or pipe text on stdin)")
            return 2
        text = sys.stdin.read()
    else:
        text = " ".join(argv)

    print(json.dumps({
        "egress_level": level_for("egress"),
        "log_level": level_for("log"),
        "would_change": bool(findings(text)),
        "secrets": secrets(text),
        "personal": personal(text),
        "idempotent": secrets(secrets(text)) == secrets(text),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
