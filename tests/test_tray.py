"""T3.1 — the optional tray icon is safe to create anywhere."""

from __future__ import annotations

from ui import tray


class _Root:
    def __init__(self):
        self.calls = []

    def after(self, ms, fn):
        self.calls.append((ms, fn))


class _UI:
    def __init__(self):
        self.root = _Root()
        self.events = []

    def show_from_tray(self):
        self.events.append("show")

    def hide_to_tray(self):
        self.events.append("hide")

    def open_settings(self):
        self.events.append("settings")

    def _on_close(self):
        self.events.append("quit")


def test_icon_is_drawn_at_any_size():
    for size in (16, 32, 64, 128):
        image = tray.icon_image(size)
        assert image.size == (size, size)
        assert image.mode == "RGBA"
        assert image.getbbox() is not None


def test_tray_is_disabled_by_request(monkeypatch):
    monkeypatch.setenv("JARVIS_NO_TRAY", "1")
    assert tray.available() is False
    assert tray.Tray(_UI()).start() is False


def test_tray_is_disabled_outside_windows(monkeypatch):
    monkeypatch.delenv("JARVIS_NO_TRAY", raising=False)
    monkeypatch.setattr(tray.sys, "platform", "linux")
    assert tray.available() is False


def test_callbacks_run_on_the_tk_thread():
    ui = _UI()
    icon = tray.Tray(ui)

    icon._show()
    icon._hide()
    icon._settings()
    icon._quit()

    # Nothing runs on the tray thread; each callback is queued with after(0).
    assert len(ui.root.calls) == 4
    assert ui.events == []
    for ms, fn in ui.root.calls:
        assert ms == 0
        fn()
    assert ui.events == ["show", "hide", "settings", "quit"]


def test_stop_is_safe_when_never_started():
    icon = tray.Tray(_UI())
    icon.stop()
    icon.stop()
    assert icon._icon is None
