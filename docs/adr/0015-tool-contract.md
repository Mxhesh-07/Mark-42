# 0015 — A tool is declared, dispatched and registered, or it is not a tool

**Status:** accepted (2026-10-20)

## Context

A tool in this project lives in three places that nothing keeps in step:

- `main.TOOL_DECLARATIONS` — the schema the model is shown, so it knows the tool
  exists and what arguments it takes;
- the `if name == "..."` chain in `main._execute_tool` — the code that actually
  runs when the model calls it;
- `config/autonomy.json` — the permission level the gate applies.

Each disagreement is a real, silent defect. Declare but do not dispatch, and the
model calls a tool that does nothing. Dispatch but do not declare, and the tool
can never be reached. Omit the policy entry, and the tool inherits
`default_level` by accident rather than by decision.

Auditing the three by hand found exactly that: `get_open_windows` — read-only, and
the tool the prompt tells the model to call *before* opening anything — was
silently inheriting `confirm` from the default, while eleven other tools had no
explicit entry at all and one (`generated_code`) was registered but unreachable.

## Decision

`agent/tool_contract.py` reads all three **statically** — `main.py` is parsed with
`ast` and never imported, so the check is fast and has no import side effects —
and reports every disagreement:

1. Every declaration has a name, a description, an `OBJECT` schema with a
   `properties` object, and every `required` name declared; names are unique and
   snake_case.
2. The declared set and the dispatched set are **equal**.
3. Every declared tool is registered in policy (or is an internal tool with a
   documented reason: `generated_code` is reached through `dev_agent` and the A11
   sandbox, never called by the model).
4. Every policy entry names a declared tool.
5. The hand-written guard sets in `policy.py` (`_SANDBOX_TOOLS`,
   `_EGRESS_TOOLS`, `_WRITE_TOOLS`) name real tools — a typo there is a silent
   hole in a security control, so it is worth a test.

`python -m agent.tool_contract --check` runs in CI. `--write` also regenerates a
**tool reference table in the README** between
`<!-- BEGIN GENERATED: tools -->` markers, and `--check` fails if that table is
stale, so the documentation is generated from the declaration rather than
maintained beside it.

`config/autonomy.json` now lists all 29 tools explicitly. That is the part of the
decision worth calling out: the fix for `get_open_windows` is a **loosening**, from
the accidental default `confirm` to `allow`. It reads window titles and changes
nothing, and it sits beside `browser_control` and `spotify_control` at `allow`;
asking permission for it was never deliberate. Every other added entry is
`confirm`, which is what those tools already resolved to, so nothing else changes
behaviour. `default_level` stays as the fallback for an unregistered tool, but
with a complete manifest it should never be reached.

## Consequences

- Adding a tool is now a four-step edit (declaration, dispatch branch, policy
  entry, `--write`), and CI refuses the commit if any step is missing.
- The README's tool table cannot drift; it is a build artifact of the code.
- The guard-set check turns a class of typo — a security control that silently
  matches nothing — into a failing test.
