"""B1 wiring: gemini_util consults the provider circuit breakers.

Only the provider (tier-2) path is wired to a breaker; the Gemini chain keeps
its own per-model cooldown, which already has the precise 429 retryDelay. These
tests patch the provider helpers so no network or config file is involved.
"""

import pytest

import gemini_util
from agent import breaker


@pytest.fixture(autouse=True)
def _clean_gemini():
    gemini_util.reset()
    yield
    gemini_util.reset()


def _one_provider(monkeypatch, pid, models=("m1",)):
    monkeypatch.setattr(gemini_util, "_providers", lambda: [{"id": pid}])
    monkeypatch.setattr(gemini_util, "_provider_ready", lambda p: True)
    monkeypatch.setattr(gemini_util, "_provider_models", lambda p: list(models))


def test_provider_breaker_uses_the_repeatable_options():
    first = gemini_util._provider_breaker("alpha")
    again = gemini_util._provider_breaker("alpha")
    assert first is again
    assert first.failure_threshold == gemini_util._PROVIDER_BREAKER["failure_threshold"]


def test_candidates_include_a_healthy_provider(monkeypatch):
    _one_provider(monkeypatch, "alpha")

    assert [m for _, m in gemini_util._external_candidates()] == ["m1"]


def test_candidates_skip_a_provider_with_an_open_breaker(monkeypatch):
    _one_provider(monkeypatch, "alpha")
    circuit = gemini_util._provider_breaker("alpha")
    for _ in range(gemini_util._PROVIDER_BREAKER["failure_threshold"]):
        circuit.record_failure()

    assert circuit.state == breaker.OPEN
    assert list(gemini_util._external_candidates()) == []


def test_a_successful_call_closes_the_breaker(monkeypatch):
    _one_provider(monkeypatch, "beta", models=("m2",))
    monkeypatch.setattr(
        gemini_util, "_openai_chat",
        lambda provider, model, prompt, system, json_mode: "hello",
    )
    circuit = gemini_util._provider_breaker("beta")
    circuit.record_failure()
    assert circuit.state == breaker.CLOSED

    response = gemini_util._external_run(("prompt", None, False), None)

    assert response.text == "hello"
    assert circuit.state == breaker.CLOSED
    assert circuit.snapshot()["failures"] == 0


def test_failures_trip_the_breaker_and_it_stops_being_offered(monkeypatch):
    # Two models so that one call produces two provider failures (the per-model
    # cooldown would otherwise hide the second attempt from the next call).
    _one_provider(monkeypatch, "gamma", models=("m3", "m4"))

    def boom(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(gemini_util, "_openai_chat", boom)
    circuit = gemini_util._provider_breaker("gamma")

    with pytest.raises(OSError):
        gemini_util._external_run(("prompt", None, False), None)

    assert circuit.state == breaker.OPEN
    assert list(gemini_util._external_candidates()) == []


def test_stats_surfaces_breaker_state(monkeypatch):
    monkeypatch.setattr(gemini_util, "_providers", lambda: [])
    gemini_util._provider_breaker("delta").record_failure()

    names = [entry["name"] for entry in gemini_util.stats()["breakers"]]

    assert "provider:delta" in names


def test_reset_clears_breaker_state(monkeypatch):
    monkeypatch.setattr(gemini_util, "_providers", lambda: [])
    gemini_util._provider_breaker("epsilon").record_failure()

    gemini_util.reset()

    assert gemini_util.stats()["breakers"] == []
