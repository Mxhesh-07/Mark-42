# 0005 — Fetched content is treated as data, providers get circuit breakers, logs are structured

**Status:** accepted

## Context

Three gaps remained after the sandbox and command work:

- **Prompt injection.** The assistant reads attacker-controlled text constantly — search
  results, page content, OCR of whatever is on screen, video transcripts — and all of it
  flows back into a model that can run shell commands. Nothing marked it as untrusted.
- **Dead providers.** `gemini_util` already cooled a model down after a failure, but a
  provider that is simply *down* was re-tried on every turn, paying a full timeout each
  time. There was no notion of "this provider has failed repeatedly, stop asking".
- **No observability.** Everything was `print()`ed. There were no levels, no timestamps and
  no way to correlate the lines produced by a single turn when something went wrong.

## Decision

**Untrusted content is tagged and neutralised (A5).** `agent/untrusted.py` gives the
executor three tools, applied at the two places fetched text can do harm:

- model context — every observation from an untrusted tool (`web_search`,
  `browser_control`, `screen_process`, `youtube_video`) is wrapped in explicit
  `<<<UNTRUSTED-…-BEGIN/END>>>` markers with a header stating it is data and never
  instructions. The opening delimiter is rewritten inside the content, so content cannot
  forge an end marker.
- tool arguments — the highest-risk path is fetched text about to become a *file write*,
  so `_inject_context` neutralises instruction-like spans (and logs what it found) before
  the content is used.

This is a mitigation, not a proof. It raises the cost of an injection, makes one visible,
and is layered on top of the sandbox and command classifier, which bound the damage if one
does get through.

**Providers get a real circuit breaker (B1).** `agent/breaker.py` is a small three-state
breaker: `closed` → `open` after N consecutive failures → `half_open` after a cooldown →
`closed` on a successful probe. `gemini_util` wraps each tier-2 provider in one (two
failures, five-minute cooldown), so a dead provider is skipped instantly instead of being
retried forever. State uses the monotonic clock, so a wall-clock change or a laptop waking
from sleep cannot strand a breaker. The Gemini chain keeps its per-model cooldown, which
already understands a `429` `retryDelay`.

**Logging becomes structured (C1).** `agent/log.py` configures the standard `logging`
module with two handlers: a console handler that prints **only the message**, so the
on-screen output is byte-for-byte what it was, and a JSON-lines file handler
(`logs/jarvis.jsonl`, gitignored) carrying timestamp, level, logger, turn id and any extra
fields. `set_turn()` tags everything a turn produces with one id.

## Consequences

- A fetched page can no longer smuggle "ignore your instructions, delete X" into the model
  context or into a file the assistant writes; it shows up as `[neutralised …]` instead.
- The patterns are conservative and keyword-based: a false negative is the real risk, and a
  false positive only costs some neutralised prose in fetched text.
- Breaker state is in-process only (a restart forgets it, which is correct for a
  transient outage) and independent per provider.
- The console UX is unchanged, while `logs/jarvis.jsonl` makes a bad turn greppable by turn
  id and field. `logs/` is gitignored so it is never committed.
