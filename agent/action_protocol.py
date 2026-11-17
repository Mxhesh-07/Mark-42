"""ULTRON's action-tag loop, as a reusable protocol for JARVIS.

Plain-text models cannot emit Gemini-style ``function_call`` parts. ULTRON gets
reliable tool use from them by asking for an action tag on its own line::

    On it.
    <action>{"tool": "open_app", "args": {"app_name": "notepad"}}</action>

The model then receives ``[TOOL RESULTS]`` as the next user turn and continues
until it has nothing left to do. This module carries the two parts that made
that loop safe, without carrying any of ULTRON's server or browser code:

* :class:`StreamParser` — streams tokens into spoken text and ``<action>`` /
  ``<think>`` / code blocks. It holds back a partial opener at the end of a
  chunk, so a tag split across tokens is never spoken to the user.
* :class:`LoopGuards` — the repeat/ceiling/double-typed-text guards that stop a
  small model from performing the same step forever.

:func:`parse_action` deliberately accepts only tools in ``allowed``. The caller
passes the same set the permission gate knows about; an invented tool name is
dropped instead of reaching the dispatcher. Nothing here executes anything —
the existing ``jarvis.tool_runner.ToolRunnerMixin._execute_tool`` stays the one
choke point for validation, approval and execution.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence


#: (opener, closer, kind). The longest opener is used to hold back partial tags.
BLOCKS = (
    ("<action>", "</action>", "action"),
    ("<think>", "</think>", "think"),
    ("```", "```", "code"),
)
_MAX_PREFIX = max(len(opener) for opener, _, _ in BLOCKS)

#: Screens change under the model's feet; only after these does it make sense
#: to feed an observation back before allowing another screen action.
SCREEN_TOOLS = frozenset({
    "screen_process", "computer_control", "desktop_control",
    "browser_control", "open_app", "open_url", "click_element",
    "click", "type_text", "press_keys", "scroll", "drag",
})
TEXT_TOOLS = frozenset({"type_text"})

MAX_STEPS = 15
MAX_ACTIONS = 30
MAX_REPEATS = 2

_TOOL_KEYS = ("tool", "action", "function", "name")
_ARG_KEYS = ("args", "arguments", "parameters", "input")
_JSON_PREFIX = re.compile(r"^json\s*", re.IGNORECASE)


def escape_control_in_strings(text: str) -> str:
    """Escape raw control characters inside JSON strings.

    Models frequently put a literal newline inside a JSON string value. Strict
    ``json.loads`` rejects it; escaping it in place recovers the action instead
    of silently discarding the whole tool call.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
                out.append(ch)
            elif ch == "\\":
                escaped = True
                out.append(ch)
            elif ch == '"':
                in_string = False
                out.append(ch)
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                continue
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_string = True
            out.append(ch)
    return "".join(out)


@dataclass(frozen=True)
class Action:
    """One parsed action tag. ``args`` is always a dict (possibly empty)."""

    tool: str
    args: dict = field(default_factory=dict)

    def signature(self) -> str:
        return self.tool + json.dumps(
            self.args or {}, sort_keys=True, default=str, ensure_ascii=False)


