"""MK-LXXXV HUD telemetry bridge (hud_mk85/telemetry.py).

The bridge is a single script rather than an installed package, so it is
loaded by path. These tests pin the parts that are easy to get quietly wrong:

* the storage percentage must be a ratio of byte counts, not of rounded GB
  values (that bug shipped once already - every volume read 0%);
* anything the machine cannot measure must be reported as ``null`` *and* be
  named in ``est``, so the HUD can label it instead of faking it;
* the HTTP surface must serve the HUD and refuse to walk out of its folder.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "hud_mk85" / "telemetry.py"


def _load():
    spec = importlib.util.spec_from_file_location("mk85_telemetry", BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


telemetry = _load()
pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# sampler
# --------------------------------------------------------------------------- #
def test_snapshot_has_the_shape_the_hud_reads():
    snap = telemetry.Sampler().one(slow=False)

    assert snap["ok"] is True
    assert isinstance(snap["ts"], float)

    cpu = snap["cpu"]
    assert 0 <= cpu["pct"] <= 100
    assert isinstance(cpu["per"], list)
    assert cpu["threads"] >= cpu["cores"] >= 1

    mem = snap["mem"]
    assert 0 <= mem["pct"] <= 100
    assert mem["total"] > 0
    assert mem["used"] <= mem["total"] + 1

    # Storage and network are always present as the right container type,
    # even when the platform reports nothing.
    assert isinstance(snap["disks"], list)
    assert isinstance(snap["usb"], list)
    net = snap["net"]
    assert net is not None
    assert net["rx"] >= 0 and net["tx"] >= 0


def test_volume_percentage_divides_bytes_by_bytes():
    """Regression: the ratio must not mix GB with bytes.

    Dividing a rounded GB figure by a byte count silently truncates every
    volume to 0.0%, which is how the original bug presented.
    """
    disks, usb = telemetry.Sampler._volumes()

    for entry in disks + usb:
        assert entry["total"] > 0
        expected = entry["used"] / entry["total"] * 100
        assert entry["pct"] == pytest.approx(expected, abs=1.0), entry


def test_unmeasured_sensors_are_declared_in_est():
    snap = telemetry.Sampler().one(slow=False)

    if snap["temps"]["cpu"] is None:
        assert "cpu_temp" in snap["est"]
    if snap["temps"]["gpu"] is None:
        assert "gpu_temp" in snap["est"]
    if snap["fans"]["cpu"] is None:
        assert "fans" in snap["est"]


def test_the_sampler_threads_fill_a_snapshot():
    s = telemetry.Sampler()
    s.start(period=0.05, slow_period=0.05)
    try:
        deadline = 3.0
        waited = 0.0
        while waited < deadline:
            snap = s.snapshot()
            if snap.get("ok") and snap.get("cpu", {}).get("threads"):
                break
            threading.Event().wait(0.05)
            waited += 0.05
        assert s.snapshot()["ok"] is True
    finally:
        s.stop()


# --------------------------------------------------------------------------- #
# http surface
# --------------------------------------------------------------------------- #
@pytest.fixture()
def bridge():
    sampler = telemetry.Sampler()
    sampler.prime()
    telemetry.Handler.sampler = sampler

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), telemetry.Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def test_bridge_serves_the_hud_and_its_json(bridge):
    with urllib.request.urlopen(f"{bridge}/", timeout=5) as res:
        body = res.read().decode("utf-8")
        assert res.status == 200
        assert "MK-LXXXV" in body

    with urllib.request.urlopen(f"{bridge}/telemetry", timeout=5) as res:
        assert res.headers["Content-Type"].startswith("application/json")
        # A file:// copy of the HUD must be able to read it too.
        assert res.headers["Access-Control-Allow-Origin"] == "*"
        payload = json.loads(res.read())
        assert payload["ok"] is True


def test_bridge_refuses_to_serve_outside_its_own_folder(bridge):
    """A path that escapes hud_mk85/ is answered with 404 or 403, never 200."""
    for attempt in ("/%2e%2e/main.py", "/..%2fmain.py", "/%2e%2e%2fmain.py"):
        try:
            with urllib.request.urlopen(bridge + attempt, timeout=5) as res:
                status = res.status
        except urllib.error.HTTPError as e:
            status = e.code
        assert status in (403, 404), (attempt, status)


# --------------------------------------------------------------------------- #
# voice state (/state)
# --------------------------------------------------------------------------- #
def test_voice_state_starts_off_and_is_served(bridge):
    telemetry.reset_voice()
    with urllib.request.urlopen(f"{bridge}/state", timeout=5) as res:
        assert res.headers["Content-Type"].startswith("application/json")
        assert res.headers["Access-Control-Allow-Origin"] == "*"
        payload = json.loads(res.read())

    assert payload["status"] == "OFFLINE"
    assert payload["mic"] == 0.0
    assert payload["you"] == "" and payload["jarvis"] == ""


def test_publish_updates_only_known_fields(bridge):
    telemetry.reset_voice()
    telemetry.publish(status="SPEAK", mic=0.42, jarvis="All systems nominal.",
                      speaking=True, evil="<script>")

    with urllib.request.urlopen(f"{bridge}/state", timeout=5) as res:
        payload = json.loads(res.read())

    assert payload["status"] == "SPEAK"
    assert payload["mic"] == 0.42
    assert payload["speaking"] is True
    assert payload["jarvis"] == "All systems nominal."
    # An unknown key must not become part of the payload.
    assert "evil" not in payload
    assert payload["ts"] > 0


def test_publish_keeps_previous_values_for_omitted_fields():
    telemetry.reset_voice()
    telemetry.publish(status="LISTEN", mic=0.5, you="run diagnostics")
    telemetry.publish(status="THINK")

    state = telemetry.voice()
    assert state["status"] == "THINK"
    assert state["mic"] == 0.5        # untouched by the second call
    assert state["you"] == "run diagnostics"


def test_voice_state_is_not_writable_over_http(bridge):
    """Only the owning process may push state: no POST/PUT surface exists."""
    for method in ("POST", "PUT", "DELETE"):
        req = urllib.request.Request(
            f"{bridge}/state", data=b'{"status":"SPEAK"}', method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                status = res.status
        except urllib.error.HTTPError as e:
            status = e.code
        assert status in (501, 405), (method, status)
    assert telemetry.voice()["status"] != "SPEAK"


# --------------------------------------------------------------------------- #
# protocols / personas
# --------------------------------------------------------------------------- #
# Three palettes live in styles.css: JARVIS (crimson), FRIDAY (amber) and
# ULTRON (hard red). The bridge carries the choice, the page morphs when it
# changes, and the assistant can set it with the switch_persona tool.
def test_persona_defaults_to_jarvis_and_is_served(bridge):
    telemetry.reset_voice()
    with urllib.request.urlopen(f"{bridge}/state", timeout=5) as res:
        payload = json.loads(res.read())
    assert payload["persona"] == "jarvis"


def test_persona_is_publishable_and_resets():
    telemetry.reset_voice()
    telemetry.publish(persona="friday")
    assert telemetry.voice()["persona"] == "friday"

    telemetry.reset_voice()
    assert telemetry.voice()["persona"] == "jarvis"


def test_switch_persona_tool_is_declared_and_allowed():
    """The contract check covers dispatch; this pins the parts it cannot see."""
    from jarvis.tools_schema import TOOL_DECLARATIONS

    declared = {d["name"]: d for d in TOOL_DECLARATIONS}
    assert "switch_persona" in declared

    params = declared["switch_persona"]["parameters"]
    assert params["properties"]["name"]["enum"] == ["jarvis", "friday", "ultron"]
    assert params["required"] == ["name"]

    policy = json.loads(
        (ROOT / "config" / "autonomy.json").read_text(encoding="utf-8"))
    # A skin change can never be destructive, so it should not need a modal.
    assert policy["tools"]["switch_persona"] == "allow"


def test_ui_set_persona_normalises_names_and_rejects_junk():
    from ui import JarvisUI

    class Stub(JarvisUI):
        def __init__(self):          # no Tk root: only the two methods used
            self.thoughts = []

        def jarvis_think(self, kind, text):
            self.thoughts.append((kind, text))

    ui = Stub()
    assert ui.set_persona("FRIDAY") == "friday"
    assert ui.get_persona() == "friday"
    assert ui.set_persona("F.R.I.D.A.Y") == "friday"
    assert ui.set_persona("J.A.R.V.I.S") == "jarvis"

    before = ui.get_persona()
    assert ui.set_persona("skynet") == ""
    assert ui.get_persona() == before      # a bad name changes nothing
    assert ui.thoughts[-1][0] == "err"


def test_hud_ui_publishes_the_persona():
    """HudUI must push the choice to the bridge, not just remember it."""
    from ui.hud_ui import HudUI

    hud = object.__new__(HudUI)
    seen = {}
    hud.jarvis_think = lambda kind, text: None
    hud._publish = lambda **kw: seen.update(kw)

    assert hud.set_persona("ultron") == "ultron"
    assert seen == {"persona": "ultron"}

    seen.clear()
    assert hud.set_persona("skynet") == ""
    assert seen == {}                      # nothing published for a bad name


