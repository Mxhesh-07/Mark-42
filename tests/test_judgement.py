"""Tier 4 W2 — risk scoring and pushback.

The formula is deliberately dull, so these tests pin the actual numbers as well
as the behaviour: a read is cheap, a delete is not, and an opinion is voiced at
most once.
"""

from agent import judgement
from agent.policy import Decision, Level


DELETE = {"action": "delete", "path": "C:/x/y.txt"}
READ = {"action": "read", "path": "C:/x/y.txt"}


# --- classification -----------------------------------------------------------

def test_a_read_scores_low():
    advice = judgement.assess("file_controller", READ, decision=Decision(Level.ALLOW, ""))
    assert advice.reversibility == "reversible"
    assert advice.blast_radius == "self"
    assert advice.risk < 0.2


def test_a_delete_scores_high():
    advice = judgement.assess("file_controller", DELETE, decision=Decision(Level.ALLOW, ""))
    assert advice.reversibility == "permanent"
    assert advice.blast_radius == "local"
    assert advice.risk > 0.6


def test_send_message_affects_other_people():
    advice = judgement.assess("send_message",
                              {"recipient": "a", "message": "hi"},
                              decision=Decision(Level.ALLOW, ""))
    assert advice.blast_radius == "other_people"
    assert advice.reversibility == "permanent"
    assert advice.risk > 0.8


def test_power_actions_are_classified():
    for action in ("shutdown", "restart", "reboot"):
        reversibility, blast = judgement.classify("computer_settings", {"action": action})
        assert reversibility == "recoverable"
        assert blast == "self"


def test_an_unknown_tool_gets_a_middle_of_the_road_score():
    advice = judgement.assess("something_brand_new", {},
                              decision=Decision(Level.ALLOW, ""))
    assert 0.0 <= advice.risk <= 1.0
    assert advice.reversibility in judgement.REVERSIBILITY
    assert advice.blast_radius in judgement.BLAST_RADIUS


def test_labels_are_drawn_from_the_declared_vocabulary():
    for tool, params in (("file_controller", READ), ("file_controller", DELETE),
                         ("send_message", {"recipient": "a", "message": "b"}),
                         ("cmd_control", {"command": "dir"})):
        advice = judgement.assess(tool, params, decision=Decision(Level.ALLOW, ""))
        assert advice.reversibility in judgement.REVERSIBILITY
        assert advice.blast_radius in judgement.BLAST_RADIUS


# --- the risk formula ---------------------------------------------------------

def test_low_confidence_raises_the_score():
    """A domain the assistant is bad at is riskier for the same action."""
    from core import self as self_model

    for _ in range(40):
        self_model.record_outcome("files", False)
    unsure = judgement.assess("file_controller", READ,
                              decision=Decision(Level.ALLOW, "")).risk

    self_model.reset_for_tests()
    self_model.STATE_PATH.unlink(missing_ok=True)
    for _ in range(40):
        self_model.record_outcome("files", True)
    sure = judgement.assess("file_controller", READ,
                            decision=Decision(Level.ALLOW, "")).risk

    assert unsure > sure


def test_the_weights_come_from_the_config_file(judgement_file):
    import json

    judgement_file.write_text(json.dumps({
        "weights": {"irreversibility": 1.0, "blast_radius": 0.0, "confidence": 0.0},
        "pushback_threshold": 0.9,
    }), encoding="utf-8")
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.ALLOW, ""))
    assert advice.risk == 1.0


def test_risk_stays_inside_zero_and_one(judgement_file):
    import json

    judgement_file.write_text(json.dumps({
        "weights": {"irreversibility": 5.0, "blast_radius": 5.0, "confidence": 5.0},
    }), encoding="utf-8")
    advice = judgement.assess("send_message", {"recipient": "a", "message": "b"},
                              decision=Decision(Level.ALLOW, ""))
    assert advice.risk == 1.0


# --- pushback rules -----------------------------------------------------------

def test_pushback_fires_once_and_never_twice():
    first = judgement.assess("file_controller", DELETE, decision=Decision(Level.ALLOW, ""))
    assert first.should_pushback is True
    assert first.opinion

    second = judgement.assess("file_controller", DELETE, decision=Decision(Level.ALLOW, ""))
    assert second.should_pushback is False
    assert second.opinion is None
    # the score is unchanged; only the repetition is suppressed
    assert second.risk == first.risk


def test_a_different_effect_is_a_different_decision():
    judgement.assess("file_controller", DELETE, decision=Decision(Level.ALLOW, ""))
    other = judgement.assess("file_controller", {"action": "delete", "path": "D:/other.txt"},
                             decision=Decision(Level.ALLOW, ""))
    assert other.should_pushback is True


