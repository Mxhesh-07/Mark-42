import json
from types import SimpleNamespace

from agent import brain, initiative, task_queue
from jarvis import live_config
from memory import ai_memory, sql_memory


def _make_brain(tmp_path, monkeypatch, *, config=None, reflect_fn=None, clock=None,
                auto_submit=None):
    """One brain, isolated from real state and from the task queue worker."""
    initiative.reset()
    monkeypatch.setattr(task_queue, "get_queue",
                        lambda: SimpleNamespace(get_all_statuses=lambda: []))
    monkeypatch.setattr(ai_memory, "BASE_DIR", tmp_path)
    cfg = dict(brain.DEFAULT_CONFIG)
    cfg.update(config or {})
    return brain.Brain(
        clock=clock or (lambda: 1_000_000.0),
        config_loader=lambda: cfg,
        state_path=tmp_path / "brain_state.json",
        reflect_fn=reflect_fn,
        auto_submit=auto_submit,
    )


def test_observations_become_persistent_intentions(tmp_path, monkeypatch):
    b = _make_brain(tmp_path, monkeypatch, config={"reflect_interval_sec": 999999})
    b.note_user_turn("I am stuck on the JARVIS voice bug and need to fix it today")

    result = b.tick()

    assert result["intentions"] == 1
    active = b.active_intentions()
    assert len(active) == 1
    assert "JARVIS voice bug" in active[0].text
    assert active[0].source_observation

    saved = json.loads((tmp_path / "brain_state.json").read_text(encoding="utf-8"))
    assert active[0].id in saved["intentions"]

    rows = sql_memory.search("JARVIS voice bug")
    assert any(row["kind"] == "intention" for row in rows)

    # The same observation must not create a second intention on the next tick.
    assert b.tick()["intentions"] == 0
    assert len(b.active_intentions()) == 1


def test_cloud_reflection_is_used_and_failure_falls_back(tmp_path, monkeypatch):
    reflected = _make_brain(
        tmp_path, monkeypatch,
        reflect_fn=lambda observations, context: [{
            "text": "Offer to summarise the bug report", "why": "pattern",
            "kind": "suggestion", "salience": 0.9, "tool": "", "parameters": {},
        }],
    )
    reflected.note_user_turn("need to finish the bug report")
    reflected.tick()
    assert "Offer to summarise" in reflected.active_intentions()[0].text

    def offline(*_args, **_kwargs):
        raise RuntimeError("no network")

    fallback = _make_brain(tmp_path / "offline", monkeypatch, reflect_fn=offline)
    (tmp_path / "offline").mkdir(exist_ok=True)
    fallback.note_user_turn("need to finish the bug report")
    fallback.tick()
    text = fallback.active_intentions()[0].text
    assert "bug report" in text
    assert "Offer to summarise" not in text


def test_observe_mode_is_silent_and_act_mode_obeys_policy(tmp_path, monkeypatch):
    quiet = _make_brain(
        tmp_path, monkeypatch,
        config={"mode": "observe", "min_salience": 0.5, "min_speak_salience": 0.5},
    )
    quiet.note_user_turn("need to finish the release notes")
    quiet.tick()
    assert quiet.active_intentions()
    assert quiet._speak_signal() is None

    calls = []
    acting = _make_brain(tmp_path / "act", monkeypatch,
                         config={"mode": "act"}, auto_submit=lambda goal: calls.append(goal) or "id")
    (tmp_path / "act").mkdir(exist_ok=True)
    risky = brain.Intention(
        id="int:risky", text="Message someone", why="test", kind="action",
        salience=0.9, tool="send_message",
        parameters={"receiver": "x", "message_text": "y", "platform": "WhatsApp"},
    )
    safe = brain.Intention(
        id="int:safe", text="Check the weather", why="test", kind="action",
        salience=0.9, tool="weather_report", parameters={"city": "Pune"},
    )
    assert acting._submit_task(risky) is False       # policy: confirm, never unattended
    assert acting._submit_task(safe) is True
    assert calls and "Check the weather" in calls[0]


