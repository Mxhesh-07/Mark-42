import asyncio
import threading
import json
import os
import random
import re
import sys
import traceback
import numpy as np
from pathlib import Path

import pyaudio
from google import genai
from google.genai import types
import time

# --- console encoding ---------------------------------------------------------
# When stdout is redirected (a log file, a pipe) Windows falls back to cp1252,
# where the status glyphs this project prints raise UnicodeEncodeError. Fixing
# the streams here also covers the case of launching without `-X utf8`.
try:
    from agent import console as _console
    _console.enable_utf8()
except Exception:
    pass

# Every PyAudio instance goes through agent.audio so that construction is
# serialized process-wide (a concurrent PyAudio() can crash Windows).
from agent import audio

# --- quota resilience ---------------------------------------------------------
# Each model has its own free-tier daily bucket, and the project's old default
# (gemini-2.5-flash-lite) is capped at ~20 requests/day — after that, memory
# updates and the natural-language command parsers fail silently. This patches
# both Gemini SDKs so every generate_content call falls back to another model
# when one is exhausted (429) or the server is busy (503). If the whole Gemini
# chain is down and the request is plain text, it can fall over to the free
# OpenAI-compatible providers in config/providers.json (tier-2). Must run before
# the first request, so it goes here, ahead of the project imports below.
try:
    from gemini_util import install_quota_fallback as _install_quota_fallback
    _install_quota_fallback()
except Exception as _quota_err:  # never block startup
    print(f"[Quota] fallback not installed: {_quota_err}")

# --- structured logging (C1) --------------------------------------------------
# Console output is unchanged; every record is also written as one JSON line to
# logs/ so a bad turn can be inspected afterwards. Never blocks startup.
try:
    from agent import log as _structured_log
    _structured_log.configure(
        json_path=Path(__file__).resolve().parent / "logs" / "jarvis.jsonl"
    )
except Exception as _log_err:  # pragma: no cover
    print(f"[Log] structured logging off: {_log_err}")

# --- crash bundles (C6) and the startup self-check (B4) ------------------------
# An uncaught exception writes a redacted bundle to memory/crashes/ before the
# process dies, and the self-check reports a broken install at startup instead
# of letting it surface as a mystery three commands later. The full probe (mic,
# model endpoint) runs on a daemon thread so it cannot delay the window.
try:
    from agent import crash as _crash
    _crash.install()
except Exception as _crash_err:  # pragma: no cover
    print(f"[Crash] bundle handler off: {_crash_err}")

try:
    from agent import health as _health

    def _startup_self_check() -> None:
        try:
            # `audio=False` is deliberate: the microphone probe is the only
            # check that initialises PortAudio, and doing that on a background
            # thread while the rest of the app is still importing its own
            # PyAudio instance crashes the process with an access violation.
            # The mic is probed on demand instead (/health?full=1, or
            # `python -m agent.health --full`).
            _health.self_check(full=True, audio=False)
        except Exception:
            pass

    threading.Thread(target=_startup_self_check, name="JarvisSelfCheck",
                     daemon=True).start()

    _health_port = os.environ.get("JARVIS_HEALTH_PORT")
    if _health_port:
        try:
            _health.serve(port=int(_health_port))
            print(f"[Health] read-only endpoint on http://127.0.0.1:{_health_port}")
        except Exception as _health_bind:
            print(f"[Health] endpoint not started: {_health_bind}")
except Exception as _health_err:  # pragma: no cover
    print(f"[Health] self-check off: {_health_err}")

from ui import JarvisUI
from memory.memory_manager import load_memory, update_memory, format_memory_for_prompt

from agent.task_queue import get_queue

from actions.flight_finder import flight_finder
from actions.open_app         import open_app
from actions.weather_report   import weather_action
from actions.send_message     import send_message
from actions.reminder         import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor import screen_process
from actions.youtube_video    import youtube_video
from actions.cmd_control      import cmd_control
from actions.desktop          import desktop_control
from actions.browser_control  import browser_control
from actions.file_controller  import file_controller
from actions.code_helper      import code_helper
from actions.dev_agent        import dev_agent
from actions.web_search       import web_search as web_search_action
from actions.computer_control import computer_control
from actions.spotify_control  import spotify_control

try:
    from system_state import describe_state as _describe_state
except Exception:  # keep the app bootable if the module is missing
    def _describe_state(*_a, **_k):  # type: ignore
        return ""

from memory.memory_extractor import extract_memory

from memory import AIMemory
from voice_id import (
    identify_speaker, register_speaker,
    warmup as voice_id_warmup,
    is_available as voice_id_available,
)
from companion import check_in, detect_emotion, respond_with_emotion, personal_joke, remember_experience, get_recent_experiences, companion_response
from work_assistant import add_task, complete_task, get_pending_tasks, save_meeting_notes, draft_email as wa_draft_email, get_email_drafts as wa_get_email_drafts, save_code_snippet, get_code_snippets, save_document, get_documents, daily_briefing, weekly_summary
from startup_partner import set_startup_info, log_metric, get_metric_trend, add_milestone, complete_milestone, get_milestones, save_pitch_draft, log_partner_message, get_partner_messages, add_competitor, get_competitors, add_product_feature, get_product_features, add_team_member, get_team, log_investor_update, get_investor_updates, startup_dashboard, strategy_prompt
from notifications import start_monitoring, stop_monitoring, briefing, get_all_notifications, mark_all_read, mark_as_read
from smart_alerts import start_monitoring as start_alert_monitoring, stop_monitoring as stop_alert_monitoring, get_status as get_alert_status, configure as configure_alerts, check_emails_and_alert, send_toast_notification, send_whatsapp_text_alert, is_important_email
from business_tools import add_event, get_events, get_today_events, delete_event, add_github_repo, get_github_repos, log_github_issue, get_github_issues, get_mood_playlist, log_mood_music, scan_document, get_scanned_documents, schedule_meeting, get_meetings, review_code, get_code_reviews, log_water, log_break, get_health_summary, log_expense, get_expenses, get_expense_summary, get_dashboard
from enterprise_tools import create_automation, get_automations, toggle_automation, run_automation, draft_email, get_email_drafts, send_email, configure_email, test_email_connection, add_news_topic, get_news_topics, check_news, get_news_alerts, add_to_watchlist, get_watchlist, get_stock_price, check_price_alerts, add_client, get_clients, update_client_status, add_deal, get_deals, get_crm_summary
from life_tools import add_habit, log_habit, get_habits, habit_status, habits_at_risk, start_focus, end_focus, get_focus_stats, focus_report, save_note, get_notes, search_notes, delete_note, save_link, get_links, start_meeting_recording, stop_meeting_recording, save_transcript, summarize_meeting, get_recordings, add_routine, get_routines, remove_routine, check_due_routines, pop_routine_alerts, start_routine_scheduler, stop_routine_scheduler, add_income, add_invoice, update_invoice_status, add_asset, add_liability, get_net_worth, get_finance_summary, get_finance_dashboard, life_briefing
from hologram import launch as hologram_launch, send_command as hologram_command, is_running as hologram_running
from hologram_models import get_model as hologram_model, save as hologram_save, list_models as hologram_list

jarvis_memory = AIMemory()

# Initial memories
jarvis_memory.set_user_info("name", "Mahesh")

jarvis_memory.add_preference("Iron Man")
jarvis_memory.add_preference("Artificial Intelligence")

jarvis_memory.add_project("MARK XXX")

jarvis_memory.remember(
    "User wants a JARVIS-like assistant that behaves like a friend."
)

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
FORMAT              = pyaudio.paInt16
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

# --- self-listening (echo) guard ---------------------------------------------
# JARVIS speaks through the speakers and hears itself through the mic; the
# server-side VAD then mistakes its own voice for the user and answers itself.
# While output audio is playing we mute the mic uplink, plus ECHO_GUARD_TAIL_S
# of tail to cover speaker + room propagation delay.
# Set ECHO_GUARD = False if you always use headphones and want to be able to
# interrupt JARVIS mid-sentence (barge-in).
ECHO_GUARD        = True
ECHO_GUARD_TAIL_S = 0.55

# --- speech detection (VAD) tuning -------------------------------------------
# The Live API's automatic VAD decides when your turn has ended. With its
# defaults, a short pause inside one sentence ("search for internships ...
# for bca students") ends the turn early, so the model acts on a truncated
# command — the classic "I said X but it heard half of X" symptom.
#
# Measured on a synthetic pause test (0.6 s gap mid-sentence):
#   default  -> "search the web for internship opportunity"        (tail lost)
#   sil=600  -> "search the web for internship opportunity for ..." (tail kept)
#   sil=800  -> truncates short non-English utterances, do not use
#   prefix_padding_ms=300 -> short utterances time out, do not use
# so only silence_duration_ms is raised. Set VAD_TUNING = False to fall back
# to the API defaults.
VAD_TUNING     = True
VAD_SILENCE_MS = 600   # pause length that ends your turn
# Sensitivity of the server VAD. HIGH on both ends reacts sooner: speech onset
# is picked up faster and the turn closes sooner once you stop, which is what
# makes JARVIS feel instant. Safe here only because the noise gate below keeps
# the room hiss out of the uplink — without it, HIGH start would false-trigger
# on noise and HIGH end would end turns mid-sentence.
VAD_START_SENS = True
VAD_END_SENS   = True

# --- input device selection ---------------------------------------------------
# Windows frequently makes the 3.5mm jack the default recording device. With
# nothing plugged in that jack captures digital near-silence, so the Live model
# never hears you and JARVIS looks completely unresponsive to speech.
#
# On startup we therefore (1) honour an explicit override in config/audio.json,
# else (2) measure the system default and keep it only if it actually captures
# sound, else (3) switch to the liveliest real input device (usually the
# built-in mic array). config/audio.json is optional:
#     { "input_device": 2 }                  # by PyAudio index
#     { "input_device": "Microphone Array" } # or by name substring
MIC_DEAD_PEAK  = 40      # peak below this = device captured only electrical noise
MIC_ALIVE_PEAK = 90      # stop scanning early once a device clears this
MIC_BAD_PEAK   = 30000   # sustained near-full-scale = saturated/broken stream
_VIRTUAL_HINTS = (
    "sound mapper", "primary sound capture", "stereo mix", "loopback",
    "what u hear", "vb-audio", "virtual", "cable output",
)

# --- microphone noise gate ----------------------------------------------------
# The built-in mic array used to run hot: its Windows capture level shipped at
# +17 dB, putting the room noise floor near RMS 400 (~-38 dBFS) — loud enough
# that even webrtcvad called most silence "speech". The level is now pinned at
# ~+10 dB (config/audio.json -> "mic_level", applied via _apply_mic_level),
# which drops the floor to ~RMS 40-64. On top of that we gate the uplink:
# nothing is sent until the signal rises clearly above the tracked noise floor,
# then audio keeps flowing for a short hangover so word tails are not clipped.
# Between utterances we send literal silence, which is what lets the VAD close
# the turn promptly. Set NOISE_GATE = False to send the raw microphone signal.
# Tunable from config/audio.json: {"noise_gate": true, "gate_factor": 2.5}
NOISE_GATE       = True
GATE_OPEN_FACTOR = 1.9    # open when chunk RMS > noise floor * this
GATE_HOLD_FACTOR = 1.3    # stay open while RMS > noise floor * this
GATE_HANGOVER_S  = 0.35   # ... and for this long after it drops below
# Floor clamps. These must track the capture level set by _apply_mic_level
# (config/audio.json "mic_level"), because both speech and the room's noise
# scale with the gain. At the default level 0.75 (+9.9 dB), measured on this
# laptop's Realtek array, a quiet room sits near RMS 40-64 and normal speech
# near RMS 250-1000:
#   * the low clamp must sit ABOVE the room's burst level (RMS ~108 here) or the
#     gate latches open at start-up and never recovers — the floor is only
#     learned while muted, so an open gate cannot correct itself;
#   * the high clamp must sit BELOW normal speech, or a loud room would mute
#     the user instead of the noise.
# Override in config/audio.json: {"gate_floor_min": 65, "gate_floor_max": 125}
GATE_MIN_FLOOR   = 65.0
GATE_MAX_FLOOR   = 125.0
GATE_PERCENTILE  = 25     # floor = low percentile of recent muted-chunk levels
GATE_WINDOW      = 90     # muted chunks kept for that estimate (~6 s)
GATE_SILENCE     = b"\x00" * CHUNK_SIZE * 2   # one chunk of 16-bit silence

