# Mark-42 — J.A.R.V.I.S.

[![CI](https://github.com/Mxhesh-07/Mark-42/actions/workflows/ci.yml/badge.svg)](https://github.com/Mxhesh-07/Mark-42/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

A voice-driven, always-on AI assistant for Windows, inspired by Iron Man's J.A.R.V.I.S.
It listens, thinks, and actually *acts*: it launches and drives your apps, reads your
screen, browses the web, manages files, keeps memory of you, watches your inbox, and
projects 3D objects as a native hologram — all while staying online when one AI
provider runs out of quota.

> Built as a personal project. It is not a sandboxed toy: it can control your mouse,
> keyboard, apps and files, so run it on a machine you're comfortable giving that access to.

---

## Highlights

- **Real-time voice** — Google **Gemini Live** native-audio streaming, continuous
  listening with voice-activity detection, barge-in, and a one-line live transcript in the UI.
- **Agentic core** — a planner/executor/task-queue that turns a spoken request into a
  sequence of concrete tool calls, with retries and an error handler.
- **Quota-resilient AI** — a model-fallback chain across Gemini models, and if *all* of
  Gemini is exhausted, automatic failover to free OpenAI-compatible providers
  (Groq → OpenRouter → local Ollama). See [AI resilience](#ai-resilience).
- **Desktop control** — open/focus running apps, sense which windows are open, OCR the
  screen, control the computer, automate a real browser (Playwright), manage files.
- **Native 3D hologram** — a generic OpenGL projector that renders *any* object,
  resolved from a built-in library, a model file, or invented by the AI builder.
- **Personal modules** — companion (mood, check-ins, experiences), work assistant,
  startup partner, life & business tooling, enterprise/CRM tools.
- **Smart alerts** — IMAP inbox monitoring with importance detection, desktop toasts
  and WhatsApp alerts.
- **Cloud monitor** — a headless, UI-less variant that runs 24/7 on a server
  (`cloud_jarvis.py`).

---

## How it works

```
You speak
   │
   ▼
Gemini Live (audio in / audio out) ──► transcript
   │
   ▼
Planner ──► Tool calls ──► Executor ──► Actions  (apps, browser, files, screen, …)
   │                                        │
   ▼                                        ▼
Memory (short + long term)              Native UI  +  Hologram projector
```

The AI layer is wrapped by `gemini_util.py`, which installs a fallback chain on **both**
Google SDKs (`google-genai` and the legacy `google-generativeai`) so a spent free-tier
bucket never silently breaks the assistant.

---

## AI resilience

Free-tier Gemini models each have their **own** daily request bucket, so a single
hardcoded model can hit its cap (sometimes ~20 requests/day) and start failing. Mark-42
handles this in two tiers:

1. **Tier 1 — Gemini model chain.** Every `generate_content` call walks a list of
   Gemini models, moving on when a model returns `429` (quota) or `503` (busy).
2. **Tier 2 — external free providers.** When the whole Gemini chain is down *and* the
   request is plain text (no image input, no `google_search` grounding), it falls back
   to the OpenAI-compatible providers listed in [`config/providers.json`](config/providers.json):

   | Order | Provider | Notes |
   |------:|----------|-------|
   | 1 | **Groq** | Free, no card, ~1000 req/day |
   | 2 | **OpenRouter** | Free, no card, ~50 req/day |
   | 3 | **Ollama** (local) | Offline, no key, no quota — auto-discovers installed models |

   Only `urllib` from the standard library is used, so tier-2 adds **no dependencies**.
   Providers are opt-in: a provider without a key (except Ollama) is simply skipped.

Each provider also has a **circuit breaker** (closed / open / half-open, in
`agent/breaker.py`). Two consecutive failures open it for five minutes, so a dead
provider is skipped instantly instead of costing a timeout on every turn; the first
call after the cooldown probes it, and a success closes the breaker again.

Get free keys and paste them into `config/api_keys.json` (or set the env vars):

- Groq → https://console.groq.com (`GROQ_API_KEY`)
- OpenRouter → https://openrouter.ai/keys (`OPENROUTER_API_KEY`)
- Ollama → https://ollama.com/download — then `ollama pull llama3.2` (no config needed)

---

## Safety & autonomy

Because Mark-42 can drive your machine, every tool call passes through one gate
(`agent/policy.py`) before it runs. The design is deliberately **fail-closed**.

| Control | What it does |
|---------|--------------|
| **Three levels** | `allow` runs; `confirm` needs your explicit OK (and is denied when nobody is there to give it); `block` never runs. |
| **Kill switch** | A sentinel file (`memory/AUTONOMY_OFF`) or an in-process event stops an in-flight agent immediately. |
| **Path sandbox** | File tools are confined to allowlisted roots (`sandbox.roots` in `config/autonomy.json`); symlinks and `..` are resolved *before* the check, so neither can escape. |
| **Command analysis** | Shell commands are classified: read-only ones run, destructive ones (recursive delete, `format`, `diskpart`, `reg delete`, …) are refused, and anything chained or redirected must be confirmed. |
| **Rate limits** | Per-tool token buckets plus a global action budget stop a runaway loop from hammering a single tool. |
| **Voice roles** | An enrolled voice can be mapped to `owner` or `guest` (`roles` in `config/autonomy.json`). A non-owner is capped at read-only actions — and a guest can never be widened by attendance. |
| **Signed approvals** | A `confirm` becomes a single-use token bound to a hash of the tool *and its full arguments*, shown to you as an effect ("delete C:\x\y.txt"), not a tool name. A refusal, an expiry, a tampered token or a replay authorises nothing (`agent/approval.py`). |
| **Network egress control** | Tools that can name a destination are checked against `egress.allow` / `egress.deny`; private and loopback addresses are refused by default, so a prompt cannot make the assistant call your own services. |
| **Sandboxed code runs** | Generated code and shell helpers run in a subprocess with a restricted environment (secrets stripped, memory/CPU limits via a Windows Job Object), not inside the assistant process. |
| **Graceful degradation** | A four-step ladder — `FULL → TEXT_ONLY → READ_ONLY → MONITOR` — lowers the assistant's capability when infrastructure fails, and climbs back one step at a time. At `READ_ONLY` writes and shell stop; at `MONITOR` tools stop entirely. |
| **Startup self-check** | At boot the assistant verifies policy, keys, disk headroom, breakers and memory, then reports what is broken instead of failing mysteriously later. The microphone probe is *not* part of it (`/health?full=1` or `python -m agent.health --full` runs it on demand), because it is the one check that initialises PortAudio and must never race the audio subsystem. |
| **Health endpoint** | A read-only, loopback-only HTTP surface (`python -m agent.health --serve`, or `JARVIS_HEALTH_PORT=8799`) exposes `/health`, `/ready`, `/status` and `/metrics`. |
| **Self-model** | A stable identity plus a per-domain confidence average fed by real outcomes (`core/self.py`). It is injected into the prompt so the assistant can name a blocked capability, its policy and a weak domain instead of guessing - and it is written once, so a restart does not rewrite who it is. |
| **Judgement** | Beyond the binary gate, each call is scored for risk (`agent/judgement.py`): `0.45 x how-undoable + 0.35 x whom-it-affects + 0.20 x (1 - confidence)`. Above the threshold, and only when a concrete safer alternative exists, one sentence is said - once per effect per session. It is folded into the confirmation prompt, never repeated, and never argued. |
| **Observability** | Counters and gauges (`agent/metrics.py`), per-turn stage timings (`agent/trace.py`), and redacted crash bundles under `memory/crashes/` (`agent/crash.py`). |
| **Tamper-evident audit log** | Every decision is appended to an append-only JSONL log, hash-chained so a later edit, reorder or deletion is detectable: `python -m agent.audit verify`. |
| **Prompt-injection defense** | Text the assistant fetches (web search, pages, OCR, transcripts) is tagged as untrusted data before it reaches a model, and instruction-like spans are neutralised — including when fetched content is about to be written to a file. |
| **Transactional memory + backup** | Memory lives in one SQLite database with a versioned schema, per-record provenance and TTLs (`memory/sql_memory.py`); `python -m memory.backup export` bundles the runtime state into one zip (secrets excluded unless asked). |

Policy lives in `config/autonomy.json` (written with safe defaults on first run) and is
read-only to the model — the assistant cannot widen its own permissions.

---

## Project layout

```
Mark-XXX-main/
├── main.py                 # entry point: wires UI, voice, memory, all tools
├── ui.py                   # native Tk UI (log + THINKING panes, input, live transcript)
├── gemini_util.py          # quota-resilient model fallback + tier-2 providers
├── system_state.py         # desktop/window awareness
├── voice_id.py             # speaker identification (resemblyzer backend)
├── enroll_voice.py         # CLI: enrol / list / forget a voice
├── smart_alerts.py         # inbox monitoring, importance detection, alerts
├── notifications.py        # notification center + briefings
├── companion.py            # companion mode (mood, check-ins, experiences)
├── work_assistant.py       # tasks, notes, email drafts, docs, snippets
├── startup_partner.py      # startup metrics, milestones, competitors, investors
├── life_tools.py           # habits, focus, notes, links, meetings, finance
├── business_tools.py       # calendar, GitHub, health, expenses, documents
├── enterprise_tools.py     # automations, email, news, stocks, CRM
├── cloud_jarvis.py         # headless 24/7 monitor (no UI/voice)
├── hologram.py             # native OpenGL 3D hologram viewer
├── hologram_gen.py         # AI model builder (turns a prompt into a 3D model)
├── hologram_models.py      # built-in object library + model persistence
├── agent/                  # planner, executor, task queue, policy gate, audit log
│   ├── policy.py           # the permission gate + kill switch
│   ├── sandbox.py          # A2: filesystem allowlist for file tools
│   ├── command_policy.py   # A3: classify shell commands before they run
│   ├── ratelimit.py        # A9: per-tool token buckets
│   ├── egress.py           # A4: network egress allow/deny for destination tools
│   ├── roles.py            # A8: speaker roles (owner/guest) as authority
│   ├── approval.py         # A1: signed, single-use approvals bound to an effect
│   ├── subprocess_sandbox.py # A11: restricted-env subprocess for generated code
│   ├── breaker.py          # B1: circuit breakers for external providers
│   ├── judgement.py        # W2: risk score + at-most-one opinion per effect
│   ├── degrade.py          # B2: FULL → TEXT_ONLY → READ_ONLY → MONITOR ladder
│   ├── clock.py            # B7: UTC storage, local display, monotonic timers
│   ├── metrics.py          # C2: counters/gauges + Prometheus text
│   ├── trace.py            # C3: per-turn stage timings
│   ├── health.py           # B4/C4: self-check + /health /ready /status /metrics
│   ├── crash.py            # C6: redacted crash bundles
│   ├── console.py          # UTF-8-safe stdout/stderr for the documented CLIs
│   ├── audio.py            # one serialized door for PortAudio instances
│   ├── untrusted.py        # A5: prompt-injection defense for fetched content
│   ├── log.py              # C1: structured logging (pretty console + JSON lines)
│   ├── audit.py            # append-only, hash-chained JSONL audit log
│   └── atomic.py           # D6: crash-safe (atomic) state-file writes
├── actions/                # the actual capabilities (see below)
├── memory/                 # short/long-term memory, config manager
│   ├── sql_memory.py       # D1–D3: SQLite store, versioned schema, provenance
│   └── backup.py           # D4: zip export/restore of runtime state
├── core/                   # operating prompt + the assistant's self-model
│   ├── prompt.txt          # the operating prompt (W5)
│   └── self.py             # W3: identity, per-domain confidence, capabilities
├── prompts/                # personality prompt
├── config/
│   ├── providers.json      # tier-2 provider configuration
│   ├── autonomy.json       # permission levels, sandbox roots, rate limits
│   ├── *.example.json      # templates for the gitignored configs
│   ├── audio.json          # mic device/level + gate tuning — gitignored
│   └── api_keys.json       # YOUR KEYS — gitignored, never committed
├── tests/                  # pytest suite (policy, sandbox, audit, voice_id, …)
├── .github/                # CI workflow (ruff + pytest, Windows + Ubuntu)
├── requirements.txt        # main (Windows desktop) dependencies, pinned
├── requirements-dev.txt    # lint/test dependencies (no heavy imports)
├── pyproject.toml          # ruff + pytest configuration
├── LICENSE                 # MIT
├── requirements-cloud.txt  # minimal deps for the cloud monitor
├── setup.py                # one-shot installer (requirements + Playwright)
└── setup_cloud.sh          # Oracle Cloud/Ubuntu setup script
```

### `actions/`

| File | Capability |
|------|------------|
| `open_app.py` | Launch apps, or **reuse/focus** one that's already open |
| `browser_control.py` | Real browser automation (Playwright) |
| `web_search.py` | Web search (DuckDuckGo by default) |
| `computer_control.py` | Mouse/keyboard control |
| `computer_settings.py` | System settings (volume, brightness, …) |
| `screen_processor.py` | Screenshot + OCR / vision |
| `desktop.py` | Desktop & window management |
| `file_controller.py` | File/folder operations (delete → Recycle Bin) |
| `cmd_control.py` | Shell command execution |
| `code_helper.py` / `dev_agent.py` | Coding help and a dev agent |
| `flight_finder.py`, `weather_report.py`, `youtube_video.py` | Everyday lookups |
| `send_message.py`, `voice_call.py` | Messaging and voice calls |
| `spotify_control.py` | Spotify playback control |
| `reminder.py` | Reminders |

---

## Requirements

- **Windows 10/11** (desktop mode uses Windows-only APIs: `comtypes`, `pycaw`, `win10toast`)
- **Python 3.10+ test-marked on 3.10** (the project was developed on 3.10.10)
- A **Google Gemini API key** (https://aistudio.google.com/apikey)
- A working **microphone** for voice mode

> On Windows, run with `python -X utf8 main.py` if your console is non-UTF-8 (e.g. cp1252)
> to avoid crashes when emoji are printed.

---

## Setup

```bash
# 1. install dependencies
python setup.py            # installs requirements.txt + Playwright browsers
#   or manually:
pip install -r requirements.txt
python -m playwright install

# 2. add your keys
#    copy config/api_keys.example.json -> config/api_keys.json and fill it in

# 3. run
python -X utf8 main.py
```

### `config/api_keys.json`

This file is **gitignored** — never commit it. Minimal template:

```json
{
  "gemini_api_key": "YOUR_GEMINI_API_KEY",
  "camera_index": 0,
  "groq_api_key": "",
  "openrouter_api_key": ""
}
```

Only `gemini_api_key` is required. The other fields enable tier-2 failover and are optional.

Other gitignored config files (created as you use those features): `email_config.json`,
`alert_config.json`, `spotify_config.json`, `audio.json` (microphone + noise gate).
Each one has a checked-in `*.example.json` template in `config/` — copy it and fill it in.

---

## Running

| Mode | Command |
|------|---------|
| Desktop assistant | `python -X utf8 main.py` |
| Cloud monitor (headless) | `python cloud_jarvis.py` |
| Hologram (standalone) | `python hologram.py --name car` |

### Voice & noise

JARVIS listens through a **noise gate**: audio quieter than the room's noise floor is
replaced with literal silence, so background noise never reaches the model, while your
speech passes through untouched. Optional **speaker recognition** identifies who is
talking (used for labelling; enable strict owner-only gating on request).

```bash
python enroll_voice.py                 # enrol as the configured owner name
python enroll_voice.py --name Alex     # enrol explicitly (re-run to refine; runs are averaged)
python enroll_voice.py --list          # show enrolled voices
python enroll_voice.py --delete Alex   # forget a voice
```

A live meter is drawn while recording so you can see the mic hearing you; it stops by
itself once it has enough speech. Voiceprints live in the gitignored
`voice_profiles.json`. You can also just say *"JARVIS, remember my voice"*.

The microphone is chosen automatically (the liveliest non-virtual input, preferring the
low-latency MME host API). To pin a device, or to tune a loud/quiet room, create a
gitignored `config/audio.json`:

```json
{
  "input_device": "Microphone Array",
  "mic_level": 0.75,
  "noise_gate": true,
  "vad_aggression": 3
}
```

| Key | Meaning |
|-----|---------|
| `input_device` | Substring of the input-device name to use (optional; auto-detected otherwise) |
| `mic_level` | Windows capture gain, `0`–`1`. Speech **and** noise scale together, so pick the level where speech clears the gate comfortably |
| `noise_gate` | `true` to silence non-speech audio (default `true`) |
| `vad_aggression` | `webrtcvad` strictness, `0` (permissive) – `3` (strict) |
| `gate_floor_min` / `gate_floor_max` | Optional overrides for the gate's noise-floor clamps |

> **`mic_level` and the gate's floor clamps are a matched pair.** If you change the
> gain, re-check the clamps: too low and the gate latches open on room noise; too high
> and it mutes your speech. `main.py` logs the tracked floor (`Mic gate: floor≈…`) and
> the live meter in `enroll_voice.py` shows the actual speech/noise levels.

> **Tip:** if JARVIS cannot hear you, the usual cause is a silent or over-attenuated
> input. Run `python enroll_voice.py` and watch the meter — if `rms` stays flat while
> you talk, raise `mic_level` (or check that the right `input_device` is selected).

### Hologram

The hologram is a **native OpenGL window** (pygame + PyOpenGL), not a browser page. It
renders any object as a glowing wireframe/solid that can be rotated, exploded, and
inspected part by part.

```bash
python hologram.py --name car             # from the built-in library
python hologram.py --model path.json      # from a model file
python hologram.py --prompt "a red car"   # invent one with the AI builder
```

Ask the assistant *"show me a <thing> in hologram"* and it resolves the object, writes a
model file, and drives the viewer.

### Cloud monitor

`cloud_jarvis.py` is a UI-less, voice-less variant meant for a small always-on VM
(e.g. Oracle Cloud). It monitors email and fires WhatsApp/toast alerts.
See `setup_cloud.sh`.

---

## Configuration reference

| File | Tracked? | Purpose |
|------|:--------:|---------|
| `config/api_keys.json` | ❌ gitignored | Gemini + tier-2 provider keys |
| `config/providers.json` | ✅ | Tier-2 provider list, models, timeouts |
| `config/autonomy.json` | ✅ | Permission levels, sandbox roots, rate limits, egress, roles |
| `config/judgement.json` | ✅ | Risk weights, pushback threshold, never-pushback tools |
| `config/email_config.json` | ❌ gitignored | IMAP/SMTP credentials |
| `config/alert_config.json` | ❌ gitignored | Alert phone number, enable flag |
| `config/spotify_config.json` | ❌ gitignored | Spotify client id/secret |
| `config/audio.json` | ❌ gitignored | Mic device/level + noise-gate tuning |
| `config/*.example.json` | ✅ | Templates for the gitignored configs |

To add or change a tier-2 model, edit `config/providers.json` — **no code changes needed**.
Set `"discover": true` on a provider to auto-list models from `GET {base_url}/models`
(used for Ollama, which needs no key).

---

## Development

```bash
pip install -r requirements-dev.txt    # pytest, ruff and numpy only
python -m pytest -q                    # 394 tests, no heavy imports
python -m ruff check .                 # lint (config in pyproject.toml)
python -m compileall -q main.py agent  # syntax check
python -m agent.audit verify           # confirm the audit log is untampered
python -m agent.health                 # one-shot startup self-check
python -m agent.health --full          # the above plus the mic and network probe
python -m agent.health --serve         # read-only /health /ready /status /metrics
python -m agent.crash list             # recent crash bundles (redacted)
python -m memory.backup export         # zip the runtime state (no secrets)
```

The suite covers the cross-platform logic — the permission gate, sandbox, command
classifier, rate limiter, circuit breakers, prompt-injection defense, structured
logging, audit chain, atomic writes, egress control, voice roles, signed approvals,
the degradation ladder, metrics/tracing, health checks, crash bundles, the serialized
PortAudio door, the self-model, the risk/opinion scorer, the SQLite memory store,
backup/restore and the
speaker-recognition helpers — and
deliberately imports nothing Windows-only, so it runs unchanged on Linux. CI runs
ruff and pytest on **Windows and Ubuntu** (`.github/workflows/ci.yml`).

---

## Privacy & secrets

This repository intentionally tracks **no** credentials:

- All key/config files live under `config/` and are gitignored.
- Runtime state (memories, alerts, companion data, hologram models) is gitignored.
- If you fork or clone this project, **add your own keys** and never commit them.

> If a key ever leaks into git history, rotate it immediately — removing the file in a
> later commit does not remove it from history.

---

## Disclaimer

This project can control your computer (mouse, keyboard, apps, files, shell) and can
send messages/alerts on your behalf. Use it responsibly and only on machines and
accounts you own or are authorized to automate.

Released under the [MIT License](LICENSE).
