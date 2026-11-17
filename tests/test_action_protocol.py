"""ULTRON action-tag protocol — parsing and loop safety, without a model."""

from __future__ import annotations

from agent.action_protocol import (
    Action, LoopGuards, StreamParser, Verdict, escape_control_in_strings,
    format_tool_results, parse_action,
)


def test_parser_splits_text_and_blocks():
    p = StreamParser()
    p.push("On it.\n<action>{\"tool\": \"open_app\", \"args\": {\"app_name\": \"notepad\"}}</action>\n")
    p.push("Done.")
    p.end()
    assert p.speech == "On it.\n\nDone."
    assert p.actions({"open_app"}) == [
        Action("open_app", {"app_name": "notepad"})]
    assert p.blocks("think") == []


def test_parser_holds_a_tag_split_across_chunks():
    """A model token stream can cut '<action>' anywhere; none of it is spoken."""
    p = StreamParser()
    heard = []
    p.on_text = heard.append
    for chunk in ("Opening", " <act", "ion>{\"tool\":\"open_app\"}</ac", "tion>ok"):
        p.push(chunk)
    p.end()
    assert "".join(heard) == "Opening ok"
    assert "action>" not in p.speech
    assert p.actions({"open_app"}) == [Action("open_app", {})]


def test_parser_keeps_think_out_of_speech():
    p = StreamParser()
    p.push("<think>plan the steps</think>Reading the file.")
    p.end()
    assert p.speech == "Reading the file."
    assert p.blocks("think") == ["plan the steps"]


def test_parser_flushes_an_unterminated_block_at_end():
    p = StreamParser()
    p.push("partial <think>still planning")
    p.end()
    assert p.speech == "partial "
    assert p.blocks("think") == ["still planning"]


def test_parser_detects_hallucinated_results_after_an_action():
    p = StreamParser()
    p.push("On it. <action>{\"tool\": \"open_app\"}</action> Opened notepad.")
    p.end()
    assert p.hallucinated is True

    q = StreamParser()
    q.push("On it. <action>{\"tool\": \"open_app\"}</action>")
    q.end()
    assert q.hallucinated is False


def test_parse_action_accepts_aliases_and_repairs_raw_newlines():
    a = parse_action(
        '```json\n{"name":"send_message","arguments":{"body":"line one\nline two"}}\n```',
        {"send_message"})
    assert a == Action("send_message", {"body": "line one\nline two"})
    assert escape_control_in_strings('"a\tb"') == '"a\\tb"'


def test_parse_action_falls_back_to_the_remaining_keys():
    assert parse_action('{"tool":"open_app","app_name":"calc"}', {"open_app"}) == (
        Action("open_app", {"app_name": "calc"}))


def test_parse_action_rejects_unknown_and_malformed():
    assert parse_action('{"tool":"rm_rf","args":{}}', {"open_app"}) is None
    assert parse_action('not json at all', {"open_app"}) is None
    assert parse_action('[]', {"open_app"}) is None
    assert parse_action('{"args":{}}', {"open_app"}) is None
    assert parse_action('{"tool":"open_app","args":"{oops"}', {"open_app"}) == (
        Action("open_app", {}))


def test_loop_guards_stop_repeats_and_ceiling():
    step = Action("click", {"mark": 12})
    guards = LoopGuards(max_steps=9, max_actions=4, max_repeats=2)
    assert guards.check(step) == Verdict(True)
    assert guards.check(step) == Verdict(True)
    blocked = guards.check(step)
    assert blocked.ok is False and "repeating" in blocked.reason
    assert guards.steps_left == 6

    fresh = LoopGuards(max_actions=1)
    assert fresh.check(Action("open_app", {"app_name": "a"})).ok is True
    assert fresh.check(Action("open_app", {"app_name": "b"})).ok is False


def test_loop_guards_block_double_typed_text_until_success_is_noted():
    guards = LoopGuards()
    send = Action("type_text", {"text": "hello"})
    assert guards.check(send).ok is True
    guards.note_success(send)
    assert guards.check(send).ok is False
    assert guards.check(Action("type_text", {"text": "goodbye"})).ok is True


def test_format_tool_results_is_machine_readable():
    out = format_tool_results([{"tool": "open_app", "ok": True, "message": "opened"}])
    assert out.startswith("[TOOL RESULTS]\n")
    assert '"tool": "open_app"' in out
