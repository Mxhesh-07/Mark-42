"""Tier 3.1/3.4 — window management and the layout spec."""

from __future__ import annotations

from ui import layout_spec, window


class FakeRoot:
    def __init__(self, w=984, h=816, sw=1920, sh=1080):
        self.w, self.h, self.sw, self.sh = w, h, sw, sh
        self.attrs = {}
        self.geometry_value = ""
        self.state_value = "normal"

    def geometry(self, value=None):
        if value is not None:
            self.geometry_value = value
        return self.geometry_value

    def state(self, value=None):
        if value is not None:
            self.state_value = value
        return self.state_value

    def attributes(self, name, value=None):
        if value is None:
            return self.attrs.get(name)
        self.attrs[name] = value

    def iconify(self):
        self.state_value = "iconic"

    def winfo_geometry(self):
        return "984x816+100+100"

    def winfo_width(self):
        return self.w

    def winfo_height(self):
        return self.h

    def winfo_screenwidth(self):
        return self.sw

    def winfo_screenheight(self):
        return self.sh


def test_metrics_keep_panes_inside_the_window():
    m = layout_spec.Metrics.from_size(984, 816)
    log, think, status = m.pane("log"), m.pane("think"), m.pane("status")
    assert log["x"] >= 0 and log["x"] + log["width"] <= m.width + 1
    assert think["x"] == log["x"] + log["width"] + m.gap
    assert think["x"] + think["width"] <= m.left_x + m.content_width + 1
    assert status["y"] < m.height
    assert log["y"] == m.panes_y


def test_metrics_enforce_a_minimum_window():
    m = layout_spec.Metrics.from_size(10, 10)
    assert m.width >= 640 and m.height >= 480


def test_unknown_pane_is_an_error():
    import pytest

    with pytest.raises(ValueError):
        layout_spec.Metrics.from_size(800, 600).pane("nope")


def test_window_snaps_to_each_corner():
    root = FakeRoot()
    for corner in ("tl", "tr", "bl", "br", "center"):
        assert window.move_to(root, corner) is True
        assert root.geometry_value.startswith("984x816+")
    assert window.move_to(root, "nope") is False


def test_window_toggles_on_top_and_minimizes():
    root = FakeRoot()
    assert window.toggle_always_on_top(root) is True
    assert root.attrs["-topmost"] is True
    assert window.toggle_always_on_top(root) is False
    assert window.minimize(root) is True
    assert root.state_value == "iconic"


def test_window_state_is_a_dict_even_for_a_broken_root():
    class Broken:
        def __getattr__(self, _name):
            raise RuntimeError("no window")

    assert window.state(Broken()) == {}
    assert window.minimize(Broken()) is False
