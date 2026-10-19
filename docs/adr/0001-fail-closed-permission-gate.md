# 0001 — One fail-closed permission gate

**Status:** accepted

## Context

Mark-42 can delete files, run shell commands and send messages as the user. Those
capabilities are reached from several places: the spoken path, the agent executor, task
queues and scheduled jobs. A per-caller permission check would inevitably drift, and the
"is this allowed?" rule would end up expressed in more than one way.

## Decision

A single module, `agent/policy.py`, decides whether a tool call may run, and every
caller goes through `policy.evaluate(tool, parameters)`. It returns one of three levels:

- `allow` — run it.
- `confirm` — run it **only** with explicit approval; when the agent is unattended there
  is nobody to approve, so the call is **denied**.
- `block` — never run, not even with approval.

Anything not listed in the policy falls back to `confirm` (fail-closed). Policy is data
(`config/autonomy.json`), not code, and every decision carries a human-readable reason
that is written to the audit log.

The gate is also where the hard guards live, so no caller can skip them: the kill
switch, the path sandbox, shell-command classification and rate limits (ADR 0004, A9).

## Consequences

- A new tool is denied until it is added to the policy — the safe default.
- The AI cannot widen its own permissions: policy lives in a file it cannot write.
- Every caller inherits every guard automatically, and they can be unit-tested in one
  place (`tests/test_policy.py`).
- Cost: one extra indirection per tool call, and a policy file to keep in sync with the
  tool list.
