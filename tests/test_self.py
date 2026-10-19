"""Tier 4 W3 — the self-model.

Two things are being proved here: that confidence is an honest running average
of real outcomes, and that identity is written once. A system that rewrites who
it is on every run does not have continuity, which is the whole point.
"""

import json

from agent import degrade
from core import self as self_model


def test_confidence_starts_at_the_default():
    assert self_model.confidence("voice") == self_model.DEFAULT_CONFIDENCE


def test_success_raises_and_failure_lowers_confidence():
    for _ in range(5):
        self_model.record_outcome("files", True)
    assert self_model.confidence("files") > self_model.DEFAULT_CONFIDENCE

    for _ in range(20):
        self_model.record_outcome("files", False)
    assert self_model.confidence("files") < self_model.DEFAULT_CONFIDENCE


def test_the_average_is_smoothed_not_a_coin_flip():
    """One outcome must not swing the number to an extreme."""
    after_one = self_model.record_outcome("code", True)
    assert after_one < 0.7

    many = self_model.DEFAULT_CONFIDENCE
    for _ in range(60):
        many = self_model.record_outcome("code", True)
    assert many > 0.99


def test_confidence_persists_and_is_per_domain():
    self_model.record_outcome("browser", False)
    assert self_model.confidence("browser") < 0.5
    assert self_model.confidence("vision") == self_model.DEFAULT_CONFIDENCE


def test_outcome_counts_are_kept(tmp_path):
    self_model.record_outcome("voice", True)
    self_model.record_outcome("voice", False)
    doc = json.loads(self_model.STATE_PATH.read_text(encoding="utf-8"))
    assert doc["outcomes"]["voice"] == {"ok": 1, "fail": 1}


def test_identity_is_written_once_and_never_mutated():
    first = self_model.identity()
    assert first["name"]

    for _ in range(5):
        self_model.record_outcome("memory", True)
    assert self_model.identity() == first


def test_an_existing_identity_is_respected(tmp_path):
    self_model.STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    self_model.STATE_PATH.write_text(
        json.dumps({"identity": {"name": "CUSTOM", "limits": []}}),
        encoding="utf-8",
    )
    assert self_model.identity()["name"] == "CUSTOM"
    # and record_outcome must not rewrite it
    self_model.record_outcome("memory", True)
    assert self_model.identity()["name"] == "CUSTOM"


def test_domain_for_maps_known_tools_and_ignores_unknown():
    assert self_model.domain_for("web_search") == "browser"
    assert self_model.domain_for("file_controller") == "files"
    assert self_model.domain_for("something_new") is None
    assert self_model.domain_for("") is None


def test_a_failing_probe_marks_the_tool_unavailable():
    self_model.register_probe("web_search", lambda: False)
    self_model.register_probe("weather_report", lambda: True)
    caps = self_model.capabilities(["web_search", "weather_report"])
    assert caps["web_search"] is False
    assert caps["weather_report"] is True


def test_a_raising_probe_counts_as_unavailable():
    def boom():
        raise RuntimeError("device gone")

    self_model.register_probe("screen_process", boom)
    assert self_model.capabilities(["screen_process"])["screen_process"] is False


def test_a_probe_result_is_cached_until_reset():
    calls = []

    def flaky():
        calls.append(1)
        return True

    self_model.register_probe("devices", flaky)
    self_model.capabilities(["devices"])
    self_model.capabilities(["devices"])
    assert len(calls) == 1

    self_model.capabilities(["devices"], refresh=True)
    assert len(calls) == 2


def test_a_policy_blocked_tool_is_unavailable(write_policy):
    write_policy({"enabled": True, "tools": {"web_search": "block",
                                             "weather_report": "allow"}})
    caps = self_model.capabilities(["web_search", "weather_report"])
    assert caps["web_search"] is False
    assert caps["weather_report"] is True


def test_monitor_mode_leaves_nothing_available(write_policy):
    write_policy({"enabled": True, "tools": {"web_search": "allow"}})
    degrade.set_level("MONITOR")
    assert self_model.capabilities(["web_search"])["web_search"] is False


def test_read_only_marks_writes_unavailable(write_policy):
    write_policy({"enabled": True, "tools": {"file_controller": "allow",
                                             "web_search": "allow"}})
    degrade.set_level("READ_ONLY")
    caps = self_model.capabilities(["file_controller", "web_search"])
    assert caps["file_controller"] is False     # deleting/writing is a write
    assert caps["web_search"] is True           # reading is still allowed


def test_state_reports_mode_and_kill_switch(policy_file):
    degrade.set_level("READ_ONLY")
    st = self_model.state()
    assert st["mode"] == "READ_ONLY"
    assert st["degraded"] is True
    assert st["kill_switch"] is False


def test_note_provider_and_quota_show_up_in_state(policy_file):
    self_model.note_provider("groq")
    self_model.note_quota(8, 20)
    st = self_model.state()
    assert st["provider"] == "groq"
    assert st["quota"] == {"remaining": 8, "limit": 20}


def test_snapshot_is_json_safe(policy_file):
    snap = self_model.snapshot()
    json.dumps(snap, default=str)          # must not raise
    assert set(snap["confidence"]) == set(self_model.DOMAINS)


def test_render_stays_within_the_line_budget(policy_file):
    lines = self_model.render().splitlines()
    assert lines[0] == "[SELF]"
    assert len(lines) <= self_model.MAX_SNAPSHOT_LINES


def test_render_names_the_weakest_domain(policy_file):
    for _ in range(30):
        self_model.record_outcome("devices", False)
    for _ in range(30):
        self_model.record_outcome("voice", True)
    text = self_model.render()
    assert "devices 0.0" in text or "devices 0." in text
    assert "voice 1.0" in text or "voice 0.9" in text


def test_prompt_block_states_the_rule(policy_file):
    block = self_model.prompt_block()
    assert "[SELF]" in block
    assert "honestly" in block


def test_reset_clears_the_probe_cache():
    self_model.register_probe("x", lambda: False)
    assert self_model.capabilities(["x"])["x"] is False
    self_model.reset_for_tests()
    assert self_model.capabilities(["x"])["x"] is True
