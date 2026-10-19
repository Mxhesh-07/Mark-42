"""Proactivity with restraint (Tier 4 W1).

The assistant already reacts — to a request, to an email. Nothing decided *when
it may speak first, and how loudly*. This module is that decision, and the whole
of it is designed around one failure mode: nagging. A companion that interrupts
you about the battery three times an hour is worse than one that says nothing.

The chain is a fixed pipeline:

    Trigger  --check()-->  signal?  --cooldown-->  --suppression caps-->
             Candidate(urgency)  --dispatch-->  SILENT / DIGEST / NOTIFY / SPEAK / INTERRUPT

**Urgency is a fixed property of a trigger.** Nothing at runtime can raise it —
only the user's config can lower it. That is the single rule that keeps this from
drifting into a system that decides an alert is more urgent than it is.

**Suppression caps, in order** (the first one that applies sets the reason):

    1. kill switch engaged   drop everything
    2. quiet hours           cap at DIGEST  (1)
    3. user is speaking      cap at NOTIFY  (2)
    4. focus mode            cap at NOTIFY  (2)
    5. meeting detected      cap at NOTIFY  (2)
    6. interrupt budget out  cap at NOTIFY  (2)
    7. speak budget out      cap at NOTIFY  (2)

**Budgets** are counted at dispatch, not at evaluate: a candidate that was never
spoken must not consume the right to speak. Cooldowns are per trigger.

The tick comes from the existing task-queue loop — no extra thread. Dispatch
hands the text to the configured sink and writes exactly one ``initiative`` audit
entry.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SILENT, DIGEST, NOTIFY, SPEAK, INTERRUPT = 0, 1, 2, 3, 4
LEVELS = ("SILENT", "DIGEST", "NOTIFY", "SPEAK", "INTERRUPT")
_INDEX = {name: i for i, name in enumerate(LEVELS)}
WINDOW_S = 3600.0
IDLE_RESET_S = 900.0          # >15 min of silence ends a focus stretch

DEFAULT_CONFIG = {
    "enabled": True,
    "max_interrupts_per_hour": 3,
    "max_speaks_per_hour": 10,
    "min_urgency": 1,               # below this a candidate is logged and dropped
    "quiet_hours": ["23:00", "07:00"],
    "triggers": {
        "battery_low": "speak",
        "long_focus_break": "digest",
    },
}


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
POLICY_PATH = BASE_DIR / "config" / "autonomy.json"


def _wall_seconds() -> float:
    lt = time.localtime()
    return lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec


def parse_hhmm(value) -> int | None:
    """``"23:00"`` -> seconds since midnight. ``None`` when unparseable."""
    try:
        text = str(value).strip()
        hours, _, minutes = text.partition(":")
        hours_i, minutes_i = int(hours), int(minutes)
    except Exception:
        return None
    if not (0 <= hours_i <= 23 and 0 <= minutes_i <= 59):
        return None
    return hours_i * 3600 + minutes_i * 60


# --- data ---------------------------------------------------------------

@dataclass(frozen=True)
class Trigger:
    """A thing worth knowing about, and the fixed loudness it may use.

    ``check`` returns a falsy value for "nothing to report", ``True`` for "fire
    with no payload", or a dict/str carrying the detail (used as the message).
    """

    id: str
    check: Callable[[], object]
    urgency: int
    cooldown_sec: int
    description: str

    def __post_init__(self) -> None:
        urgency = int(self.urgency)
        if urgency < SILENT or urgency > INTERRUPT:
            raise ValueError(f"urgency must be {SILENT}..{INTERRUPT}, got {urgency}")


@dataclass(frozen=True)
class Candidate:
    """One firing, with the *effective* urgency after suppression."""

    trigger_id: str
    urgency: int
    payload: dict
    reason: str
    description: str = ""
    declared_urgency: int = 0
    suppressed_by: str = ""
    checked_at: float = 0.0

    @property
    def action(self) -> str:
        return LEVELS[max(0, min(INTERRUPT, int(self.urgency)))]

    @property
    def message(self) -> str:
        text = str(self.payload.get("message") or "").strip()
        return text or self.description or self.trigger_id

    def as_dict(self) -> dict:
        return {
            "trigger": self.trigger_id,
            "urgency": self.urgency,
            "action": self.action,
            "declared_urgency": self.declared_urgency,
            "suppressed_by": self.suppressed_by,
            "reason": self.reason,
            "message": self.message,
            "payload": self.payload,
        }


# --- the engine ----------------------------------------------------------------

class Initiative:
    """Holds the triggers, the suppression state and the budgets."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = _wall_seconds,
                 config: Callable[[], dict] | None = None) -> None:
        self._clock = clock
        self._wall = wall
        self._config_loader = config or load_config
        self._triggers: dict[str, Trigger] = {}
        self._last: dict[str, float] = {}
        self._events: list[tuple[float, int]] = []
        self._digest: list[Candidate] = []
        self._notifications: list[Candidate] = []
        self._focus = False
        self._user_speaking = False
        self._meeting = False
        self._activity_start: float | None = None
        self._activity_last: float | None = None
        self._speaker: Callable[[str], None] | None = None
        self._notifier: Callable[[str, str], None] | None = None
        self._lock = threading.RLock()

    # -- registration ----------------------------------------------------------

    def register(self, trigger: Trigger) -> None:
        with self._lock:
            self._triggers[trigger.id] = trigger

    def unregister(self, trigger_id: str) -> None:
        with self._lock:
            self._triggers.pop(trigger_id, None)
            self._last.pop(trigger_id, None)

    def triggers(self) -> list[str]:
        with self._lock:
            return sorted(self._triggers)

    def configure(self, *, speaker=None, notifier=None) -> None:
        """Set the dispatch sinks. ``speaker(text)``, ``notifier(title, text)``."""
        with self._lock:
            if speaker is not None:
                self._speaker = speaker
            if notifier is not None:
                self._notifier = notifier

    # -- context ---------------------------------------------------------------

    def set_focus(self, on: bool) -> None:
        with self._lock:
            self._focus = bool(on)

    def set_user_speaking(self, on: bool) -> None:
        with self._lock:
            self._user_speaking = bool(on)

    def set_meeting(self, on: bool) -> None:
        with self._lock:
            self._meeting = bool(on)

    def note_activity(self) -> None:
        """Called on a user turn, so 'you have been at this for 2h' is real."""
        now = self._clock()
        with self._lock:
            if self._activity_last is None or (now - self._activity_last) > IDLE_RESET_S:
                self._activity_start = now
            self._activity_last = now

    def focus_stretch_sec(self) -> float:
        with self._lock:
            if self._activity_start is None:
                return 0.0
            return max(0.0, self._clock() - self._activity_start)

    # -- evaluation ------------------------------------------------------------

    def evaluate(self) -> list[Candidate]:
        """Run every trigger once and return what is worth reporting."""
        config = self._config_loader() or {}
        if not bool(config.get("enabled", True)) or self._killed():
            return []

        now = self._clock()
        self._prune(now)
        min_urgency = int(config.get("min_urgency", DEFAULT_CONFIG["min_urgency"]))
        found: list[Candidate] = []

        with self._lock:
            triggers = sorted(self._triggers.values(), key=lambda t: (-t.urgency, t.id))
            last_seen = dict(self._last)

        for trigger in triggers:
            # The check runs exactly once per tick: these are probes, and some of
            # them touch the disk or the network.
            raw = self._signal(trigger)
            if not raw:
                continue

            cooldown = max(0, int(trigger.cooldown_sec))
            previous = last_seen.get(trigger.id)
            if previous is not None and (now - previous) < cooldown:
                continue

            declared = self._declared_urgency(trigger, config)
            effective, suppressed_by = self._suppress(declared, config)

            with self._lock:
                self._last[trigger.id] = now

            if effective < min_urgency:
                self._metric("dropped", trigger.id)
                continue

            payload = self._payload(raw)
            found.append(Candidate(
                trigger_id=trigger.id,
                urgency=effective,
                payload=payload,
                reason=self._reason(trigger, declared, effective, suppressed_by),
                description=trigger.description,
                declared_urgency=declared,
                suppressed_by=suppressed_by,
                checked_at=now,
            ))
            self._metric("candidate", trigger.id)

        found.sort(key=lambda c: (-c.urgency, c.trigger_id))
        return found

    def dispatch(self, candidate: Candidate) -> str:
        """Act on one candidate. Returns the action actually taken."""
        if self._killed():
            self._metric("dispatch", "DROPPED")
            return "DROPPED"

        action = candidate.action
        text = candidate.message
        with self._lock:
            if action == "DIGEST":
                self._digest.append(candidate)
            elif action == "NOTIFY":
                self._notifications.append(candidate)
            elif action in ("SPEAK", "INTERRUPT"):
                self._events.append((self._clock(), int(candidate.urgency)))

        try:
            if action in ("SPEAK", "INTERRUPT"):
                if self._speaker is not None:
                    self._speaker(text)
                else:
                    self._hud(text)      # no live voice yet: say it in the HUD
            elif action == "NOTIFY":
                if self._notifier is not None:
                    self._notifier("JARVIS", text)
                else:
                    self._hud(text)
            elif action == "DIGEST":
                self._hud(text)
            # SILENT: log only, which the audit line below is.
        except Exception as e:            # a broken sink must never break the tick
            print(f"[Initiative] ⚠️ dispatch sink failed: {e}")

        self._audit(candidate, action)
        self._metric("dispatch", action)
        return action

    def tick(self) -> list[tuple[str, str]]:
        """evaluate + dispatch in one step — what the queue loop calls."""
        return [(c.trigger_id, self.dispatch(c)) for c in self.evaluate()]

    # -- budgets and state -----------------------------------------------------

    def budget_state(self) -> dict:
        config = self._config_loader() or {}
        now = self._clock()
        self._prune(now)
        with self._lock:
            return {
                "window_sec": WINDOW_S,
                "interrupts": {"used": self._used(INTERRUPT),
                               "max": int(config.get("max_interrupts_per_hour", 3))},
                "speaks": {"used": self._used(SPEAK),
                           "max": int(config.get("max_speaks_per_hour", 10))},
                "quiet": self._quiet(now),
                "focus": self._focus,
                "user_speaking": self._user_speaking,
                "meeting": self._meeting,
                "focus_stretch_sec": self.focus_stretch_sec(),
                "digest_pending": len(self._digest),
                "notifications_pending": len(self._notifications),
                "triggers": sorted(self._triggers),
            }

    def take_digest(self) -> list[Candidate]:
        with self._lock:
            items, self._digest = self._digest, []
            return items

    def take_notifications(self) -> list[Candidate]:
        with self._lock:
            items, self._notifications = self._notifications, []
            return items

    def reset_for_tests(self) -> None:
        with self._lock:
            self._triggers.clear()
            self._last.clear()
            self._events.clear()
            self._digest.clear()
            self._notifications.clear()
            self._focus = self._user_speaking = self._meeting = False
            self._activity_start = self._activity_last = None
            self._speaker = self._notifier = None

    # -- internals -------------------------------------------------------------

    def _signal(self, trigger: Trigger):
        try:
            return trigger.check()
        except Exception:
            return None

    @staticmethod
    def _payload(signal) -> dict:
        if isinstance(signal, dict):
            return dict(signal)
        if isinstance(signal, str):
            return {"message": signal}
        return {}

    def _declared_urgency(self, trigger: Trigger, config: dict) -> int:
        """The trigger's fixed urgency, optionally *lowered* by the user's config."""
        declared = max(0, min(INTERRUPT, int(trigger.urgency)))
        configured = (config.get("triggers") or {}).get(trigger.id)
        if isinstance(configured, str):
            cap = _INDEX.get(configured.upper())
            if cap is not None:
                declared = min(declared, cap)
        return declared

    def _suppress(self, urgency: int, config: dict) -> tuple[int, str]:
        caps: list[tuple[int, str]] = []
        now = self._clock()
        with self._lock:
            focus = self._focus
            speaking = self._user_speaking
            meeting = self._meeting
        if self._quiet(now):
            caps.append((DIGEST, "quiet hours"))
        if speaking:
            caps.append((NOTIFY, "user is speaking"))
        if focus:
            caps.append((NOTIFY, "focus mode"))
        if meeting:
            caps.append((NOTIFY, "meeting in progress"))
        if urgency >= INTERRUPT:
            if self._used(INTERRUPT) >= int(config.get("max_interrupts_per_hour", 3)):
                caps.append((NOTIFY, "interrupt budget exhausted"))
        elif urgency >= SPEAK:
            if self._used(SPEAK) >= int(config.get("max_speaks_per_hour", 10)):
                caps.append((NOTIFY, "speak budget exhausted"))

        effective, reason = urgency, ""
        for cap, why in caps:
            if cap < effective:
                effective, reason = cap, why
        return effective, reason

    @staticmethod
    def _reason(trigger: Trigger, declared: int, effective: int, suppressed_by: str) -> str:
        base = trigger.description or trigger.id
        if suppressed_by:
            return f"{base} (urgency {declared} capped to {effective}: {suppressed_by})"
        return f"{base} (urgency {declared})"

    def _prune(self, now: float) -> None:
        with self._lock:
            self._events = [(ts, u) for ts, u in self._events if (now - ts) < WINDOW_S]

    def _used(self, level: int) -> int:
        with self._lock:
            return sum(1 for _ts, urgency in self._events if urgency >= level)

    def _quiet(self, now: float) -> bool:
        window = (self._config_loader() or {}).get("quiet_hours",
                                                  DEFAULT_CONFIG["quiet_hours"])
        if not isinstance(window, (list, tuple)) or len(window) != 2:
            return False
        start = parse_hhmm(window[0])
        end = parse_hhmm(window[1])
        if start is None or end is None or start == end:
            return False
        seconds = self._wall()
        if start < end:
            return start <= seconds < end
        return seconds >= start or seconds < end      # wraps midnight

    def _killed(self) -> bool:
        try:
            from agent import policy

            return bool(policy.kill_requested())
        except Exception:
            return False

    def _hud(self, text: str) -> None:
        try:
            from ui import jarvis_think

            jarvis_think("sys", text)
        except Exception:
            print(f"[Initiative] {text}")

    def _audit(self, candidate: Candidate, action: str) -> None:
        """Exactly one entry per dispatched candidate."""
        try:
            from agent import audit

            audit.record("initiative", tool=candidate.trigger_id, level=action.lower(),
                         outcome=action.lower(), detail=candidate.reason,
                         urgency=candidate.urgency, payload=candidate.payload)
        except Exception:
            pass

    @staticmethod
    def _metric(counter: str, label: str) -> None:
        try:
            from agent import metrics

            metrics.inc(f"initiative.{counter}", outcome=label)
        except Exception:
            pass


