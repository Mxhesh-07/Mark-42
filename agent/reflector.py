"""
Reflector — the "observe → decide" and "verify" half of the agent loop.

The planner produces a whole plan up front. The reflector is the adaptive part:
after every single action it looks at what actually happened and decides the
ONE next action, or declares the goal finished. A separate pass then verifies
that the goal was genuinely achieved before JARVIS is allowed to claim success.

Both calls reuse the planner's JSON-mode Gemini client (agent.planner), so the
model, reasoning budget and quota fallback stay in one place.
"""

from agent.planner import _generate_json, PLANNER_MODEL  # noqa: F401  (re-exported)


# Compact tool reference for the decision prompt. Kept intentionally shorter
# than the planner's catalogue: here the model picks ONE next action from a
# known-good list, it does not need the full parameter prose.
TOOL_REFERENCE = """TOOLS (choose exactly one, or none when done):

open_app(app_name)
web_search(query, mode="search"|"compare", items, aspect)
browser_control(action="go_to"|"search"|"click"|"type"|"scroll"|"get_text"|"press"|"close", url, query, text, direction)
file_controller(action="write"|"create_file"|"read"|"list"|"delete"|"move"|"copy"|"find"|"disk_usage", path, name, content)
cmd_control(task, visible)
computer_settings(action, description, value)
computer_control(action="type"|"click"|"hotkey"|"press"|"scroll"|"screenshot"|"screen_find"|"screen_click", text, x, y, keys, key, direction, description)
screen_process(text, angle="screen"|"camera")
send_message(receiver, message_text, platform)
reminder(date, time, message)
youtube_video(action="play"|"summarize"|"trending", query)
weather_report(city)
flight_finder(origin, destination, date)
code_helper(action="write"|"edit"|"run"|"explain", description, language, output_path, file_path)
dev_agent(description, language)
desktop_control(action="wallpaper"|"organize"|"clean"|"list"|"task", path, task)
spotify_control(action="play"|"pause"|"next"|"previous"|"volume_up"|"volume_down", query)
"""

KNOWN_TOOLS = {
    "open_app", "web_search", "browser_control", "file_controller",
    "cmd_control", "computer_settings", "computer_control", "screen_process",
    "send_message", "reminder", "youtube_video", "weather_report",
    "flight_finder", "code_helper", "dev_agent", "desktop_control",
    "spotify_control", "generated_code",
}


DECIDE_PROMPT = f"""You are the decision core of JARVIS, an autonomous agent running on the user's computer.

You are given:
  - the user's GOAL
  - a HISTORY of actions already taken and their real OBSERVATIONS
  - optionally an INITIAL PLAN (a hint, not a contract)

Your job: decide the SINGLE next action, or declare the goal COMPLETE.

HOW TO DECIDE:
- Read the history carefully. Trust the OBSERVATIONS over the plan — the plan
  is only a guess; what actually happened is the truth.
- Never repeat an action that already succeeded with the same parameters.
- Never invent a result. If a fact is needed and not yet observed, act to get it.
- If the goal is already achieved by the observations, set "done": true.
- If you are stuck, try a genuinely different tool or a different set of
  parameters rather than the same thing again.
- Return ONE action at a time. The history of your past actions is right here.

{TOOL_REFERENCE}

Return ONLY valid JSON, no markdown, no code fences:
{{
  "done": false,
  "reasoning": "one short sentence: why this is the right next action",
  "tool": "tool_name",
  "description": "what this action does, in a few words",
  "parameters": {{}}
}}

When the goal is already achieved, return:
{{"done": true, "reasoning": "why the goal is complete", "tool": "", "description": "", "parameters": {{}}}}
"""


