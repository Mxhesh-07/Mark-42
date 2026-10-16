# Mark-42 — J.A.R.V.I.S.

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

Get free keys and paste them into `config/api_keys.json` (or set the env vars):

- Groq → https://console.groq.com (`GROQ_API_KEY`)
- OpenRouter → https://openrouter.ai/keys (`OPENROUTER_API_KEY`)
- Ollama → https://ollama.com/download — then `ollama pull llama3.2` (no config needed)

---

## Project layout

```
Mark-XXX-main/
├── main.py                 # entry point: wires UI, voice, memory, all tools
├── ui.py                   # native Tk UI (log + THINKING panes, input, live transcript)
├── gemini_util.py          # quota-resilient model fallback + tier-2 providers
├── system_state.py         # desktop/window awareness
├── voice_id.py             # speaker identification
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
├── agent/                  # planner, executor, task queue, error handler
├── actions/                # the actual capabilities (see below)
├── memory/                 # short/long-term memory, config manager
├── core/                   # core prompt / system instructions
├── prompts/                # personality prompt
├── config/
│   ├── providers.json      # tier-2 provider configuration
│   └── api_keys.json       # YOUR KEYS — gitignored, never committed
├── requirements.txt        # main (Windows desktop) dependencies
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
#    create config/api_keys.json (see below)

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
`alert_config.json`, `spotify_config.json`.

---

## Running

| Mode | Command |
|------|---------|
| Desktop assistant | `python -X utf8 main.py` |
| Cloud monitor (headless) | `python cloud_jarvis.py` |
| Hologram (standalone) | `python hologram.py --name car` |

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
| `config/email_config.json` | ❌ gitignored | IMAP/SMTP credentials |
| `config/alert_config.json` | ❌ gitignored | Alert phone number, enable flag |
| `config/spotify_config.json` | ❌ gitignored | Spotify client id/secret |

To add or change a tier-2 model, edit `config/providers.json` — **no code changes needed**.
Set `"discover": true` on a provider to auto-list models from `GET {base_url}/models`
(used for Ollama, which needs no key).

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
