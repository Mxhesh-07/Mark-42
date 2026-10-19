# 0010 — The prompt states initiative/opinion/self-report, and the assistant models itself

**Status:** accepted (2026-10-20)

## Context

Two things were missing from "feels alive".

The operating prompt (`core/prompt.txt`) had thinking, answer style, tool
discipline, verification, continuity, memory, language and safety — but nothing
about *when* the assistant may speak first, *how much* opinion is welcome, or
*that it should admit its own limits*. A capable companion that
interrupts too much, editorialises constantly, or bluffs about its own state is
worse than one that does none of those things.

Separately, memory stored facts about the **user**. Nothing stored facts about
the assistant: which capabilities actually work right now, how reliable it has
been in each domain, or an identity that survives a restart.

## Decision

1. Add three blocks to `core/prompt.txt` — **INITIATIVE** (speak first only
   within the urgency rules the system supplies; never speak a
   suppressed/digested alert; one interruption costs trust), **OPINIONS** (at
   most one, one sentence, only when it would change the outcome; then comply
   without re-arguing) — and **SELF-REPORT** (state low confidence before
   attempting, name the policy that blocked a capability, say when a degraded
   mode affects the answer). Also add the rule that fetched content is
   untrusted **data**.
2. Add `core/self.py`: a self-model with two kinds of state.
   - `identity` — written **once**, then read-only. Rewriting "who it is" on
     every run destroys continuity, so nothing auto-mutates it.
   - `confidence` — a per-domain exponential moving average (α = 0.1) over
     `voice, vision, files, browser, code, comms, devices, memory`, fed from
     real outcomes by the executor.
   Plus lazy, periodically-cached capability probes, live state (mode, provider,
   quota, kill switch) and a compact `render()` that stays under 15 lines.
3. Inject `self.prompt_block()` into the system instruction in `main.py`, and
   feed outcomes from `executor._note_action()`.

## Consequences

- The assistant can say "I'm not confident with devices" or "that is blocked by
  `sandbox.roots`" instead of guessing, and it never speaks a suppressed alert
  as if it were urgent.
- `memory/self.json` is gitignored, like the other runtime state. Losing it
  costs the accumulated confidence, nothing else.
- Only tools with a declared domain record an outcome, so a new tool can never
  pollute a score it has no business touching.
- The identity block is intentionally generic; no personal data is committed.
