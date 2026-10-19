# 0003 — The audit log is append-only and hash-chained

**Status:** accepted

## Context

When the assistant acts on the user's behalf, the record of *what it did and why* is the
only evidence available afterwards. A plain text log is trivially editable: anyone (or
any bug) can quietly change, reorder or delete a line and the log still looks plausible.
The log also has to survive indefinite use without growing without bound.

## Decision

`agent/audit.py` writes one JSON object per line (JSONL) and never rewrites history,
with two extras:

1. **Hash chain.** Each entry stores `prev` (the previous entry's hash) and its own
   `hash` = `sha256(prev + canonical_json(entry_without_hash))`. Editing an entry changes
   its hash and breaks every later `prev`; deleting or reordering a line breaks the link.
2. **Adaptive trimming.** Only the newest lines are kept, so the file stays bounded. The
   first line of a trimmed file is treated as the chain start, which is why verification
   checks links from the second line onward.

`python -m agent.audit verify` recomputes the chain and reports the first problem;
`tail [n]` prints recent entries. Entries written before the chain existed have no `hash`
and are reported as skipped, so older logs verify cleanly.

## Consequences

- Tampering is *detectable*, not preventable — the log is local, so an attacker with
  write access can rebuild a consistent chain from scratch. That is acceptable: the goal
  is to catch accidents and casual edits, and to make silent edits evident.
- Verification is O(n) in the retained log and runs standalone from the CLI.
- Adding a field to an entry is safe; changing the canonicalisation is a breaking change
  and would invalidate existing chains.
