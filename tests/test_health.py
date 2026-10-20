"""Tier 2 B4 / C4 - health, readiness and status."""

import json

import pytest

from agent import audit, health


def test_checks_cover_the_subsystems(policy_file, monkeypatch):
    monkeypatch.setattr(health, "check_disk", lambda: {"ok": True, "detail": ""})
    result = health.checks()
    assert set(result) == {"policy", "config", "keys", "disk", "breaker", "memory",
                           "budget"}


def test_the_audio_probe_can_be_left_out_of_a_full_check(policy_file, monkeypatch):
    """Regression: the startup thread must never touch PortAudio."""
    monkeypatch.setattr(health, "check_model", lambda: {"ok": True, "detail": ""})
    monkeypatch.setattr(health, "check_mic",
                        lambda: pytest.fail("the mic must not be probed here"))

    result = health.checks(full=True, audio=False)
    assert "mic" not in result
    assert "model" in result


def test_the_audio_probe_is_included_when_asked(policy_file, monkeypatch):
    monkeypatch.setattr(health, "check_model", lambda: {"ok": True, "detail": ""})
    monkeypatch.setattr(health, "check_mic", lambda: {"ok": True, "detail": "mic"})

    assert "mic" in health.checks(full=True, audio=True)
    assert "mic" in health.checks(full=True)        # backwards compatible
    assert "mic" not in health.checks()


def test_policy_check_passes_with_a_valid_policy(policy_file):
    assert health.check_policy()["ok"] is True


def test_policy_check_fails_when_the_policy_is_empty(write_policy):
    write_policy({})
    result = health.check_policy()
    assert result["ok"] is False


def test_a_missing_config_is_reported(monkeypatch):
    from memory import config_manager

    monkeypatch.setattr(config_manager, "config_exists", lambda: False)
    assert health.check_config()["ok"] is False


def test_a_placeholder_key_is_reported(monkeypatch):
    from memory import config_manager

    monkeypatch.setattr(config_manager, "load_api_keys",
                        lambda: {"gemini_api_key": "your_api_key_here"})
    assert health.check_keys()["ok"] is False


def test_a_real_looking_key_passes(monkeypatch):
    from memory import config_manager

    monkeypatch.setattr(config_manager, "load_api_keys",
                        lambda: {"gemini_api_key": "AIza" + "x" * 30})
    assert health.check_keys()["ok"] is True


def test_check_keys_never_echoes_the_value(monkeypatch):
    from memory import config_manager

    monkeypatch.setattr(config_manager, "load_api_keys",
                        lambda: {"gemini_api_key": "your_api_key_here"})
    assert "your_api_key_here" not in json.dumps(health.check_keys())


def test_disk_check_uses_its_threshold(monkeypatch):
    monkeypatch.setattr(health, "MIN_FREE_BYTES", 0)
    assert health.check_disk()["ok"] is True
    monkeypatch.setattr(health, "MIN_FREE_BYTES", 1 << 62)
    assert health.check_disk()["ok"] is False


def test_breaker_check_reports_open_breakers(monkeypatch):
    from agent import breaker

    monkeypatch.setattr(breaker, "open_names", lambda: ["gemini"])
    assert health.check_breaker()["ok"] is False
    monkeypatch.setattr(breaker, "open_names", lambda: [])
    assert health.check_breaker()["ok"] is True


def test_memory_check_reads_the_store():
    assert health.check_memory()["ok"] is True


