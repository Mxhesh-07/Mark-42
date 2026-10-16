import json
import re
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _think(kind: str, text: str) -> None:
    """Best-effort feed to the THINKING pane (the UI may not be loaded)."""
    try:
        from ui import jarvis_think
        jarvis_think(kind, text)
    except Exception:
        pass


PLANNER_PROMPT = """You are the planning module of JARVIS (MARK-42), a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

THINK BEFORE YOU WRITE:
- First decide what "done" actually looks like for this goal, then choose the
  fewest steps that truly get there. Never pad the list.
- Each step must be doable with what exists at the moment it runs; order them so
  the plan never depends on something a later step produces.
- If the goal is a single action, return exactly ONE step.
- Only add a save/open step when the user asked for a file or an artifact.
- Never invent tools, parameters or values that are not listed below.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- NEVER reference previous step results in parameters. Every step is independent.
- Use web_search for ANY information retrieval, research, or current data.
- Use file_controller to save content to disk.
- Use cmd_control to open files or run system commands.
- Max 5 steps. Use the minimum steps needed.

AVAILABLE TOOLS AND THEIR PARAMETERS:

open_app
  app_name: string (required)

web_search
  query: string (required) — write a clear, focused search query
  mode: "search" or "compare" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)

browser_control
  action: "go_to" | "search" | "click" | "type" | "scroll" | "get_text" | "press" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  text: string (for click/type)
  direction: "up" | "down" (for scroll)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" (required)
  path: string — use "desktop" for Desktop folder
  name: string — filename
  content: string — file content (for write/create_file)

cmd_control
  task: string (required) — natural language description of what to do
  visible: boolean (optional)

computer_settings
  action: string (required)
  description: string — natural language description
  value: string (optional)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" (required)
  text: string (for type)
  x, y: int (for click)
  keys: string (for hotkey, e.g. "ctrl+c")
  key: string (for press)
  direction: "up" | "down" (for scroll)
  description: string (for screen_find/screen_click)

screen_process
  text: string (required) — what to analyze or ask about the screen
  angle: "screen" | "camera" (optional)

send_message
  receiver: string (required)
  message_text: string (required)
  platform: string (required)

reminder
  date: string YYYY-MM-DD (required)
  time: string HH:MM (required)
  message: string (required)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "trending" (required)
  query: string (for play)

spotify_control
  action: "play" | "pause" | "next" | "previous" | "volume_up" | "volume_down" (required)
  query: string (for play)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

dev_agent
  description: string (required)
  language: string (optional)

EXAMPLES:

Goal: "makine mühendisliği hakkında araştırma yap ve not defterine kaydet"
Steps:
  1. web_search | query: "mechanical engineering overview definition history"
  2. web_search | query: "mechanical engineering applications and future trends"
  3. file_controller | action: write, path: desktop, name: makine_muhendisligi.txt, content: "MAKINE MUHENDISLIGI ARASTIRMASI\n\nBu dosya web arastirmasi sonuclari ile doldurulacak."
  4. cmd_control | task: "open makine_muhendisligi.txt on desktop with notepad"

Goal: "Bitcoin fiyatı nedir"
Steps:
  1. web_search | query: "Bitcoin price today USD"

Goal: "Masaüstündeki dosyaları listele ve en büyük 5 dosyayı bul"
Steps:
  1. file_controller | action: list, path: desktop
  2. file_controller | action: largest, path: desktop, count: 5

Goal: "WhatsApp'tan Ahmet'e yarın toplantı var de"
Steps:
  1. send_message | receiver: Ahmet, message_text: "Yarın toplantı var", platform: WhatsApp

Goal: "Saati aç ve 30 dakika sonraya hatırlatıcı kur"
Steps:
  1. reminder | date: [today], time: [now+30min], message: "Hatırlatıcı"

Goal: "play songs in Spotify"
Steps:
  1. spotify_control | action: play, query: "songs"

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


PLANNER_MODEL = "gemini-2.5-flash"

# Reasoning budget for the planner. gemini-2.5-flash-lite is deliberately NOT
# used any more: it is the model this project's key exhausts first (429), and a
# plan is a one-shot reasoning task where quality matters more than latency.
# 0 = no reasoning (old behaviour); >0 = think first; -1 = let the model decide.
# Verified: with thinking on, gemini-2.5-flash still returns strict JSON, and
# produced a tighter plan than budget=0.
PLANNER_THINKING_BUDGET = 4096

_client_cache = None


def _client():
    """
    Cached google-genai client.

    Creating a client per call and using it inline let it be garbage-collected
    mid-request → "Cannot send a request, as the client has been closed".
    """
    global _client_cache
    if _client_cache is None:
        from google import genai
        _client_cache = genai.Client(api_key=_get_api_key())
    return _client_cache


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a model reply (tolerates fences/preamble)."""
    text = (text or "").strip()
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _generate_json(prompt: str, system_instruction: str) -> dict:
    """
    Ask Gemini for a strict JSON object.

    Uses the current google-genai SDK with response_mime_type=application/json
    and reasoning enabled (PLANNER_THINKING_BUDGET). The old SDK + thinking model
    returned an empty text part, which is why thinking used to be disabled; on
    the new SDK it is verified to return parseable JSON, so the planner thinks
    again.
    """
    from google.genai import types

    config_kwargs: dict = {
        "system_instruction": system_instruction,
        "response_mime_type": "application/json",
    }
    try:
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=PLANNER_THINKING_BUDGET
        )
    except Exception:
        pass

    client = _client()
    response = client.models.generate_content(
        model=PLANNER_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )
    return _extract_json(getattr(response, "text", "") or "")


