"""Per-tool token buckets (upgrade list A9).

The per-task and hourly caps in ``config/autonomy.json`` do not stop a single
task from calling one tool in a tight loop. This adds a token bucket per tool
(a sustained rate plus a burst allowance) and a global action budget, enforced
from ``policy.evaluate`` so no caller can bypass it.

Configured under ``rate_limits`` in config/autonomy.json::

    "rate_limits": {
      "default": { "per_minute": 30, "burst": 12 },
      "global":  { "per_minute": 120, "burst": 40 },
      "tools":   { "web_search": { "per_minute": 10, "burst": 4 } }
    }
"""

import threading
import time

_lock = threading.Lock()
_buckets: dict[str, list] = {}          # key -> [tokens, last_ts]

_DEFAULT = {"per_minute": 30, "burst": 12}
_GLOBAL = {"per_minute": 120, "burst": 40}


def _cfg(tool: str) -> tuple[dict, dict]:
    try:
        from agent import policy
        pol = policy.load_policy()
    except Exception:
        pol = {}
    rl = pol.get("rate_limits") if isinstance(pol, dict) else None

    base, glob = dict(_DEFAULT), dict(_GLOBAL)
    if isinstance(rl, dict):
        if isinstance(rl.get("default"), dict):
            base.update(rl["default"])
        if isinstance(rl.get("global"), dict):
            glob.update(rl["global"])
        tools = rl.get("tools")
        if isinstance(tools, dict) and isinstance(tools.get(tool), dict):
            base.update(tools[tool])
    return base, glob


def _take(key: str, per_minute: float, burst: float, now: float) -> bool:
    """Consume one token from ``key`` if available."""
    tokens, last = _buckets.get(key, [float(burst), now])
    tokens = min(float(burst), tokens + (now - last) * (float(per_minute) / 60.0))
    if tokens < 1.0:
        _buckets[key] = [tokens, now]
        return False
    _buckets[key] = [tokens - 1.0, now]
    return True


def check(tool: str) -> tuple[bool, str]:
    """Return ``(allowed, reason)`` for one action of ``tool``."""
    if not tool:
        return True, ""
    base, glob = _cfg(str(tool))
    now = time.monotonic()
    with _lock:
        if not _take("tool:" + str(tool), base["per_minute"], base["burst"], now):
            return False, (f"rate limit: '{tool}' exceeded "
                           f"{base['per_minute']}/min (burst {base['burst']})")
        if not _take("global", glob["per_minute"], glob["burst"], now):
            return False, (f"rate limit: global budget exceeded "
                           f"({glob['per_minute']}/min)")
    return True, ""


def reset() -> None:
    """Forget all buckets (used by tests)."""
    with _lock:
        _buckets.clear()
