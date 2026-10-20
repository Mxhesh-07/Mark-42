"""Tool arguments are checked against the schema the model was given (Tier 2 G2).

The model is handed a JSON schema for every tool and asked to fill it in. Until
now nothing checked what came back: `_execute_tool` took `fc.args`, wrapped it in
a dict, and passed it to a handler. The permission gate decides *what a tool may
do*, and it decides that from the tool's name and a few well-known fields — it
never looks at whether `app_name` is a string, whether `required` was honoured, or
whether a parameter the tool has never heard of was sent. So a malformed call
reached real code, and the failure surfaced as a `TypeError` deep inside a
handler, or worse, as a handler silently doing something with `None`.

This closes that gap with the one rule that makes it safe to add: **fail closed**.
An argument set that does not match the declaration is refused, not repaired.
Repairing is the tempting option and the wrong one — a value guesses its way
into a shape nobody asked for, and the gate has already been passed.

The vocabulary is deliberately tiny, because that is what the declarations
actually use: STRING, BOOLEAN, INTEGER, NUMBER, ARRAY. Unknown type names are
*not* silently allowed through; a schema this module does not understand is
reported as a finding so the contract check can fail on it, rather than becoming
a hole. That is the same reasoning as `policy._guards`: a check that cannot
decide must not allow.

The schema comes from `tool_contract.declarations()`, which reads `main.py`
statically. Importing `main` here would drag in the SDK and start health checks
just to look at a dict, and the contract module already owns that extraction.
"""

from __future__ import annotations

import json
import sys

# The JSON-schema type names the declarations use, mapped to the Python types
# that satisfy them. `bool` is checked before `int` everywhere, because in Python
# `True` is an `int` and a boolean must not be accepted as a number.
_TYPE_CHECKS: dict[str, tuple] = {
    "STRING": ("a string", lambda v: isinstance(v, str)),
    "BOOLEAN": ("true or false", lambda v: isinstance(v, bool)),
    "INTEGER": ("a whole number",
                lambda v: isinstance(v, int) and not isinstance(v, bool)),
    "NUMBER": ("a number",
               lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)),
    "ARRAY": ("a list", lambda v: isinstance(v, (list, tuple))),
}

KNOWN_TYPES = frozenset(_TYPE_CHECKS)


class Problem:
    """One reason an argument set was rejected."""

    __slots__ = ("kind", "field", "detail")

    def __init__(self, kind: str, field: str, detail: str):
        self.kind = kind        # "unknown_tool" | "missing" | "type" | "unexpected"
        self.field = field
        self.detail = detail

    def __str__(self) -> str:
        return self.detail

    def __repr__(self) -> str:
        return f"Problem({self.kind!r}, {self.field!r}, {self.detail!r})"

    def as_dict(self) -> dict:
        return {"kind": self.kind, "field": self.field, "detail": self.detail}


def _schemas() -> dict[str, dict]:
    """`{tool: parameters-schema}` from the tool contract, cached.

    A declaration whose `parameters` failed to parse is skipped: the contract
    check reports that, and this module must not invent a schema for it.
    """
    global _SCHEMAS
    if _SCHEMAS is not None:
        return _SCHEMAS

    from agent import tool_contract

    out: dict[str, dict] = {}
    for entry in tool_contract.declarations():
        name = entry.get("name")
        if not isinstance(name, str) or entry.get("_error"):
            continue
        params = entry.get("parameters")
        out[name] = params if isinstance(params, dict) else {}
    _SCHEMAS = out
    return out


_SCHEMAS: dict[str, dict] | None = None


def reset_for_tests() -> None:
    global _SCHEMAS
    _SCHEMAS = None


def schema(tool: str) -> dict | None:
    """The declared parameter schema for `tool`, or `None` if it is not a tool."""
    return _schemas().get(tool)


def known(tool: str) -> bool:
    return tool in _schemas()


def properties(tool: str) -> dict:
    params = schema(tool) or {}
    found = params.get("properties")
    return found if isinstance(found, dict) else {}


def required(tool: str) -> list[str]:
    params = schema(tool) or {}
    found = params.get("required")
    return [str(x) for x in found] if isinstance(found, (list, tuple)) else []


