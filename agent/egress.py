"""Network egress control (A4).

Several tools can reach the network: `web_search`, `browser_control`,
`send_message`, generated code. If the agent is hijacked by injected content,
that reach is the exfiltration path — read a page, then post the user's data to
a host the *injection* chose. This module bounds that reach:

* private, loopback, link-local and cloud-metadata addresses are refused by
  default (the SSRF guard);
* a denylist always wins;
* when an allowlist is configured, only those hosts (and their subdomains) are
  reachable;
* every destination that is *allowed* is recorded, so the audit log shows where
  the assistant actually went.

Config lives in ``config/autonomy.json`` -> ``"egress"``::

    "egress": {
      "enabled": true,
      "block_private": true,
      "allow": ["api.github.com"],
      "deny": ["pastebin.com"],
      "log_allowed": true
    }
"""

import ipaddress
import re
from urllib.parse import urlsplit

DEFAULT_EGRESS: dict = {
    "enabled": True,
    "block_private": True,
    "allow": [],
    "deny": [],
    "log_allowed": True,
}

# Parameter names that carry a destination.
_URL_KEYS = frozenset({
    "url", "uri", "link", "href", "address", "endpoint", "website", "site",
    "page", "navigate", "target_url",
})
_HOST_KEYS = frozenset({"host", "hostname", "domain", "server", "ip"})
_EMAIL_KEYS = frozenset({"to", "recipient", "email", "cc", "bcc"})

_URL_RE = re.compile(r"https?://[^\s\"'<>()\[\],]+", re.IGNORECASE)

# Addresses that are sensitive targets in their own right.
_METADATA_HOSTS = frozenset({
    "metadata", "metadata.google.internal", "169.254.169.254",
    "metadata.azure.com", "instance-data",
})
_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".home", ".localhost", ".localdomain")


def _cfg() -> dict:
    """Egress settings from the policy, over the safe defaults."""
    from agent import policy

    cfg = {
        "enabled": DEFAULT_EGRESS["enabled"],
        "block_private": DEFAULT_EGRESS["block_private"],
        "log_allowed": DEFAULT_EGRESS["log_allowed"],
        "allow": [],
        "deny": [],
    }
    block = policy.load_policy().get("egress")
    if isinstance(block, dict):
        for key in ("enabled", "block_private", "log_allowed"):
            if key in block:
                cfg[key] = block[key]
        for key in ("allow", "deny"):
            value = block.get(key)
            if isinstance(value, str):
                value = [value]
            if isinstance(value, (list, tuple, set)):
                cfg[key] = [str(v) for v in value if str(v).strip()]
    return cfg


def host_of(value) -> str:
    """Lowercase hostname for a URL, a bare host, or a ``host:port`` pair."""
    if value is None:
        return ""
    text = str(value).strip().strip("\"'`").strip()
    if not text:
        return ""
    if "://" in text:
        try:
            return (urlsplit(text).hostname or "").lower().strip("[]")
        except Exception:
            return ""
    # bare host / host:port / user@host / host/path
    text = text.split("/", 1)[0]
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    if text.count(":") == 1:
        text = text.split(":", 1)[0]
    return text.lower().strip("[]")


def is_private_host(host: str) -> bool:
    """True for loopback, private, link-local, reserved or metadata targets."""
    if not host:
        return False
    host = host.lower().rstrip(".")
    if host in _METADATA_HOSTS or host in ("localhost", "localhost.localdomain"):
        return True
    if host.endswith(_PRIVATE_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _matches(host: str, patterns) -> bool:
    for raw in patterns or ():
        pattern = str(raw).strip().lower().lstrip(".")
        if not pattern:
            continue
        if pattern.startswith("*."):
            pattern = pattern[2:]
        if host == pattern or host.endswith("." + pattern):
            return True
    return False


def check(value) -> tuple[bool, str]:
    """May we talk to this URL or host?  Returns ``(ok, reason)``."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return True, "egress control disabled"
    host = host_of(value)
    if not host:
        return True, "no host in the destination"
    if _matches(host, cfg.get("deny")):
        return False, f"{host} is on the egress denylist"
    if _matches(host, cfg.get("allow")):
        return True, f"{host} is on the egress allowlist"
    if cfg.get("allow"):
        return False, f"{host} is not on the egress allowlist"
    if cfg.get("block_private", True) and is_private_host(host):
        return False, f"{host} is a private/loopback address (SSRF guard)"
    return True, f"{host} allowed"


def destinations(params) -> list[str]:
    """Destinations named in a tool call's parameters (deduplicated by host)."""
    if not isinstance(params, dict):
        return []
    found: list[str] = []
    for key, value in params.items():
        if isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            items = [value]
        for item in items:
            if not isinstance(item, str) or not item.strip():
                continue
            lowered = str(key).lower()
            if lowered in _EMAIL_KEYS:
                if "@" in item:
                    found.append(item.rsplit("@", 1)[1].strip("> "))
                continue
            if lowered in _HOST_KEYS or lowered in _URL_KEYS:
                found.append(item)
                continue
            found.extend(_URL_RE.findall(item))

    seen: set[str] = set()
    unique: list[str] = []
    for item in found:
        host = host_of(item)
        if host and host not in seen:
            seen.add(host)
            unique.append(item)
    return unique


def guard(tool: str, params) -> tuple[bool, str]:
    """Check every destination a tool call names; record the ones that pass."""
    cfg = _cfg()
    if not cfg.get("enabled", True):
        return True, "egress control disabled"
    for dest in destinations(params):
        ok, why = check(dest)
        _record(tool, dest, allowed=ok, detail=why)
        if not ok:
            return False, why
    return True, "all destinations allowed"


def _record(tool: str, dest: str, *, allowed: bool, detail: str) -> None:
    try:
        from agent import audit

        audit.record(
            "egress",
            tool=str(tool),
            parameters={"destination": str(dest)},
            outcome="ok" if allowed else "blocked",
            detail=detail,
        )
    except Exception:
        pass


def status() -> dict:
    cfg = _cfg()
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "block_private": bool(cfg.get("block_private", True)),
        "allow": list(cfg.get("allow") or []),
        "deny": list(cfg.get("deny") or []),
    }
