"""Tier 4 W4 — the device layer.

The registry and the transports are the parts that can be tested without a phone
on the desk; the *rules* are the parts that matter. Every test here is about a
refusal, because that is what keeps a reach-outward feature from becoming an
open door.
"""

import pytest

from agent import devices
from agent.policy import Level

PHONE = {
    "transport": "adb",
    "address": "100.64.0.5:5555",
    "capabilities": ["info", "status", "notify", "screenshot", "ring", "media",
                     "sms", "call"],
}
LAPTOP = {"transport": "ssh", "address": "192.168.1.20",
          "capabilities": ["status", "exec", "wol"]}


@pytest.fixture
def registry():
    devices.reset_for_tests()
    devices.register("phone", PHONE)
    devices.register("laptop", LAPTOP)
    yield devices.registry()
    devices.reset_for_tests()


# --- the registry -------------------------------------------------------------

def test_an_empty_registry_is_not_an_error():
    devices.reset_for_tests()
    assert devices.registry() == {}
    assert devices.summary() == []
    result = devices.dispatch("list")
    assert result["ok"] is True
    assert result["devices"] == []


def test_a_registered_device_round_trips(registry):
    assert sorted(devices.names()) == ["laptop", "phone"]
    assert devices.capabilities("phone")[0] == "info"
    assert "exec" in devices.capabilities("laptop")


def test_a_device_description_lists_its_transport(registry):
    described = devices.describe("laptop")
    assert described["known"] is True
    assert described["transport"] == "ssh"


def test_an_unknown_device_describes_itself_as_unknown():
    described = devices.describe("toaster")
    assert described["known"] is False
    assert "unknown device" in described["error"]


def test_an_unknown_transport_is_refused(registry):
    with pytest.raises(ValueError):
        devices.register("mystery", {"transport": "carrier-pigeon", "address": "1.2.3.4"})


def test_a_device_needs_a_name(registry):
    with pytest.raises(ValueError):
        devices.register("", {"transport": "adb"})


def test_capabilities_are_filtered_to_the_known_ones(registry):
    devices.register("odd", {"transport": "ssh", "address": "192.168.1.30",
                             "capabilities": ["status", "teleport"]})
    assert devices.capabilities("odd") == ["status"]


def test_forget_removes_a_device(registry):
    assert devices.forget("phone") is True
    assert devices.forget("phone") is False
    assert "phone" not in devices.registry()


def test_a_corrupt_registry_reads_as_empty(registry):
    devices.CONFIG_PATH.write_text("{not json", encoding="utf-8")
    assert devices.registry() == {}
    assert devices.names() == []


def test_the_registry_cli_reports_state(registry, capsys):
    assert devices._cli([]) == 0
    out = capsys.readouterr().out
    assert "phone" in out
    assert "blast_radius" in out


# --- capability checks --------------------------------------------------------

def test_unknown_device_is_a_clean_refusal(registry):
    ok, why = devices.check("toaster", "status")
    assert ok is False
    assert "unknown device" in why


def test_a_capability_the_device_does_not_have_is_refused(registry):
    ok, why = devices.check("phone", "exec")
    assert ok is False
    assert "does not expose" in why


def test_an_unknown_capability_is_refused(registry):
    ok, why = devices.check("phone", "teleport")
    assert ok is False
    assert "unknown capability" in why


def test_a_declared_capability_passes(registry):
    assert devices.check("phone", "ring") == (True, "ok")


def test_capability_lookup_is_case_insensitive(registry):
    assert devices.check("phone", "RING")[0] is True


def test_a_missing_capability_name_is_refused(registry):
    ok, why = devices.check("phone", "")
    assert ok is False
    assert "required" in why


def test_reaching_other_people_is_marked(registry):
    assert devices.reaches_other_people("sms") is True
    assert devices.reaches_other_people("call") is True
    assert devices.reaches_other_people("ring") is False