def check(tool: str, args: dict | None) -> list[Problem]:
    """Every way `args` fails the declared schema for `tool`.

    An empty list means the call is well-formed. Unknown tools produce a problem
    rather than an empty list: "no schema" must never read as "no constraints".
    """
    if not known(tool):
        return [Problem("unknown_tool", "", f"no declared tool named {tool!r}")]

    if args is None:
        args = {}
    if not isinstance(args, dict):
        return [Problem("type", "", f"arguments must be a mapping, got {type(args).__name__}")]

    props = properties(tool)
    problems: list[Problem] = []

    for name in required(tool):
        if name not in args:
            problems.append(Problem("missing", name, f"{name} is required"))

    for name, value in args.items():
        declared = props.get(name)
        if declared is None:
            # A field the tool never declared. The model invented it, or a rename
            # left a caller behind. Either way the handler will not read it, so
            # accepting it silently is accepting a call that does not mean what
            # it says.
            problems.append(Problem("unexpected", name,
                                    f"{name} is not a parameter of {tool}"))
            continue
        if not isinstance(declared, dict):
            continue
        wanted = str(declared.get("type") or "").upper()
        if wanted not in _TYPE_CHECKS:
            # A type this validator does not implement. Reported, never allowed:
            # an unknown type is exactly where a hole would hide.
            problems.append(Problem("type", name,
                                    f"{name} declares unsupported type {wanted!r}"))
            continue
        label, predicate = _TYPE_CHECKS[wanted]
        if not predicate(value):
            problems.append(Problem(
                "type", name,
                f"{name} must be {label}, got {type(value).__name__}"))
        elif wanted == "ARRAY":
            items = declared.get("items")
            if isinstance(items, dict):
                item_type = str(items.get("type") or "").upper()
                check_item = _TYPE_CHECKS.get(item_type)
                if check_item is None:
                    problems.append(Problem(
                        "type", name,
                        f"{name} declares unsupported item type {item_type!r}"))
                else:
                    item_label, item_predicate = check_item
                    bad = [i for i, v in enumerate(value) if not item_predicate(v)]
                    if bad:
                        problems.append(Problem(
                            "type", name,
                            f"{name}[{bad[0]}] must be {item_label}"))

    return problems


def valid(tool: str, args: dict | None) -> bool:
    return not check(tool, args)


def describe(problems: list[Problem], limit: int = 3) -> str:
    """A short human sentence for the log and the spoken refusal."""
    if not problems:
        return ""
    shown = "; ".join(str(p) for p in problems[:limit])
    if len(problems) > limit:
        shown += f"; (+{len(problems) - limit} more)"
    return shown


def audit_findings() -> list[str]:
    """Schema problems in the declarations themselves, for the contract check.

    Things this module cannot validate are, by construction, things it cannot
    enforce — so they belong in CI as failures, not in a runtime warning nobody
    reads.
    """
    findings: list[str] = []
    for name, params in sorted(_schemas().items()):
        props = params.get("properties")
        if props is not None and not isinstance(props, dict):
            findings.append(f"{name}: properties is not a mapping")
            continue
        for field, declared in (props or {}).items():
            if not isinstance(declared, dict):
                findings.append(f"{name}.{field}: declaration is not a mapping")
                continue
            wanted = str(declared.get("type") or "").upper()
            if wanted not in KNOWN_TYPES:
                findings.append(f"{name}.{field}: unsupported type {wanted!r}")
            items = declared.get("items")
            if isinstance(items, dict):
                item_type = str(items.get("type") or "").upper()
                if item_type not in KNOWN_TYPES:
                    findings.append(
                        f"{name}.{field}[]: unsupported item type {item_type!r}")
        for field in required(name):
            if field not in (props or {}):
                findings.append(
                    f"{name}.{field}: required but not declared in properties")
    return findings


def snapshot() -> dict:
    """What the validator knows, for the health surface and for debugging."""
    schemas = _schemas()
    return {
        "tools": len(schemas),
        "types": sorted(KNOWN_TYPES),
        "required_fields": sum(len(required(name)) for name in schemas),
    }


_USAGE = (
    "usage: python -m agent.tool_args [--check] [TOOL [JSON]]\n"
    "\n"
    "  --check              validate every declaration's schema\n"
    "  TOOL [JSON]          check an argument set against a tool's schema\n"
    "  (no arguments)       what the validator knows\n"
)


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] == "--check":
        findings = audit_findings()
        for finding in findings:
            print(f"  finding: {finding}")
        print(f"schemas ok ({len(_schemas())} tools)" if not findings
              else f"{len(findings)} schema finding(s)")
        return 0 if not findings else 1

    if argv:
        tool = argv[0]
        if not known(tool):
            print(f"no declared tool named {tool!r}")
            return 1
        raw = argv[1] if len(argv) > 1 else "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"arguments are not JSON: {exc}")
            return 2
        problems = check(tool, args)
        for problem in problems:
            print(f"  {problem.kind}: {problem.detail}")
        print("valid" if not problems else f"invalid ({len(problems)} problem(s))")
        return 0 if not problems else 1

    print(json.dumps(snapshot(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
