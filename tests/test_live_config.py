"""Tier 1.6 — Live session config composition, without the network or a mic."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from jarvis import live_config


class Stub:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def fake_types():
    return SimpleNamespace(
        LiveConnectConfig=Stub,
        SessionResumptionConfig=Stub,
        SpeechConfig=Stub,
        VoiceConfig=Stub,
        PrebuiltVoiceConfig=Stub,
        RealtimeInputConfig=Stub,
        AutomaticActivityDetection=Stub,
        ThinkingConfig=Stub,
        ContextWindowCompressionConfig=Stub,
        SlidingWindow=Stub,
        StartSensitivity=SimpleNamespace(START_SENSITIVITY_HIGH="start-high"),
        EndSensitivity=SimpleNamespace(END_SENSITIVITY_HIGH="end-high"),
    )


def _prompt(monkeypatch, *, memory="", state="[STATE]", budget=None):
    # Keep the test independent of the repo's prompt files and self-model.
    monkeypatch.setattr(live_config, "_read_personality",
                        lambda _base: "[PERSONALITY]")
    monkeypatch.setattr(
        live_config, "compose_prompt", live_config.compose_prompt
    )
    import core.self as self_model

    monkeypatch.setattr(self_model, "prompt_block", lambda: "[SELF]")
    return live_config.compose_prompt(
        base_dir=None,
        memory_text=memory,
        load_system_prompt=lambda: "[SYSTEM]",
        describe_state=lambda **_kw: state,
        prompt_budget=(budget or (lambda text: text)),
        now=datetime(2026, 10, 23, 14, 5),
    )


def test_prompt_order_and_content(monkeypatch):
    text = _prompt(monkeypatch, memory="[MEMORY]")
    assert text.index("[PERSONALITY]") < text.index("[SYSTEM]")
    assert text.index("[CURRENT DATE & TIME]") < text.index("[MEMORY]")
    assert "Friday, October 23, 2026" in text
    assert "[SELF]" in text
    assert text.index("[STATE]") < text.index("[CURRENT DATE & TIME]")


def test_prompt_survives_a_broken_state_or_personality(monkeypatch):
    monkeypatch.setattr(live_config, "_read_personality", lambda _base: "")
    text = live_config.compose_prompt(
        base_dir=None,
        memory_text="",
        load_system_prompt=lambda: "[SYSTEM]",
        describe_state=lambda **_kw: (_ for _ in ()).throw(RuntimeError("no")),
        prompt_budget=lambda value: value,
    )
    assert "[SYSTEM]" in text


def test_prompt_budget_is_the_last_step(monkeypatch):
    text = _prompt(monkeypatch, budget=lambda value: "COMPACT:" + value)
    assert text.startswith("COMPACT:")


def test_config_carries_vad_thinking_and_voice():
    cfg = live_config.build_config(
        types=fake_types(),
        base_dir=None,
        memory_text="",
        load_system_prompt=lambda: "[SYSTEM]",
        describe_state=lambda **_kw: "",
        prompt_budget=lambda value: value,
        tool_declarations=[{"name": "demo"}],
        vad_tuning=True,
        vad_silence_ms=700,
        vad_start_sens=True,
        vad_end_sens=True,
        thinking_budget=512,
        affective_dialog=True,
        ctx_trigger=100000,
        ctx_target=80000,
        temperature=0.85,
    )
    assert cfg.kwargs["response_modalities"] == ["AUDIO"]
    assert cfg.kwargs["tools"] == [{"function_declarations": [{"name": "demo"}]}]
    vad = cfg.kwargs["realtime_input_config"]
    assert vad.kwargs["automatic_activity_detection"].kwargs == {
        "silence_duration_ms": 700,
        "start_of_speech_sensitivity": "start-high",
        "end_of_speech_sensitivity": "end-high",
    }
    assert cfg.kwargs["thinking_config"].kwargs == {"thinking_budget": 512}
    assert cfg.kwargs["enable_affective_dialog"] is True
    assert cfg.kwargs["context_window_compression"].kwargs["trigger_tokens"] == 100000
    assert cfg.kwargs["temperature"] == 0.85
    voice = cfg.kwargs["speech_config"].kwargs["voice_config"]
    assert voice.kwargs["prebuilt_voice_config"].kwargs["voice_name"] == "Charon"


def test_config_omits_disabled_features():
    cfg = live_config.build_config(
        types=fake_types(),
        base_dir=None,
        memory_text="",
        load_system_prompt=lambda: "",
        describe_state=lambda **_kw: "",
        prompt_budget=lambda value: value,
        tool_declarations=[],
        vad_tuning=False,
        vad_silence_ms=500,
        vad_start_sens=False,
        vad_end_sens=False,
        thinking_budget=0,
        affective_dialog=False,
        ctx_trigger=0,
        ctx_target=0,
        temperature=0.9,
    )
    assert "realtime_input_config" not in cfg.kwargs
    assert "thinking_config" not in cfg.kwargs
    assert "enable_affective_dialog" not in cfg.kwargs
    assert "context_window_compression" not in cfg.kwargs