def test_the_blast_radius_of_sms_is_other_people(registry):
    assert devices.blast_radius("sms") == "other_people"
    assert devices.reversibility("sms") == "permanent"
    assert devices.blast_radius("status") == "self"


# --- addresses ----------------------------------------------------------------

@pytest.mark.parametrize("address", ["127.0.0.1:5555", "192.168.1.20", "10.0.0.7",
                                     "100.64.0.5:5555", "100.101.102.103",
                                     "::1"])
def test_a_private_address_is_allowed(address):
    ok, why = devices.address_allowed(address)
    assert ok is True, why


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1:5555", "93.184.216.34",
                                     "2001:4860:4860::8888"])
def test_a_public_address_is_refused(address):
    ok, why = devices.address_allowed(address)
    assert ok is False
    assert "public" in why or "never expose" in why


def test_no_address_is_refused():
    assert devices.address_allowed("")[0] is False


def test_a_public_device_address_is_refused_at_dispatch(registry):
    devices.register("exposed", {"transport": "adb", "address": "93.184.216.34:5555",
                                 "capabilities": ["status"]})
    result = devices.dispatch("status", target="exposed")
    assert result["ok"] is False
    assert "public" in result["error"]


# --- dispatch -----------------------------------------------------------------

def test_list_needs_no_target(registry):
    result = devices.dispatch("list")
    assert result["ok"] is True
    assert {row["device"] for row in result["devices"]} == {"phone", "laptop"}


def test_an_unknown_action_is_refused(registry):
    result = devices.dispatch("detonate", target="phone")
    assert result["ok"] is False
    assert "unknown action" in result["error"]


def test_run_without_a_target_is_refused(registry):
    result = devices.dispatch("run", cmd="ring")
    assert result["ok"] is False
    assert "target" in result["error"]


def test_run_without_a_capability_is_refused(registry):
    result = devices.dispatch("run", target="phone")
    assert result["ok"] is False
    assert "capability" in result["error"]


def test_run_against_an_undeclared_capability_is_refused(registry):
    result = devices.dispatch("run", target="laptop", cmd="sms")
    assert result["ok"] is False
    assert "does not expose" in result["error"]


def test_the_shell_capability_is_refused_even_if_declared(registry):
    devices.register("open", {"transport": "ssh", "address": "192.168.1.40",
                              "capabilities": ["status", "shell"]})
    result = devices.dispatch("run", target="open", cmd="shell")
    assert result["ok"] is False
    assert "always blocked" in result["error"]


def test_a_transport_failure_is_reported_as_failure(registry, monkeypatch):
    def broken(device, capability, params):
        raise devices.TransportError("no route to host")

    monkeypatch.setitem(devices._TRANSPORTS, "adb", broken)
    result = devices.dispatch("run", target="phone", cmd="ring")
    assert result["ok"] is False
    assert result["error"] == "no route to host"
    assert result["capability"] == "ring"


def test_a_transport_bug_is_still_a_failure_not_success(registry, monkeypatch):
    def explode(device, capability, params):
        raise ValueError("bug in the transport")

    monkeypatch.setitem(devices._TRANSPORTS, "adb", explode)
    result = devices.dispatch("run", target="phone", cmd="ring")
    assert result["ok"] is False
    assert "transport error" in result["error"]


def test_a_missing_transport_binary_is_a_clean_failure(registry, monkeypatch):
    """The adb path with no adb on PATH fails cleanly; it never pretends."""
    monkeypatch.setattr(devices.shutil, "which", lambda _name: None)
    result = devices.dispatch("run", target="phone", cmd="info")
    assert result["ok"] is False
    assert "platform-tools" in result["error"]


def test_a_device_without_an_address_is_refused(registry):
    devices.register("nameless", {"transport": "adb", "capabilities": ["status"]})
    result = devices.dispatch("status", target="nameless")
    assert result["ok"] is False


