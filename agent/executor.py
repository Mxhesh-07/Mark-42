import json
import re
import sys
import time
import threading
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision
from agent.reflector     import decide_next_step, verify_goal
from agent import audit, policy, untrusted
from agent.policy        import Level


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


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


# Tool results that actually mean "this did not work" — a model refusal or a
# hard error returned as a string. Without this the executor marked refusals
# as "✅ done" and reported success.
_REFUSAL_MARKERS = (
    "i am sorry, but i cannot", "i'm sorry, but i cannot",
    "i am sorry, but i can't", "i'm sorry, but i can't",
    "i cannot directly", "i can't directly",
    "i cannot control", "i can't control",
    "i cannot interact", "i can't interact",
    "i am unable to", "i'm unable to",
    "i do not have the ability", "i don't have the ability",
    "as an ai", "as a language model",
    "i don't have access to", "i do not have access to",
)
_ERROR_MARKERS = (
    "navigation error:", "timeout loading:", "browser error:",
    "click error:", "type error:", "scroll error:", "key error:",
    "could not find:", "could not get", "unknown action:",
    "failed to open", "couldn't confirm it launched",
    "search failed", "web search failed",
)


def _looks_like_failure(result) -> bool:
    """True when a tool's returned text is really a refusal or an error."""
    if result is None:
        return True
    text = str(result).strip()
    if not text:
        return True
    low = text.lower()
    return any(m in low for m in _REFUSAL_MARKERS) or any(
        m in low for m in _ERROR_MARKERS
    )

def _run_generated_code(description: str, speak: Callable | None = None) -> str:
    import google.generativeai as genai

    if speak:
        speak("Writing custom code for this task.")

    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"

    if not desktop.exists():
        try:
            import winreg
            key     = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=(
            "You are an expert Python developer. "
            "Write clean, complete, working Python code. "
            "Use standard library + common packages. "
            "Install missing packages with subprocess + pip if needed. "
            "Return ONLY the Python code. No explanation, no markdown, no backticks.\n\n"
            f"SYSTEM PATHS:\n"
            f"  Desktop   = r'{desktop}'\n"
            f"  Downloads = r'{downloads}'\n"
            f"  Documents = r'{documents}'\n"
            f"  Home      = r'{home}'\n"
        )
    )

    try:
        response = model.generate_content(
            f"Write Python code to accomplish this task:\n\n{description}"
        )
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                tmp_path = f.name

            print(f"[Executor] 🐍 Running generated code: {tmp_path}")

            result = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True, text=True,
                timeout=120, cwd=str(Path.home())
            )
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        output = result.stdout.strip()
        error  = result.stderr.strip()

        if result.returncode == 0 and output:
            return output
        elif result.returncode == 0:
            return "Task completed successfully."
        elif error:
            raise RuntimeError(f"Code error: {error[:400]}")
        raise RuntimeError(
            f"Code error: process exited with code {result.returncode}."
        )

    except subprocess.TimeoutExpired:
        raise RuntimeError("Generated code timed out after 120 seconds.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Generated code failed: {e}")

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if isinstance(v, str) and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                # A5: fetched content about to become a file write is the
                # highest-risk path for an injection, so neutralise it first.
                findings = untrusted.scan(combined)
                if findings:
                    labels = ", ".join(sorted({f["label"] for f in findings}))
                    print(f"[Executor] 🛡️ Neutralised {len(findings)} instruction-like "
                          f"pattern(s) in fetched content: {labels}")
                combined = untrusted.safe_for_injection(combined)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                print("[Executor] 💉 Injected + translated content")

    return params
