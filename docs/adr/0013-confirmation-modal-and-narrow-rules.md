# 0013 — A confirmation is answered in the UI, and "always allow" is narrow

**Status:** accepted (2026-10-20)

## Context

The permission gate returns `confirm`, and the unattended executor fails closed
when no approver is configured. That is the correct default, but it meant the
project's best safety work was invisible: the user asked for something, the
policy asked for a confirmation, and *nothing appeared*. The old `ui.py` had no
way to ask.

The obvious fix — a modal — has an obvious failure mode too. "Always allow" is the
button users press to make a dialog stop appearing, and the lazy implementation
writes a tool-wide rule, turning one careful decision into a permanent hole.

## Decision

1. **`ui/confirm.py` renders the modal; it never decides.** Deny holds the focus,
   the window close button denies, a 30 s countdown denies, and a missing display
   denies. Nothing in the module can approve by accident.
2. **The Tk event loop is never blocked.** `ask` runs on the executor's worker
   thread; the dialog is built on the Tk thread via `root.after` and the worker
   waits on a `threading.Event`. The Tk thread only builds a window.
3. **One audit entry per decision**, naming the outcome and why (`chosen`,
   `timeout`, `dialog failed`, `no UI available`).
4. **"Always allow" writes the narrowest rule that still covers the decision**
   (`agent/approval_rules.py`): one tool, the discriminating action, and exactly
   one resolved target — a path, a recipient, a host. A rule cannot cover a
   different path, a different recipient or a different action, and a call with
   nothing narrow to bind to (a shell command, a generated script) does not offer
   the button at all.
5. **Rules are consulted last.** `policy._guards` upgrades `CONFIRM` to `ALLOW`
   for a matching rule *only after* every hard guard has run, and *only for the
   owner*. A rule can never lift the kill switch, a sandbox escape or a refused
   command, and can never widen a guest.
6. **Rules are state, not config.** They live in the gitignored
   `config/approval_rules.json`, like approvals and memories.

The executor also stopped computing the opinion itself and now receives the whole
`judgement.Assessment`, so the modal shows the same risk the executor saw. The
approver call is backward compatible: an approver that only takes three arguments
still works.

## Consequences

- `ui.py` became the package `ui/` so `ui.confirm` could exist beside it. That is
  the first step of the T3.3 split; `get_base_dir()` now walks up one level.
- The live voice path is unchanged: a spoken request is still its own
  authorisation, so the modal only appears for the background agent.
- Every rule is revocable: `python -m agent.approval_rules clear`, or delete one
  by re-issuing it as a deny.
