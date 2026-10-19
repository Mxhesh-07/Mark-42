# 0016 — Redaction has two levels, and outbound text gets the smaller one

**Status:** accepted (2026-10-20)

## Context

Redaction existed, in `agent/crash.py`, applied when a crash bundle was written.
That is one of the places text leaves the process, and not the most important
one: the prompt sent to a model leaves the machine on every single turn, and no
prompt was ever cleaned.

The obvious fix — mask everything, everywhere — is wrong. "Redact personal data
before egress" reads as one requirement, but masking the user's own email
address in an outbound prompt breaks the task it was meant to protect: "email
Sam about Thursday" cannot survive having Sam removed. A control that breaks the
feature it protects gets switched off on the first real session, which is worse
than having no control.

## Decision

Split it. `agent/redact.py` has two levels and the whole point is the
difference between them.

- **`secrets`** — things that are never the content: API keys (Google, OpenAI,
  GitHub, Slack, AWS), JWTs, bearer headers, labelled assignments
  (`password=...`), whole private-key blocks, URL-embedded passwords, and
  card-like numbers. Cards are recognised by the **Luhn check** over 13-19
  digits, not by length alone, so an arbitrary long number is left alone — a
  false positive here is a destroyed task, so the check must be tight.
- **`personal`** — adds emails, phone numbers, and the user name inside
  Windows/POSIX home paths. For logs, crash bundles and audit entries.

Outbound model text gets `secrets`; logs get `personal`. Both are configurable
in `config/autonomy.json` → `privacy`, and an unrecognised value falls back to
that context's own default, so a typo cannot silently turn redaction off.

Where the hook goes: `gemini_util.install_quota_fallback()` already patches
`generate_content` on **both** Gemini SDKs so every call site gets model
fallback. The same wrappers now run `redact.outbound()` on `contents`, so the
session, the vision path, the hologram renderer and the startup model test are
all covered without any call site having to remember. `_clean()` walks only
strings and the built-in containers, so SDK objects pass through untouched; the
masking is idempotent, so the sync and async wrappers cannot double-apply it.

`agent/crash.py` now imports its redactor from here instead of keeping a private
copy, and keeps the name `redact()` its capture path has always used.

## Consequences

- One redactor, one place to add a pattern, one set of tests.
- `python -m agent.redact "<text>"` shows what each level would mask — useful
  when deciding whether a particular pattern belongs in `secrets` or
  `personal`.
- The egress level is a *privacy* setting, not a security control: it protects
  what the user pastes, and it is documented as such so nobody assumes it makes
  the model trustworthy.
- Tier-2 providers get the same treatment with no separate hook: they are
  reached through `_text_plan(contents)`, and the wrappers build that plan from
  the cleaned contents. The one path this does **not** cover is
  `smart_alert`'s outbound email, which is a stated gap.