# --- voice activity detection -------------------------------------------------
# WebRTC's VAD is built for exactly this job: separating speech from background
# noise. When webrtcvad is installed the gate decision is delegated to it (per
# 20 ms frame), with the RMS floor above still used for the onset/hangover
# timing and as a fallback when webrtcvad is missing.
#
# NOTE: these detectors have absolute energy thresholds, so they only behave
# when the capture gain is sane. This machine's "Microphone Array" shipped at
# +17 dB, where webrtcvad flagged ~80% of *silent* frames as speech; at +3 dB it
# flags 0%. Windows mic level is the first thing to check if noise returns.
VAD_ENGINE     = True   # use webrtcvad for the gate decision when available
VAD_AGGRESSION = 3      # 0 (permissive) .. 3 (most aggressive noise rejection)
VAD_FRAME_MS   = 20     # webrtcvad accepts 10, 20 or 30 ms frames
VAD_RATE       = 16000  # ... at 8, 16, 32 or 48 kHz


def _webrtcvad_available() -> bool:
    try:
        import webrtcvad  # noqa: F401
        return True
    except Exception:
        return False



def _owner_name() -> str:
    """The user's name from memory, else a neutral fallback.

    Used as the default label when a voice is enrolled without an explicit name.
    """
    try:
        entry = (load_memory().get("identity", {}) or {}).get("name")
        name = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass
    return "Owner"


def _load_audio_config() -> dict:
    """Optional user overrides (input device, noise gate). Never fatal."""
    from jarvis.device_setup import load_audio_config

    return load_audio_config(BASE_DIR)


AUDIO_CONFIG = _load_audio_config()

# T1.6: the capture helpers live in jarvis/device_setup.py; these constants are
# passed in so the module does not depend on main's tuning block.
from jarvis import device_setup as _device_setup

_CAPTURE = _device_setup.CaptureSpec(
    format=FORMAT,
    channels=CHANNELS,
    rate=SEND_SAMPLE_RATE,
    chunk=CHUNK_SIZE,
    dead_peak=MIC_DEAD_PEAK,
    alive_peak=MIC_ALIVE_PEAK,
    bad_peak=MIC_BAD_PEAK,
    virtual_hints=_VIRTUAL_HINTS,
)


def _device_peak(pa, index: int, seconds: float = 0.6) -> int:
    """Peak sample magnitude captured from `index` (-1 if unusable)."""
    return _device_setup.device_peak(pa, index, _CAPTURE, seconds)


def _pick_input_device():
    """Return the PyAudio index of the microphone to listen on (or None).

    Preference: config/audio.json -> system default if it captures sound ->
    liveliest real input device -> system default.
    """
    return _device_setup.pick_input_device(
        AUDIO_CONFIG, _CAPTURE, audio, printer=print
    )


def _device_name(index) -> str:
    """Friendly name of a PyAudio input device index ('' if unknown)."""
    return _device_setup.device_name(index, audio)


def _apply_mic_level(device_name: str, level: float) -> None:
    """Set the Windows capture level for `device_name` (0.0 .. 1.0).

    Microphone gain is the single biggest cause of a noisy transcript: this
    machine's array shipped at +17 dB, where the room noise floor alone was loud
    enough for a VAD to read it as speech. Only applied when config/audio.json
    sets "mic_level", so JARVIS never changes system audio on its own.
    """
    _device_setup.apply_mic_level(device_name, level, printer=print)

# --- cognitive / character tuning (Live model) -------------------------------
# These shape how JARVIS thinks and answers, not just what he says.
#
# Probed live against LIVE_MODEL: thinking, affective dialog and context-window
# compression are all ACCEPTED; 'proactivity' is REJECTED as an unknown field
# ("Unknown name \"proactivity\" at 'setup'"), so it is deliberately not set here.
#
#   THINKING_BUDGET  >0 = reason before answering (deeper, slightly slower).
#                      0  = answer instantly (old behaviour).
#   AFFECTIVE_DIALOG    = read the user's tone and answer the person, not just
#                         the words (mood-aware delivery).
#   CTX_*               = compress long sessions instead of forgetting the start.
#   LIVE_TEMPERATURE    = a little warmth/variety in wording. Too high = flaky
#                         and over-familiar; ~0.85 is expressive but sane.
THINKING_BUDGET    = 512
AFFECTIVE_DIALOG   = True
CTX_TRIGGER_TOKENS = 100000
CTX_TARGET_TOKENS  = 80000
LIVE_TEMPERATURE   = 0.85

pya = audio.open_pyaudio()

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]
    
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _apply_prompt_budget(prompt: str) -> str:
    """I4: optional compact variant for small-context models.

    Disabled by default (max_chars 0) so the full prompt is unchanged. Set
    `config/prompt_budget.json` -> {"max_chars": N} or the environment variable
    JARVIS_PROMPT_MAX_CHARS to trim the assembled instruction to fit a smaller
    context window. The original is returned on any error.
    """
    try:
        limit = int(os.environ.get("JARVIS_PROMPT_MAX_CHARS", "0") or 0)
    except ValueError:
        limit = 0
    if not limit:
        try:
            with open(BASE_DIR / "config" / "prompt_budget.json", "r", encoding="utf-8") as f:
                limit = int(json.load(f).get("max_chars", 0) or 0)
        except Exception:
            limit = 0
    if limit <= 0 or len(prompt) <= limit:
        return prompt
    try:
        from agent import routing

        return routing.compact(prompt, limit=limit)
    except Exception:
        return prompt


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_memory_turn_counter  = 0
_memory_turn_lock     = threading.Lock()
_MEMORY_EVERY_N_TURNS = 5
_last_memory_input    = ""


def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    """
    Multilingual memory updater.
    Model  : gemini-2.5-flash-lite, with automatic fallback to the next model
             when its free-tier quota is exhausted (see gemini_util.py)
    Stage 1: Quick YES/NO check  → ~5 tokens output
    Stage 2: Full extraction     → only if Stage 1 says YES
    Result : ~80% fewer API calls vs original
    """
    global _memory_turn_counter, _last_memory_input

    with _memory_turn_lock:
        _memory_turn_counter += 1
        current_count = _memory_turn_counter

    if current_count % _MEMORY_EVERY_N_TURNS != 0:
        return

    text = user_text.strip()
    if len(text) < 10:
        return
    if text == _last_memory_input:
        return
    _last_memory_input = text

    try:
        from google import genai
        client = genai.Client(api_key=_get_api_key())

        check = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=(
                f"Does this message contain personal facts about the user "
                f"(name, age, city, job, hobby, relationship, birthday, preference)? "
                f"Reply only YES or NO.\n\nMessage: {text[:300]}"
            )
        )
        if "YES" not in (getattr(check, "text", "") or "").upper():
            return

        raw = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=(
                f"Extract personal facts from this message. Any language.\n"
                f"Return ONLY valid JSON or {{}} if nothing found.\n"
                f"Extract: name, age, birthday, city, job, hobbies, preferences, relationships, language.\n"
                f"Skip: weather, reminders, search results, commands.\n\n"
                f"Format:\n"
                f'{{"identity":{{"name":{{"value":"..."}}}}}}, '
                f'"preferences":{{"hobby":{{"value":"..."}}}}, '
                f'"notes":{{"job":{{"value":"..."}}}}}}\n\n'
                f"Message: {text[:500]}\n\nJSON:"
            )
        ).text or ""

        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        if not raw or raw == "{}":
            return

        data = json.loads(raw)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ Updated: {list(data.keys())}")

    except json.JSONDecodeError:
        pass
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")


TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens an application, or brings it to the front if it is already "
            "open. Use this whenever the user asks to open, launch, or start an "
            "app or program. If the app is already running this focuses the "
            "existing window instead of opening a duplicate — so it is always "
            "safe to call. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "forget",
        "description": (
            "The user's own data, under their own control. Use action='report' "
            "to list what is stored about the user and where. Use action='export' "
            "to write a zip of it. Use action='forget' ONLY when the user "
            "explicitly asks to be forgotten, to have everything erased, or to "
            "delete their data — it is irreversible, and it removes memories, "
            "the profile, the spend ledger, the voiceprint, crash bundles and "
            "(unless include_audit is false) the audit log. Never call "
            "action='forget' because the user is frustrated or because it might "
            "help: ask first."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "report (default), export, or forget",
                    "enum": ["report", "export", "forget"],
                },
                "path": {
                    "type": "STRING",
                    "description": "Where to write the export zip (export only)",
                },
                "include_audit": {
                    "type": "BOOLEAN",
                    "description": (
                        "forget only: also wipe the audit log. Defaults to true; "
                        "false keeps the record of the deletion."
                    ),
                },
                "include_voiceprints": {
                    "type": "BOOLEAN",
                    "description": (
                        "forget only: also delete the voiceprint. Defaults to "
                        "true."
                    ),
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_open_windows",
        "description": (
            "Lists the windows and apps currently open on the computer. Call "
            "this when the user refers to something already open — 'continue', "
            "'that window', 'the app I opened', 'the same page' — and BEFORE "
            "opening an app or website, so you can continue in the existing "
            "window instead of opening a duplicate."
        ),
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "devices",
        "description": (
            "Talks to your other devices (phone, laptop, tablet...) registered in "
            "config/devices.json. action=list shows what is registered, "
            "action=status asks a device how it is, and action=run performs one "
            "capability (cmd) on a target. A capability the device does not "
            "declare is refused. Reaching other people (sms, call) always needs "
            "your confirmation, and the shell capability is always blocked. If it "
            "reports a failure, say so — never claim success."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "list | status | run"},
                "target": {"type": "STRING", "description": "Device name from the registry"},
                "cmd":    {"type": "STRING", "description": "Capability: info, notify, screenshot, ring, media, sms, call, lock, exec, wol"},
                "text":   {"type": "STRING", "description": "Message text, for notify/sms"},
                "number": {"type": "STRING", "description": "Phone number, for sms/call"},
                "command": {"type": "STRING", "description": "Command, for exec"}
            },
            "required": ["action"]
        }
    },
{
    "name": "web_search",
    "description": "Searches the web for any information.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query":  {"type": "STRING", "description": "Search query"},
            "mode":   {"type": "STRING", "description": "search (default) or compare"},
            "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
            "aspect": {"type": "STRING", "description": "price | specs | reviews"}
        },
        "required": ["query"]
    }
},
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
    "name": "youtube_video",
    "description": (
        "Controls YouTube. Use for: playing videos, summarizing a video's content, "
        "getting video info, or showing trending videos."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "play | summarize | get_info | trending (default: play)"
            },
            "query":  {"type": "STRING", "description": "Search query for play action"},
            "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
            "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
            "url":    {"type": "STRING", "description": "Video URL for get_info action"},
        },
        "required": []
    }
    },{
    "name": "spotify_control",
    "description": "Play music on Spotify app using system control.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "play"},
            "query": {"type": "STRING", "description": "Song name"}
        },
        "required": ["action"]
    }
},
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {
                    "type": "STRING",
                    "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"
                },
                "text": {
                    "type": "STRING",
                    "description": "The question or instruction about the captured image"
                }
            },
            "required": ["text"]
        }
    },
    {
    "name": "computer_settings",
    "description": (
        "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
        "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
        "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
        "ALSO use for repeated actions: 'refresh 10 times', 'reload page 5 times' → action: reload_n, value: 10. "
        "Use for ANY single computer control command — even if repeated N times. "
        "NEVER route simple computer commands to agent_task."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "The action to perform (if known). For repeated reload: 'reload_n'"},
            "description": {"type": "STRING", "description": "Natural language description of what to do"},
            "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, number of times, etc."}
        },
        "required": []
    }
},
    {
        "name": "browser_control",
        "description": (
            "Controls the web browser. It reuses ONE persistent browser window "
            "across calls, so pass a URL to continue browsing in that same "
            "window instead of opening a new one. Use for: opening websites, "
            "searching the web, clicking elements, filling forms, scrolling, "
            "finding cheapest products, booking flights, any web-based task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders. Use for: listing files, creating/deleting/moving/copying "
            "files, reading file contents, finding files by name or extension, checking disk usage, "
            "organizing the desktop, getting file info."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "cmd_control",
        "description": (
            "Runs CMD/terminal commands by understanding natural language. "
            "Use when user wants to: find large files, check disk space, list processes, "
            "get system info, navigate folders, check network, find files by name, "
            "or do ANYTHING in the command line they don't know how to do themselves."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":    {"type": "STRING", "description": "Natural language description of what to do. Example: 'find the 10 largest files on C drive'"},
                "visible": {"type": "BOOLEAN", "description": "Open visible CMD window so user can see. Default: true"},
                "command": {"type": "STRING", "description": "Optional: exact command if already known"},
            },
            "required": ["task"]
        }
    },
    {
        "name": "desktop_control",
        "description": (
            "Controls the desktop. Use for: changing wallpaper, organizing desktop files, "
            "cleaning the desktop, listing desktop contents, or ANY other desktop-related task "
            "the user describes in natural language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language description of any desktop task"},
            },
            "required": ["action"]
        }
    },
    {
    "name": "code_helper",
    "description": (
        "Writes, edits, explains, runs, or self-builds code files. "
        "Use for ANY coding request: writing a script, fixing a file, "
        "editing existing code, running a file, or building and testing automatically."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
            "description": {"type": "STRING", "description": "What the code should do, or what change to make"},
            "language":    {"type": "STRING", "description": "Programming language (default: python)"},
            "output_path": {"type": "STRING", "description": "Where to save the file (full path or filename)"},
            "file_path":   {"type": "STRING", "description": "Path to existing file for edit / explain / run / build"},
            "code":        {"type": "STRING", "description": "Raw code string for explain"},
            "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
            "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
        },
        "required": ["action"]
    }
    },
    {
    "name": "dev_agent",
    "description": (
        "Builds complete multi-file projects from scratch. "
        "Plans structure, writes all files, installs dependencies, "
        "opens VSCode, runs the project, and fixes errors automatically. "
        "Use for any project larger than a single script."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "description":  {"type": "STRING", "description": "What the project should do"},
            "language":     {"type": "STRING", "description": "Programming language (default: python)"},
            "project_name": {"type": "STRING", "description": "Optional project folder name"},
            "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
        },
        "required": ["description"]
    }
    },
    {
        "name": "business",
        "description": (
            "Business tools: calendar, GitHub, mood music, document scanner, "
            "meeting scheduler, code review, health tracker, expense tracker. "
            "Use when user says 'add event', 'log expense', 'review code', "
            "'what's my health today', 'scan document', 'schedule meeting', "
            "'add github repo', 'play mood music', 'business dashboard', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "calendar_add | calendar_today | calendar_list | calendar_delete | github_repos | github_add_repo | github_issues | github_add_issue | mood_music | scan_doc | meeting_add | meeting_list | code_review | health | water | break | expense_add | expense_summary | expense_list | dashboard"
                },
                "id": {"type": "STRING", "description": "Record id (e.g. to delete an event)"},
                "title": {"type": "STRING", "description": "Event/task/repo/issue title"},
                "date": {"type": "STRING", "description": "Date YYYY-MM-DD"},
                "time": {"type": "STRING", "description": "Time HH:MM"},
                "description": {"type": "STRING", "description": "Details"},
                "amount": {"type": "NUMBER", "description": "Expense amount"},
                "category": {"type": "STRING", "description": "Category (food, transport, tools, etc.)"},
                "name": {"type": "STRING", "description": "Name"},
                "url": {"type": "STRING", "description": "URL"},
                "path": {"type": "STRING", "description": "File path"},
                "code": {"type": "STRING", "description": "Code to review"},
                "language": {"type": "STRING", "description": "Programming language"},
                "mood": {"type": "STRING", "description": "Mood for music"},
                "attendees": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Meeting attendees"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "enterprise",
        "description": (
            "Enterprise tools: task automation, email drafting, news monitoring, "
            "stock/crypto tracking, client CRM. "
            "Use when user says 'create automation', 'draft an email to', 'send email', "
            "'track news about', 'add to watchlist', 'stock price', 'add client', "
            "'update client status', 'add deal', 'crm summary', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "automation_create | automation_list | automation_toggle | automation_run | email_draft | email_drafts | email_send | email_config | email_test | news_add | news_topics | news_check | news_alerts | watchlist_add | watchlist_list | stock_price | price_alerts | client_add | client_list | client_status | deal_add | deal_list | crm_summary"
                },
                "name": {"type": "STRING", "description": "Automation name / client name"},
                "title": {"type": "STRING", "description": "Title / subject / deal title"},
                "trigger": {"type": "STRING", "description": "Automation trigger description"},
                "actions": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Automation actions"},
                "to": {"type": "STRING", "description": "Email recipient"},
                "subject": {"type": "STRING", "description": "Email subject"},
                "body": {"type": "STRING", "description": "Email body / details"},
                "topic": {"type": "STRING", "description": "News topic"},
                "keywords": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "News keywords"},
                "symbol": {"type": "STRING", "description": "Stock/crypto symbol"},
                "alert_price": {"type": "NUMBER", "description": "Price alert threshold"},
                "company": {"type": "STRING", "description": "Client company"},
                "email": {"type": "STRING", "description": "Client email"},
                "app_password": {"type": "STRING", "description": "Gmail app password (16 chars) for email_config"},
                "phone": {"type": "STRING", "description": "Client phone"},
                "status": {"type": "STRING", "description": "Client/deal status"},
                "stage": {"type": "STRING", "description": "Deal stage"},
                "value": {"type": "NUMBER", "description": "Deal/client value"},
                "id": {"type": "STRING", "description": "Record id"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "life",
        "description": (
            "Personal life management: habits & streaks, focus/Pomodoro sessions, "
            "knowledge base (notes & links), meeting recording + summaries, "
            "daily routine alarms, and finance / net-worth tracking. "
            "Use when user says 'log my habit', 'start focus', 'save a note', "
            "'search my notes', 'start meeting recording', 'summarize this', "
            "'add a routine', 'log income', 'add invoice', 'net worth', "
            "'finance dashboard', 'life briefing', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "habit_add | habit_log | habits | habit_status | habits_at_risk | focus_start | focus_end | focus_stats | focus_report | note_add | note_search | notes | note_delete | link_add | links | meeting_start | meeting_stop | meeting_save | meeting_summarize | recordings | routine_add | routines | routine_remove | routines_due | income_add | invoice_add | invoice_status | asset_add | liability_add | net_worth | finance_summary | finance_dashboard | life_briefing"
                },
                "name": {"type": "STRING", "description": "Habit/routine/asset/liability name"},
                "title": {"type": "STRING", "description": "Note title / meeting title"},
                "content": {"type": "STRING", "description": "Note content"},
                "transcript": {"type": "STRING", "description": "Meeting transcript text"},
                "query": {"type": "STRING", "description": "Search query / identifier"},
                "tags": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Tags for a note or link"},
                "frequency": {"type": "STRING", "description": "Habit frequency (daily | weekly)"},
                "target_per_week": {"type": "INTEGER", "description": "Habit target per week"},
                "url": {"type": "STRING", "description": "URL to save"},
                "task": {"type": "STRING", "description": "Focus task name"},
                "minutes": {"type": "INTEGER", "description": "Focus session length in minutes"},
                "time": {"type": "STRING", "description": "Routine time HH:MM"},
                "days": {"type": "ARRAY", "items": {"type": "INTEGER"}, "description": "Routine weekdays (0=Mon..6=Sun)"},
                "action_text": {"type": "STRING", "description": "What the routine should do/say"},
                "amount": {"type": "NUMBER", "description": "Money amount"},
                "source": {"type": "STRING", "description": "Income source"},
                "client": {"type": "STRING", "description": "Invoice client"},
                "status": {"type": "STRING", "description": "Status (e.g. pending | paid)"},
                "due": {"type": "STRING", "description": "Invoice due date"},
                "kind": {"type": "STRING", "description": "Asset/liability kind"},
                "id": {"type": "STRING", "description": "Record id / identifier"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "smart_alert",
        "description": (
            "Configure and manage smart alerts. Use when user says 'enable whatsapp alerts', "
            "'set my phone number', 'check alert status', 'send test alert', "
            "'check now', 'enable alerts', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "configure | status | test_alert | check_now | enable | disable"
                },
                "phone_number": {"type": "STRING", "description": "Your phone number (with country code)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "notification",
        "description": (
            "Check and manage notifications. Use when user says 'any notifications', "
            "'check emails', 'whatsapp messages', 'instagram notifications', "
            "'mark all as read', 'notification briefing', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "briefing | mark_all_read | get_all"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "startup_task",
        "description": (
            "Manages startup tasks and milestones. Use when user says 'add startup task', "
            "'complete milestone', 'show startup dashboard', 'what's our runway', "
            "'track metric', 'save pitch draft', 'log partner message', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "add_task | complete_task | dashboard | add_milestone | complete_milestone | log_metric | save_pitch | partner_message | competitor | feature | team | investor"
                },
                "title": {"type": "STRING", "description": "Task/milestone title"},
                "description": {"type": "STRING", "description": "Details"},
                "priority": {"type": "STRING", "description": "low | normal | high | critical"},
                "metric_name": {"type": "STRING", "description": "Metric name (e.g. MRR, users, runway)"},
                "metric_value": {"type": "NUMBER", "description": "Metric value"},
                "partner_name": {"type": "STRING", "description": "Partner name"},
                "investor_name": {"type": "STRING", "description": "Investor name"},
                "feature_name": {"type": "STRING", "description": "Feature name"},
                "team_name": {"type": "STRING", "description": "Team member name"},
                "role": {"type": "STRING", "description": "Role"},
                "name": {"type": "STRING", "description": "General name field"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "work_task",
        "description": (
            "Work productivity: tasks, emails, documents, code snippets. "
            "Use when user says 'add task', 'draft email', 'save document', "
            "'save code snippet', 'daily briefing', 'weekly summary', etc."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "add_task | complete_task | pending_tasks | daily_briefing | weekly_summary | save_email | get_emails | save_document | get_documents | save_snippet | get_snippets | meeting_notes"
                },
                "title": {"type": "STRING", "description": "Task/title"},
                "description": {"type": "STRING", "description": "Details/content"},
                "to": {"type": "STRING", "description": "Email recipient"},
                "subject": {"type": "STRING", "description": "Email subject"},
                "body": {"type": "STRING", "description": "Email body or document content"},
                "priority": {"type": "STRING", "description": "low | normal | high"},
                "doc_type": {"type": "STRING", "description": "note | spec | proposal"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "register_voice",
        "description": (
            "Enrols the current speaker's voice so JARVIS can recognise them "
            "later. Use whenever the user says 'remember my voice', 'learn my "
            "voice', 'this is me', or 'register my voice as [name]'. The voice "
            "sample is taken from what the user just said, so call it as soon "
            "as possible after they speak."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {
                    "type": "STRING",
                    "description": (
                        "Name to associate with the voice (e.g. 'Mahesh'). "
                        "Optional — omit it to use the user's configured name."
                    )
                }
            }
        }
    },
    {
    "name": "agent_task",
    "description": (
        "Executes complex multi-step tasks that require MULTIPLE DIFFERENT tools. "
        "Always respond to the user in the language they spoke. "
        "Examples: 'research X and save to file', 'find files and organize them', "
        "'fill a form on a website', 'write and test code'. "
        "DO NOT use for simple computer commands like volume, refresh, close, scroll, "
        "minimize, screenshot, restart, shutdown — use computer_settings for those. "
        "DO NOT use if the task can be done with a single tool call."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {
                "type": "STRING",
                "description": "Complete description of what needs to be accomplished"
            },
            "priority": {
                "type": "STRING",
                "description": "low | normal | high (default: normal)"
            }
        },
        "required": ["goal"]
    }
},
    {
    "name": "computer_control",
    "description": (
        "Direct computer control: type text, click buttons, use keyboard shortcuts, "
        "scroll, move mouse, take screenshots, fill forms, find elements on screen. "
        "Use when the user wants to interact with any app on the computer directly. "
        "Can generate random data for forms or use user's real info from memory."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
            "text":        {"type": "STRING", "description": "Text to type or paste"},
            "x":           {"type": "INTEGER", "description": "X coordinate for click/move"},
            "y":           {"type": "INTEGER", "description": "Y coordinate for click/move"},
            "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
            "key":         {"type": "STRING", "description": "Single key to press e.g. 'enter'"},
            "direction":   {"type": "STRING", "description": "Scroll direction: up | down | left | right"},
            "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
            "seconds":     {"type": "NUMBER", "description": "Seconds to wait"},
            "title":       {"type": "STRING", "description": "Window title for focus_window"},
            "description": {"type": "STRING", "description": "Element description for screen_find/screen_click"},
            "type":        {"type": "STRING", "description": "Data type for random_data: name|email|username|password|phone|birthday|address"},
            "field":       {"type": "STRING", "description": "Field for user_data: name|email|city"},
            "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            "path":        {"type": "STRING", "description": "Save path for screenshot"},
        },
        "required": ["action"]
    }
},

{
    "name": "flight_finder",
    "description": (
        "Searches for flights on Google Flights and speaks the best options. "
        "Use when user asks about flights, plane tickets, uçuş, bilet, etc."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "origin":       {"type": "STRING",  "description": "Departure city or airport code"},
            "destination":  {"type": "STRING",  "description": "Arrival city or airport code"},
            "date":         {"type": "STRING",  "description": "Departure date (any format)"},
            "return_date":  {"type": "STRING",  "description": "Return date for round trips"},
            "passengers":   {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
            "cabin":        {"type": "STRING",  "description": "economy | premium | business | first"},
            "save":         {"type": "BOOLEAN", "description": "Save results to Notepad"},
        },
        "required": ["origin", "destination", "date"]
    }
},
{
    "name": "hologram",
    "description": (
        "Holographic 3D projector. Renders ANY object the user asks for as a "
        "rotatable, glowing 3D hologram that can be exploded and inspected PART BY PART "
        "(like Iron Man reviewing a build). It has a built-in library (cars, planes, houses, "
        "animals, planets, devices, the Iron Man suit, shapes...) and can invent anything else "
        "on the fly. Use when user says 'show me a car', 'display a dog in hologram', "
        "'show the Earth in 3d', 'project the Iron Man suit', 'show a dragon hologram', "
        "'explode the suit', 'show the wheels', 'close the hologram', etc."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "show | explode | assemble | show_part | rotate | close | list"
            },
            "object": {
                "type": "STRING",
                "description": "What to display as a hologram (e.g. 'car', 'red car', 'dog', 'Earth', 'Iron Man suit', 'a coffee machine', 'dragon')"
            },
            "part": {
                "type": "STRING",
                "description": "Optional part to highlight after showing (e.g. 'wheels', 'helmet', 'engine')"
            },
            "value": {"type": "BOOLEAN", "description": "For rotate: true = auto-rotate, false = stop"}
        },
        "required": ["action"]
    }
}
]

