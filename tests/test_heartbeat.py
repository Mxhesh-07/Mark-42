import threading
import time

from agent import brain, executor as executor_mod, heartbeat, initiative, task_queue


def test_tick_once_isolates_failures_and_respects_skip():
    calls = []

    result = heartbeat.tick_once(
        initiative_fn=lambda: calls.append("initiative") or "ok",
        brain_fn=lambda: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert result["initiative"] == "ok"
    assert "brain_error" in result
    assert calls == ["initiative"]

    calls.clear()
    result = heartbeat.tick_once(initiative_fn=heartbeat.SKIP,
                                 brain_fn=lambda: calls.append("brain"))
    assert "initiative" not in result
    assert calls == ["brain"]


def test_heartbeat_runs_both_layers_on_its_own_thread(monkeypatch):
    counts = {"initiative": 0, "brain": 0}
    monkeypatch.setattr(heartbeat, "INITIATIVE_INTERVAL_S", 0.02)
    monkeypatch.setattr(heartbeat, "BRAIN_INTERVAL_S", 0.02)
    monkeypatch.setattr(heartbeat, "TICK_S", 0.01)
    monkeypatch.setattr(initiative, "tick", lambda: counts.__setitem__(
        "initiative", counts["initiative"] + 1))
    monkeypatch.setattr(brain, "tick", lambda: {"count": counts.__setitem__(
        "brain", counts["brain"] + 1)})

    try:
        assert heartbeat.start() is True
        assert heartbeat.start() is True          # idempotent
        time.sleep(0.25)
    finally:
        heartbeat.stop()

    assert counts["initiative"] > 0
    assert counts["brain"] > 0
    assert heartbeat.status()["running"] is False


def test_heartbeat_ticks_while_a_background_task_is_running(monkeypatch):
    """The old worker-loop ticks starved here; the dedicated thread must not."""
    started = threading.Event()
    release = threading.Event()

    class BlockingExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, goal, speak=None, cancel_flag=None):
            started.set()
            release.wait(timeout=3.0)
            return "done"

    monkeypatch.setattr(executor_mod, "AgentExecutor", BlockingExecutor)
    counts = {"brain": 0}
    monkeypatch.setattr(brain, "tick",
                        lambda: {"n": counts.__setitem__("brain", counts["brain"] + 1)})
    monkeypatch.setattr(initiative, "tick", lambda: None)
    monkeypatch.setattr(heartbeat, "INITIATIVE_INTERVAL_S", 0.02)
    monkeypatch.setattr(heartbeat, "BRAIN_INTERVAL_S", 0.02)
    monkeypatch.setattr(heartbeat, "TICK_S", 0.01)

    queue = task_queue.TaskQueue()
    queue.start()
    heartbeat.start()
    try:
        queue.submit("blocking test task")
        assert started.wait(timeout=2.0)
        time.sleep(0.2)
        statuses = queue.get_all_statuses()
        assert any(t["status"] == "running" for t in statuses)
        assert counts["brain"] > 0
    finally:
        release.set()
        heartbeat.stop()
        queue.stop()
