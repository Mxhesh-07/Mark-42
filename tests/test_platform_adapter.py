"""Tier 1.5 — platform adapters never raise and no-op off Windows.

The real Windows functions touch COM/hardware, so these tests check the base
implementation and the adapter surface instead of exercising a device.
"""

from __future__ import annotations

import sys

from core import platform as platform_adapter
from core.platform import base


def test_adapter_exposes_the_expected_surface():
    for name in ("is_windows", "set_mic_level", "beep", "notify",
                 "get_master_volume", "set_master_volume"):
        assert callable(getattr(platform_adapter, name))


def test_base_adapter_is_an_explicit_no_op():
    assert base.is_windows() is False
    assert base.set_mic_level("x", 1.0) is False
    assert base.beep() is False
    assert base.notify("x", "y") is False
    assert base.get_master_volume() is None
    assert base.set_master_volume(0.5) is False


def test_adapter_selection_matches_the_host():
    if sys.platform == "win32":
        from core.platform import win

        assert win.is_windows() is True
    assert platform_adapter.is_windows() is (sys.platform == "win32")
