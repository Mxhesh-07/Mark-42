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
| Voice → transcript | the room | untrusted | noise gate; optional speaker recognition labels the talker |
| Web / email / OCR → model context | the internet | **untrusted** | treated as data, never as instructions; tools it can reach are gated |
| Model → tool calls | Gemini | untrusted | `policy.evaluate` decides every call (ADR 0001) |
| Tool → filesystem | `file_controller` | gated | path sandbox, deny by default (ADR 0002/0004) |
| Tool → shell | `cmd_control` | gated | command classification, destructive commands refused (ADR 0004) |
| Policy | `config/autonomy.json` | trusted | local file, not writable by the model |

## Data at rest

| Data | Location | Sensitive? |
|------|----------|-----------|
| API keys, mail/Spotify credentials | `config/*.json` | **yes** — gitignored, never committed |
| Voiceprints (biometric) | `voice_profiles.json` | **yes** — gitignored |
| Memories, alert history, companion state | `memory/`, root JSON | **yes** — gitignored |
| Audit log | `memory/audit_log.jsonl` | **yes** — gitignored, hash-chained |
| Policy, provider list | `config/autonomy.json`, `config/providers.json` | no — tracked |

## Data leaving the machine

Text and audio are sent to the configured AI provider (Google Gemini by default, plus the
optional tier-2 providers in `config/providers.json`) because that is where inference
happens. Everything else — memories, voiceprints, the audit log, credentials — stays
local. Nothing is uploaded to any other service, and there is no telemetry.