def test_a_disabled_layer_refuses_everything(registry):
    cfg = devices.load_config()
    cfg["enabled"] = False
    devices._save(cfg)
    result = devices.dispatch("list")
    assert result["ok"] is False
    assert "disabled" in result["error"]


def test_status_requires_the_device_to_declare_it(registry):
    devices.register("thin", {"transport": "adb", "address": "100.64.0.9:5555",
                              "capabilities": ["info"]})
    result = devices.dispatch("status", target="thin")
    assert result["ok"] is False
    assert "does not expose" in result["error"]


def test_transport_availability_is_a_bool():
    for name in devices.TRANSPORTS:
        assert isinstance(devices.transport_available(name), bool)


def test_the_cli_run_is_honest_about_failure(registry, capsys):
    assert devices._cli(["run", "phone", "teleport"]) == 0
    assert "failed" in capsys.readouterr().out


# --- rendering ----------------------------------------------------------------

def test_render_shortens_a_failure():
    assert devices.render({"ok": False, "error": "nope"}) == "devices: failed — nope"


def test_render_lists_devices(registry):
    text = devices.render(devices.dispatch("list"))
    assert "phone" in text and "laptop" in text


def test_render_reports_an_empty_registry():
    devices.reset_for_tests()
    assert devices.render(devices.dispatch("list")) == "devices: none registered"


# --- the policy hard rules ----------------------------------------------------

def write_devices_policy(write_policy, actions: dict):
    write_policy({"enabled": True, "tools": {"devices": "confirm"},
                  "actions": {"devices": actions},
                  "sandbox": {"enabled": False}})


def test_sms_is_never_allow_even_when_the_config_says_so(write_policy):
    from agent import policy

    write_devices_policy(write_policy, {"sms": "allow"})
    decision = policy.evaluate("devices", {"action": "run", "cmd": "sms"})
    assert decision.level is Level.CONFIRM
    assert "other people" in decision.reason
    assert decision.hard is False          # a confirm may still be answered


def test_call_is_never_allow_even_when_the_config_says_so(write_policy):
    from agent import policy

    write_devices_policy(write_policy, {"call": "allow"})
    assert policy.evaluate("devices", {"action": "run", "cmd": "call"}).level is Level.CONFIRM


def test_shell_is_blocked_even_when_the_config_says_allow(write_policy):
    from agent import policy

    write_devices_policy(write_policy, {"shell": "allow"})
    decision = policy.evaluate("devices", {"action": "run", "cmd": "shell"})
    assert decision.level is Level.BLOCK
    assert decision.hard is True           # a hard block can never be approved away


def test_a_benign_capability_keeps_its_configured_level(write_policy):
    from agent import policy

    write_devices_policy(write_policy, {"ring": "allow", "sms": "confirm"})
    assert policy.evaluate("devices", {"action": "run", "cmd": "ring"}).level is Level.ALLOW


def test_the_capability_decides_not_the_tool_level(write_policy):
    """`run` is not a capability; the gate must key off `cmd`."""
    from agent import policy

    write_devices_policy(write_policy, {"list": "allow", "ring": "confirm"})
    assert policy.evaluate("devices", {"action": "list"}).level is Level.ALLOW
    assert policy.evaluate("devices",
                           {"action": "run", "cmd": "ring"}).level is Level.CONFIRM


# --- judgement integration ----------------------------------------------------

def test_sms_is_classified_as_reaching_other_people():
    from agent import judgement

    assert judgement.classify("devices", {"cmd": "sms"}) == ("permanent", "other_people")


def test_ring_is_classified_as_local_and_reversible():
    from agent import judgement

    assert judgement.classify("devices", {"cmd": "ring"}) == ("reversible", "local")


def test_an_unknown_capability_classifies_conservatively():
    from agent import judgement

    reversibility, blast = judgement.classify("devices", {"cmd": "???"})
    assert reversibility in judgement.REVERSIBILITY
    assert blast in judgement.BLAST_RADIUS