# --- configuration -------------------------------------------------------------

def load_config() -> dict:
    """The ``initiative`` block of config/autonomy.json, or {} when absent."""
    try:
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    block = raw.get("initiative") if isinstance(raw, dict) else None
    return block if isinstance(block, dict) else {}


# --- starter triggers ----------------------------------------------------------
#
# Every check is best-effort: a missing data source means "nothing to report",
# never an exception. The three that need a source this process does not own
# (important email, quota, a remote device) are seams — call provide(name, fn)
# to switch them on.

_SOURCES: dict[str, Callable[[], object]] = {}


def provide(name: str, check: Callable[[], object]) -> None:
    """Register a data source for a trigger that needs one."""
    _SOURCES[name] = check


def _source(name: str):
    return _SOURCES.get(name)


def check_battery_low() -> dict | None:
    """Laptop battery under 20% and not charging."""
    try:
        import psutil

        battery = psutil.sensors_battery()
        if battery is None or battery.power_plugged:
            return None
        percent = float(battery.percent)
        if percent < 20:
            return {"message": f"Your battery is at {percent:.0f}%.",
                    "percent": percent}
    except Exception:
        pass
    return None


def check_disk_full() -> dict | None:
    """The drive holding the project under 10% free."""
    try:
        import shutil

        usage = shutil.disk_usage(str(BASE_DIR))
        if not usage.total:
            return None
        free_percent = 100.0 * usage.free / usage.total
        if free_percent < 10:
            return {"message": f"Only {free_percent:.0f}% is left on the drive "
                               f"holding the project.",
                    "free_percent": round(free_percent, 1)}
    except Exception:
        pass
    return None


