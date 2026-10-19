# 0017 — A spend cap is a floor on the degradation ladder, not a step down it

**Status:** accepted (2026-10-20)

## Context

The ladder in `agent/degrade.py` moves on evidence: two consecutive failures
drop a step, three consecutive successes climb one back. That is the right rule
for a flaky network — it stops the system flapping between full and crippled.

It is the wrong rule for a budget. `I2` asks for hard caps per hour and per day,
and a cap that is lifted by *three calls going well* is not a cap: the runaway
loop that exhausted the budget is exactly the thing generating those "successes".
Stepping the ladder down would be undone a second later, on the next three turns
of the same loop.

Two further pieces of context shaped the design:

- The gate already enforces READ_ONLY. `policy._guards` refuses every write when
  `degrade.level()` is `READ_ONLY`, so the budget guard does not need its own
  enforcement path — it needs to move the ladder, and the existing rule does the
  rest. Duplicating it would create a second place for the two to disagree.
- A cap on *model calls* cannot mean "stop talking". Reads still need the model,
  and so does the answer to "why have my tools stopped working?". The cap has to
  bite on **effects**, not on speech.

## Decision

`agent/quota.py` keeps a ledger and enforces caps through a new primitive:
`degrade.set_floor(level, why)`.

A floor is like an override that only works downwards. The ladder may still fall
further — a real infrastructure failure during a budget breach should still be
able to reach MONITOR — but it can never climb above the floor. The floor is a
*view* constraint: it does not move the underlying level, so clearing it puts
the ladder back exactly where it was rather than stranding it at the floor.

The details that matter:

- **Successful calls only.** One ledger entry per successful model call. A 429
  that walks six models before giving up costs nothing, so counting attempts
  would trip the guard during a free-tier outage and blame the user for it.
- **A rolling hour and a local calendar day.** A burst straddling the hour
  boundary must still count, so the hourly window is the last 60 minutes. "Today"
  means the user's today, so the daily window is the local calendar day.
- **One hook.** Every successful call — Gemini sync, Gemini async, and each
  tier-2 provider — funnels through `gemini_util._record_success`, which is where
  the ledger is written. Gemini model names carry no colon and tier-2 keys are
  `provider:model`, so the split is unambiguous.
- **Announced once per window**, on the console, in the audit log and as a
  metric, and surfaced at startup by `health.check_budget()` and in
  `health.status()["quota"]`. Silent degradation is the failure mode this
  project keeps designing against.
- **Accounting never breaks a conversation.** `_note_usage` swallows every
  exception; a ledger that cannot be written must not take a working session
  down.

Config lives in `config/autonomy.json` → `budget` with defaults of 60 calls/hour
and 400/day, both configurable to `0` for unlimited. `on_breach` has exactly one
implemented value (`read_only`) and an unrecognised value is treated as
read-only rather than as "off": a typo must not disable the guard.

`health.status()` deliberately calls `quota.usage()`, **not** `quota.status()`.
Status is a read-only view and must not be the thing that flips the ladder.

## Consequences

- The guard is enforced by the gate, in the one place every tool call passes
  through, so no caller can forget it.
- `degrade.set_floor` is a general primitive: any limit whose clock is not "a
  run of successes" can use it.
- `python -m agent.quota` shows the ledger and the caps; `clear --yes` wipes it
  and lifts its own floor (but never somebody else's).
- Prompt budgeting (`I4`) and cost-aware routing (`I3`) are still open; the
  ledger is the thing they will need to read.
