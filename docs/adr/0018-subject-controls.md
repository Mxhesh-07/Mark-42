# 0018 — "Forget everything about me" means every store, and the receipt proves it

**Status:** accepted (2026-10-20)

## Context

`D5` shipped subject control over the SQLite memory table: `sql_memory.forget_all()`
empties `memories`. That is one of roughly a dozen places a fact about the user
survives, and the other eleven are not edge cases:

- `memory/long_term.json` — the distilled profile the prompt is built from
- `memory/memories.json` — AIMemory: preferences, projects, notes
- `memory/procedural_memory.json`, `memory/agent_tasks.json`
- `memory/self.json` — what the assistant observed about itself
- `memory/quota_ledger.json` — which models were used, and when
- `voice_profiles.json` — a **voiceprint**, i.e. biometric data
- `companion_experiences.json`, `notifications.json`
- `memory/crashes/*.json` — crash bundles, which quote the prompt
- `memory/audit_log.jsonl` — every gated action, with details in the clear

A control that clears one of these and reports "done" is worse than no control:
the user believes their data is gone, acts on that belief, and is wrong. The
failure is not the leftover file, it is the false assurance.

There is also the question of what "everything" must **not** mean. `config/*.json`
holds API keys and mail credentials; `memory/approval.key` signs the approval
tokens the permission gate depends on. Deleting those does not forget a person —
it breaks the assistant and, in the key's case, invalidates every signed approval.

## Decision

`agent/forget.py` is the single subject-control surface, and its defining
property is that **the dry run and the receipt agree**. `inventory()` reports how
many records each store holds; `forget_all()` returns the same shape with what it
removed and what is left. A test asserts the promised count equals the removed
count per store, so the two can never drift into disagreement.

Details that matter:

- **`_store_path()` is the one resolver.** Stores are looked up at call time, not
  captured at import. During implementation this caught two real bugs: an
  import-time path that would have kept pointing at the *real* file after a
  redirect, and a seed that wrote `memories.json` to a different directory than
  the reader used. Tests assert the resolver's paths equal the seeded paths.
- **Emptying is not deleting.** JSON stores are rewritten to their empty shape
  (`{}` or `[]`) so their readers still find valid JSON. Crash bundles *are*
  deleted — nothing reads them expecting a file.
- **Records, not keys.** Counting is record-aware: the ledger is
  `{version, calls:[…]}`, and counting top-level keys would call an empty ledger
  "2 records".
- **The audit log is cleared last, then written to.** Deleting it is a real right —
  an audit log that cannot be deleted is not a subscription, it is a trap — but
  deleting it silently would also erase the record of the deletion. So the
  tombstone is the first entry of the new log: it says the log was wiped, when,
  and how many entries went, and the hash chain restarts from there.
- **The tombstone is not user data.** A `forget` entry is excluded from the count
  of "things to forget", so a second forget correctly reports having removed
  nothing.
- **Voiceprints are opt-out.** A user asking to be forgotten is not asking to
  keep their voice on file.
- **`inventory()` names what it keeps**, so the boundary is visible rather than
  implied.

It ships as a tool (`forget`, actions `report` / `export` / `forget`), with the
gate at `confirm`. The dry run is the default action, so a bare call reports
rather than deletes, and the approval modal shows the exact effect before anything
runs — the same A1 intent-binding rule every other destructive tool obeys. The
tool name is in `policy._WRITE_TOOLS`, so a budget breach (ADR 0017) or an
infrastructure degradation stops it with the same rule that stops a shell
command. Export delegates to `memory.backup`, so there is one archive format and
credentials stay out unless explicitly requested.

## Consequences

- "forget everything" is now honest, and auditable: the audit entry records the
  deletion, and the count is the number the dry run showed.
- The gate is coarser than the tool: `report` is grouped with `forget` under one
  name, so READ_ONLY blocks the report too. Deliberate — one decision per tool
  name, and the cost of a coarser rule is that the report waits until the ladder
  recovers.
- `A6` (secrets at rest) is still open, and `config/*.json` remains out of scope
  for this control by design.