def _detect_language(text: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel("gemini-2.5-flash")
    try:
        response = model.generate_content(
            f"What language is this text written in? "
            f"Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        import google.generativeai as genai
        genai.configure(api_key=_get_api_key())
        model = genai.GenerativeModel("gemini-2.5-flash")

        target_lang = _detect_language(goal)
        print(f"[Executor] 🌐 Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        response = model.generate_content(prompt)
        translated = response.text.strip()
        print(f"[Executor] ✅ Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Executor] ⚠️ Translation failed: {e}")
        return content

def _call_tool(tool: str, parameters: dict, speak: Callable | None) -> str:

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."

    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(parameters=parameters, player=None) or "Done."

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."

    elif tool == "cmd_control":
        from actions.cmd_control import cmd_control
        return cmd_control(parameters=parameters, player=None) or "Done."

    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        screen_process(parameters=parameters, player=None)
        return "Screen captured and analyzed."

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."

    elif tool == "generated_code":
        description = parameters.get("description", "")
        if not description:
            raise ValueError("generated_code requires a 'description' parameter.")
        return _run_generated_code(description, speak=speak)

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."

    else:
        print(f"[Executor] ⚠️ Unknown tool '{tool}' — falling back to generated_code")
        return _run_generated_code(f"Accomplish this task: {parameters}", speak=speak)


class _TaskAborted(Exception):
    """Raised internally when the error handler decides the task cannot continue."""


class AgentExecutor:
    """
    The agent loop.

    Instead of running a frozen list of steps, it repeatedly:
        1. looks at the goal + everything that has actually happened,
        2. decides the ONE next action (agent.reflector),
        3. runs it and records the real observation,
    then verifies the goal was genuinely achieved before claiming success.

    A proven trajectory from procedural memory is used as a head-start hint,
    and the planner's full plan is kept as a fallback if the reflector cannot
    be reached (e.g. the model is rate-limited).
    """

    MAX_ACTIONS       = 8   # hard ceiling on actions per run
    MAX_VERIFY_ROUNDS = 2   # how many times we may re-try after a failed verify
    MAX_ATTEMPTS      = 3   # per-action retries

    def __init__(self, task_id: str | None = None, approver=None):
        self.task_id       = task_id
        self.approver      = approver    # optional callable(tool, params, reason) -> bool
        self._goal         = ""
        self._step_results = {}   # step number -> result string (for _inject_context)
        self._seq          = 0
        self._deadline     = None

    # ------------------------------------------------------------------ utils

    def _journal(self, entry: dict) -> None:
        """Best-effort: append an action to the persistent task journal."""
        if not self.task_id:
            return
        try:
            from agent import task_store
            task_store.append_journal(self.task_id, entry)
        except Exception:
            pass

    # ------------------------------------------------------------ one action

    def _run_action(
        self,
        tool: str,
        params: dict,
        desc: str,
        speak: Callable | None,
        cancel_flag: threading.Event | None,
    ) -> tuple[bool, str]:
        """
        Run a single tool call with retries and error recovery.

        Returns (ok, observation). Raises _TaskAborted when recovery says stop.
        """
        # --- permission gate + kill switch (the single choke point) ---
        if policy.kill_requested():
            audit.record("action_denied", tool=tool, parameters=params,
                         outcome="blocked", detail="kill switch engaged",
                         task_id=self.task_id, goal=self._goal)
            raise _TaskAborted("the kill switch is engaged")

        gate = policy.evaluate(tool, params)
        if gate.level is not Level.ALLOW:
            approved = False
            if gate.level is Level.CONFIRM and self.approver is not None:
                try:
                    approved = bool(self.approver(tool, params, gate.reason))
                except Exception as e:
                    print(f"[Executor] ⚠️ approver error: {e}")
                    approved = False
            if not approved:
                outcome = "blocked" if gate.level is Level.BLOCK else "denied"
                print(f"[Executor] 🛑 {outcome.upper()}: [{tool}] — {gate.reason}")
                _think("err", f"{outcome}: [{tool}] — {gate.reason}")
                audit.record("action_denied", tool=tool, parameters=params,
                             level=gate.level.value, outcome=outcome,
                             detail=gate.reason, task_id=self.task_id, goal=self._goal)
                return False, f"DENIED ({outcome}): {gate.reason}"

        self._seq += 1
        step_num = self._seq
        params = _inject_context(params, tool, self._step_results, goal=self._goal)

        print(f"\n[Executor] ▶️ Action {step_num}: [{tool}] {desc}")
        _think("tool", f"action {step_num} [{tool}] {desc}")
        if params:
            _think("args", json.dumps(params, ensure_ascii=False, default=str))

        step = {
            "step":        step_num,
            "tool":        tool,
            "description": desc,
            "parameters":  params,
            "critical":    True,
        }

        attempt = 1
        while attempt <= self.MAX_ATTEMPTS:
            if cancel_flag and cancel_flag.is_set():
                return False, "cancelled"
            try:
                result = _call_tool(tool, params, speak)
                if _looks_like_failure(result):
                    raise RuntimeError(
                        f"Tool '{tool}' returned no usable result: {str(result)[:200]}"
                    )
                self._step_results[step_num] = result
                print(f"[Executor] ✅ Action {step_num} done: {str(result)[:100]}")
                _think("result", f"action {step_num}: {str(result)[:130]}")
                audit.record("action", tool=tool, parameters=params, level="allow",
                             outcome="ok", detail=str(result)[:300],
                             task_id=self.task_id, goal=self._goal)
                return True, str(result)

            except Exception as e:
                error_msg = str(e)
                print(f"[Executor] ❌ Action {step_num} attempt {attempt} failed: {error_msg}")
                _think("err", f"action {step_num} attempt {attempt} failed: {error_msg}")

                recovery = analyze_error(step, error_msg, attempt=attempt)
                decision = recovery["decision"]
                user_msg = recovery.get("user_message", "")
                if speak and user_msg:
                    speak(user_msg)

                if decision == ErrorDecision.RETRY:
                    attempt += 1
                    time.sleep(2)
                    continue

                if decision == ErrorDecision.SKIP:
                    print(f"[Executor] ⏭️ Skipping action {step_num}")
                    return True, "Skipped (non-critical)."

                if decision == ErrorDecision.ABORT:
                    raise _TaskAborted(recovery.get("reason", error_msg))

                # REPLAN — try an auto-generated alternative once.
                fix = recovery.get("fix_suggestion", "")
                if fix and tool != "generated_code":
                    try:
                        fixed = generate_fix(step, error_msg, fix)
                        if speak:
                            speak("Trying an alternative approach.")
                        res = _call_tool(fixed["tool"], fixed["parameters"], speak)
                        if not _looks_like_failure(res):
                            self._step_results[step_num] = res
                            print(f"[Executor] ✅ Action {step_num} recovered via fix")
                            return True, str(res)
                    except Exception as fix_err:
                        print(f"[Executor] ⚠️ Fix failed: {fix_err}")

                audit.record("action", tool=tool, parameters=params, outcome="failed",
                             detail=error_msg[:300],
                             task_id=self.task_id, goal=self._goal)
                return False, error_msg

        audit.record("action", tool=tool, parameters=params, outcome="failed",
                     detail="max retries exceeded",
                     task_id=self.task_id, goal=self._goal)
        return False, "Max retries exceeded"

    # -------------------------------------------------------- fallback path

    def _run_plan(
        self,
        plan: dict,
        speak: Callable | None,
        cancel_flag: threading.Event | None,
        history: list,
        actions_taken: list,
    ) -> None:
        """Execute the planner's fixed steps in order (used if the reflector is down)."""
        for step in plan.get("steps", []):
            if cancel_flag and cancel_flag.is_set():
                return
            tool   = step.get("tool", "web_search")
            params = step.get("parameters", {}) or {}
            desc   = step.get("description", "")
            ok, result = self._run_action(tool, params, desc, speak, cancel_flag)
            history.append({
                "tool": tool, "parameters": params, "description": desc,
                # A5: third-party content enters model context as tagged data.
                "observation": untrusted.observation(tool, result), "ok": ok,
            })
            actions_taken.append({"tool": tool, "parameters": params, "description": desc})
            self._journal({"tool": tool, "parameters": params, "ok": ok,
                           "observation": str(result)[:500]})

    # ------------------------------------------------------------- main loop

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
    ) -> str:
        print(f"\n[Executor] 🎯 Goal: {goal}")
        _think("sys", f"goal: {goal}")

        if policy.kill_requested():
            msg = "The kill switch is engaged — I won't start any tasks."
            print("[Executor] 🛑 kill switch engaged — refusing to start")
            _think("err", "kill switch engaged — task refused")
            audit.record("task_start", outcome="blocked", detail="kill switch engaged",
                         task_id=self.task_id, goal=goal)
            if speak:
                speak(msg)
            return msg

        self._goal         = goal
        self._step_results = {}
        self._seq          = 0

        # Budgets come from config/autonomy.json so they can be tuned without
        # touching code. Wall-clock is a hard stop, independent of action count.
        lim      = policy.limits()
        budget   = int(lim.get("max_actions_per_task", self.MAX_ACTIONS) or self.MAX_ACTIONS)
        max_mins = float(lim.get("max_minutes_per_task", 10) or 10)
        self._deadline = time.time() + max_mins * 60
        print(f"[Executor] 🧭 budget: {budget} actions / {max_mins:g} min")

        audit.record("task_start", task_id=self.task_id, goal=goal,
                     detail=f"budget {budget} actions / {max_mins:g} min")

        # 1. Procedural memory — a proven trajectory for a similar goal.
        remembered = None
        pm = None
        try:
            from memory import procedural_memory as pm
            remembered = pm.find_plan(goal)
        except Exception as e:
            pm = None
            print(f"[Executor] ⚠️ procedural memory unavailable: {e}")

        # 2. A fresh plan, used as the first decision's hint and as a fallback.
        plan = create_plan(goal)
        hint = remembered or plan.get("steps", [])

        history:       list = []
        actions_taken: list = []
        verdict = {"satisfied": False, "reason": "", "missing": ""}

        remaining = budget
        rounds    = 0

        try:
            while remaining > 0:
                progressed = False

                # ---- observe → decide → act ----
                while remaining > 0:
                    if cancel_flag and cancel_flag.is_set():
                        if speak:
                            speak("Task cancelled.")
                        return "Task cancelled."

                    if policy.kill_requested():
                        raise _TaskAborted("the kill switch was engaged")
                    if self._deadline and time.time() > self._deadline:
                        raise _TaskAborted("the time budget for this task ran out")

                    decision = decide_next_step(
                        goal, history, plan=hint, note=verdict.get("missing", "")
                    )

                    if decision.get("error"):
                        # The reflector could not be reached — run the plan directly.
                        print("[Executor] ⚠️ Reflector unavailable — executing the plan directly")
                        _think("sys", "reflector unavailable — running the fixed plan")
                        self._run_plan(plan, speak, cancel_flag, history, actions_taken)
                        remaining -= len(plan.get("steps", [])) or 1
                        progressed = True
                        break

                    if decision.get("done"):
                        print(f"[Executor] 🧠 Agent decided done: {decision.get('reasoning', '')}")
                        _think("sys", f"agent decided done: {decision.get('reasoning', '')[:100]}")
                        break

                    tool   = decision["tool"]
                    params = decision["parameters"]
                    desc   = decision["description"]

                    ok, result = self._run_action(tool, params, desc, speak, cancel_flag)
                    history.append({
                        "tool": tool, "parameters": params, "description": desc,
                        # A5: third-party content enters model context as tagged data.
                        "observation": untrusted.observation(tool, result), "ok": ok,
                    })
                    actions_taken.append({"tool": tool, "parameters": params,
                                          "description": desc})
                    self._journal({"tool": tool, "parameters": params, "ok": ok,
                                   "observation": str(result)[:500]})
                    remaining -= 1
                    progressed = True
                    hint = None   # the plan hint only informs the first decision

                # ---- verify before claiming success ----
                verdict = verify_goal(goal, history)
                print(f"[Executor] 🔎 Verify: satisfied={verdict['satisfied']} — "
                      f"{verdict['reason'][:120]}")
                _think("sys",
                       f"verify: {'satisfied' if verdict['satisfied'] else 'not yet'} — "
                       f"{verdict['reason'][:100]}")

                if verdict["satisfied"]:
                    break
                if not progressed or remaining <= 0:
                    break
                if rounds >= self.MAX_VERIFY_ROUNDS:
                    break

                rounds += 1
                if speak:
                    speak("Not quite there yet — double-checking.")

        except _TaskAborted as e:
            msg = f"Task aborted. {str(e).capitalize()}"
            audit.record("task_end", outcome="aborted", detail=str(e),
                         task_id=self.task_id, goal=goal)
            if speak:
                speak(msg)
            return msg

        # 3. Learn from what happened.
        if verdict["satisfied"]:
            if pm is not None:
                try:
                    pm.save_success(goal, actions_taken)
                except Exception as e:
                    print(f"[Executor] ⚠️ could not save procedure: {e}")
            audit.record("task_end", outcome="ok", task_id=self.task_id, goal=goal,
                         detail=f"{len(actions_taken)} action(s), verified satisfied")
            return self._summarize(goal, actions_taken, speak, satisfied=True)

        if pm is not None:
            try:
                pm.note_failure(goal)
            except Exception:
                pass
        audit.record("task_end", outcome="failed", task_id=self.task_id, goal=goal,
                     detail=verdict.get("missing") or verdict.get("reason") or "not verified")
        return self._summarize(
            goal, actions_taken, speak, satisfied=False,
            missing=verdict.get("missing") or verdict.get("reason", ""),
        )

    # -------------------------------------------------------------- summary

    def _summarize(
        self,
        goal:      str,
        actions:   list,
        speak:     Callable | None,
        satisfied: bool = True,
        missing:   str  = "",
    ) -> str:
        if not actions:
            msg = ("I couldn't make progress on that." if not satisfied
                   else f"Done. {goal[:60]}.")
            if speak:
                speak(msg)
            return msg

        if satisfied:
            fallback = (f"All done. Completed {len(actions)} action(s) "
                        f"for: {goal[:60]}.")
        else:
            fallback = (f"I did {len(actions)} action(s), but couldn't fully "
                        f"finish: {goal[:50]}.")

        try:
            import google.generativeai as genai
            genai.configure(api_key=_get_api_key())
            model     = genai.GenerativeModel(model_name="gemini-2.5-flash")
            steps_str = "\n".join(f"- {a.get('description', '')}" for a in actions)

            if satisfied:
                prompt = (
                    f'User goal: "{goal}"\n'
                    f"Completed actions:\n{steps_str}\n\n"
                    "Write a single natural sentence summarizing what was accomplished. "
                    "No formal titles. Be direct and positive."
                )
            else:
                prompt = (
                    f'User goal: "{goal}"\n'
                    f"Actions attempted:\n{steps_str}\n\n"
                    f"Still missing: {missing[:300]}\n\n"
                    "Write a single honest natural sentence: what you managed to do and "
                    "what you could not finish. Do not use formal titles. Do not claim "
                    "success if it was not achieved."
                )

            response = model.generate_content(prompt)
            summary  = response.text.strip()
            if speak:
                speak(summary)
            return summary
        except Exception:
            if speak:
                speak(fallback)
            return fallback
