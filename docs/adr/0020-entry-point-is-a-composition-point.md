# 0020 — The entry point is a composition point, not a library

**Status:** accepted (2026)

## Context

`main.py` had grown to ~2,800 lines and had stopped being an entry point. It held
four unrelated things:

- a ~700-line `TOOL_DECLARATIONS` literal (pure data),
- `_build_config`, which assembled the system prompt, date/time context, memory,
  open-window snapshot, self-model, VAD tuning, thinking budget and voice config,
- `_execute_tool`, a ~680-line dispatcher whose every branch names a different
  action module, and
- the actual audio loop and process lifetime.

None of it could be tested without importing a microphone, a Tk window and the
whole action surface. Every change to tool declarations also showed up as a
thousand-line diff, which made review of the safety-critical dispatch code
harder rather than easier.

## Decision

`main.py` composes; cohesive pieces live in modules under `jarvis/`:

| Piece | Home |
|---|---|
| Tool schema given to the model | `jarvis/tools_schema.py` |
| Prompt/config composition | `jarvis/live_config.py` |
| Tool dispatch | `jarvis/tool_runner.ToolRunnerMixin` |
| Shared text helpers | `jarvis/text_utils.py` |

`JarvisLive` inherits `ToolRunnerMixin`, so the dispatcher still sees the same
`self` (UI, loop, gate, session) and no behaviour is duplicated. `live_config`
takes its dependencies as arguments rather than importing `main`, which makes it
testable with stub callables and a fake `types` module.

The static contract check follows the code: declarations are read from
`jarvis/tools_schema.py` and dispatch branches from `jarvis/tool_runner.py`,
falling back to `main.py` when either file is absent. Moving code therefore
cannot silently remove a tool from the check.

**The audio loop deliberately stays in `main.py`.** It is the one part that
cannot be exercised in CI without a real capture device, and a textual move of
code no test covers is a behaviour change waiting to happen. Splitting it is
worth doing only when the loop can be driven against a fake input stream.

## Consequences

- The entry point is ~1,200 lines: constants, small device helpers, the audio
  loop and `main()`.
- Tool schema and prompt composition have direct tests; the dispatcher and the
  loop keep their existing end-to-end contract check and smoke import.
- `agent.tool_contract` remains the source of truth for "declared, dispatched,
  registered". A refactor that moves a branch without updating the check fails
  CI instead of shipping an unreachable tool.
- Error messages and audit entries are unchanged: this was a move, not a
  redesign.
