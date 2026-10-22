"""Tier 2 G3/G4 — the tool contract.

A tool touches three lists: what the model is told it can call
(`main.TOOL_DECLARATIONS`), what actually handles the call (`_execute_tool`), and
what the permission gate allows (`config/autonomy.json`). Nothing in the language
itself keeps them in step, so a tool can be announced and not implemented, or
implemented and unreachable, or silently inherit a default level. These tests
hold the three together, and hold the generated README table to the same source.
"""

import json

import pytest

from agent import tool_contract


FAKE_MAIN = '''\
TOOL_DECLARATIONS = [
    {
        "name": "phantom",
        "description": "Does nothing at all.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]
'''

FAKE_MAIN_WITH_HANDLER = FAKE_MAIN + '''

def _execute_tool(name):
    if name == "phantom":
        return None
'''


@pytest.fixture
def fake_source(tmp_path, monkeypatch):
    """Point the extractor at a synthetic main.py / autonomy.json pair."""
    def _install(source: str, policy: dict):
        main = tmp_path / "main.py"
        main.write_text(source, encoding="utf-8")
        pol = tmp_path / "autonomy.json"
        pol.write_text(json.dumps(policy), encoding="utf-8")
        monkeypatch.setattr(tool_contract, "MAIN_PATH", main)
        monkeypatch.setattr(tool_contract, "SCHEMA_PATH", main)
        monkeypatch.setattr(tool_contract, "DISPATCH_PATH", main)
        monkeypatch.setattr(tool_contract, "POLICY_PATH", pol)
        return tool_contract.findings()

    return _install


def tool_problems(problems):
    """Drop the guard-set findings: those check policy.py against the *real*
    tool list, so they are expected when the tool list is synthetic."""
    return [p for p in problems if not p.startswith("policy.")]


# --- the real project ---------------------------------------------------------

def test_every_tool_satisfies_the_contract():
    problems = tool_contract.findings()
    assert problems == [], "\n".join(problems)


def test_the_readme_tool_table_is_current():
    ok, why = tool_contract.readme_ok()
    assert ok is True, why


def test_the_extractor_sees_a_realistic_number_of_tools():
    names = {entry.get("name") for entry in tool_contract.declarations()}
    assert len(names) >= 20
    assert {"open_app", "file_controller", "web_search", "devices"} <= names


def test_declared_and_dispatched_agree_in_the_real_project():
    names = {entry.get("name") for entry in tool_contract.declarations()}
    assert names == tool_contract.dispatched()


def test_every_real_tool_is_registered_in_policy():
    names = {entry.get("name") for entry in tool_contract.declarations()}
    missing = names - set(tool_contract.registered())
    assert missing == set()


def test_the_table_has_one_row_per_tool():
    rows = [line for line in tool_contract.table().splitlines() if line.startswith("| `")]
    assert len(rows) == len(tool_contract.declarations())


def test_the_cli_check_passes(capsys):
    assert tool_contract._cli(["--check"]) == 0
    assert "ok" in capsys.readouterr().out


# --- the checker itself -------------------------------------------------------

def test_a_declaration_with_no_handler_is_reported(fake_source):
    problems = fake_source(FAKE_MAIN, {"tools": {"phantom": "confirm"}})
    assert any("no dispatch branch" in p for p in problems), problems


def test_a_matching_handler_satisfies_the_contract(fake_source):
    problems = fake_source(FAKE_MAIN_WITH_HANDLER, {"tools": {"phantom": "confirm"}})
    assert tool_problems(problems) == [], problems


def test_an_unregistered_tool_is_reported(fake_source):
    problems = fake_source(FAKE_MAIN_WITH_HANDLER, {"tools": {}})
    assert any("not registered" in p for p in problems), problems


def test_a_handler_with_no_declaration_is_reported(fake_source):
    source = 'TOOL_DECLARATIONS = []\n\n\ndef _execute_tool(name):\n' \
             '    if name == "orphan":\n        return None\n'
    problems = fake_source(source, {"tools": {"orphan": "confirm"}})
    assert any("never declared" in p for p in problems), problems


def test_a_missing_description_is_reported(fake_source):
    source = 'TOOL_DECLARATIONS = [\n' \
             '    {"name": "quiet", "description": "",\n' \
             '     "parameters": {"type": "OBJECT", "properties": {}}},\n' \
             ']\n\n\ndef _execute_tool(name):\n' \
             '    if name == "quiet":\n        return None\n'
    problems = fake_source(source, {"tools": {"quiet": "confirm"}})
    assert any("no description" in p for p in problems), problems


def test_a_bad_parameter_schema_is_reported(fake_source):
    source = 'TOOL_DECLARATIONS = [\n' \
             '    {"name": "bad", "description": "x",\n' \
             '     "parameters": {"type": "STRING", "properties": {}}},\n' \
             ']\n\n\ndef _execute_tool(name):\n' \
             '    if name == "bad":\n        return None\n'
    problems = fake_source(source, {"tools": {"bad": "confirm"}})
    assert any("must be OBJECT" in p for p in problems), problems


def test_a_required_name_that_is_not_declared_is_reported(fake_source):
    source = 'TOOL_DECLARATIONS = [\n' \
             '    {"name": "req", "description": "x",\n' \
             '     "parameters": {"type": "OBJECT", "properties": {},\n' \
             '                    "required": ["city"]}},\n' \
             ']\n\n\ndef _execute_tool(name):\n' \
             '    if name == "req":\n        return None\n'
    problems = fake_source(source, {"tools": {"req": "confirm"}})
    assert any("required but not declared" in p for p in problems), problems


def test_a_duplicate_declaration_is_reported(fake_source):
    source = 'TOOL_DECLARATIONS = [\n' \
             '    {"name": "twice", "description": "x",\n' \
             '     "parameters": {"type": "OBJECT", "properties": {}}},\n' \
             '    {"name": "twice", "description": "x",\n' \
             '     "parameters": {"type": "OBJECT", "properties": {}}},\n' \
             ']\n\n\ndef _execute_tool(name):\n' \
             '    if name == "twice":\n        return None\n'
    problems = fake_source(source, {"tools": {"twice": "confirm"}})
    assert any("declared more than once" in p for p in problems), problems


def test_an_internal_tool_is_allowed_to_be_undeclared(fake_source):
    problems = fake_source(FAKE_MAIN_WITH_HANDLER,
                           {"tools": {"phantom": "confirm",
                                      "generated_code": "confirm"}})
    assert tool_problems(problems) == [], problems


def test_the_guard_sets_are_checked_against_the_tool_list(fake_source):
    problems = fake_source(FAKE_MAIN_WITH_HANDLER, {"tools": {"phantom": "confirm"}})
    assert any(p.startswith("policy._SANDBOX_TOOLS") for p in problems), problems


def test_a_typo_in_a_guard_set_is_caught(monkeypatch):
    from agent import policy

    monkeypatch.setattr(policy, "_SANDBOX_TOOLS", frozenset({"file_controler"}))
    problems = tool_contract.findings()
    assert any("file_controler" in p for p in problems), problems


# --- what the table must look like --------------------------------------------

def test_a_description_is_shortened_to_its_first_sentence():
    text = tool_contract._first_sentence("One thing. Then a second thing that is long.")
    assert text == "One thing."


def test_a_pipe_in_a_description_cannot_break_the_table():
    assert "\\|" in tool_contract._first_sentence("a | b")


def test_the_table_names_the_policy_level():
    assert "| `devices` | confirm |" in tool_contract.table()
