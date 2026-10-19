"""Tier 2 G3/G4 — the tool contract.

A tool is declared to the model in ``main.TOOL_DECLARATIONS``, dispatched in
``main._execute_tool`` and gated by ``config/autonomy.json``. Those three lists
drift apart silently: a tool can be declared but not dispatched (the model calls
it and nothing happens), dispatched but not declared (nothing can ever call it),
or omitted from policy (it silently inherits the default level).

This module reads all three **statically** — ``main`` is never imported, so the
check is fast and free of import side effects — and reports every disagreement.
``python -m agent.tool_contract --check`` is what CI runs, and ``--write``
regenerates the tool table in the README so the documentation cannot drift
either.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

# Tools the model never calls directly: another tool (dev_agent) routes generated
# code through this name, so it is registered but deliberately not declared.
INTERNAL_TOOLS = {
    "generated_code": "run through dev_agent / the A11 sandbox, never called directly",
}

_DISPATCH_RE = re.compile(r'^\s+(?:if|elif)\s+name\s*==\s*"([a-z][a-z0-9_]*)"', re.M)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

README_PATH = None            # set in get_base_dir() below
README_BEGIN = "<!-- BEGIN GENERATED: tools -->"
README_END = "<!-- END GENERATED: tools -->"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
MAIN_PATH = BASE_DIR / "main.py"
POLICY_PATH = BASE_DIR / "config" / "autonomy.json"
README_PATH = BASE_DIR / "README.md"


# --- static extraction --------------------------------------------------------

def main_source() -> str:
    return MAIN_PATH.read_text(encoding="utf-8")


def declarations() -> list[dict]:
    """Every entry in ``main.TOOL_DECLARATIONS``, as plain data.

    A malformed entry (no ``name``, a non-literal ``parameters``) is returned
    with whatever could be read plus an ``_error`` key, so the check reports it
    rather than raising.
    """
    source = main_source()
    tree = ast.parse(source)
    found: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                   for t in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            found.append({"_error": "TOOL_DECLARATIONS is not a list literal"})
            continue
        for element in node.value.elts:
            if not isinstance(element, ast.Dict):
                found.append({"_error": "a declaration is not a dict literal"})
                continue
            entry: dict = {"_line": getattr(element, "lineno", 0)}
            for key, value in zip(element.keys, element.values):
                if not isinstance(key, ast.Constant):
                    continue
                try:
                    entry[str(key.value)] = ast.literal_eval(value)
                except Exception:
                    entry[str(key.value)] = None
                    entry["_error"] = f"{key.value} is not a literal"
            found.append(entry)
    return found


def dispatched() -> set[str]:
    """Tool names with a real dispatch branch in ``_execute_tool``."""
    return set(_DISPATCH_RE.findall(main_source()))


def registered() -> dict:
    """The policy table: tool name -> level (via ``tools`` and ``actions``)."""
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    levels: dict = {}
    for name, level in (policy.get("tools") or {}).items():
        levels[str(name)] = str(level)
    for name in (policy.get("actions") or {}):
        levels.setdefault(str(name), "per-action")
    return levels


# --- the contract -------------------------------------------------------------

def findings() -> list[str]:
    """Every disagreement between the three lists, as human-readable lines."""
    problems: list[str] = []
    entries = declarations()

    for entry in entries:
        line = entry.get("_line")
        if entry.get("_error"):
            problems.append(f"main.py:{line}: malformed declaration ({entry['_error']})")
            continue
        name = str(entry.get("name") or "")
        if not name:
            problems.append(f"main.py:{line}: a declaration has no name")
            continue
        if not _NAME_RE.match(name):
            problems.append(f"main.py:{line}: {name!r} is not a valid tool name")
        if not str(entry.get("description") or "").strip():
            problems.append(f"{name}: no description for the model to read")
        params = entry.get("parameters")
        if not isinstance(params, dict):
            problems.append(f"{name}: parameters is not an object")
        else:
            if str(params.get("type", "")).upper() != "OBJECT":
                problems.append(f"{name}: parameters.type must be OBJECT")
            if not isinstance(params.get("properties"), dict):
                problems.append(f"{name}: parameters.properties must be an object")
            for required in params.get("required") or []:
                if required not in (params.get("properties") or {}):
                    problems.append(f"{name}: {required!r} is required but not declared")

    names = [str(e.get("name")) for e in entries if e.get("name")]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    for name in duplicates:
        problems.append(f"{name}: declared more than once")

    declared = set(names)
    handled = dispatched()
    for name in sorted(declared - handled):
        problems.append(f"{name}: declared to the model but has no dispatch branch")
    for name in sorted(handled - declared):
        problems.append(f"{name}: dispatched but never declared — the model cannot call it")

    levels = registered()
    for name in sorted(declared - set(levels)):
        if name not in INTERNAL_TOOLS:
            problems.append(f"{name}: not registered in config/autonomy.json "
                            "(it would silently inherit the default level)")
    for name in sorted(set(levels) - declared):
        if name not in INTERNAL_TOOLS:
            problems.append(f"{name}: registered in policy but never declared")

    # The guard sets are hand-written; a typo there is a silent hole.
    problems.extend(_guard_set_findings(declared | set(levels)))
    return problems


def _guard_set_findings(known: set[str]) -> list[str]:
    from agent import policy

    problems = []
    for label in ("_SANDBOX_TOOLS", "_EGRESS_TOOLS", "_WRITE_TOOLS"):
        module_set = getattr(policy, label, None)
        if not isinstance(module_set, (set, frozenset)):
            problems.append(f"policy.{label} is missing")
            continue
        for name in sorted(set(module_set) - known):
            problems.append(f"policy.{label} names {name!r}, which is not a known tool")
    return problems


# --- G4: the README table -----------------------------------------------------

def _first_sentence(text: str, limit: int = 110) -> str:
    text = " ".join(str(text or "").split())
    stop = text.find(". ")
    if 0 < stop < limit:
        text = text[:stop + 1]
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    return text.replace("|", r"\|")


def table() -> str:
    levels = registered()
    rows = ["| Tool | Policy | What it does |", "|------|--------|--------------|"]
    for entry in sorted(declarations(), key=lambda e: str(e.get("name"))):
        name = str(entry.get("name"))
        rows.append(f"| `{name}` | {levels.get(name, 'default')} | "
                    f"{_first_sentence(entry.get('description'))} |")
    return "\n".join(rows)


def readme_ok() -> tuple[bool, str]:
    text = README_PATH.read_text(encoding="utf-8")
    if README_BEGIN not in text or README_END not in text:
        return False, "the README has no generated tool-table markers"
    start = text.index(README_BEGIN) + len(README_BEGIN)
    end = text.index(README_END)
    current = text[start:end].strip()
    return current == table(), "the README tool table is stale"


def write_readme() -> bool:
    """Replace the marked block. True if the file changed."""
    text = README_PATH.read_text(encoding="utf-8")
    if README_BEGIN not in text or README_END not in text:
        raise SystemExit("the README has no generated tool-table markers; "
                         f"add them first:\n{README_BEGIN}\n{README_END}")
    start = text.index(README_BEGIN) + len(README_BEGIN)
    end = text.index(README_END)
    updated = f"{text[:start]}\n{table()}\n{text[end:]}"
    if updated == text:
        return False
    README_PATH.write_text(updated, encoding="utf-8", newline="\n")
    return True


# --- CLI ----------------------------------------------------------------------

def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    mode = argv[0] if argv else "--check"

    problems = findings()
    if mode == "--write":
        write_readme()
        problems = findings()
    if problems:
        print(f"tool contract: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    ok, why = readme_ok()
    if not ok:
        print(f"tool contract: {why}")
        return 1
    print(f"tool contract: ok — {len(declarations())} tools declared, dispatched "
          f"and registered; README table in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