def _fmt_args(args: dict, limit: int = 90) -> str:
    """Compact single-line form of tool arguments for the THINKING pane."""
    try:
        s = ", ".join(f"{k}={v}" for k, v in args.items())
    except Exception:
        s = str(args)
    s = " ".join(str(s).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _tidy_sentence(chunks) -> str:
    """Join streaming transcription fragments into one clean sentence.

    Gemini Live emits the transcript word-piece by word-piece (" O", "pen",
    " the", " note", "pad application."), so the fragments must be
    concatenated verbatim and only then have their whitespace collapsed —
    joining with " " would turn "note" + "pad" into "note pad".
    """
    try:
        return " ".join("".join(str(c) for c in chunks).split())
    except Exception:
        return ""


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._mic_buffer    = bytearray()
        self._mic_lock      = threading.Lock()
        self._mic_max_bytes = SEND_SAMPLE_RATE * 2 * 3  # ~3s of 16-bit mono audio

        # --- echo guard state -------------------------------------------------
        self._last_play_ts = 0.0                 # when output last hit the speaker
        self._play_lock    = threading.Lock()
        self._echo_dropped = 0                   # mic chunks suppressed (diagnostic)

        # --- noise gate state -------------------------------------------------
        # T1.6: gate state/logic lives in jarvis/mic_gate.py.
        from jarvis.mic_gate import MicGate
        self._gate = MicGate(
            open_factor=GATE_OPEN_FACTOR,
            hold_factor=GATE_HOLD_FACTOR,
            hangover_s=GATE_HANGOVER_S,
            percentile=GATE_PERCENTILE,
            window=GATE_WINDOW,
            min_floor=GATE_MIN_FLOOR,
            max_floor=GATE_MAX_FLOOR,
        )
        self._vad_carry  = b""                   # leftover bytes for webrtcvad
        self._last_speaker = None                # last (name, confidence) heard

        # --- speaker ID throttle ---------------------------------------------
        # Input transcription streams many chunks per turn; only run speaker
        # identification occasionally instead of spawning a thread per chunk.
        self._last_voiceid_ts = 0.0

    def speak(self, text: str):
        """Thread-safe speak — any thread can call this."""
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
         )
    
    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime 

        memory  = load_memory()
        mem_str = format_memory_for_prompt(memory)

        sys_prompt = _load_system_prompt()

        try:
            with open(
                BASE_DIR / "prompts" / "jarvis_personality.txt",
                "r",
                encoding="utf-8"
            ) as f:
                personality_prompt = f.read()
        except Exception:
            personality_prompt = ""

        sys_prompt = personality_prompt + "\n\n" + sys_prompt

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders. "
            f"If user says 'in 2 minutes', add 2 minutes to this time.\n\n"
        )

        if mem_str:
            sys_prompt = time_ctx + mem_str + "\n\n" + sys_prompt
        else:
            sys_prompt = time_ctx + sys_prompt

        # Snapshot of what is already open, so JARVIS continues in existing
        # windows instead of opening duplicates.
        try:
            state_str = _describe_state(max_windows=10, max_apps=10)
        except Exception:
            state_str = ""
        if state_str:
            sys_prompt = (
                "[CURRENTLY OPEN ON THE COMPUTER — continue in these windows "
                "instead of opening duplicates; call get_open_windows for a "
                "fresh list]\n" + state_str + "\n\n" + sys_prompt
            )

        # W3: the self-model. JARVIS reports its own mode, confidence and limits
        # honestly instead of guessing what it can do.
        try:
            from core import self as _self_model
            _self_block = _self_model.prompt_block()
        except Exception:
            _self_block = ""
        if _self_block:
            sys_prompt = _self_block + "\n\n" + sys_prompt

        # Automatic-VAD tuning (see VAD_* constants). Only raise the
        # end-of-turn silence window; prefix padding and longer windows were
        # measured to hurt short utterances, so they are deliberately unused.
        vad_kwargs = {}
        if VAD_TUNING:
            aad = {"silence_duration_ms": VAD_SILENCE_MS}
            if VAD_START_SENS:
                aad["start_of_speech_sensitivity"] = (
                    types.StartSensitivity.START_SENSITIVITY_HIGH
                )
            if VAD_END_SENS:
                aad["end_of_speech_sensitivity"] = (
                    types.EndSensitivity.END_SENSITIVITY_HIGH
                )
            vad_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(**aad)
            )

        # Cognitive settings (see THINKING_BUDGET / AFFECTIVE_DIALOG / CTX_*).
        # 'proactivity' is intentionally absent — this model rejects the field.
        cognition_kwargs = {}
        if THINKING_BUDGET and THINKING_BUDGET > 0:
            cognition_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=THINKING_BUDGET
            )
        if AFFECTIVE_DIALOG:
            cognition_kwargs["enable_affective_dialog"] = True
        if CTX_TRIGGER_TOKENS and CTX_TARGET_TOKENS:
            cognition_kwargs["context_window_compression"] = (
                types.ContextWindowCompressionConfig(
                    trigger_tokens=CTX_TRIGGER_TOKENS,
                    sliding_window=types.SlidingWindow(
                        target_tokens=CTX_TARGET_TOKENS
                    ),
                )
            )
        cognition_kwargs["temperature"] = LIVE_TEMPERATURE

        # I4: optional compact variant for small-context fallbacks (default off).
        sys_prompt = _apply_prompt_budget(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction=sys_prompt,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            **vad_kwargs,
            **cognition_kwargs,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon" 
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 TOOL: {name}  ARGS: {args}")
        self.ui.jarvis_think("tool", f"{name}({_fmt_args(args)})")
        if args:
            self.ui.jarvis_think("args",
                                 json.dumps(args, ensure_ascii=False, default=str))

        # --- the permission gate, the same choke point as the background agent ---
        # The user is present and made this request, so a soft `confirm` (or a
        # soft policy-table `block`) is satisfied by attendance; a hard block —
        # kill switch, sandbox escape, refused command, denied destination,
        # non-owner speaker — is refused here too.
        from agent import audit as _audit
        from agent import policy as _policy
        from agent.policy import Level as _Level

        try:
            _gate = _policy.evaluate_live(name, args)
        except Exception as _e:
            # Fail closed: a gate that cannot decide must not allow.
            _gate = None
            print(f"[JARVIS] ⚠️ permission gate error: {_e}")

        if _gate is None or _gate.level is _Level.BLOCK:
            _reason = _gate.reason if _gate is not None else "the permission gate failed"
            print(f"[JARVIS] 🛑 Refused [{name}]: {_reason}")
            self.ui.write_log(f"🛑 [{name}] {_reason}")
            self.ui.jarvis_think("err", f"blocked [{name}]: {_reason}")
            try:
                _audit.record("action_denied", tool=name, parameters=args,
                              level="block", outcome="blocked", detail=_reason)
            except Exception:
                pass
            return types.FunctionResponse(
                id=fc.id,
                name=name,
                response={"result": f"Refused: {_reason}"},
            )

        loop   = asyncio.get_event_loop()
        result = "Done."
        failed = False
        _tool_started = time.perf_counter()

        try:
            if name == "open_app":
                r = await loop.run_in_executor(
                    None, lambda: open_app(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Opened {args.get('app_name')} successfully."

            elif name == "get_open_windows":
                r = await loop.run_in_executor(None, lambda: _describe_state())
                result = r or "No notable windows or apps are currently open."

            elif name == "forget":
                # H4: the user's own data, by their own request. Destructive and
                # irreversible, so policy puts it at `confirm` and the approval
                # modal shows the exact effect before it runs. The dry run is the
                # default action so a bare call reports rather than deletes.
                from agent import forget as _forget

                def _call_forget(_args=args):
                    payload = dict(_args)
                    action = str(payload.pop("action", "report") or "report")
                    if action == "report":
                        return json.dumps(_forget.inventory(), ensure_ascii=False)
                    if action == "export":
                        where = payload.get("path") or None
                        return json.dumps(_forget.export(where), ensure_ascii=False)
                    if action == "forget":
                        include_audit = bool(payload.get("include_audit", True))
                        include_voice = bool(payload.get("include_voiceprints", True))
                        done = _forget.forget_all(include_audit=include_audit,
                                                  include_voiceprints=include_voice)
                        return (f"Forgot {done['total_removed']} records. "
                                f"{json.dumps(done['remaining'], ensure_ascii=False)}")
                    return f"Unknown forget action: {action}"

                result = await loop.run_in_executor(None, _call_forget)

            elif name == "devices":
                # W4: one tool over the device registry. The permission gate has
                # already run above; a result with ok=False is reported as a
                # failure so the model never turns it into a claim of success.
                from agent import devices as _devices

                def _call_devices(_args=args):
                    payload = dict(_args)
                    action = str(payload.pop("action", "list") or "list")
                    target = str(payload.pop("target", "") or "")
                    cmd = str(payload.pop("cmd", "") or "")
                    return _devices.render(
                        _devices.dispatch(action, target=target, cmd=cmd, **payload)
                    )

                result = await loop.run_in_executor(None, _call_devices)

            elif name == "weather_report":
                r = await loop.run_in_executor(
                    None, lambda: weather_action(parameters=args, player=self.ui)
                )
                result = r or f"Weather report for {args.get('city')} delivered."

            elif name == "browser_control":
                r = await loop.run_in_executor(
                    None, lambda: browser_control(parameters=args, player=self.ui)
                )
                result = r or "Browser action completed."

            elif name == "file_controller":
                r = await loop.run_in_executor(
                    None, lambda: file_controller(parameters=args, player=self.ui)
                )
                result = r or "File operation completed."

            elif name == "send_message":
                r = await loop.run_in_executor(
                    None, lambda: send_message(
                        parameters=args, response=None,
                        player=self.ui, session_memory=None
                    )
                )
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(
                    None, lambda: reminder(parameters=args, response=None, player=self.ui)
                )
                result = r or f"Reminder set for {args.get('date')} at {args.get('time')}."

            elif name == "youtube_video":
                r = await loop.run_in_executor(
                    None, lambda: youtube_video(parameters=args, response=None, player=self.ui)
                )
                result = r or "Done."

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = (
                    "Vision module activated. "
                    "Stay completely silent — vision module will speak directly."
                )

            elif name == "computer_settings":
                r = await loop.run_in_executor(
                    None, lambda: computer_settings(
                        parameters=args, response=None, player=self.ui
                    )
                )
                result = r or "Done."

            elif name == "cmd_control":
                r = await loop.run_in_executor(
                    None, lambda: cmd_control(parameters=args, player=self.ui)
                )
                result = r or "Command executed."

            elif name == "desktop_control":
                r = await loop.run_in_executor(
                    None, lambda: desktop_control(parameters=args, player=self.ui)
                )
                result = r or "Desktop action completed."
            elif name == "code_helper":
                r = await loop.run_in_executor(
                    None, lambda: code_helper(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak 
                    )
                )
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(
                    None, lambda: dev_agent(
                        parameters=args,
                        player=self.ui,
                        speak=self.speak
                    )
                )
                result = r or "Done."
            elif name == "register_voice":
                speaker_name = (args.get("name") or "").strip() or _owner_name()
                voice_id = np.frombuffer(self._snapshot_mic_audio(), dtype=np.int16)
                success = register_speaker(speaker_name, voice_id, sample_rate=SEND_SAMPLE_RATE)
                result = f"Voice registered as '{speaker_name}'." if success else "Voice registration failed."

            elif name == "business":
                action = args.get("action", "")
                if action == "calendar_add":
                    e = add_event(args.get("title", ""), args.get("date", ""), args.get("time", ""), args.get("description", ""))
                    result = f"Event added: {e['title']} on {e['date']} at {e['time']}"
                elif action == "calendar_today":
                    events = get_today_events()
                    result = f"Today: {len(events)} events\n" + "\n".join(f"- {e['time']} {e['title']}" for e in events[:10]) if events else "No events today."
                elif action == "calendar_list":
                    events = get_events(args.get("date", ""))
                    result = f"Events: {len(events)}\n" + "\n".join(f"- {e['date']} {e['time']} {e['title']}" for e in events[:10])
                elif action == "calendar_delete":
                    ok = delete_event(args.get("id", "") or args.get("title", ""))
                    result = "Event deleted." if ok else "Event not found."
                elif action == "github_repos":
                    repos = get_github_repos()
                    result = f"Repos: {len(repos)}\n" + "\n".join(f"- {r['name']}: {r['url']}" for r in repos[:10])
                elif action == "github_add_repo":
                    r = add_github_repo(args.get("name", ""), args.get("url", ""), args.get("description", ""))
                    result = f"Repo added: {r['name']} ({r['url']})"
                elif action == "github_issues":
                    issues = get_github_issues()
                    result = f"Open issues: {len(issues)}\n" + "\n".join(f"- [{i['repo']}] {i['title']}" for i in issues[:10])
                elif action == "github_add_issue":
                    i = log_github_issue(args.get("name", ""), args.get("title", ""), args.get("status", "open") or "open")
                    result = f"Issue logged: {i['title']} in {i['repo']}"
                elif action == "mood_music":
                    mood = args.get("mood", "neutral")
                    playlist = get_mood_playlist(mood)
                    result = f"For {mood} mood: {', '.join(playlist[:3])}"
                elif action == "scan_doc":
                    d = scan_document(args.get("path", ""))
                    result = f"Document scanned: {d.get('text', 'No text found')[:200]}"
                elif action == "meeting_add":
                    m = schedule_meeting(args.get("title", ""), args.get("date", ""), args.get("time", ""), args.get("attendees", []))
                    result = f"Meeting scheduled: {m['title']} on {m['date']} at {m['time']}"
                elif action == "meeting_list":
                    meetings = get_meetings(args.get("date", ""))
                    result = f"Meetings: {len(meetings)}\n" + "\n".join(f"- {m['date']} {m['time']} {m['title']}" for m in meetings[:10])
                elif action == "code_review":
                    r = review_code(args.get("code", ""), args.get("language", "python"))
                    result = f"Code Review Score: {r['score']}/100\nIssues: {len(r['issues'])}\n" + "\n".join(f"- {i}" for i in r['issues'][:5])
                elif action == "health":
                    h = get_health_summary()
                    result = f"Water: {h['water_today_ml']}ml ({h['water_percentage']}%)\nBreaks: {h['breaks_today']}/{h['recommended_breaks']}"
                elif action == "water":
                    w = log_water(args.get("amount", 250))
                    result = f"Water logged. Today: {w['water_today_ml']}ml of {w['goal_ml']}ml"
                elif action == "break":
                    b = log_break()
                    result = f"Break logged. Today: {b['breaks_today']} breaks"
                elif action == "expense_add":
                    e = log_expense(args.get("amount", 0), args.get("category", ""), args.get("description", ""))
                    result = f"Expense logged: ₹{e['amount']} for {e['category']}"
                elif action == "expense_summary":
                    s = get_expense_summary()
                    result = f"Today: ₹{s['today_total']}\nMonth: ₹{s['month_total']}\nCategories: {s['by_category']}"
                elif action == "expense_list":
                    expenses = get_expenses()
                    result = f"Expenses: {len(expenses)}\n" + "\n".join(f"- {e['date']} ₹{e['amount']} {e['category']}" for e in expenses[:10])
                elif action == "dashboard":
                    d = get_dashboard()
                    result = f"Business Dashboard:\n- Health: {d['health']['water_percentage']}% water, {d['health']['breaks_today']} breaks\n- Expenses: ₹{d['expenses']['today_total']} today\n- Calendar: {d['calendar_today']} events today\n- GitHub: {d['open_issues']} open issues"
                else:
                    result = f"Unknown business action: {action}"

            elif name == "enterprise":
                action = args.get("action", "")
                if action == "automation_create":
                    a = create_automation(args.get("name", ""), args.get("trigger", ""), args.get("actions", []))
                    result = f"Automation created: {a['name']} ({len(a['actions'])} actions)"
                elif action == "automation_list":
                    autos = get_automations()
                    result = f"Automations: {len(autos)}\n" + "\n".join(f"- {a['id']} {a['name']} [{'on' if a['active'] else 'off'}]" for a in autos[:10]) if autos else "No automations."
                elif action == "automation_toggle":
                    ok = toggle_automation(args.get("id", ""))
                    result = "Automation toggled." if ok else "Automation not found."
                elif action == "automation_run":
                    r = run_automation(args.get("id", ""))
                    result = f"Automation {r.get('automation', '')} {r['status']}."
                elif action == "email_draft":
                    d = draft_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
                    result = f"Draft saved (id {d['id']}) to {d['to']}, subject '{d['subject']}'."
                elif action == "email_drafts":
                    drafts = get_email_drafts()
                    result = f"Drafts: {len(drafts)}\n" + "\n".join(f"- {d['id']} to {d['to']}: {d['subject']}" for d in drafts[:10])
                elif action == "email_send":
                    ok, msg = send_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
                    result = msg
                elif action == "email_config":
                    c = configure_email(args.get("email", ""), args.get("app_password", ""))
                    result = c.get("note") or c.get("error", "Done.")
                elif action == "email_test":
                    ok, msg = test_email_connection()
                    result = msg
                elif action == "news_add":
                    n = add_news_topic(args.get("topic", ""), args.get("keywords", []))
                    result = f"Now tracking news on '{n['topic']}'."
                elif action == "news_topics":
                    topics = get_news_topics()
                    result = f"News topics: {len(topics)}\n" + "\n".join(f"- {t['topic']}" for t in topics[:10])
                elif action == "news_check":
                    alerts = check_news()
                    result = f"News check complete: {len(alerts)} new items.\n" + "\n".join(f"- {a['title']}" for a in alerts[:5])
                elif action == "news_alerts":
                    alerts = get_news_alerts()
                    result = f"Recent news: {len(alerts)}\n" + "\n".join(f"- {a['title']}" for a in alerts[:5])
                elif action == "watchlist_add":
                    w = add_to_watchlist(args.get("symbol", ""), args.get("name", ""), args.get("alert_price"))
                    result = f"Added {w['symbol']} ({w['name']}) to watchlist."
                elif action == "watchlist_list":
                    wl = get_watchlist()
                    result = f"Watchlist: {len(wl)}\n" + "\n".join(f"- {w['symbol']} ({w['name']})" for w in wl[:10])
                elif action == "stock_price":
                    p = get_stock_price(args.get("symbol", ""))
                    result = f"{p['symbol']}: {p['price']} {p['currency']} ({p['change']}%)"
                elif action == "price_alerts":
                    alerts = check_price_alerts()
                    result = f"Triggered price alerts: {len(alerts)}\n" + "\n".join(f"- {a['symbol']} at {a['current_price']}" for a in alerts[:10])
                elif action == "client_add":
                    c = add_client(args.get("name", ""), args.get("company", ""), args.get("email", ""), args.get("phone", ""), args.get("value", 0))
                    result = f"Client added: {c['name']} ({c['company']}) [{c['status']}]"
                elif action == "client_list":
                    clients = get_clients(args.get("status") or None)
                    result = f"Clients: {len(clients)}\n" + "\n".join(f"- {c['name']} ({c['company']}) [{c['status']}]" for c in clients[:10])
                elif action == "client_status":
                    ok = update_client_status(args.get("id", ""), args.get("status", ""))
                    result = "Client status updated." if ok else "Client not found or invalid status."
                elif action == "deal_add":
                    d = add_deal(args.get("name", ""), args.get("title", ""), args.get("value", 0), args.get("stage", "lead"))
                    result = f"Deal added: {d['title']} for {d['client']} (₹{d['value']}) [{d['stage']}]"
                elif action == "deal_list":
                    deals = get_deals(args.get("stage") or None)
                    result = f"Deals: {len(deals)}\n" + "\n".join(f"- {d['client']} {d['title']} ₹{d['value']} [{d['stage']}]" for d in deals[:10])
                elif action == "crm_summary":
                    s = get_crm_summary()
                    result = f"CRM: {s['total_clients']} clients, {s['active_deals']} deals\nPipeline value: ₹{s['total_pipeline_value']}\nWon: ₹{s['won_value']} ({s['win_rate']:.0f}%)"
                else:
                    result = f"Unknown enterprise action: {action}"

            elif name == "life":
                action = args.get("action", "")
                if action == "habit_add":
                    h = add_habit(args.get("name", ""), args.get("frequency", "daily"), args.get("target_per_week", 7))
                    result = f"Habit tracked: {h['name']} (streak {h['streak']})"
                elif action == "habit_log":
                    h = log_habit(args.get("name", ""))
                    result = f"{h['name']} logged. Streak: {h['streak']} day(s), best {h['best_streak']}."
                elif action == "habits":
                    hs = get_habits()
                    result = "Habits:\n" + "\n".join(f"- {h['name']}: {h['streak']}d streak ({h['this_week']}/{h['target_per_week']} this week)" for h in hs) if hs else "No habits yet."
                elif action == "habit_status":
                    h = habit_status(args.get("name", ""))
                    result = f"{h['name']}: streak {h['streak']}, best {h['best_streak']}, done today: {h['done_today']}" if h else "Habit not found."
                elif action == "habits_at_risk":
                    r = habits_at_risk()
                    result = "Pending today: " + ", ".join(h["name"] for h in r) if r else "All habits done today."
                elif action == "focus_start":
                    f = start_focus(args.get("task", ""), args.get("minutes", 25))
                    result = f"Focus started: {f['task']} for {f['minutes']} minutes."
                elif action == "focus_end":
                    result = end_focus()["message"]
                elif action == "focus_stats":
                    s = get_focus_stats()
                    result = f"Focus: {s['minutes_today']} min today ({s['sessions_today']} sessions), {s['minutes_week']} min this week."
                elif action == "focus_report":
                    result = focus_report()
                elif action == "note_add":
                    n = save_note(args.get("title", ""), args.get("content", ""), args.get("tags", []))
                    result = f"Note saved: {n['title']} ({n['id']})"
                elif action == "note_search":
                    res = search_notes(args.get("query", ""))
                    result = f"Found {len(res)}:\n" + "\n".join(f"- {r.get('title','')}: {(r.get('content') or r.get('url',''))[:60]}" for r in res[:5]) if res else "Nothing found."
                elif action == "notes":
                    ns = get_notes(args.get("name") or None)
                    result = f"Notes: {len(ns)}\n" + "\n".join(f"- {n['title']}" for n in ns[:10]) if ns else "No notes yet."
                elif action == "note_delete":
                    ok = delete_note(args.get("query", "") or args.get("title", ""))
                    result = "Note deleted." if ok else "Note not found."
                elif action == "link_add":
                    l = save_link(args.get("url", ""), args.get("title", ""), args.get("tags", []))
                    result = f"Link saved: {l['title']}"
                elif action == "links":
                    ls = get_links(args.get("name") or None)
                    result = f"Links: {len(ls)}\n" + "\n".join(f"- {l['title']}: {l['url']}" for l in ls[:10]) if ls else "No links saved."
                elif action == "meeting_start":
                    m = start_meeting_recording(args.get("title", "Meeting"))
                    result = f"Recording meeting '{m['title']}'."
                elif action == "meeting_stop":
                    m = stop_meeting_recording(args.get("transcript", ""))
                    if m.get("status") == "none":
                        result = m["message"]
                    else:
                        s = m.get("summary") or {}
                        result = f"Meeting saved: {m['title']}. Summary: {s.get('summary','')[:200]}"
                elif action == "meeting_save":
                    r = save_transcript(args.get("title", "Meeting"), args.get("transcript", ""))
                    s = r.get("summary") or {}
                    result = f"Meeting saved with {len(s.get('action_items',[]))} action item(s)."
                elif action == "meeting_summarize":
                    s = summarize_meeting(args.get("transcript", ""))
                    result = ("Summary: " + s["summary"][:300] +
                              "\nActions: " + "; ".join(s["action_items"][:5]) +
                              "\nDecisions: " + "; ".join(s["decisions"][:5]))
                elif action == "recordings":
                    rs = get_recordings()
                    result = f"Recordings: {len(rs)}\n" + "\n".join(f"- {r['title']} ({r['ended'][:10]})" for r in rs[:10]) if rs else "No recordings."
                elif action == "routine_add":
                    r = add_routine(args.get("name", ""), args.get("time", ""), args.get("action_text", "") or args.get("name", ""), args.get("days"))
                    result = f"Routine set: {r['name']} at {r['time']}."
                elif action == "routines":
                    rs = get_routines()
                    result = "Routines:\n" + "\n".join(f"- {r['time']} {r['name']}" for r in rs) if rs else "No routines set."
                elif action == "routine_remove":
                    ok = remove_routine(args.get("name", "") or args.get("id", ""))
                    result = "Routine removed." if ok else "Routine not found."
                elif action == "routines_due":
                    fired = check_due_routines()
                    result = "Fired: " + ", ".join(f["routine"] for f in fired) if fired else "No routines due right now."
                elif action == "income_add":
                    i = add_income(args.get("amount", 0), args.get("source", ""), args.get("content", ""))
                    result = f"Income logged: \u20b9{i['amount']} from {i['source']}."
                elif action == "invoice_add":
                    inv = add_invoice(args.get("client", ""), args.get("amount", 0), args.get("status", "pending"), args.get("due", ""))
                    result = f"Invoice added: {inv['client']} \u20b9{inv['amount']} [{inv['status']}], due {inv['due'] or 'n/a'}."
                elif action == "invoice_status":
                    ok = update_invoice_status(args.get("client", "") or args.get("id", ""), args.get("status", ""))
                    result = "Invoice status updated." if ok else "Invoice not found."
                elif action == "asset_add":
                    a = add_asset(args.get("name", ""), args.get("amount", 0), args.get("kind", "asset"))
                    result = f"Asset added: {a['name']} \u20b9{a['value']}."
                elif action == "liability_add":
                    l = add_liability(args.get("name", ""), args.get("amount", 0), args.get("kind", "loan"))
                    result = f"Liability added: {l['name']} \u20b9{l['value']}."
                elif action == "net_worth":
                    nw = get_net_worth()
                    result = f"Net worth: \u20b9{nw['net_worth']} (assets \u20b9{nw['assets']}, liabilities \u20b9{nw['liabilities']})."
                elif action == "finance_summary":
                    s = get_finance_summary()
                    result = f"Finance: income \u20b9{s['income_month']} / expenses \u20b9{s['expenses_month']} this month, profit \u20b9{s['profit_month']}, outstanding \u20b9{s['invoices_outstanding']}."
                elif action == "finance_dashboard":
                    result = get_finance_dashboard()
                elif action == "life_briefing":
                    result = life_briefing()
                else:
                    result = f"Unknown life action: {action}"

            elif name == "hologram":
                action = (args.get("action") or "show").lower()
                obj = args.get("object") or args.get("name") or args.get("part")
                part = args.get("part")
                try:
                    if action in ("show", "open", "display", "view", "launch", "project"):
                        if not obj:
                            result = "What shall I project?"
                        else:
                            model = hologram_model(obj)
                            path = hologram_save(model, obj)
                            hologram_launch(model_path=path)
                            result = (f"Projecting {model['name']} as a hologram "
                                      f"({len(model['parts'])} parts).")
                    elif action in ("show_part", "focus", "select"):
                        if not obj:
                            result = "Which object and part?"
                        else:
                            model = hologram_model(obj)
                            path = hologram_save(model, obj)
                            hologram_launch(model_path=path, part=part or obj)
                            result = f"Highlighting the {part or obj}."
                    elif action == "explode":
                        hologram_launch(explode=True)
                        result = "Exploded view engaged."
                    elif action == "assemble":
                        hologram_launch(explode=False)
                        result = "Reassembling."
                    elif action == "rotate":
                        val = args.get("value")
                        hologram_command({"action": "autorotate",
                                          "value": True if val is None else bool(val)})
                        result = "Rotation updated."
                    elif action in ("close", "quit", "stop", "hide"):
                        hologram_command({"action": "quit"})
                        result = "Closing the hologram."
                    elif action in ("list", "library"):
                        names = ", ".join(hologram_list())
                        result = f"I have {len(hologram_list())} built-in objects: {names}."
                    else:
                        result = f"Unknown hologram action: {action}"
                except Exception as e:
                    print(f"[JARVIS] Hologram error: {e}")
                    result = "I couldn't open the holographic display."

            elif name == "smart_alert":
                action = args.get("action", "")
                if action == "configure":
                    config = configure_alerts(args.get("phone_number", ""))
                    result = f"WhatsApp alerts configured. Phone: {config['user_phone']}"
                elif action == "status":
                    s = get_alert_status()
                    result = f"Alerts enabled: {s['enabled']}\nTotal alerts: {s['total_alerts_sent']}\nInterval: {s['check_interval']}s"
                elif action == "test_alert":
                    from smart_alerts import _load_config
                    cfg = _load_config()
                    ok = send_whatsapp_text_alert(cfg["user_phone"], "JARVIS test: WhatsApp alerts are working.")
                    result = "Test WhatsApp alert sent." if ok else "Failed. Check phone number."
                elif action == "check_now":
                    emails = check_emails_and_alert()
                    result = f"Found {len(emails)} important emails." if emails else "No important emails right now."
                elif action == "enable":
                    start_alert_monitoring()
                    result = "WhatsApp alerts enabled."
                elif action == "disable":
                    stop_alert_monitoring()
                    result = "WhatsApp alerts disabled."
                else:
                    result = f"Unknown alert action: {action}"

            elif name == "notification":
                action = args.get("action", "")
                if action == "briefing":
                    result = briefing()
                elif action == "get_all":
                    n = get_all_notifications()
                    result = f"Total unread: {n['total']}\nEmails: {len(n['emails'])}\nWhatsApp: {len(n['whatsapp'])}\nInstagram: {len(n['instagram'])}"
                elif action == "mark_all_read":
                    mark_all_read()
                    result = "All notifications marked as read."
                else:
                    result = f"Unknown notification action: {action}"

            elif name == "startup_task":
                action = args.get("action", "")
                if action == "dashboard":
                    result = json.dumps(startup_dashboard(), indent=2, ensure_ascii=False)
                elif action == "add_task":
                    task = add_task(args.get("title", ""), args.get("priority", "normal"))
                    result = f"Task added: {task['title']}"
                elif action == "complete_task":
                    ok = complete_task(args.get("title", ""))
                    result = "Milestone completed." if ok else "Task not found."
                elif action == "add_milestone":
                    ms = add_milestone(args.get("title", ""), args.get("description", ""))
                    result = f"Milestone added: {ms['title']}"
                elif action == "complete_milestone":
                    ok = complete_milestone(args.get("title", ""))
                    result = "Milestone completed." if ok else "Milestone not found."
                elif action == "log_metric":
                    m = log_metric(args.get("metric_name", ""), args.get("metric_value", 0), args.get("description", ""))
                    result = f"Metric logged: {m['metric']} = {m['value']}"
                elif action == "save_pitch":
                    d = save_pitch_draft(args.get("title", ""), args.get("description", ""))
                    result = f"Pitch draft saved: {d['title']}"
                elif action == "partner_message":
                    m = log_partner_message(args.get("partner_name", ""), args.get("message", args.get("description", "")))
                    result = f"Message logged for {m['partner']}"
                elif action == "competitor":
                    c = add_competitor(args.get("name", ""), args.get("title", ""), args.get("description", ""))
                    result = f"Competitor added: {c['name']}"
                elif action == "feature":
                    f = add_product_feature(args.get("feature_name", args.get("name", "")), args.get("description", ""))
                    result = f"Feature added: {f['name']}"
                elif action == "team":
                    t = add_team_member(args.get("team_name", args.get("name", "")), args.get("role", ""))
                    result = f"Team member added: {t['name']} as {t['role']}"
                elif action == "investor":
                    u = log_investor_update(args.get("investor_name", ""), args.get("update", args.get("description", "")))
                    result = f"Investor update logged: {u['investor']}"
                else:
                    result = f"Unknown startup action: {action}"

            elif name == "work_task":
                action = args.get("action", "")
                if action == "add_task":
                    t = add_task(args.get("title", ""), args.get("priority", "normal"))
                    result = f"Task added: {t['title']}"
                elif action == "complete_task":
                    ok = complete_task(args.get("title", "") or args.get("id", ""))
                    result = "Task marked complete." if ok else "Task not found."
                elif action == "pending_tasks":
                    tasks = get_pending_tasks()
                    result = f"Pending tasks: {len(tasks)}\n" + "\n".join(f"- [{t['priority']}] {t['title']}" for t in tasks[:10])
                elif action == "daily_briefing":
                    b = daily_briefing()
                    result = f"Daily Briefing ({b['date']}):\n- Pending tasks: {b['total_pending_tasks']}\n- High priority: {b['high_priority_tasks']}\n- Meetings today: {b['meetings_today']}\n- Pending emails: {b['pending_emails']}"
                elif action == "weekly_summary":
                    w = weekly_summary()
                    result = f"Week of {w['week_of']}:\n- Completed: {w['tasks_completed']}\n- Pending: {w['tasks_pending']}\n- Meetings: {w['meetings_this_week']}"
                elif action == "save_email":
                    d = wa_draft_email(args.get("to", ""), args.get("subject", ""), args.get("body", ""))
                    result = f"Email draft saved to {d['to']}"
                elif action == "get_emails":
                    emails = wa_get_email_drafts()
                    result = f"Email drafts: {len(emails)}"
                elif action == "save_document":
                    d = save_document(args.get("title", ""), args.get("description", args.get("body", "")), args.get("doc_type", "note"))
                    result = f"Document saved: {d['title']}"
                elif action == "get_documents":
                    docs = get_documents()
                    result = f"Documents: {len(docs)}"
                elif action == "save_snippet":
                    s = save_code_snippet(args.get("title", ""), args.get("description", args.get("body", "")))
                    result = f"Code snippet saved: {s['description'][:50]}"
                elif action == "meeting_notes":
                    m = save_meeting_notes(args.get("title", ""), args.get("description", args.get("body", "")))
                    result = f"Meeting notes saved: {m['title']}"
                else:
                    result = f"Unknown work action: {action}"

            elif name == "agent_task":
                goal         = args.get("goal", "")
                priority_str = args.get("priority", "normal").lower()

                from agent.task_queue import get_queue, TaskPriority
                priority_map = {
                    "low":    TaskPriority.LOW,
                    "normal": TaskPriority.NORMAL,
                    "high":   TaskPriority.HIGH,
                }
                priority = priority_map.get(priority_str, TaskPriority.NORMAL)

                queue   = get_queue()
                task_id = queue.submit(
                    goal=goal,
                    priority=priority,
                    speak=self.speak,
                )
                self.ui.jarvis_think("sys", f"queued background task "
                                            f"[{task_id}]: {goal}")
                result = f"Task started (ID: {task_id}). I'll update you as I make progress."
            elif name == "spotify_control":
                r = await loop.run_in_executor(
                    None, lambda: spotify_control(parameters=args)
                )
                result = r or "Spotify action completed."
            elif name == "web_search":
                r = await loop.run_in_executor(
                    None, lambda: web_search_action(parameters=args, player=self.ui)
                    )
                result = r or "Search completed."
            elif name == "computer_control":
                r = await loop.run_in_executor(
                    None, lambda: computer_control(parameters=args, player=self.ui)
                )
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(
                    None, lambda: flight_finder(parameters=args, player=self.ui)
                )
                result = r or "Done."

            else:
                result = f"Unknown tool: {name}"
            
        except Exception as e:
            failed = True
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.ui.jarvis_think("err", result)

        print(f"[JARVIS] 📤 {name} → {result[:80]}")
        if not failed:
            self.ui.jarvis_think("result", str(result))

        _tool_ms = (time.perf_counter() - _tool_started) * 1000.0
        try:
            from agent import degrade as _degrade, metrics as _metrics, trace as _trace

            _metrics.observe_ms("tool.call", _tool_ms, tool=name)
            _metrics.inc("tool.failure" if failed else "tool.success", tool=name)
            _trace.record("tool", ms=_tool_ms, ok=not failed, tool=name)
            if not failed:
                _degrade.note_success()
        except Exception:
            pass

        return types.FunctionResponse(
            id=fc.id,
            name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    def _snapshot_mic_audio(self) -> bytes:
        """Return a copy of the most recent microphone audio (thread-safe)."""
        with self._mic_lock:
            return bytes(self._mic_buffer)

    def _mark_output_playing(self):
        """Record that a chunk of JARVIS audio just went to the speaker."""
        with self._play_lock:
            self._last_play_ts = time.time()

    def _output_playing(self) -> bool:
        """True while JARVIS's own voice may still be audible in the room.

        Includes ECHO_GUARD_TAIL_S of tail so speaker + room propagation is
        covered; the mic uplink is muted for this whole window.
        """
        if not ECHO_GUARD:
            return False
        with self._play_lock:
            return (time.time() - self._last_play_ts) < ECHO_GUARD_TAIL_S

    async def _listen_audio(self):
        device = await asyncio.to_thread(_pick_input_device)

        # Optional: pin the Windows capture level (see _apply_mic_level).
        _lvl = AUDIO_CONFIG.get("mic_level")
        if _lvl is not None:
            await asyncio.to_thread(_apply_mic_level, _device_name(device), float(_lvl))

        try:
            stream = await asyncio.to_thread(
                pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE,
                input_device_index=device,
            )
        except Exception as e:
            print(f"[JARVIS] ⚠️ Input device {device} failed ({e}) — using default")
            stream = await asyncio.to_thread(
                pya.open,
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE,
            )
        print(f"[JARVIS] 🎤 Mic started (device={device}, echo guard: "
              f"{'ON' if ECHO_GUARD else 'OFF'}, tail {ECHO_GUARD_TAIL_S}s)")

        # Noise-gate settings (see the NOISE_GATE block above).
        gate_on      = bool(AUDIO_CONFIG.get("noise_gate", NOISE_GATE))
        gate_factor  = float(AUDIO_CONFIG.get("gate_factor", GATE_OPEN_FACTOR))
        self._gate.min_floor = float(
            AUDIO_CONFIG.get("gate_floor_min", GATE_MIN_FLOOR))
        self._gate.max_floor = float(
            AUDIO_CONFIG.get("gate_floor_max", GATE_MAX_FLOOR))
        gate_sent    = 0     # chunks actually forwarded (diagnostic)
        gate_dropped = 0     # chunks replaced with silence (diagnostic)

        # WebRTC VAD: decides speech vs background noise, per 20 ms frame.
        vad = None
        if VAD_ENGINE and _webrtcvad_available():
            try:
                import webrtcvad
                mode = int(AUDIO_CONFIG.get("vad_aggression", VAD_AGGRESSION))
                vad = webrtcvad.Vad(max(0, min(3, mode)))
                print(f"[JARVIS] 🔇 Voice-activity filter on "
                      f"(webrtcvad, aggression {mode})")
            except Exception as e:
                print(f"[JARVIS] ⚠️ webrtcvad unavailable ({e}) — RMS gate only")
        vad_frame_bytes = int(VAD_RATE * VAD_FRAME_MS / 1000) * 2   # 16-bit mono

        # Dead-mic watchdog: if the open device never produces sound, say so
        # once instead of silently ignoring the user for the whole session.
        win_start   = time.time()
        win_peak    = 0
        warned_dead = False
        try:
            while True:
                data = await asyncio.to_thread(
                    stream.read, CHUNK_SIZE, exception_on_overflow=False
                )

                # Half-duplex echo guard: keep reading so the device buffer
                # never backs up, but don't let JARVIS's own voice reach
                # Gemini (which would treat it as a user command).
                if self._output_playing():
                    self._echo_dropped += 1
                    self.ui.update_mic_level(0.0)
                    await asyncio.sleep(0)
                    continue

                samples = np.frombuffer(data, dtype=np.int16)

                level = min(
                    np.abs(samples).mean() / 5000,
                    1.0
                )

                self.ui.update_mic_level(level)

                # --- dead-mic watchdog (one check per ~12s window) -----------
                if samples.size:
                    win_peak = max(win_peak, int(np.abs(samples).max()))
                if time.time() - win_start > 12:
                    if win_peak < MIC_DEAD_PEAK and not warned_dead:
                        warned_dead = True
                        msg = (f"No sound detected on input device {device} — "
                               "check the selected microphone "
                               "(config/audio.json -> \"input_device\").")
                        print(f"[JARVIS] ⚠️ {msg}")
                        self.ui.jarvis_think("err", msg)
                        self.ui.write_log(f"[Audio] {msg}")
                    if gate_on:
                        total = gate_sent + gate_dropped
                        muted = (gate_dropped / total * 100) if total else 0.0
                        print(f"[JARVIS] 🎙️ Mic gate: floor≈{self._gate.floor:.0f} "
                              f"RMS, muted {muted:.0f}% of the last 12s "
                              f"(now {'open' if self._gate.open else 'shut'})")
                    win_start, win_peak = time.time(), 0
                    gate_sent = gate_dropped = 0

                # --- noise gate ----------------------------------------------
                # Forward audio only when it rises above the room's noise floor;
                # otherwise hand the VAD literal silence so it can close the turn.
                vad_speech = None
                if vad is not None:
                    buf = self._vad_carry + data
                    n_frames = len(buf) // vad_frame_bytes
                    speech = False
                    for k in range(n_frames):
                        frame = buf[k * vad_frame_bytes:(k + 1) * vad_frame_bytes]
                        if vad.is_speech(frame, VAD_RATE):
                            speech = True
                            break
                    # Keep only the incomplete tail; frames stay aligned.
                    self._vad_carry = buf[n_frames * vad_frame_bytes:]
                    vad_speech = speech

                raw_data = data          # ungated audio, kept for speaker ID

                if self._gate_keeps_audio(samples, gate_on, gate_factor, vad_speech):
                    gate_sent += 1
                else:
                    data = GATE_SILENCE[:len(data)]
                    gate_dropped += 1

                with self._mic_lock:
                    self._mic_buffer.extend(raw_data)
                    if len(self._mic_buffer) > self._mic_max_bytes:
                        del self._mic_buffer[:-self._mic_max_bytes]

                await self.out_queue.put({
                    "data": data,
                    "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}"
                })
        except Exception as e:
            print(f"[JARVIS] ❌ Mic error: {e}")
            raise
        finally:
            stream.close()

    def _gate_keeps_audio(self, samples, gate_on: bool, gate_factor: float,
                          vad_speech=None) -> bool:
        """Say whether this chunk is speech, tracking the room noise floor.

        The logic (union of webrtcvad and RMS, muted-only floor learning,
        hangover) lives in `jarvis/mic_gate.MicGate` so it can be tested without
        a microphone; this method only supplies the per-call gate switch.
        """
        return self._gate.keeps(samples, gate_on, gate_factor, vad_speech)

    def _identify_speaker(self, audio_data: bytes):
        """Run speaker identification on captured audio."""
        try:
            if not voice_id_available():
                return
            samples = np.frombuffer(audio_data, dtype=np.int16)
            if len(samples) < 16000:
                return
            result = identify_speaker(samples, sample_rate=SEND_SAMPLE_RATE)

            # A8: turn the identified voice into authority. Noise/unavailable
            # leave the role alone; an unrecognised voice is only restricted
            # when roles.enforce_on_unknown is on.
            try:
                from agent import roles
                role = roles.set_from_speaker(result["name"], status=result["status"])
                if role != "owner":
                    self.ui.jarvis_think("sys", f"role: {role}")
                    print(f"[JARVIS] 🔐 Speaker role: {role}")
            except Exception as e:
                print(f"[JARVIS] ⚠️ role assignment failed: {e}")

            if result["status"] == "known":
                self._last_speaker = (result["name"], result["confidence"])
                self.ui.write_log(f"Speaker: {result['name']} ({result['confidence']:.0%})")
                self.ui.jarvis_think("sys", f"voice match: {result['name']} "
                                            f"({result['confidence']:.0%})")
            elif result["status"] == "unknown":
                self.ui.write_log(f"Speaker: {result['name']} (new — will remember)")
                self.ui.jarvis_think("sys", f"new voice: {result['name']} "
                                            f"— registering")
        except Exception as e:
            print(f"[VoiceID] Identification error: {e}")

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf = []
        in_buf  = []
        last_activity = time.time()

        try:
            while True:
                turn = self.session.receive()
                async for response in turn:

                    if response.data:
                        # B6: drop the oldest audio chunk rather than raise when
                        # the speaker side is behind; speech degrades gracefully,
                        # an exception here would kill the session.
                        try:
                            self.audio_in_queue.put_nowait(response.data)
                        except asyncio.QueueFull:
                            try:
                                self.audio_in_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            try:
                                self.audio_in_queue.put_nowait(response.data)
                            except asyncio.QueueFull:
                                pass
                        last_activity = time.time()

                    if response.server_content:
                        sc = response.server_content

                        if sc.input_transcription and sc.input_transcription.text:
                            frag = sc.input_transcription.text
                            if self._output_playing():
                                # Bleed-through of JARVIS's own voice — never
                                # treat it as a user command or a memory.
                                shown = frag.strip()
                                if shown:
                                    self.ui.jarvis_think("sys", f"ignored echo: {shown[:70]}")
                            else:
                                # Gemini streams the transcript in fragments
                                # (" O", "pen", ...). Keep them verbatim and log
                                # the finished sentence once, when the turn ends,
                                # so the LOG pane doesn't look like garbled
                                # listening.
                                in_buf.append(frag)
                                # Speaker ID is expensive and streams many
                                # chunks per turn — throttle it and skip
                                # entirely when the backend is missing.
                                now_ts = time.time()
                                if (
                                    voice_id_available()
                                    and now_ts - self._last_voiceid_ts >= 2.0
                                ):
                                    self._last_voiceid_ts = now_ts
                                    threading.Thread(
                                        target=self._identify_speaker,
                                        args=(self._snapshot_mic_audio(),),
                                        daemon=True
                                    ).start()

                        if sc.output_transcription and sc.output_transcription.text:
                            frag = sc.output_transcription.text
                            if frag and frag.strip():
                                out_buf.append(frag)
                                # live single-line preview while JARVIS talks
                                self.ui.stream_jarvis_text(frag.strip() + " ")

                        if sc.turn_complete:
                            # Fragments are additive, so concatenate them (NOT
                            # join with spaces: "note" + "pad" -> "notepad").
                            full_in  = _tidy_sentence(in_buf)
                            full_out = _tidy_sentence(out_buf)
                            in_buf = []
                            out_buf = []

                            if full_in:
                                # C3: everything logged from here until the next
                                # turn shares one id, so a bad turn can be replayed.
                                try:
                                    from agent import log as _jlog

                                    _jlog.set_turn()
                                except Exception:
                                    pass
                                # W1: a real user turn is activity, so "you have
                                # been at this for two hours" is measured, not guessed.
                                try:
                                    from agent import initiative as _initiative

                                    _initiative.get().note_activity()
                                except Exception:
                                    pass
                                self.ui.write_log(f"You: {full_in}")
                                self.ui.jarvis_think("in", full_in)

                                memory_update = extract_memory(full_in)
                                if memory_update:
                                    update_memory(memory_update)

                                emotion = detect_emotion(full_in)
                                if emotion != "neutral":
                                    self.ui.write_log(f"[Mood: {emotion}]")
                                    remember_experience(
                                        f"User was {emotion}: {full_in[:80]}")

                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True
                                ).start()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 Tool call: {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[JARVIS] ❌ Recv error: {e}")
            self.ui.jarvis_think("err", f"receive loop: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")
        stream = await asyncio.to_thread(
            pya.open,
            format=FORMAT,
            channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE,
            output=True,
        )
        silence_start = None
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.5
                    )
                    if not self.ui.speaking:
                        self.ui.start_speaking()
                    self._mark_output_playing()
                    await asyncio.to_thread(stream.write, chunk)
                    silence_start = None
                except asyncio.TimeoutError:
                    pass

                try:
                    while not self.audio_in_queue.empty():
                        extra = self.audio_in_queue.get_nowait()
                        self._mark_output_playing()
                        await asyncio.to_thread(stream.write, extra)
                except asyncio.QueueEmpty:
                    pass

                # queue drained and the echo tail has elapsed → mic live again
                if self.ui.speaking and not self._output_playing():
                    self.ui.stop_speaking()
        except Exception as e:
            print(f"[JARVIS] ❌ Play error: {e}")
            raise
        finally:
            stream.close()

    async def _watch_routines(self):
        """Proactively surface daily-routine alerts and habit nudges."""
        from datetime import datetime as _dt
        last_nudge = 0.0
        while True:
            try:
                alerts = await asyncio.to_thread(pop_routine_alerts)
                for alert in alerts:
                    self.ui.write_log(f"Routine: {alert['message']}")
                    self.speak(f"Routine reminder. {alert['message']}")

                # Every ~30 min, nudge about habits not done yet today (evening only).
                now = time.time()
                if now - last_nudge > 1800:
                    last_nudge = now
                    pending = await asyncio.to_thread(habits_at_risk)
                    if pending and _dt.now().hour >= 18:
                        names = ", ".join(h["name"] for h in pending)
                        self.speak(f"You still haven't logged these habits today: {names}.")
            except Exception as e:
                print(f"[JARVIS] Routine watcher error: {e}")

            await asyncio.sleep(20)

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        reconnect_attempts = 0

        while True:
            try:
                print("[JARVIS] 🔌 Connecting...")
                config = self._build_config()

                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    reconnect_attempts = 0
                    self.session        = session
                    self._loop          = asyncio.get_event_loop() 
                    # B6: bounded queues. Speaker-out already drops oldest on
                    # overflow (see the put loop); mic-in is bounded here too so
                    # a slow consumer cannot grow memory without limit.
                    self.audio_in_queue = asyncio.Queue(maxsize=50)
                    self.out_queue      = asyncio.Queue(maxsize=10)

                    print("[JARVIS] ✅ Connected.")
                    self.ui.write_log("JARVIS online.")
                    self.ui.jarvis_think("sys", "connected to Gemini Live — session established")

                    # W1: hand the initiative engine the live voice as its
                    # speaker. Re-done on every reconnect, so a proactive nudge
                    # reaches whichever session is current; before the first
                    # connect it degrades to the HUD.
                    try:
                        from agent import initiative as _initiative

                        _initiative.get().configure(speaker=self.speak)
                    except Exception:
                        pass
                    _name = ""
                    try:
                        _identity = load_memory().get("identity", {}) or {}
                        _entry = _identity.get("name")
                        _name = (_entry.get("value") if isinstance(_entry, dict) else _entry) or ""
                    except Exception:
                        _name = ""
                    greeting = check_in(_name or "Mahesh")
                    if greeting:
                        self.speak(greeting)
                    start_monitoring()
                    start_alert_monitoring()
                    start_routine_scheduler()

                    # Speaker recognition: load the voice model in the
                    # background so the first identification is instant rather
                    # than stalling ~7 s on the first utterance.
                    if voice_id_available():
                        threading.Thread(target=voice_id_warmup,
                                         daemon=True).start()
                    notif_brief = briefing()
                    self.ui.write_log(notif_brief)

                    # Life briefing: habits, focus, finance
                    try:
                        life_brief = life_briefing()
                        self.ui.write_log(life_brief)
                        self.speak("Here is your life briefing. " + life_brief.replace("\n", ". "))
                    except Exception as e:
                        print(f"[JARVIS] Life briefing failed: {e}")

                    # Surface routines that fired while JARVIS was offline
                    try:
                        for alert in pop_routine_alerts():
                            self.ui.write_log(f"Routine: {alert['message']}")
                            self.speak(f"Routine reminder. {alert['message']}")
                    except Exception:
                        pass

                    tasks = [
                        asyncio.create_task(self._send_realtime()),
                        asyncio.create_task(self._listen_audio()),
                        asyncio.create_task(self._receive_audio()),
                        asyncio.create_task(self._play_audio()),
                        asyncio.create_task(self._watch_routines()),
                    ]
                    try:
                        await asyncio.gather(*tasks)
                    finally:
                        for t in tasks:
                            t.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                print(f"[JARVIS] ⚠️  Error: {e}")
                self.ui.jarvis_think("err", f"connection: {e}")
                traceback.print_exc()

            print("[JARVIS] 🔄 Reconnecting...")
            # B5: exponential backoff with a cap, so a dead network is not hit
            # every three seconds forever. The delay resets after a successful
            # connection (see reconnect_attempts = 0 above).
            reconnect_attempts = min(reconnect_attempts + 1, 6)
            delay = min(60.0, 3.0 * (2 ** (reconnect_attempts - 1)))
            delay += random.uniform(0, 1.5)
            print(f"[JARVIS]    retry {reconnect_attempts} in {delay:.1f}s")
            await asyncio.sleep(delay)

def main():
    ui = JarvisUI("face.png")

    # T3.23: a short drawn splash; it never blocks startup and removes itself.
    try:
        from agent.version import version as _version
        from ui import splash as _splash
        _splash.show(ui.root, ms=900, version=_version())
    except Exception:
        pass

    ui.set_tasks([
        "✓ Listen",
        "✓ Understand",
        "⟳ Search",
        "□ Execute"
    ])

    ui.set_memory(
        "User: MAHESH\nMode: Voice\nContext: Active"
    )

    ui.set_agent("Planner", "THINKING")

    def runner():
        ui.wait_for_api_key()

        # E2: first-run wizard (microphone choice with a level meter). Runs once;
        # the marker is written only after the questions are answered. Import
        # failures or a non-tty console never stop startup.
        try:
            from agent import first_run
            if not first_run.is_complete():
                first_run.run()
        except Exception as _first_run_err:
            print(f"[JARVIS] first-run wizard skipped: {_first_run_err}")

        # W1: the initiative tick rides the task queue's worker loop, so that
        # loop has to be running for a proactive nudge to ever fire. Starting it
        # is idempotent.
        try:
            _queue = get_queue()
            # W6: a background `confirm` now appears as a modal that shows the
            # exact effect, the risk and the opinion, answered on the Tk thread
            # instead of failing closed with nothing on screen. Deny holds the
            # focus and it denies itself after 30 s.
            from ui import confirm as _confirm

            _queue.set_approver(_confirm.ui_approver(getattr(ui, "root", None)))
        except Exception as _approver_err:
            print(f"[JARVIS] confirmation modal off: {_approver_err}")

        jarvis = JarvisLive(ui)
        # T3.7: typed commands go through the same path as voice turns.
        try:
            ui.on_text_input = jarvis.speak
        except Exception:
            pass
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

    # E3: apply a staged, signature-verified update only after the UI has closed.
    try:
        from agent import updater

        if updater.pending() is not None:
            result = updater.apply_on_exit()
            print(f"[Update] {result.get('status')}: {result.get('reason', result.get('script', ''))}")
    except Exception as _update_err:
        print(f"[Update] apply on exit skipped: {_update_err}")

if __name__ == "__main__":
    main()
    