def test_mic_check_skips_without_pyaudio(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyaudio":
            raise ImportError("no pyaudio")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = health.check_mic()
    assert result["ok"] is True and result.get("skipped") is True


def test_mic_check_goes_through_the_serialized_opener(monkeypatch):
    """agent.audio owns every PyAudio instance; check_mic must use it."""
    from agent import audio

    class _FakePa:
        def get_device_count(self):
            return 1

        def get_default_input_device_info(self):
            return {"name": "Fake Mic"}

    opened, closed = [], []
    monkeypatch.setattr(audio, "open_pyaudio", lambda: opened.append(1) or _FakePa())
    monkeypatch.setattr(audio, "close", lambda instance: closed.append(instance))

    result = health.check_mic()
    assert result["ok"] is True
    assert result["device"] == "Fake Mic"
    assert opened and closed


def test_self_check_has_a_stable_shape():
    outcome = health.self_check()
    assert set(outcome) >= {"ok", "failed", "checks", "took_ms"}
    assert isinstance(outcome["ok"], bool)


def test_self_check_is_audited():
    health.self_check()
    assert any(e.get("event") == "self_check" for e in audit.tail(20))


def test_ready_is_false_with_the_kill_switch(policy_file, monkeypatch):
    from agent import policy

    monkeypatch.setattr(policy, "kill_requested", lambda: True)
    result = health.ready()
    assert result["ready"] is False
    assert any("kill" in r for r in result["reasons"])


def test_ready_is_false_when_monitoring(policy_file):
    from agent import degrade

    degrade.set_level("MONITOR")
    assert health.ready()["ready"] is False


def test_ready_is_true_by_default(policy_file):
    assert health.ready()["ready"] is True


def test_status_aggregates_and_is_json_safe(policy_file):
    data = health.status()
    assert json.dumps(data, default=str)
    for key in ("policy", "breakers", "degradation", "metrics", "queue", "memory", "ready"):
        assert key in data


def test_status_reports_which_build_is_answering(policy_file):
    """E1: "which build is this?" is the first question in a bug report."""
    from agent import version

    build = health.status()["build"]
    assert build["version"] == version.version()
    assert build["release"] == version.release_name()
    assert "formats" in build


def test_status_survives_a_broken_version_module(policy_file, monkeypatch):
    """A health check that raises while describing itself is the worse failure."""
    import agent as agent_pkg

    class Broken:
        @staticmethod
        def snapshot():
            raise RuntimeError("boom")

        @staticmethod
        def version():
            raise RuntimeError("boom")

    monkeypatch.setattr(agent_pkg, "version", Broken, raising=False)
    assert "error" in health.status()["build"]
    assert health._server_version().startswith("JarvisHealth/")


def test_the_http_identity_header_carries_the_real_version():
    from agent import version

    assert health._server_version() == f"JarvisHealth/{version.version()}"


def test_queue_status_does_not_start_the_queue():
    import sys

    health.status()
    # On CI the queue module may not even import (no google SDK); either way,
    # reporting status must never have started the worker threads.
    module = sys.modules.get("agent.task_queue")
    if module is not None:
        assert module._queue_started is False


def test_self_check_prints_the_outcome(capsys):
    health.self_check()
    out = capsys.readouterr().out
    assert "[Health]" in out
    assert "self-check" in out


def test_routes_include_the_four_endpoints():
    assert set(health.routes()) >= {"/health", "/ready", "/status", "/metrics"}


def test_resolve_returns_404_for_an_unknown_path():
    code, _body, _ctype = health.resolve("/nope")
    assert code == 404


def test_every_route_accepts_a_query_string():
    """Regression: routes are called with the raw query, so they take an arg."""
    for path in ("/", "/health", "/ready", "/status", "/metrics"):
        code, _body, _ctype = health.resolve(path + "?x=1")
        assert code in (200, 503)


def test_a_trailing_slash_is_ignored():
    code, _body, _ctype = health.resolve("/status/")
    assert code == 200


def test_the_health_route_probes_the_mic_only_when_asked(policy_file, monkeypatch):
    monkeypatch.setattr(health, "check_mic", lambda: {"ok": True, "detail": "mic"})

    _code, body, _ctype = health.resolve("/health")
    assert "mic" not in json.loads(body)["checks"]

    _code, body, _ctype = health.resolve("/health?full=1")
    assert json.loads(body)["checks"]["mic"]["detail"] == "mic"


def test_the_metrics_route_is_plain_text():
    code, _body, ctype = health.resolve("/metrics")
    assert code == 200 and ctype.startswith("text/plain")


def test_the_status_route_is_json(policy_file):
    code, body, _ctype = health.resolve("/status")
    assert code == 200
    json.loads(body)


def test_the_health_route_always_answers():
    code, body, _ctype = health.resolve("/health")
    assert code in (200, 503)
    json.loads(body)


def test_the_http_surface_answers_on_loopback():
    import urllib.request

    server = health.serve(port=0)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["service"] == "jarvis"
    finally:
        server.shutdown()
        server.server_close()
