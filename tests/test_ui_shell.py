"""Tier 3.19/3.20/3.23/3.25 — overlay, hologram, splash and icon helpers."""

from __future__ import annotations

from ui import hologram_control, icons, layout, notifications, splash


def test_icons_are_drawn_at_the_requested_size_and_colour():
    for name in icons.NAMES:
        image = icons.pil_icon(name, 24, "#ff0000")
        assert image.size == (24, 24)
        assert image.mode == "RGBA"
        assert image.getbbox() is not None


def test_unknown_icon_is_an_error_not_an_empty_image():
    import pytest

    with pytest.raises(ValueError):
        icons.pil_icon("does-not-exist")


def test_hologram_launch_requires_a_model_or_prompt():
    assert hologram_control.launch()["ok"] is False
    assert hologram_control.launch("no-such-model")["ok"] is False


def test_hologram_status_line_is_always_a_string():
    line = hologram_control.status_line()
    assert line.startswith("hologram:")
    assert "models" in line


def test_splash_text_includes_version_and_stage():
    text = splash.splash_text("1.2.3", "audio")
    assert "J.A.R.V.I.S." in text and "v1.2.3" in text and "audio" in text


def test_shutdown_steps_are_ordered_and_end_with_exit():
    steps = splash.shutdown_steps()
    assert steps[-1] == "exit"
    assert steps.index("save window layout") < steps.index("exit")


def test_notification_digest_counts_unread_rows():
    raw = {
        "email": [{"id": "1", "subject": "a", "read": False},
                  {"id": "2", "subject": "b", "read": True}],
        "whatsapp": [{"id": "3", "subject": "c"}],
    }
    assert notifications.digest(raw) == "2 unread: 1 email, 1 whatsapp"
    assert notifications.digest({}) == "No unread notifications."
    assert len(notifications.rows(raw)) == 3


def test_notification_rows_preserve_unread_state():
    raw = {"email": [{"id": "1", "subject": "hello"}]}
    row = notifications.rows(raw)[0]
    assert row["title"] == "hello"
    assert row["unread"] is True
    assert row["kind"] == "email"


def test_setup_saves_a_key_atomically_and_refuses_an_empty_one(tmp_path, monkeypatch):
    from ui import setup

    monkeypatch.setattr(setup, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(setup, "API_FILE", tmp_path / "api_keys.json")
    assert setup.save_key("  ") is False
    assert setup.save_key("abc") is True
    import json

    saved = json.loads((tmp_path / "api_keys.json").read_text(encoding="utf-8"))
    assert saved["gemini_api_key"] == "abc"


def test_opacity_is_clamped():
    class FakeRoot:
        def __init__(self):
            self.value = None

        def attributes(self, _name, value=None):
            self.value = value

    root = FakeRoot()
    assert layout.set_opacity(root, 5) is True
    assert root.value == 1.0
    layout.set_opacity(root, -3)
    assert root.value == 0.2
