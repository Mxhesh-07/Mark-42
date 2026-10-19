"""C2/C3/B2 - the executor records every action it runs."""

import time

from agent import degrade, metrics, trace
from agent.executor import _note_action


def test_a_success_is_counted_and_timed():
    _note_action("web_search", time.perf_counter() - 0.01, True)
    assert metrics.value("tool.success", tool="web_search") == 1
    assert metrics.value("tool.call_count", tool="web_search") == 1
    assert metrics.value("tool.call_ms_max", tool="web_search") >= 10


def test_a_failure_is_counted_and_does_not_move_the_ladder_alone():
    _note_action("web_search", time.perf_counter(), False)
    assert metrics.value("tool.failure", tool="web_search") == 1
    assert degrade.level() == "FULL"


def test_successes_recover_a_degraded_system():
    degrade.set_level("TEXT_ONLY")
    for _ in range(degrade.RECOVER_AFTER):
        _note_action("web_search", time.perf_counter(), True)
    assert degrade.level() == "FULL"


def test_an_action_is_traced():
    from agent import log

    log.set_turn("exec-turn")
    _note_action("cmd_control", time.perf_counter(), True)
    spans = trace.current_turn()["spans"]
    assert spans and spans[0]["name"] == "action"
    assert spans[0]["tool"] == "cmd_control"
    assert spans[0]["ok"] is True
