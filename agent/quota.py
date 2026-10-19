"""Tier 2 I1/I2 — the quota ledger and the budget guard.

I1 asks *what has been spent*; I2 asks *what to do when the answer is "too
much"*. They are one module because the second question is unanswerable without
the first.

What is counted
    One entry per **successful** model call, with the provider, the model and
    (when the SDK reports it) the token count. Deliberately not failures: a
    429 that walks six models before giving up costs nothing, so counting
    attempts would trip the guard during a free-tier outage and blame the user.

The windows
    The hourly cap is a **rolling** 60 minutes — a burst straddling the hour
    boundary still counts. The daily cap is the **local** calendar day, because
    "today's budget" means the user's today, not UTC's.

The response
    On breach the ladder is floored at READ_ONLY (see `agent/degrade.py`) and
    the existing gate rule does the rest: `policy._guards` already refuses every
    write, so a runaway agentic loop is broken at its source while the
    conversation keeps working. The floor is released by the clock, not by
    successes, which is exactly why it is a floor and not a step down.

    This is a **hard cap on effects, not on speech.** It is a cost control, not
    a security control, and it is documented that way so nobody trusts it to
    stop something hostile — `policy`, `roles` and the kill switch do that.

`python -m agent.quota` prints the ledger; `clear --yes` wipes it.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

VERSION = 1

DEFAULTS = {
    "enabled": True,
    "max_calls_per_hour": 60,
    "max_calls_per_day": 400,
    "on_breach": "read_only",
}

# Entries older than this are dropped on write; the ledger is a rolling window,
# not a history (the audit log is the history).
RETENTION_DAYS = 8
MAX_ENTRIES = 5000

HOUR_SECONDS = 3600
_FLOOR_REASON = "budget"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


LEDGER_PATH = get_base_dir() / "memory" / "quota_ledger.json"

_lock = threading.RLock()
# Which breach has already been announced, keyed by "hour"/"day". In memory
# only: a restart re-announcing once is better than a silent cap.
_announced: dict[str, str] = {}


# --- configuration ------------------------------------------------------------

def config() -> dict:
    """DEFAULTS merged with `config/autonomy.json` → `budget`."""
    merged = dict(DEFAULTS)
    try:
        from agent import policy

        raw = policy.load_policy().get("budget")
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    merged[key] = raw[key]
    except Exception:
        pass
    return merged


def _limit(value) -> int:
    """A call limit; 0 or a non-number means unlimited."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


# --- the ledger ---------------------------------------------------------------

def _empty() -> dict:
    return {"version": VERSION, "calls": []}


def _load() -> dict:
    try:
        raw = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _empty()
    if not isinstance(raw, dict) or not isinstance(raw.get("calls"), list):
        return _empty()
    return {"version": VERSION,
            "calls": [c for c in raw["calls"] if isinstance(c, dict)]}


