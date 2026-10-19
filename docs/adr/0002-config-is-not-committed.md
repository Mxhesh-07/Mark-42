# 0002 — Credentials and machine state are never committed

**Status:** accepted

## Context

The repository is public. The app needs API keys, mail and Spotify credentials, a phone
number for alerts, the user's microphone device name, and it accumulates personal state
(memories, voiceprints, alert history). Accidentally committing any of that is hard to
undo: rewriting history is disruptive and a leaked key must be rotated regardless.

## Decision

Keep every secret and every piece of machine-specific state out of git, and ship a
checked-in **template** instead:

- Gitignored: `config/api_keys.json`, `email_config.json`, `alert_config.json`,
  `spotify_config.json`, `audio.json`; `voice_profiles.json`; `memory/long_term.json`;
  runtime JSON/JSONL under `memory/` and the repository root.
- Tracked, safe to publish: `config/providers.json` (model list and *env-var names*,
  no keys) and `config/*.example.json` (placeholder values).

A fresh clone copies each template and fills it in.

## Consequences

- The repository can be made public without leaking anything.
- Onboarding takes one extra copy step, which the README documents.
- Local private changes to tracked config (`autonomy.json`) stay visible in `git diff`,
  which is intentional — that file holds no secrets.
- Anything that must live in a tracked file (e.g. the assistant's display name) is a
  configuration value, not a hard-coded personal detail.
