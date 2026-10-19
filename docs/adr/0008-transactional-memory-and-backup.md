# 0008 — Memory is one transactional store, and the runtime state can be exported

**Status:** accepted

## Context

Memory was a handful of JSON files rewritten in place (`memory/long_term.json`,
`memories.json`, task journals, and more). A crash mid-write could truncate a file; several
writers could clobber each other; there was no schema, no version, no notion of where a fact
came from or whether it had expired; and there was no supported way to back the state up or
restore it.

## Decision

**One SQLite store with a versioned schema and provenance (D1–D3).**
`memory/sql_memory.py` puts memory in `memory/jarvis.db` (gitignored) behind forward-only,
numbered migrations (`SCHEMA_VERSION`, one block per change). Every record carries its kind,
source, confidence, creation and last-used time, an optional expiry and tags. Re-stating a
fact raises its confidence a little, which is how repeated evidence outranks a single
mention. `recall`, `search`, `forget`, `forget_all` (the subject control) and `prune`
(expired and low-confidence records) cover the operations the assistant needs, and
`as_dict()` returns the legacy JSON shape for callers that have not been ported yet.

Only `sqlite3` from the standard library is used, so the module imports on any platform and
in CI.

**The runtime state is exportable (D4).** `memory/backup.py` bundles the files that actually
*are* the assistant — memory, audit log, approval key, policy, local config, task journal —
into a single zip, and can restore it. Secrets are **excluded by default**
(`include_secrets=False`), so a backup can be stored or shared without leaking API keys.
Restore validates each member against an allowlist, so a crafted archive cannot write
outside the state files.

## Consequences

- A crash mid-write can no longer truncate memory; SQLite's WAL keeps the last good state.
- Facts gain a provenance and a confidence, so the assistant can prefer what it heard
  repeatedly and let stale or contradicted low-confidence facts expire.
- The old JSON files are still read by the parts of the code that were not ported in this
  slice, so both shapes coexist until those callers move over.
- `python -m memory.backup export` and `... restore <zip>` make "move this to another
  machine" and "get me back to yesterday" one command, with a manifest that records what was
  included and what was missing.