def _save(ledger: dict) -> None:
    directory = LEDGER_PATH.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(LEDGER_PATH) + ".tmp")
        tmp.write_text(json.dumps(ledger, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, LEDGER_PATH)
    except Exception:
        # A ledger we cannot write must never take the assistant down; the
        # in-memory count for this process is lost, which is the safe failure.
        pass


def _trim(ledger: dict, now: float) -> None:
    cutoff = now - RETENTION_DAYS * 86400
    calls = [c for c in ledger["calls"] if _ts(c) >= cutoff]
    if len(calls) > MAX_ENTRIES:
        calls = calls[-MAX_ENTRIES:]
    ledger["calls"] = calls


def _ts(entry: dict) -> float:
    try:
        return float(entry.get("ts") or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --- recording ----------------------------------------------------------------

def record(provider: str, model: str | None = None, *,
           tokens=None, now: float | None = None) -> dict:
    """Note one successful model call, then re-check the budget.

    Returns the usage summary (and so also the breach, if this call caused one).
    """
    moment = time.time() if now is None else float(now)
    entry: dict = {"ts": moment, "provider": str(provider or "unknown")}
    if model:
        entry["model"] = str(model)
    if tokens:
        try:
            entry["tokens"] = int(tokens)
        except (TypeError, ValueError):
            pass

    with _lock:
        ledger = _load()
        ledger["calls"].append(entry)
        _trim(ledger, moment)
        _save(ledger)

    return enforce(now=moment)


# --- windows ------------------------------------------------------------------

def _local_day(moment: float) -> str:
    return datetime.fromtimestamp(moment).date().isoformat()


def _tally(rows: list) -> dict:
    providers: dict[str, int] = {}
    models: dict[str, int] = {}
    tokens = 0
    for row in rows:
        providers[row["provider"]] = providers.get(row["provider"], 0) + 1
        name = row.get("model")
        if name:
            models[name] = models.get(name, 0) + 1
        try:
            tokens += int(row.get("tokens") or 0)
        except (TypeError, ValueError):
            pass
    return {"calls": len(rows), "tokens": tokens,
             "providers": providers, "models": models}


def _rows(ledger: dict, now: float) -> tuple[list, list]:
    hour_start = now - HOUR_SECONDS
    today = _local_day(now)
    hour = [c for c in ledger["calls"] if _ts(c) >= hour_start]
    day = [c for c in ledger["calls"] if _local_day(_ts(c)) == today]
    return hour, day


def usage(*, now: float | None = None) -> dict:
    """Calls in the rolling hour and the local day, plus the configured caps."""
    moment = time.time() if now is None else float(now)
    cfg = config()
    with _lock:
        ledger = _load()
        hour_rows, day_rows = _rows(ledger, moment)

    hour_cap = _limit(cfg.get("max_calls_per_hour"))
    day_cap = _limit(cfg.get("max_calls_per_day"))
    breach = None
    if cfg.get("enabled", True):
        if day_cap and len(day_rows) >= day_cap:
            breach = "day"
        elif hour_cap and len(hour_rows) >= hour_cap:
            breach = "hour"

    return {
        "hour": _tally(hour_rows),
        "day": _tally(day_rows),
        "limits": {"calls_per_hour": hour_cap, "calls_per_day": day_cap},
        "breached": breach,
        "on_breach": str(cfg.get("on_breach") or "read_only"),
    }


def breached(*, now: float | None = None) -> str | None:
    """`"hour"`, `"day"`, or None."""
    return usage(now=now)["breached"]


def describe(*, now: float | None = None) -> str:
    """One human line — for the health report and the tray."""
    state = usage(now=now)
    hour, day, limits = state["hour"], state["day"], state["limits"]
    text = (f"{hour['calls']} calls this hour (cap {limits['calls_per_hour']}), "
            f"{day['calls']} today (cap {limits['calls_per_day']})")
    if state["breached"]:
        text += f" — OVER the {state['breached']} budget"
    return text


# --- the guard ----------------------------------------------------------------

def enforce(*, now: float | None = None) -> dict:
    """Apply the budget: floor the ladder on breach, lift our floor when clear.

    Called after every recorded call, so the guard converges on its own — a
    breach that is only visible after a restart (the ledger persisted, the
    process did not) is corrected by the next call, and `status()` calls it too.
    """
    moment = time.time() if now is None else float(now)
    state = usage(now=moment)
    reason = state["breached"]

    if reason is None:
        _release_our_floor()
        return state

    _announce(reason, state, moment)
    # `on_breach` has exactly one implemented value, and an unrecognised one is
    # treated as read-only rather than as "off": a typo must not disable the
    # guard it was meant to configure.
    try:
        from agent import degrade

        degrade.set_floor("READ_ONLY", f"{_FLOOR_REASON}: {reason} call cap reached")
    except Exception:
        pass
    return state


def release() -> bool:
    """Lift a budget floor by hand. Returns True when one was lifted."""
    return _release_our_floor()


def _release_our_floor() -> bool:
    try:
        from agent import degrade

        current = degrade.floor()
        if current is None:
            return False
        _name, why = current
        if not str(why).startswith(_FLOOR_REASON):
            return False                      # somebody else's floor
        degrade.clear_floor()
        return True
    except Exception:
        return False


def _window_key(reason: str, moment: float) -> str:
    if reason == "hour":
        return str(int(moment // HOUR_SECONDS))
    return _local_day(moment)


def _announce(reason: str, state: dict, moment: float) -> None:
    key = _window_key(reason, moment)
    if _announced.get(reason) == key:
        return
    _announced[reason] = key

    calls = state[reason]["calls"]
    cap = state["limits"]["calls_per_day" if reason == "day" else "calls_per_hour"]
    detail = f"{calls} model calls in the {reason} (cap {cap}); read-only until it rolls over"
    print(f"[Budget] {detail}")
    try:
        from agent import audit

        audit.record("budget", outcome=reason, detail=detail)
    except Exception:
        pass
    try:
        from agent import metrics

        metrics.inc("budget_breach", window=reason)
    except Exception:
        pass


# --- reporting ----------------------------------------------------------------

def status() -> dict:
    """The ledger plus where the ladder currently sits. Safe to call any time."""
    enforce()
    state = usage()
    try:
        from agent import degrade

        state["degradation"] = degrade.status()
    except Exception:
        state["degradation"] = None
    state["enabled"] = bool(config().get("enabled", True))
    state["ledger"] = str(LEDGER_PATH)
    return state


def clear() -> int:
    """Wipe the ledger. The audit log still records that it happened."""
    with _lock:
        ledger = _load()
        removed = len(ledger["calls"])
        _save(_empty())
    _announced.clear()
    _release_our_floor()
    try:
        from agent import audit

        audit.record("budget", outcome="cleared", detail=f"{removed} entries removed")
    except Exception:
        pass
    return removed


def reset_for_tests() -> None:
    global _announced
    with _lock:
        _announced = {}
        try:
            LEDGER_PATH.unlink()
        except OSError:
            pass


# --- CLI ----------------------------------------------------------------------

_USAGE = ("usage: python -m agent.quota [--text] [clear --yes]\n"
          "  (no arguments prints the ledger as JSON)")


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "clear":
        if "--yes" not in argv:
            print("refusing to clear without --yes")
            return 2
        print(f"cleared {clear()} ledger entries")
        return 0

    if argv and argv[0] == "--text":
        print(describe())
        return 0

    if argv and argv[0] not in ("--json",):
        print(_USAGE)
        return 2

    print(json.dumps(status(), indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
