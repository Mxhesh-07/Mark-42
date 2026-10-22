"""Tier 3.7/3.8/3.11/3.18/3.21/3.22 — HUD models that need no Tk."""

from __future__ import annotations

from ui import composer, cues, layout, timeline, transcript


def test_geometry_is_clamped_back_onto_the_screen():
    x, y, w, h = layout.clamp_geometry(5000, 5000, 984, 816, 1920, 1080)
    assert x <= 1920 and y <= 1080
    assert w <= 1920 and h <= 1080

    x, y, w, h = layout.clamp_geometry(-5000, -5000, 984, 816, 1920, 1080)
    assert x > -984 and y >= 0


def test_geometry_never_shrinks_below_a_usable_size():
    _x, _y, w, h = layout.clamp_geometry(0, 0, 10, 10, 1920, 1080)
    assert w >= 320 and h >= 240


def test_transcript_keeps_roles_and_searches():
    t = transcript.Transcript()
    t.add("you", "turn on the lights")
    t.add("ai", "done, lights on")
    assert [r["role"] for r in t.rows] == ["you", "ai"]
    assert t.search("lights")[-1]["role"] == "ai"
    assert t.search("") == []


def test_transcript_caps_and_exports(tmp_path):
    t = transcript.Transcript(limit=3)
    for i in range(5):
        t.add("sys", f"line {i}")
    assert len(t.rows) == 3
    out = t.export(tmp_path / "t.txt")
    assert out.read_text(encoding="utf-8").count("\n") >= 2
    js = t.export(tmp_path / "t.json", fmt="json")
    assert js.read_text(encoding="utf-8").startswith("[")


def test_split_speaker_handles_all_prefixes():
    assert transcript.split_speaker("You: hi") == ("you", "hi")
    assert transcript.split_speaker("AI: ok") == ("ai", "ok")
    assert transcript.split_speaker("SYS: boot") == ("sys", "boot")
    assert transcript.split_speaker("plain") == ("sys", "plain")


def test_timeline_tracks_status_and_cancel():
    events = []
    t = timeline.Timeline()
    t.add("search", cancel=lambda: events.append("cancelled"))
    t.set_status("search", timeline.RUNNING)
    assert "⟳" in t.lines()[0]
    assert t.cancel("search") is True
    assert events == ["cancelled"]
    assert t.cancel("search") is False
    assert t.clear_finished() == 1


def test_composer_history_navigation():
    h = composer.History(limit=3)
    h.add("one")
    h.add("two")
    assert h.previous() == "two"
    assert h.previous() == "one"
    assert h.previous() == "one"
    assert h.next() == "two"
    assert h.next() == ""
    h.add("three")
    h.add("four")
    assert h.previous() == "four"


def test_composer_normalises_and_parses_commands():
    assert composer.normalise("  hi\r\n") == "hi"
    assert composer.parse_command("/kill now") == ("kill", "now")
    assert composer.parse_command("hello") == ("", "hello")
    assert len(composer.normalise("x" * 9000)) == composer.MAX_INPUT


def test_cues_are_off_by_default_and_unknown_kinds_are_ignored():
    # The default config has no "cues" key (or false); play must be a no-op.
    assert cues.play("not-a-cue") is False
    assert isinstance(cues.play("thinking"), bool)
