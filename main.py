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
from jarvis.text_utils import (
    fmt_args as _fmt_args,
    owner_name as _owner_name,
    tidy_sentence as _tidy_sentence,
)
from jarvis.tool_runner import ToolRunnerMixin

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


from jarvis.tools_schema import TOOL_DECLARATIONS


class JarvisLive(ToolRunnerMixin):

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
        """T1.6: prompt composition and config live in jarvis/live_config.py."""
        from jarvis import live_config

        memory = load_memory()
        return live_config.build_config(
            types=types,
            base_dir=BASE_DIR,
            memory_text=format_memory_for_prompt(memory),
            load_system_prompt=_load_system_prompt,
            describe_state=_describe_state,
            prompt_budget=_apply_prompt_budget,
            tool_declarations=TOOL_DECLARATIONS,
            vad_tuning=VAD_TUNING,
            vad_silence_ms=VAD_SILENCE_MS,
            vad_start_sens=VAD_START_SENS,
            vad_end_sens=VAD_END_SENS,
            thinking_budget=THINKING_BUDGET,
            affective_dialog=AFFECTIVE_DIALOG,
            ctx_trigger=CTX_TRIGGER_TOKENS,
            ctx_target=CTX_TARGET_TOKENS,
            temperature=LIVE_TEMPERATURE,
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
    