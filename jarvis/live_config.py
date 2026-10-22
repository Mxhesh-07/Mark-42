"""Tier 1.6 — the Live session config, out of `JarvisLive`.

Builds the exact `types.LiveConnectConfig` the voice loop used to build inline:
system prompt (personality + operating prompt + time + memory + open windows +
self-model), VAD tuning, thinking/affective/context settings and the tool schema.

Everything platform-specific is passed in, so this is testable with stub
callables and a fake `types` module.
"""

from __future__ import annotations

from datetime import datetime


def _read_personality(base_dir) -> str:
    try:
        path = base_dir / "prompts" / "jarvis_personality.txt"
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def compose_prompt(
    *,
    base_dir,
    memory_text: str,
    load_system_prompt,
    describe_state,
    prompt_budget,
    now: datetime | None = None,
) -> str:
    """The system instruction, in the same order the inline builder used."""
    sys_prompt = _read_personality(base_dir) + "\n\n" + load_system_prompt()

    now = now or datetime.now()
    time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
    time_ctx = (
        f"[CURRENT DATE & TIME]\n"
        f"Right now it is: {time_str}\n"
        f"Use this to calculate exact times for reminders. "
        f"If user says 'in 2 minutes', add 2 minutes to this time.\n\n"
    )

    if memory_text:
        sys_prompt = time_ctx + memory_text + "\n\n" + sys_prompt
    else:
        sys_prompt = time_ctx + sys_prompt

    # Snapshot of what is already open, so JARVIS continues in existing windows
    # instead of opening duplicates.
    try:
        state_str = describe_state(max_windows=10, max_apps=10)
    except Exception:
        state_str = ""
    if state_str:
        sys_prompt = (
            "[CURRENTLY OPEN ON THE COMPUTER — continue in these windows "
            "instead of opening duplicates; call get_open_windows for a "
            "fresh list]\n" + state_str + "\n\n" + sys_prompt
        )

    # W3: the self-model. JARVIS reports its own mode, confidence and limits
    # honestly instead of guessing what it can do.
    try:
        from core import self as self_model

        self_block = self_model.prompt_block()
    except Exception:
        self_block = ""
    if self_block:
        sys_prompt = self_block + "\n\n" + sys_prompt

    # I4: optional compact variant for small-context fallbacks (default off).
    return prompt_budget(sys_prompt)


def _vad_kwargs(types, *, enabled, silence_ms, start_sensitive, end_sensitive):
    # Only the end-of-turn silence window is raised; prefix padding and longer
    # windows were measured to hurt short utterances, so they are unused.
    if not enabled:
        return {}
    aad = {"silence_duration_ms": silence_ms}
    if start_sensitive:
        aad["start_of_speech_sensitivity"] = (
            types.StartSensitivity.START_SENSITIVITY_HIGH
        )
    if end_sensitive:
        aad["end_of_speech_sensitivity"] = (
            types.EndSensitivity.END_SENSITIVITY_HIGH
        )
    return {
        "realtime_input_config": types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(**aad)
        )
    }


def _cognition_kwargs(types, *, thinking_budget, affective_dialog,
                      ctx_trigger, ctx_target, temperature):
    # 'proactivity' is intentionally absent — this model rejects the field.
    kwargs = {}
    if thinking_budget and thinking_budget > 0:
        kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget
        )
    if affective_dialog:
        kwargs["enable_affective_dialog"] = True
    if ctx_trigger and ctx_target:
        kwargs["context_window_compression"] = (
            types.ContextWindowCompressionConfig(
                trigger_tokens=ctx_trigger,
                sliding_window=types.SlidingWindow(target_tokens=ctx_target),
            )
        )
    kwargs["temperature"] = temperature
    return kwargs


def build_config(
    *,
    types,
    base_dir,
    memory_text: str,
    load_system_prompt,
    describe_state,
    prompt_budget,
    tool_declarations,
    vad_tuning: bool,
    vad_silence_ms: int,
    vad_start_sens: bool,
    vad_end_sens: bool,
    thinking_budget: int,
    affective_dialog: bool,
    ctx_trigger: int,
    ctx_target: int,
    temperature: float,
    voice: str = "Charon",
    now: datetime | None = None,
):
    sys_prompt = compose_prompt(
        base_dir=base_dir,
        memory_text=memory_text,
        load_system_prompt=load_system_prompt,
        describe_state=describe_state,
        prompt_budget=prompt_budget,
        now=now,
    )
    vad_kwargs = _vad_kwargs(
        types, enabled=vad_tuning, silence_ms=vad_silence_ms,
        start_sensitive=vad_start_sens, end_sensitive=vad_end_sens,
    )
    cognition = _cognition_kwargs(
        types, thinking_budget=thinking_budget,
        affective_dialog=affective_dialog, ctx_trigger=ctx_trigger,
        ctx_target=ctx_target, temperature=temperature,
    )
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        input_audio_transcription={},
        system_instruction=sys_prompt,
        tools=[{"function_declarations": tool_declarations}],
        session_resumption=types.SessionResumptionConfig(),
        **vad_kwargs,
        **cognition,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice
                )
            )
        ),
    )
