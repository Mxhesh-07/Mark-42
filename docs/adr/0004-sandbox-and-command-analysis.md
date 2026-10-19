# 0004 — File tools are sandboxed and shell commands are classified

**Status:** accepted

## Context

Two tools are the widest attack surface in the app:

- `file_controller` takes an arbitrary path. The assistant reads untrusted text all day —
  web pages, emails, OCR output — and a prompt injection in any of it could aim a delete
  or read anywhere on disk.
- `cmd_control` runs a shell command. A `confirm` prompt is a weak control when the user
  cannot tell what the command does, and confirm-fatigue makes it weaker over time.

## Decision

**Paths are confined to allowlisted roots (A2).** `agent/sandbox.py` checks every path
parameter against `sandbox.roots` in the policy. The path is resolved — symlinks and `..`
included — *before* the comparison, so neither can be used to climb out, and the check
denies by default. Roots come from config only, never from the model.

**Commands are classified before they run (A3).** `agent/command_policy.py` sorts a
command into three buckets:

- read-only → allowed without a prompt (so the user only ever confirms real risk);
- destructive → refused outright (recursive delete, `format`, `diskpart`, `reg delete`,
  `shutdown`, …);
- anything else → confirmed, including any command that chains or redirects (`&&`, `|`,
  `>`), because the safe-looking prefix of `dir && del x` says nothing about the rest.

Both guards are applied inside `policy.evaluate` (ADR 0001), so they cannot be bypassed
by a caller forgetting them.

## Consequences

- A prompt injection has to work within the sandbox, and the worst shell commands are
  unreachable even with a "yes" from the user.
- Legitimate work outside the roots needs a one-line addition to `config/autonomy.json`.
- The classifier is a denylist plus a small allowlist, so it is conservative by design:
  an unrecognised command is confirmed, never silently allowed.
