# 0007 — The assistant degrades gracefully and explains itself

**Status:** accepted

## Context

A long-running desktop assistant meets failures the gate cannot see: a provider that has
gone down, an audio device that has vanished, a disk that is nearly full, a microphone that
never opened. Before this work the assistant had two modes — running, or throwing — and
almost no way to answer "what was it doing when it went wrong?".

## Decision

**A degradation ladder (B2).** `agent/degrade.py` has four modes:

    FULL        voice in, voice out, tools, writes
    TEXT_ONLY   audio output falls back to the HUD; tools still run
    READ_ONLY   no writes, no shell, no messages — observation only
    MONITOR     logging and alerts only

Drops are driven by *infrastructure* failures — a provider circuit breaker tripping, an
audio device disappearing — never by an ordinary tool error, which is recorded as a metric
only. Recovery needs consecutive successes and climbs one step at a time. The ladder is
enforced in the gate: `READ_ONLY` refuses writes (and still allows reads), `MONITOR` refuses
tools, and both are `hard`. `TEXT_ONLY` is advisory — **nothing ever switches the microphone
off on its own**, because the voice path is the user-facing feature that must keep working.

**Clock discipline (B7).** `agent/clock.py` is the single place that decides which clock is
which: everything stored is UTC, everything shown is local, and every elapsed-time measure —
cooldowns, timeouts, watchdog deadlines — uses the monotonic clock, so a laptop sleeping or
an NTP correction can never fire a timer early, late, or never.

**Observability (C2/C3/C4/C6).** `agent/metrics.py` is a process-wide counter/gauge registry
that renders Prometheus text; the gate, breakers, executor and approvals write to it.
`agent/trace.py` keeps the stage timings of the current turn (tagged with the turn id from
`agent/log.py`). `agent/health.py` answers `/health` (subsystem checks), `/ready` (may a new
request start?) and `/status` (a full JSON dump), served read-only on loopback only, plus a
one-shot startup self-check (`python -m agent.health`). `agent/crash.py` writes a redacted
crash bundle to `memory/crashes/` — traceback, recent log tail, health snapshot, with API
keys, emails, home paths and phone numbers masked — so a bundle is safe to attach to a bug
report.

## Consequences

- A dead provider no longer produces a cascade of timeouts followed by silence; the
  assistant steps down, says so, and steps back up.
- Nothing here can silently disable the microphone. `TEXT_ONLY` only asks the audio-output
  path to fall back; enforcement in the gate is limited to writes and tools.
- Metrics are in-process and reset on restart (correct for gauges; counters are per-run).
- The health endpoint binds to `127.0.0.1` and is read-only; it reports keys as
  present/absent and never echoes a value.
- Crash bundles are capped (20 retained) and redacted, so they do not become a second secret
  leak.
