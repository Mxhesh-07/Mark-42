# Data flow and trust boundaries

Where data comes from, where it goes, and what is trusted at each hop.

```
                        ┌──────────────────────────── your machine ────────────────────────────┐
                        │                                                                       │
  microphone ──audio──► │  noise gate ──► Gemini Live (audio in/out) ──► transcript            │
                        │      │                     ▲                                          │
                        │      └── voice_id ────────┘   (labels who is speaking)                │
                        │                                                                       │
                        │  planner ──► policy.evaluate ──► executor ──► actions                 │
                        │                   ▲               │                                   │
                        │                   │               ▼                                   │
                        │  config/autonomy.json        UI + hologram                            │
                        │  (allow / confirm / block)                                            │
                        └───────────────────┬───────────────────────────────────────────────────┘
                                            │
                        ┌───────────────────▼───────────────────────────────────────────────────┐
                        │  audit log (append-only, hash-chained)  +  memory (short / long term) │
                        └───────────────────────────────────────────────────────────────────────┘
```

## Trust boundaries

| Boundary | Source | Trust | What limits it |
|----------|--------|-------|----------------|
| Voice → transcript | the room | untrusted | noise gate; optional speaker recognition labels the talker, and a non-owner is capped at read-only (ADR 0006) |
| Web / email / OCR → model context | the internet | **untrusted** | treated as data, never as instructions; tools it can reach are gated |
| Model → tool calls | Gemini | untrusted | `policy.evaluate` decides every call (ADR 0001) |
| Tool → filesystem | `file_controller` | gated | path sandbox, deny by default (ADR 0002/0004) |
| Tool → shell | `cmd_control` | gated | command classification, destructive commands refused (ADR 0004) |
| Tool → network | destination tools | gated | egress allow/deny, private addresses refused (ADR 0006) |
| Assistant → model provider | `gemini_util` request path | **redacted** | credentials and card numbers stripped before the request is built; emails survive because they are usually the request (ADR 0016) |
| Tool → generated code | `generated_code` | untrusted | run in a restricted-env subprocess, secrets stripped (ADR 0006) |
| Confirmations | the user | trusted | bound to the effect and signed; single-use (ADR 0006) |
| Policy | `config/autonomy.json` | trusted | local file, not writable by the model |

## Data at rest

| Data | Location | Sensitive? |
|------|----------|-----------|
| API keys, mail/Spotify credentials | `config/*.json` | **yes** — gitignored, never committed |
| Voiceprints (biometric) | `voice_profiles.json` | **yes** — gitignored |
| Memories | `memory/jarvis.db` (SQLite, WAL) | **yes** — gitignored |
| Memories, alert history, companion state (legacy JSON) | `memory/`, root JSON | **yes** — gitignored |
| Audit log | `memory/audit_log.jsonl` | **yes** — gitignored, hash-chained |
| Approval key | `memory/approval.key` | **yes** — gitignored, generated on first use |
| Structured logs | `logs/jarvis.jsonl` | **yes** — gitignored |
| Crash bundles | `memory/crashes/` | **yes** — gitignored, redacted on write |
| Self-model (identity + per-domain confidence) | `memory/self.json` | **yes** — gitignored, written atomically |
| Policy, provider list | `config/autonomy.json`, `config/providers.json` | no - tracked |
| Narrow "always allow" rules (W6) | `config/approval_rules.json` | **yes** - gitignored, one tool + action + resolved target per rule |
| Device registry (W4) | `config/devices.json` | **yes** - gitignored, private addresses only |
| Model-call ledger (I1) | `memory/quota_ledger.json` | no - gitignored, provider + model + timestamp per call, no prompts |

**Subject controls (H4).** Everything in the table above except `config/*.json` and
`memory/approval.key` is under one control: `python -m agent.forget` reports what is
held, `--yes` erases it, and `export` writes a zip. The report is the receipt — the
count it shows is the count the erase removes, per store. Credentials and the
approval signing key are kept on purpose (deleting them breaks the assistant rather
than forgetting a person) and are named in the report so the line is visible. The
audit log is cleared last and then written to, so the deletion is itself the first
entry of the new log.

## Data leaving the machine

Text and audio are sent to the configured AI provider (Google Gemini by default, plus the
optional tier-2 providers in `config/providers.json`) because that is where inference
happens. Everything else — memories, voiceprints, the audit log, credentials — stays
local. Nothing is uploaded to any other service, and there is no telemetry.

Outbound text passes through `agent/redact.py` first (`egress_redaction`, `secrets` by
default): API keys, tokens, private-key blocks, bearer headers, URL-embedded passwords
and Luhn-valid card numbers are masked before the request is built. Email addresses and
phone numbers are deliberately **not** masked outbound — they are usually the request
itself ("email Sam about Thursday") — but they are masked in logs and crash bundles,
along with home paths. The level is configurable in `config/autonomy.json` → `privacy`.



## H1: explicit exits (audio/text/screen)
| Exit | Where | Notes |
|---|---|---|
| Live audio (mic) | Google Gemini Live API (or configured live endpoint) | Never stored by default; transcripts may be derived locally. |
| Text prompts/responses | Gemini / tier-2 providers (`config/providers.json`) | Redacted via `agent.redact` before egress. |
| Screenshots/vision | Gemini / vision providers | Sent only when user invokes screen features; redacted where applicable. |
| Web search | DuckDuckGo / configured search | Queries may include user text; avoid PII. |
| Browser automation | Playwright (local browser) | No remote proxy by default. |
| Device actions (ADB/SSH/HTTP) | Target devices on local/Tailscale mesh | Devices must be private; `shell` blocked; `sms`/`call` require confirmation. |
| Email/SMS/notifications | Configured providers (gitignored configs) | Only when explicitly requested. |

All exits are gated by policy/egress; audit logs record tool decisions.