def test_pushback_is_suppressed_below_the_threshold(judgement_file):
    import json

    judgement_file.write_text(json.dumps({"pushback_threshold": 0.99}),
                              encoding="utf-8")
    advice = judgement.assess("send_message", {"recipient": "a", "message": "b"},
                              decision=Decision(Level.ALLOW, ""))
    assert advice.risk > 0.0
    assert advice.should_pushback is False
    assert advice.opinion is None


def test_never_pushback_tools_are_honoured(judgement_file):
    import json

    judgement_file.write_text(json.dumps({"never_pushback_tools": ["send_message"]}),
                              encoding="utf-8")
    advice = judgement.assess("send_message", {"recipient": "a", "message": "b"},
                              decision=Decision(Level.ALLOW, ""))
    assert advice.should_pushback is False


def test_safety_paths_never_push_back():
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.ALLOW, ""), safety=True)
    assert advice.should_pushback is False
    assert advice.opinion is None


def test_a_refused_call_is_never_pushed_back_on():
    advice = judgement.assess("cmd_control", {"command": "format c:"},
                              decision=Decision(Level.BLOCK, "refused", hard=True))
    assert advice.allowed is False
    assert advice.should_pushback is False


def test_pushback_on_allow_can_be_switched_off(judgement_file):
    import json

    judgement_file.write_text(json.dumps({"pushback_on_allow": False}),
                              encoding="utf-8")
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.ALLOW, ""))
    assert advice.should_pushback is False


def test_a_confirmation_keeps_its_opinion_even_when_allow_pushback_is_off(judgement_file):
    """The user is already being asked, so the concern belongs in the prompt."""
    import json

    judgement_file.write_text(json.dumps({"pushback_on_allow": False}),
                              encoding="utf-8")
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.CONFIRM, "needs a yes"))
    assert advice.needs_confirmation is True
    assert advice.should_pushback is True


def test_remember_false_does_not_consume_the_session_slot():
    judgement.assess("file_controller", DELETE, decision=Decision(Level.ALLOW, ""),
                     remember=False)
    again = judgement.assess("file_controller", DELETE,
                             decision=Decision(Level.ALLOW, ""))
    assert again.should_pushback is True


def test_the_opinion_is_one_sentence():
    advice = judgement.assess("send_message", {"recipient": "a", "message": "b"},
                              decision=Decision(Level.ALLOW, ""))
    assert advice.opinion.count(".") == 1 or advice.opinion.count("!") == 1
    assert not advice.opinion.strip().endswith(",")


def test_reset_session_allows_the_pushback_again():
    judgement.assess("file_controller", DELETE, decision=Decision(Level.ALLOW, ""))
    assert judgement.pushed_this_session() == 1
    judgement.reset_session()
    assert judgement.pushed_this_session() == 0
    assert judgement.assess("file_controller", DELETE,
                            decision=Decision(Level.ALLOW, "")).should_pushback is True


# --- the decision is reused, not recomputed -----------------------------------

def test_the_supplied_decision_is_authoritative(write_policy, monkeypatch):
    """A second policy.evaluate() would spend a second rate-limit token."""
    from agent import policy

    def explode(*_args, **_kwargs):
        raise AssertionError("assess must not call policy.evaluate again")

    monkeypatch.setattr(policy, "evaluate", explode)
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.ALLOW, "given"))
    assert advice.allowed is True


def test_without_a_decision_it_evaluates(write_policy):
    write_policy({"enabled": True, "tools": {"file_controller": "block"}})
    advice = judgement.assess("file_controller", READ)
    assert advice.allowed is False
    assert advice.level == "block"


def test_a_blocked_tool_is_not_pushed_back_on_even_without_a_decision(write_policy):
    write_policy({"enabled": True, "tools": {"file_controller": "block"}})
    assert judgement.assess("file_controller", DELETE).should_pushback is False


# --- views --------------------------------------------------------------------

def test_explain_is_one_line_and_names_the_score():
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.ALLOW, ""))
    text = judgement.explain(advice)
    assert "\n" not in text
    assert f"{advice.risk:.2f}" in text


def test_the_effect_is_included_for_the_modal():
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.CONFIRM, "needs a yes"))
    assert "y.txt" in advice.effect


def test_as_dict_is_json_safe():
    import json

    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.ALLOW, ""))
    assert json.dumps(advice.as_dict(), default=str)


def test_a_missing_config_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(judgement, "CONFIG_PATH", tmp_path / "absent.json")
    assert judgement.load_config() == {}
    advice = judgement.assess("file_controller", DELETE,
                              decision=Decision(Level.ALLOW, ""))
    assert advice.risk > 0.6            # the built-in defaults still apply
    assert advice.should_pushback is True


def test_a_corrupt_config_is_ignored(judgement_file):
    judgement_file.write_text("{not json", encoding="utf-8")
    assert judgement.load_config() == {}
    assert judgement.assess("file_controller", READ,
                            decision=Decision(Level.ALLOW, "")).risk >= 0.0
