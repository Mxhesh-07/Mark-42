# 0011 — Risk is scored, and a concern is raised at most once per effect

**Status:** accepted (2026-10-20)

## Context

The permission gate is binary: allow, confirm, block. It cannot distinguish
"safe but unwise" from "fine", and it has no way to let the assistant say so.
A companion that silently deletes a file you will want back is not being
helpful; neither is one that objects to everything.

## Decision

`agent/judgement.py` scores each proposed call on three explainable axes:

```
risk = 0.45 * irreversibility + 0.35 * blast_radius + 0.20 * (1 - confidence)
```

- **irreversibility** — `reversible` 0.0, `recoverable` 0.5, `permanent` 1.0
- **blast_radius** — `self` 0.0, `local` 0.35, `network` 0.6, `other_people` 1.0
- **confidence** — the self-model's per-domain average (W3)

It is a weighted sum on purpose, not a model: a person can read the number and
disagree with it. Labels come from a static tool table refined by action (a
`file_controller` *read* is reversible/self; a *delete* is permanent/local).

A concern (one sentence) is raised **only** when all of these hold:

1. the call was not refused by policy;
2. `risk > pushback_threshold` (default 0.6);
3. a concrete safer alternative exists for this tool/action — an objection
   without one is just noise;
4. the tool is not in `never_pushback_tools`;
5. the same effect has not already been raised in this session;
6. it is not a safety path (`safety=True`).

The opinion is folded into the confirmation prompt for a `confirm` (the user is
already deciding), spoken once for an `allow`, and never repeated or re-argued.
`pushback_on_allow` can silence the spoken case while leaving the modal case.

`assess()` takes the `policy.Decision` the caller already computed. Reusing it
is not just tidier: a second `policy.evaluate()` would spend a second
rate-limit token for the same call, halving the effective budget.

## Consequences

- `config/judgement.json` is tracked and is the only place the weights live.
- The pushback memory is in-process, so it resets with the session — which is
  what "never repeat within a session" means.
- Adding a new tool only requires a row in `_TOOL_PROFILE` (and optionally an
  alternative) to get sensible judgement; an unlisted tool defaults to
  `recoverable`/`network`, which is cautious but not pushback-prone.
