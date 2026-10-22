"""Tier 2 I3/I4 — cost-aware routing and prompt budgeting."""

from agent import routing


def test_trivial_intents_prefer_the_cheap_model():
    assert routing.classify("hi") == "trivial"
    assert routing.classify("open chrome") == "trivial"
    assert routing.classify("what time is it") == "trivial"


def test_reasoning_intents_prefer_the_stronger_model():
    assert routing.classify("why did the build fail and how should I fix it") == "reasoning"
    assert routing.classify("compare two designs step by step") == "reasoning"
    assert routing.classify("x" * 401) == "reasoning"


def test_unclear_intent_stays_standard():
    assert routing.classify("") == "standard"
    assert routing.classify("tell me about the weather tomorrow afternoon") == "standard"


def test_order_keeps_the_same_set_of_models():
    chain = ("gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash")
    for text in ("hi", "why does this happen", "something else entirely"):
        ordered = routing.order(chain, text)
        assert sorted(ordered) == sorted(chain)


def test_order_moves_the_preferred_model_to_the_front():
    chain = ("gemini-2.5-flash", "gemini-2.5-flash-lite")
    assert routing.order(chain, "hi")[0] == "gemini-2.5-flash-lite"
    assert routing.order(chain, "why is the sky blue")[0] == "gemini-2.5-flash"


def test_compact_never_exceeds_the_limit_and_keeps_both_ends():
    text = "INSTRUCTION\n" + ("middle line\n" * 500) + "LAST TURN"
    out = routing.compact(text, limit=200)
    assert len(out) <= 200
    assert out.startswith("INSTRUCTION")
    assert out.endswith("LAST TURN")


def test_compact_leaves_short_prompts_alone():
    assert routing.compact("short prompt") == "short prompt"