def check_calendar_conflict() -> dict | None:
    """Two events today sharing a start time (the only overlap this model has)."""
    try:
        from business_tools import get_today_events

        events = get_today_events() or []
        seen: dict[str, str] = {}
        for event in events:
            slot = str(event.get("time") or "").strip()
            if not slot:
                continue
            title = str(event.get("title") or "an event")
            if slot in seen:
                return {"message": f"'{title}' and '{seen[slot]}' are both at {slot}.",
                        "time": slot, "titles": [seen[slot], title]}
            seen[slot] = title
    except Exception:
        pass
    return None


def check_deadline_near() -> dict | None:
    """A pending task due within 24 hours."""
    try:
        from datetime import datetime

        from work_assistant import get_pending_tasks

        now = datetime.now()
        for task in get_pending_tasks() or []:
            due = str(task.get("due") or "").strip()
            if not due:
                continue
            try:
                when = datetime.fromisoformat(due.replace("Z", ""))
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d-%m-%Y"):
                    try:
                        when = datetime.strptime(due, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
            hours = (when - now).total_seconds() / 3600.0
            if 0 <= hours <= 24:
                title = str(task.get("title") or "a task")
                return {"message": f"'{title}' is due in about {hours:.0f}h.",
                        "hours": round(hours, 1), "title": title}
    except Exception:
        pass
    return None


def _seam(name: str):
    def check():
        source = _source(name)
        if source is None:
            return None
        try:
            return source()
        except Exception:
            return None

    return check


def check_focus_stretch(factory: Callable[[], float]) -> Callable[[], dict | None]:
    """Build the '>2h without a break' check around a focus clock."""

    def check() -> dict | None:
        try:
            stretch = float(factory())
        except Exception:
            return None
        if stretch >= 7200.0:
            return {"message": "You have been at this for over two hours — "
                               "worth a break.",
                    "seconds": round(stretch)}
        return None

    return check


def default_triggers(engine: Initiative) -> list[Trigger]:
    """The starter set, with urgency fixed as the spec declares it."""
    return [
        Trigger("battery_low", check_battery_low, 3, 1800, "battery is low"),
        Trigger("disk_full", check_disk_full, 3, 3600, "the drive is nearly full"),
        Trigger("calendar_conflict", check_calendar_conflict, 3, 300,
                "two calendar events clash"),
        Trigger("deadline_near", check_deadline_near, 2, 3600,
                "a task is due within a day"),
        Trigger("email_important", _seam("email_important"), 2, 600,
                "an important email arrived"),
        Trigger("long_focus_break", check_focus_stretch(engine.focus_stretch_sec), 1,
                7200, "a long stretch without a break"),
        Trigger("quota_exhausted", _seam("quota_exhausted"), 2, 1800,
                "the provider quota is spent"),
        Trigger("device_offline", _seam("device_offline"), 2, 900,
                "a device is unreachable"),
    ]


# --- the shared instance -------------------------------------------------------

_engine: Initiative | None = None
_engine_lock = threading.Lock()


def get() -> Initiative:
    """The process-wide engine, with the starter triggers registered."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = Initiative()
            for trigger in default_triggers(_engine):
                _engine.register(trigger)
        return _engine


def reset() -> None:
    """Drop the shared instance (tests, and a full restart)."""
    global _engine
    with _engine_lock:
        _engine = None


def tick() -> list[tuple[str, str]]:
    """One tick of the shared engine. Never raises."""
    try:
        return get().tick()
    except Exception:
        return []


# --- CLI ----------------------------------------------------------------------

def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "tick":
        print(json.dumps([{"trigger": t, "action": a} for t, a in tick()],
                         indent=2, default=str))
        return 0
    if argv and argv[0] == "send":
        from agent.initiative import Candidate

        engine = get()
        for text in argv[1:]:
            engine.dispatch(Candidate("cli", NOTIFY, {"message": text}, "cli", "cli"))
        return 0
    print(json.dumps({"triggers": get().triggers(),
                      "budget": get().budget_state()}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
