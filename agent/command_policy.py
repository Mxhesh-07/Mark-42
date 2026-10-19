"""Static analysis for shell commands (upgrade list A3).

``cmd_control`` is confirm-gated, but "confirm" is a weak control when the user
cannot see what a command will do, and confirm-fatigue erodes even that. This
module classifies a command so that read-only commands can run without a prompt
and genuinely destructive ones are refused outright - leaving the user to
confirm only the commands that actually change something.

Any command that chains or redirects (``&&``, ``|``, ``>`` ...) is treated as
mutating, because the safe-looking prefix of ``dir && del x`` says nothing about
the rest.
"""

import re

CATEGORY_ALLOW = "read-only"
CATEGORY_CONFIRM = "mutating"
CATEGORY_BLOCK = "destructive"

# Never run, whatever the confirmation.
_DENY = (
    (r"\brm\s+-[a-z]*[rf]", "recursive/forced delete"),
    (r"\brm\s+-[a-z]*[rf][a-z]*\s+/(?:\s|$)", "delete from the filesystem root"),
    (r"\bmkfs(\.\w+)?\b", "format a filesystem"),
    (r"\bformat\s+[a-z]:", "format a drive"),
    (r"\bdiskpart\b", "partition manipulation"),
    (r"\bbcdedit\b", "edit boot configuration"),
    (r"\bvssadmin\b.*\bdelete\b", "delete shadow copies"),
    (r"\breg\s+delete\b", "delete registry keys"),
    (r"\bnet\s+user\b", "account manipulation"),
    (r"\b(shutdown|reboot|poweroff|halt)\b", "change power state"),
    (r":\(\)\s*\{.*\}\s*;?\s*:", "fork bomb"),
    (r">\s*/dev/sd[a-z]", "raw disk write"),
    (r"\bdd\b[^\n]*of=/dev/[a-z]", "raw disk write"),
    (r"\bchmod\s+-R\s+777\s+/(?:\s|$)", "make the root world-writable"),
    (r"\btakeown\b", "change file ownership"),
    (r"\bcipher\s+/w\b", "wipe free space"),
)

# Commands that only read state; safe to run without a prompt.
_ALLOW = (
    "dir", "ls", "type", "cat", "more", "head", "tail", "echo", "whoami",
    "hostname", "ver", "systeminfo", "ipconfig", "ifconfig", "ping", "tracert",
    "netstat", "tasklist", "where", "which", "pwd", "date", "find", "findstr",
    "grep", "wc", "sort", "tree", "attrib", "getmac", "nslookup", "vol",
    "git status", "git diff", "git log", "git show", "pip list", "pip show",
    "python --version", "python -v",
)

_CHAIN = ("&&", "||", ";", "|", "&", ">", "<", "`", "$(")

_MUTATING = re.compile(
    r"\b(del|erase|rmdir|rd|rm|mv|move|copy|cp|ren|rename|mkdir|md|touch|"
    r"set|setx|export|reg\s+add|sc|net|taskkill|start|kill|curl|wget|"
    r"pip\s+install|npm\s+install|git\s+(add|commit|push|reset|checkout|clean)"
    r"|python\s+\S+\.py)\b",
    re.IGNORECASE,
)


def classify(command) -> tuple[str, str]:
    """Return ``(category, reason)`` for a shell command string."""
    cmd = " ".join(str(command or "").split())
    if not cmd:
        return CATEGORY_CONFIRM, "empty command"

    low = cmd.lower()
    for pattern, why in _DENY:
        if re.search(pattern, low):
            return CATEGORY_BLOCK, why

    if any(op in cmd for op in _CHAIN):
        return CATEGORY_CONFIRM, "chained or redirected command"

    for allowed in _ALLOW:
        if low == allowed or low.startswith(allowed + " "):
            return CATEGORY_ALLOW, f"read-only command '{allowed}'"

    if _MUTATING.search(low):
        return CATEGORY_CONFIRM, "command changes state"
    return CATEGORY_CONFIRM, "unrecognised command"
