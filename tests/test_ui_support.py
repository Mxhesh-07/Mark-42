"""Tier 3.10/3.13/3.15/3.17/3.24/3.27 — HUD support modules (no Tk)."""

from __future__ import annotations

from ui import support, theme, widgets


def test_themes_all_have_the_same_keys():
    keys = set(theme.THEMES[theme.DEFAULT_THEME])
    for name, colors in theme.THEMES.items():
        assert set(colors) == keys, name


def test_hud_constants_follow_the_configured_theme():
    import ui

    colors = theme.palette()
    assert ui.C_PRI == colors["pri"]
    assert ui.C_BG == colors["bg"]


def test_unknown_theme_falls_back_rather_than_raising():
    assert theme.palette("does_not_exist") == theme.THEMES[theme.DEFAULT_THEME]
    assert theme.save_theme("does_not_exist") is False


def test_font_helper_returns_tk_tuples():
    assert theme.font(9) == ("Courier", 9)
    assert theme.font(9, bold=True) == ("Courier", 9, "bold")
    assert theme.font("11", bold=True) == ("Courier", 11, "bold")


def test_status_text_is_compact_and_never_empty():
    text = support.status_text({"provider": "gemini", "model": "m1", "mode": "FULL",
                                "queue": 0, "breakers": 0, "recording": False})
    assert "gemini" in text and "m1" in text and "FULL" in text
    assert "\n" not in text


def test_status_snapshot_is_total_even_when_subsystems_fail(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr(support, "audit_lines", boom)
    state = support.status_snapshot()
    assert isinstance(state, dict)
    assert "mode" in state and "queue" in state


def test_audit_lines_tolerates_a_broken_audit(monkeypatch):
    import agent.audit as audit

    monkeypatch.setattr(audit, "tail", lambda _n=50: (_ for _ in ()).throw(RuntimeError("x")))
    assert support.audit_lines() == []


def test_empty_states_exist_for_every_pane():
    for kind in ("tasks", "memory", "thinking", "audit", "recordings"):
        assert widgets.empty_state(kind)
    assert widgets.empty_state("unknown") == "Nothing here yet."


def test_kill_state_is_fail_closed_when_policy_is_unavailable(monkeypatch):
    import agent.policy as policy

    monkeypatch.setattr(policy, "kill_requested",
                        lambda: (_ for _ in ()).throw(RuntimeError("x")))
    state = support.kill_state()
    assert state["engaged"] is True
