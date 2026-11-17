"""The web HUD's Python side: state board, bridge and barge-in decision."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest import mock

import pytest

from jarvis.barge_in import BargeInDetector
from ui import confirm
from ui.web.bridge import Bridge
from ui.web.state import WebState

DELETE = {"action": "delete", "path": "C:/x/y.txt"}


def _get(base, path, headers=None):
    req = urllib.request.Request(base + path, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status, res.read()


def _post(base, path, payload, headers=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status, res.read()


# -- state board ----------------------------------------------------------- #
def test_state_classifies_log_lines_and_bumps_revision():
    state = WebState()
    start = state.rev
    state.log("You: open the workshop")
    state.log("Jarvis: opening it now")
    state.log("[Audio] barge-in")
    board = state.snapshot()
    assert board["rev"] > start
    assert [e["role"] for e in board["log"]] == ["you", "jarvis", "sys"]
    assert board["log"][1]["text"] == "opening it now"


def test_state_merges_and_caps_the_log():
    state = WebState()
    for i in range(200):
        state.log(f"sys: {i}")
    board = state.snapshot()
    assert len(board["log"]) == 120
    assert board["log"][-1]["text"].endswith("199")
    state.update(status="SPEAK", mic=0.5)
    board = state.snapshot()
    assert board["status"] == "SPEAK"
    assert board["mic"] == 0.5


def test_state_records_action_loop_events():
    state = WebState()
    for i in range(50):
        state.action(f"tool_{i}", "DONE")
    board = state.snapshot()
    assert len(board["actions"]) == 40
    assert board["actions"][-1]["name"] == "tool_49"


def test_server_quiets_peer_resets_but_keeps_real_errors():
    import ui.web.bridge as bridge_mod

    base = mock.Mock()
    server = object.__new__(bridge_mod._Server)  # no bind; enough for super()
    with mock.patch.object(bridge_mod.ThreadingHTTPServer, "handle_error", base):
        def raise_and_handle(exc):
            try:
                raise exc
            except BaseException:
                bridge_mod._Server.handle_error(server, object(), object())

        raise_and_handle(ConnectionResetError(10054, "peer closed"))
        raise_and_handle(BrokenPipeError(32, "pipe"))
        assert base.call_count == 0          # no stack trace for dead pollers

        raise_and_handle(ValueError("a real bug"))
        assert base.call_count == 1          # real failures still surface


def test_machine_state_sweeps_up_a_stale_think():
    """write_log('You: ...') sets THINK after the machine closes the turn.

    A reply with no spoken audio never calls stop_speaking, so without the
    sweep in update_machine the HUD sits on THINK over a fresh user turn.
    """
    from ui.web_ui import WebUI

    ui = object.__new__(WebUI)          # avoid Tk init / opening a browser
    ui._state = WebState()
    ui._bridge = object()               # _publish only checks `is None`
    ui._thinking = True
    ui.speaking = False
    ui._last_status = "THINK"

    ui.update_machine("standby")
    assert ui._state.snapshot()["machine"] == "standby"
    assert ui._state.snapshot()["status"] == "STANDBY"
    assert ui._state.snapshot()["thinking"] is False
    assert ui._thinking is False

    # A new turn re-arms THINK; moving to LISTENING clears it to LISTEN.
    ui._thinking = True
    ui._last_status = "THINK"
    ui.update_machine("listening")
    assert ui._state.snapshot()["status"] == "LISTEN"

    # SPEAK is never overwritten — the machine may lag a fraction of a second
    # behind the speaker, but the visible state must follow the audio.
    ui.speaking = True
    ui._thinking = True
    ui.update_machine("standby")
    assert ui._state.snapshot()["status"] != "STANDBY"


# -- barge-in -------------------------------------------------------------- #
def test_barge_in_needs_consecutive_loud_chunks():
    det = BargeInDetector(floor=0.14, ratio=1.45, hits=3)
    assert det.check(0.30, 0.0) is False
    assert det.check(0.30, 0.0) is False
    assert det.check(0.02, 0.0) is False       # a quiet chunk resets the count
    assert det.check(0.30, 0.0) is False
    assert det.check(0.30, 0.0) is False
    assert det.check(0.30, 0.0) is True
    assert det.check(0.30, 0.0) is False       # fires once per interruption


def test_barge_in_threshold_tracks_playback_level():
    det = BargeInDetector(floor=0.10, ratio=2.0, hits=1)
    assert det.threshold(0.02) == pytest.approx(0.10)
    assert det.threshold(0.20) == pytest.approx(0.40)
    assert det.check(0.30, 0.20) is False      # loud, but could be bleed
    assert det.check(0.45, 0.20) is True


def test_barge_in_reset_forgets_partial_count():
    det = BargeInDetector(floor=0.1, ratio=1.5, hits=2)
    assert det.check(0.5, 0.0) is False
    det.reset()
    assert det.check(0.5, 0.0) is False
    assert det.check(0.5, 0.0) is True


def test_barge_in_echo_baseline_blocks_own_voice():
    det = BargeInDetector(floor=0.10, ratio=1.45, hits=2)
    # JARVIS's own voice at the mic, with a matching playback level. It is
    # loud in absolute terms but must not be mistaken for the user.
    assert det.check(0.50, 0.35, 0.50) is False
    assert det.check(0.50, 0.35, 0.50) is False
    # A real voice clearly above the learned echo confirms the interruption.
    assert det.check(0.85, 0.35, 0.50) is False
    assert det.check(0.85, 0.35, 0.50) is True


# -- bridge ---------------------------------------------------------------- #
@pytest.fixture()
def hud():
    state = WebState()
    state.update(status="LISTEN", mic=0.4, connected=True)
    bridge = Bridge(state, port=0).start()
    base = bridge.url.rstrip("/")
    yield bridge, state, base
    bridge.stop()


def test_bridge_serves_the_page_and_state(hud):
    bridge, state, base = hud
    code, body = _get(base, "/")
    assert code == 200
    assert b"J.A.R.V.I.S" in body

    code, body = _get(base, "/api/state")
    board = json.loads(body)
    assert board["status"] == "LISTEN"
    assert board["mic"] == 0.4
    assert board["ok"] is True


def test_bridge_sends_commands_through_the_queue(hud):
    bridge, state, base = hud
    code, _ = _post(base, "/api/command", {"kind": "text", "text": "status"})
    assert code == 200
    drained = bridge.commands.drain()
    assert drained == [{"kind": "text", "text": "status"}]

    _post(base, "/api/command", {"kind": "mute", "on": True})
    assert bridge.commands.drain() == [{"kind": "mute", "on": True}]


def test_confirm_commands_carry_a_decision(hud):
    bridge, state, base = hud
    _post(base, "/api/command",
          {"kind": "confirm", "id": "c1", "decision": "approve"})
    _post(base, "/api/command",
          {"kind": "confirm", "id": "c2", "decision": "always"})
    # An unrecognised decision is not an approval.
    _post(base, "/api/command",
          {"kind": "confirm", "id": "c3", "decision": "yes please"})
    # The older boolean form still resolves, and never to "always".
    _post(base, "/api/command", {"kind": "confirm", "id": "c4", "allow": True})
    assert bridge.commands.drain() == [
        {"kind": "confirm", "id": "c1", "decision": "approve"},
        {"kind": "confirm", "id": "c2", "decision": "always"},
        {"kind": "confirm", "id": "c3", "decision": "deny"},
        {"kind": "confirm", "id": "c4", "decision": "approve"},
    ]


# -- confirmations over the HUD -------------------------------------------- #
@pytest.fixture()
def shower():
    """Install a web-style shower and always restore the Tk default."""
    def install(fn):
        confirm.set_shower(fn)
        return fn

    yield install
    confirm.set_shower(None)


def test_a_registered_shower_replaces_the_tk_dialog(shower):
    seen = []
    shower(lambda panel, done: seen.append(panel))
    answer = confirm.consult("file_controller", DELETE, timeout_s=0.05)
    assert seen and seen[0]["tool"] == "file_controller"
    assert seen[0]["buttons"]
    assert answer.decision == confirm.DENY
    assert answer.reason == "timeout"


def test_a_shower_can_approve_the_same_way_the_dialog_can(shower):
    shower(lambda panel, done: done(confirm.APPROVE))
    answer = confirm.consult("file_controller", DELETE)
    assert answer.decision == confirm.APPROVE
    assert answer.approved is True


def test_a_broken_shower_fails_closed(shower):
    def explode(panel, done):
        raise RuntimeError("page gone")

    shower(explode)
    answer = confirm.consult("file_controller", DELETE)
    assert answer.decision == confirm.DENY
    assert answer.reason == "dialog failed"


def test_consult_on_prefers_the_shower_over_the_hidden_root(shower):
    calls = []

    def show_panel(panel, done):
        calls.append(panel["tool"])
        done(confirm.DENY)

    shower(show_panel)

    class Root:
        def after(self, *args):
            raise AssertionError("the Tk dialog should not be built")

    answer = confirm.consult_on(Root(), "file_controller", DELETE)
    assert calls == ["file_controller"]
    assert answer.decision == confirm.DENY


def test_bridge_refuses_cross_origin_and_unknown_commands(hud):
    bridge, state, base = hud
    with pytest.raises(urllib.error.HTTPError) as err:
        _post(base, "/api/command", {"kind": "stop"},
              headers={"Origin": "http://evil.example"})
    assert err.value.code == 403

    with pytest.raises(urllib.error.HTTPError) as err:
        _post(base, "/api/command", {"kind": "shell", "cmd": "whoami"})
    assert err.value.code == 400
    assert bridge.commands.drain() == []


def test_bridge_does_not_serve_outside_the_static_root(hud):
    bridge, state, base = hud
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(base, "/../bridge.py")
    assert err.value.code == 403