def test_act_mode_runs_a_model_written_action_without_a_tool(tmp_path, monkeypatch):
    submitted = []
    acting = _make_brain(
        tmp_path / "act_toolless", monkeypatch,
        config={"mode": "act"},
        reflect_fn=lambda observations, context: [{
            "text": "Check the project notes and list what is still unfinished",
            "why": "the user keeps asking about pending work",
            "kind": "action", "salience": 0.92, "tool": "", "parameters": {},
        }],
        auto_submit=lambda goal: submitted.append(goal) or "id",
    )
    (tmp_path / "act_toolless").mkdir(exist_ok=True)
    acting.note_user_turn("what is still pending on the JARVIS project")

    result = acting.tick()

    assert result["actions"] == 1
    assert len(submitted) == 1
    assert "Check the project notes" in submitted[0]
    assert "low-risk" in submitted[0]


def test_act_mode_never_acts_on_ambient_followups(tmp_path, monkeypatch):
    submitted = []
    acting = _make_brain(
        tmp_path / "act_noise", monkeypatch,
        config={"mode": "act", "reflect_interval_sec": 999999},
        auto_submit=lambda goal: submitted.append(goal) or "id",
    )
    (tmp_path / "act_noise").mkdir(exist_ok=True)
    acting.note_user_turn(
        "the elevator door slides open and he follows her all the way home"
    )

    acting.tick()

    assert submitted == []


def test_act_mode_respects_min_act_salience(tmp_path, monkeypatch):
    submitted = []
    acting = _make_brain(
        tmp_path / "act_low", monkeypatch,
        config={"mode": "act"},
        reflect_fn=lambda observations, context: [{
            "text": "Maybe look into the build warning at some point",
            "why": "weak signal", "kind": "action", "salience": 0.55,
            "tool": "", "parameters": {},
        }],
        auto_submit=lambda goal: submitted.append(goal) or "id",
    )
    (tmp_path / "act_low").mkdir(exist_ok=True)
    acting.note_user_turn("there is a build warning")

    acting.tick()

    assert submitted == []


def test_initiative_speaks_thought_once_without_a_feedback_loop(tmp_path, monkeypatch):
    spoken = []
    b = _make_brain(
        tmp_path, monkeypatch,
        config={"min_salience": 0.5, "min_speak_salience": 0.6},
    )
    engine = initiative.get()
    engine.configure(speaker=spoken.append)
    engine.observe(b.on_initiative)

    b.note_user_turn("need to finish the release notes")
    b.tick()

    signal = b._speak_signal()
    assert signal and signal["intention_id"]
    engine.dispatch(initiative.Candidate(
        "brain_intention", 3, signal, "test", "test",
    ))
    assert spoken and "release notes" in spoken[0]

    # Dispatching our own thought marks it spoken; it does not become a new
    # observation and start a self-sustaining conversation.
    assert b._speak_signal() is None
    assert b.tick()["intentions"] == 0


def test_prompt_block_redacts_observations_and_reaches_the_prompt(tmp_path, monkeypatch):
    b = _make_brain(tmp_path, monkeypatch, config={"reflect_interval_sec": 999999})
    b.note_user_turn(
        "need to email mahesh@example.com with key AIza" + "S" * 30
    )
    b.tick()

    block = b.prompt_block()
    assert "CURRENT THINKING" in block
    assert "mahesh@example.com" not in block
    assert "AIza" not in block
    assert "[redacted-key]" in block or "<email>" in block

    monkeypatch.setattr(brain, "prompt_block", lambda: block)
    text = live_config.compose_prompt(
        base_dir=tmp_path,
        memory_text="",
        load_system_prompt=lambda: "SYSTEM",
        describe_state=lambda **kwargs: "",
        prompt_budget=lambda value: value,
    )
    assert "CURRENT THINKING" in text
    assert text.index("CURRENT THINKING") < text.index("SYSTEM")