def _sanitize_plan(plan: dict, goal: str) -> dict:
    """Validate structure and replace unsupported tools."""
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list):
        raise ValueError("Invalid plan structure")

    for i, step in enumerate(plan["steps"], start=1):
        if not isinstance(step, dict):
            raise ValueError("Invalid step in plan")
        step.setdefault("step", i)
        if step.get("tool") in (None, "", "generated_code"):
            print(f"[Planner] ⚠️ step {step.get('step')} has unsupported tool "
                  f"'{step.get('tool')}' — replacing with web_search")
            desc = step.get("description", goal)
            step["tool"] = "web_search"
            step["parameters"] = {"query": desc[:200]}

    return plan


def create_plan(goal: str, context: str = "") -> dict:
    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        plan = _sanitize_plan(_generate_json(user_input, PLANNER_PROMPT), goal)

        print(f"[Planner] ✅ Plan: {len(plan['steps'])} steps")
        _think("sys", f"plan built — {len(plan['steps'])} steps")
        for s in plan["steps"]:
            print(f"  Step {s['step']}: [{s['tool']}] {s['description']}")
            _think("sys", f"plan ▸ step {s.get('step', '?')} "
                          f"[{s.get('tool', '?')}] {s.get('description', '')[:80]}")

        return plan

    except json.JSONDecodeError as e:
        print(f"[Planner] ⚠️ JSON parse failed: {e}")
        _think("err", f"plan JSON parse failed: {e}")
        return _fallback_plan(goal)
    except Exception as e:
        print(f"[Planner] ⚠️ Planning failed: {e}")
        _think("err", f"planning failed: {e}")
        return _fallback_plan(goal)


_BROWSE_HINTS = (
    "navigate", "browse", "website", "web page", "webpage", "url", "online",
    "linkedin", "instagram", "facebook", "youtube", "amazon", "flipkart",
    "github", "twitter", "google", ".com", ".in", ".org", ".net",
)
_OPEN_HINTS = ("open ", "launch ", "start ")


def _fallback_plan(goal: str) -> dict:
    """
    Last-resort single-step plan.

    Picks a tool from the goal text instead of blindly web_search-ing
    everything — searching a "navigate/open X" goal just makes the search
    model reply with a refusal, which then looked like success.
    """
    print("[Planner] 🔄 Fallback plan")
    g = (goal or "").lower()
    stripped = goal.strip()

    if any(h in g for h in _BROWSE_HINTS):
        query = re.sub(
            r"^(please\s+)?(navigate to|go to|open|browse|search for|find)\s+",
            "", stripped, flags=re.IGNORECASE
        ).strip() or stripped
        return {
            "goal": goal,
            "steps": [{
                "step": 1,
                "tool": "browser_control",
                "description": f"Open a browser and search for: {query}",
                "parameters": {"action": "search", "query": query[:180]},
                "critical": True,
            }],
        }

    if g.startswith(_OPEN_HINTS) or "open the app" in g:
        app_name = re.sub(
            r"^(please\s+)?(open|launch|start)\s+", "", stripped, flags=re.IGNORECASE
        ).strip() or stripped
        return {
            "goal": goal,
            "steps": [{
                "step": 1,
                "tool": "open_app",
                "description": f"Open {app_name}",
                "parameters": {"app_name": app_name[:60]},
                "critical": True,
            }],
        }

    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True
            }
        ]
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    try:
        completed_summary = "\n".join(
            f"  - Step {s.get('step', '')} ({s.get('tool', '')}): DONE" for s in completed_steps
        )
    except Exception as e:
        print(f"[Planner] ⚠️ Failed to build completed summary: {e}")
        completed_summary = ""

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        plan = _sanitize_plan(_generate_json(prompt, PLANNER_PROMPT), goal)

        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        _think("sys", f"replan after failure → {len(plan['steps'])} steps")
        for s in plan["steps"]:
            _think("sys", f"plan ▸ step {s.get('step', '?')} "
                          f"[{s.get('tool', '?')}] {s.get('description', '')[:80]}")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan failed: {e}")
        _think("err", f"replan failed: {e}")
        return _fallback_plan(goal)