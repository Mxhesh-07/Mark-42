"""Tier 2 C3 - per-turn tracing."""

from agent import log, trace


def test_a_span_records_its_name_and_duration():
    log.set_turn("turn-a")
    with trace.span("speech_to_text"):
        pass
    spans = trace.current_turn()["spans"]
    assert [s["name"] for s in spans] == ["speech_to_text"]
    assert spans[0]["ok"] is True
    assert spans[0]["ms"] >= 0


def test_spans_belong_to_the_current_turn():
    log.set_turn("turn-1")
    with trace.span("a"):
        pass
    assert trace.current_turn()["turn_id"] == "turn-1"
    log.set_turn("turn-2")
    assert trace.current_turn()["spans"] == []


def test_a_failing_span_is_marked_and_the_error_propagates():
    log.set_turn("turn-x")
    raised = False
    try:
        with trace.span("tool"):
            raise ValueError("boom")
    except ValueError:
        raised = True
    assert raised
    span = trace.current_turn()["spans"][0]
    assert span["ok"] is False
    assert "boom" in span["detail"]


def test_extra_fields_are_kept():
    log.set_turn("turn-y")
    with trace.span("tool", tool="open_app", attempt=2):
        pass
    span = trace.current_turn()["spans"][0]
    assert span["tool"] == "open_app"
    assert span["attempt"] == 2


def test_record_captures_a_duration_measured_elsewhere():
    log.set_turn("turn-z")
    trace.record("planning", ms=42.5, model="gemini")
    span = trace.current_turn()["spans"][0]
    assert span["name"] == "planning"
    assert span["ms"] == 42.5
    assert span["model"] == "gemini"


def test_total_is_the_sum_of_the_stages():
    log.set_turn("turn-t")
    trace.record("a", ms=10)
    trace.record("b", ms=5)
    assert trace.current_turn()["total_ms"] == 15


def test_old_turns_are_evicted(monkeypatch):
    monkeypatch.setattr(trace, "MAX_TURNS", 3)
    for i in range(6):
        log.set_turn(f"t{i}")
        with trace.span("s"):
            pass
    assert len(trace.snapshot(limit=100)["turns"]) == 3


def test_reset_clears_the_buffer():
    log.set_turn("turn-r")
    with trace.span("s"):
        pass
    trace.reset()
    assert trace.current_turn()["spans"] == []
