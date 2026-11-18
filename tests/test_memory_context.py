import json

from jarvis import live_config, memory_context
from memory import ai_memory, sql_memory


def _scrubbed_note(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_memory, "BASE_DIR", tmp_path)
    mem = ai_memory.AIMemory()
    mem.remember("Email me at mahesh@example.com about the launch")
    return mem


def test_build_context_collects_notes_events_and_actions(tmp_path, monkeypatch):
    _scrubbed_note(tmp_path, monkeypatch)

    sql_memory.remember(
        "exchange:1",
        "User: push the upgraded code | JARVIS: pushed to main",
        kind="exchange",
        source="voice",
    )

    audit = tmp_path / "audit_log.jsonl"
    audit.write_text(
        json.dumps({
            "tool": "open_app",
            "detail": "opened notepad",
            "outcome": "ok",
        })
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(memory_context, "AUDIT_PATH", audit)

    ctx = memory_context.build_context()

    assert "MEMORIES & EVENTS" in ctx
    assert "push the upgraded code" in ctx
    assert "RECENT ACTIONS" in ctx
    assert "opened notepad" in ctx
    # personal contact details are scrubbed before the prompt leaves the machine
    assert "mahesh@example.com" not in ctx
    assert "[redacted]" in ctx


def test_record_exchange_and_explicit_remember(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_memory, "BASE_DIR", tmp_path)

    memory_context.record_exchange("I have been testing the voice memory", "Got it")
    rows = sql_memory.search("testing the voice memory")
    assert rows and rows[0]["kind"] == "exchange"

    memory_context.record_exchange(
        "Remember that my birthday is June 5", "I will remember that"
    )
    assert any(
        "birthday is June 5" in note for note in ai_memory.AIMemory().data["notes"]
    )
    notes = [r for r in sql_memory.search("birthday") if r["kind"] == "note"]
    assert notes


def test_compose_prompt_includes_episodic_block(tmp_path):
    text = live_config.compose_prompt(
        base_dir=tmp_path,
        memory_text="[USER MEMORY]\n- Name: Mahesh",
        episodic_text="- [exchange] User: fixed the mic",
        load_system_prompt=lambda: "SYSTEM",
        describe_state=lambda **kwargs: "",
        prompt_budget=lambda value: value,
    )
    assert "[LONG-TERM MEMORY" in text
    assert "fixed the mic" in text
    assert text.index("[LONG-TERM MEMORY") < text.index("SYSTEM")