VERIFY_PROMPT = """You are the verification module of JARVIS, an autonomous agent.

You are given a GOAL and the HISTORY of actions taken with their real
OBSERVATIONS. Decide honestly whether the goal has ACTUALLY been achieved.

BE STRICT:
- Only mark satisfied=true if the observations genuinely show the goal is met.
- A tool that merely ran is NOT proof of success. Evidence matters.
- If the goal asked for a file, a message sent, a value found, or an app opened,
  there must be an observation showing it happened.
- If something is missing or uncertain, set satisfied=false and describe exactly
  what is still missing so the agent can fix it.
- If the goal is impossible or was already fully done before the run, mark
  satisfied=true and say why.

Return ONLY valid JSON, no markdown, no code fences:
{
  "satisfied": true,
  "reason": "why the goal is or is not achieved",
  "missing": "what is still missing (empty string when satisfied)"
}
"""


def _format_history(history: list[dict], limit: int = 14, clip: int = 500) -> str:
    if not history:
        return "(no actions taken yet)"
    lines = []
    for i, h in enumerate(history[-limit:], start=1):
        tool = h.get("tool", "?")
        params = h.get("parameters", {}) or {}
        try:
            import json
            pstr = json.dumps(params, ensure_ascii=False, default=str)
        except Exception:
            pstr = str(params)
        obs = str(h.get("observation", "")).replace("\n", " ")
        status = "OK" if h.get("ok") else "FAILED"
        lines.append(
            f"{i}. [{status}] {tool} {pstr[:180]}\n"
            f"   observation: {obs[:clip]}"
        )
    return "\n".join(lines)


def _format_plan(plan: list[dict] | None) -> str:
    if not plan:
        return ""
    steps = []
    for s in plan:
        if isinstance(s, dict):
            steps.append(f"  - [{s.get('tool', '?')}] {s.get('description', '')}")
    if not steps:
        return ""
    return "\nINITIAL PLAN (hint only):\n" + "\n".join(steps) + "\n"


def decide_next_step(
    goal: str,
    history: list[dict],
    plan: list[dict] | None = None,
    note: str = "",
) -> dict:
    """
    Decide the single next action, or completion.

    Returns a normalised dict:
        {"done": bool, "reasoning": str, "tool": str,
         "description": str, "parameters": dict}
    """
    prompt = (
        f"GOAL: {goal}\n"
        f"{_format_plan(plan)}"
        f"\nHISTORY:\n{_format_history(history)}\n"
    )
    if note:
        prompt += f"\nEXTRA NOTE FROM VERIFIER: {note}\n"

    try:
        raw = _generate_json(prompt, DECIDE_PROMPT)
    except Exception as e:
        print(f"[Reflector] ⚠️ decide failed: {e}")
        return {"done": False, "reasoning": f"decide error: {e}", "tool": "",
                "description": "", "parameters": {}, "error": True}

    done = bool(raw.get("done"))
    tool = str(raw.get("tool") or "").strip()
    params = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}

    if not done and tool not in KNOWN_TOOLS:
        print(f"[Reflector] ⚠️ decision named an unknown tool '{tool}'")
        return {"done": False, "reasoning": raw.get("reasoning", ""), "tool": "",
                "description": raw.get("description", ""), "parameters": {},
                "error": True}

    return {
        "done":        done,
        "reasoning":   str(raw.get("reasoning") or "")[:400],
        "tool":        tool,
        "description": str(raw.get("description") or "")[:200],
        "parameters":  params,
    }


def verify_goal(goal: str, history: list[dict]) -> dict:
    """
    Judge whether the goal was actually achieved.

    Returns {"satisfied": bool, "reason": str, "missing": str}.
    On any failure the result is *not* satisfied — JARVIS must never claim a
    success the evidence does not support.
    """
    prompt = f"GOAL: {goal}\n\nHISTORY:\n{_format_history(history, limit=20)}\n"
    try:
        raw = _generate_json(prompt, VERIFY_PROMPT)
        return {
            "satisfied": bool(raw.get("satisfied")),
            "reason":    str(raw.get("reason") or "")[:400],
            "missing":   str(raw.get("missing") or "")[:400],
        }
    except Exception as e:
        print(f"[Reflector] ⚠️ verification failed: {e}")
        return {"satisfied": False, "reason": f"verification error: {e}",
                "missing": "could not verify"}