def parse_action(
    body: str,
    allowed: Optional[Iterable[str]] = None,
    *,
    tool_keys: Sequence[str] = _TOOL_KEYS,
) -> Optional[Action]:
    """Parse an ``<action>`` body into an :class:`Action`.

    ``allowed`` is an allow-list of tool names. ``None`` accepts any non-empty
    name (useful for parsing a transcript before the dispatcher exists), but
    production callers should always pass the dispatcher's tool set.
    """
    text = _JSON_PREFIX.sub("", body.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        payload = json.loads(escape_control_in_strings(text[start:end + 1]))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    known = set(allowed) if allowed is not None else None
    key = next((k for k in tool_keys
                if isinstance(payload.get(k), str) and payload[k]
                and (known is None or payload[k] in known)), None)
    if key is None:
        return None

    args = next((payload[k] for k in _ARG_KEYS if k in payload), None)
    if isinstance(args, str):
        try:
            args = json.loads(escape_control_in_strings(args))
        except (ValueError, TypeError):
            args = {}
    if not isinstance(args, dict):
        args = {k: v for k, v in payload.items() if k != key}
    return Action(tool=payload[key], args=args)


class StreamParser:
    """Split a stream of model tokens into text and tagged blocks.

    Every segment is also accumulated, so callers can either react through the
    callbacks (stream speech to the user as it arrives) or simply read
    :attr:`speech` / :meth:`actions` at the end of the turn.
    """

    def __init__(
        self,
        on_text: Optional[Callable[[str], None]] = None,
        on_block: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.on_text = on_text
        self.on_block = on_block
        self.buf = ""
        self.block: Optional[tuple[str, str]] = None  # (closer, kind)
        self.parts: list[tuple[str, str]] = []

    def push(self, chunk: str) -> None:
        self.buf += chunk
        self._process(final=False)

    def end(self) -> None:
        self._process(final=True)

    # -- collected view -----------------------------------------------------

    @property
    def speech(self) -> str:
        return "".join(body for kind, body in self.parts if kind == "text")

    def blocks(self, kind: str) -> list[str]:
        return [body for k, body in self.parts if k == kind]

    def actions(self, allowed: Optional[Iterable[str]] = None) -> list[Action]:
        found = []
        for body in self.blocks("action"):
            action = parse_action(body, allowed)
            if action is not None:
                found.append(action)
        return found

    @property
    def hallucinated(self) -> bool:
        """True when the model narrated a result after emitting an action.

        Once an action has been emitted, anything else the model writes is a
        guess at its outcome (small models love to invent ``[TOOL RESULTS]``).
        Dropping that text keeps the next turn honest.
        """
        seen_action = False
        for kind, body in self.parts:
            if kind == "action" and parse_action(body) is not None:
                seen_action = True
            elif kind == "text" and seen_action and body.strip():
                return True
        return False

    # -- streaming core -----------------------------------------------------

    def _text(self, text: str) -> None:
        if not text:
            return
        self.parts.append(("text", text))
        if self.on_text:
            self.on_text(text)

    def _block(self, kind: str, body: str) -> None:
        self.parts.append((kind, body))
        if self.on_block:
            self.on_block(kind, body)

    def _process(self, final: bool) -> None:
        while self.buf:
            if self.block is not None:
                closer, kind = self.block
                index = self.buf.find(closer)
                if index < 0:
                    if final:
                        self._block(kind, self.buf)
                        self.buf = ""
                        self.block = None
                    return
                body = self.buf[:index]
                self.buf = self.buf[index + len(closer):]
                self.block = None
                self._block(kind, body)
                continue

            best = None
            at = -1
            for opener, closer, kind in BLOCKS:
                index = self.buf.find(opener)
                if index >= 0 and (at < 0 or index < at):
                    at, best = index, (opener, closer, kind)
            if best is not None:
                if at > 0:
                    self._text(self.buf[:at])
                opener, closer, kind = best
                self.buf = self.buf[at + len(opener):]
                self.block = (closer, kind)
                continue

            if not final:
                # Hold back a possible partial opener at the end of the buffer.
                for size in range(min(_MAX_PREFIX, len(self.buf)), 0, -1):
                    tail = self.buf[-size:]
                    if any(opener.startswith(tail) for opener, _, _ in BLOCKS):
                        if len(self.buf) > size:
                            self._text(self.buf[:-size])
                        self.buf = tail
                        return
            self._text(self.buf)
            self.buf = ""


@dataclass(frozen=True)
class Verdict:
    """Whether an action may run, and why not if it may not."""

    ok: bool
    reason: str = ""


class LoopGuards:
    """ULTRON's runaway-loop protection, stateful for one user turn.

    ``note_success`` must be called after an action actually succeeded; that is
    what makes the double-text guard track real sends rather than attempts.
    """

    def __init__(
        self,
        *,
        max_steps: int = MAX_STEPS,
        max_actions: int = MAX_ACTIONS,
        max_repeats: int = MAX_REPEATS,
        text_tools: Iterable[str] = TEXT_TOOLS,
    ) -> None:
        self.max_steps = max_steps
        self.max_actions = max_actions
        self.max_repeats = max_repeats
        self.text_tools = frozenset(text_tools)
        self._last_sig: Optional[str] = None
        self._repeats = 0
        self._actions = 0
        self._typed: set[str] = set()

    def check(self, action: Action) -> Verdict:
        sig = action.signature()
        if sig == self._last_sig:
            self._repeats += 1
        else:
            self._last_sig, self._repeats = sig, 0
        self._actions += 1

        if self._repeats >= self.max_repeats:
            return Verdict(False, (
                "Stopped: you keep repeating this action. Try a different "
                "approach, or tell me what is blocking you."))
        if self._actions > self.max_actions:
            return Verdict(False, (
                "Stopped: this turn has run too many actions. Finish with "
                "one short sentence about what actually happened."))
        if action.tool in self.text_tools:
            text = str(action.args.get("text", "") or "").strip()
            if text and text in self._typed:
                return Verdict(False, (
                    "Not typed: you already typed exactly this text in this "
                    "task. Check whether it is in the field or already sent; "
                    "never type it twice."))
        return Verdict(True)

    def note_success(self, action: Action) -> None:
        if action.tool in self.text_tools:
            text = str(action.args.get("text", "") or "").strip()
            if text:
                self._typed.add(text)

    @property
    def steps_left(self) -> int:
        return max(0, self.max_steps - self._actions)


def format_tool_results(results: Sequence[dict]) -> str:
    """The follow-up user turn that closes an action loop.

    Kept as a helper so JARVIS and ULTRON-shaped callers feed the model the
    same compact, machine-readable contract instead of prose that drifts.
    """
    return "[TOOL RESULTS]\n" + json.dumps(list(results), indent=1,
                                            ensure_ascii=False, default=str)
