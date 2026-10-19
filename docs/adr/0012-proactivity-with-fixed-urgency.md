# 0012 — Proactivity is capped by fixed urgency, budgets and quiet hours

**Status:** accepted (2026-10-20)

## Context

The assistant reacted to requests and to email, but nothing decided *when it may
speak first, or how loudly*. Adding that decision naively produces the worst
failure mode a companion can have: nagging. A system that decides at runtime
that an alert is "actually urgent" will eventually interrupt you about the
battery while you are on a call.

## Decision

`agent/initiative.py` runs a fixed pipeline:

```
Trigger --check()--> signal? --cooldown--> --suppression caps--> Candidate --dispatch--> SILENT|DIGEST|NOTIFY|SPEAK|INTERRUPT
```

1. **Urgency is a fixed property of a trigger** (0 SILENT … 4 INTERRUPT) and is
   declared at registration. Nothing at runtime can raise it. The user's config
   may only *lower* it (the configured value is applied as a cap, never a raise).
2. **Suppression caps**, first match sets the reason:
   * kill switch → drop everything
   * quiet hours (default 23:00–07:00) → cap at DIGEST
   * user is speaking / focus mode / meeting → cap at NOTIFY
   * hourly interrupt budget (3) or speak budget (10) exhausted → cap at NOTIFY
3. **Budgets are counted at dispatch, not at evaluate.** A candidate that was
   never spoken must not consume the right to speak; a DIGEST must not spend the
   SPEAK budget.
4. **Cooldowns are per trigger** and are consumed at evaluate, even when the
   candidate is then dropped — otherwise a SILENT trigger would be re-logged on
   every tick.
5. The **tick rides the existing task-queue worker loop**, throttled to once per
   30 s. No new thread, and no busy loop: that loop can spin freely while a task
   is in flight, which is exactly why the throttle exists.
6. Dispatch writes **exactly one** `initiative` audit entry per candidate, and
   hands the text to a sink: the live voice when a session is up, the HUD
   otherwise. A broken sink is caught and never breaks the tick.

Starter triggers are best-effort probes (battery, disk, calendar clash, deadline,
long focus stretch) that answer `None` when their data source is unavailable. The
three that need a source this process does not own — important email, quota, a
remote device — are **seams**: `initiative.provide(name, fn)` switches them on.

## Consequences

- Nothing ships at urgency 4, and a test asserts it: an interruption is not a
  thing the code can do by default.
- `config/autonomy.json` → `initiative` is the only place to tune it, and the
  engine is off in one key (`"enabled": false`).
- Adding a trigger never requires touching the engine; a new trigger cannot
  exceed whatever its declared urgency allows.
