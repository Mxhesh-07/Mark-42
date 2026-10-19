"""Tier 2 C2 - metrics registry."""

from agent import metrics


def test_a_counter_counts():
    metrics.inc("thing")
    metrics.inc("thing", 2)
    assert metrics.value("thing") == 3


def test_labels_are_part_of_the_identity():
    metrics.inc("denied", level="block")
    metrics.inc("denied", level="confirm")
    metrics.inc("denied", level="block")
    assert metrics.value("denied", level="block") == 2
    assert metrics.value("denied", level="confirm") == 1


def test_label_order_does_not_matter():
    metrics.inc("x", a=1, b=2)
    metrics.inc("x", b=2, a=1)
    assert metrics.value("x", a=1, b=2) == 2


def test_a_gauge_is_set_not_added():
    metrics.set_gauge("level", 1)
    metrics.set_gauge("level", 5)
    assert metrics.value("level") == 5


def test_observe_records_count_total_and_max():
    metrics.observe_ms("stage", 10)
    metrics.observe_ms("stage", 30)
    assert metrics.value("stage_count") == 2
    assert metrics.value("stage_ms_total") == 40
    assert metrics.value("stage_ms_max") == 30


def test_snapshot_is_json_safe():
    import json

    metrics.inc("thing")
    snap = metrics.snapshot()
    assert "uptime_s" in snap
    assert json.dumps(snap)


def test_render_emits_the_prometheus_format():
    metrics.inc("thing", 4)
    metrics.set_gauge("level", 2)
    text = metrics.render()
    assert "thing 4" in text
    assert "level 2" in text
    assert text.endswith("\n")


def test_reset_clears_everything():
    metrics.inc("thing")
    metrics.reset()
    assert metrics.value("thing") == 0
    assert metrics.snapshot()["counters"] == {}
