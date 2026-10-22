"""Tier 1.6 — the small text helpers the live loop and tool runner share."""

from __future__ import annotations

from jarvis import text_utils


def test_fmt_args_is_single_line_and_bounded():
    assert text_utils.fmt_args({"a": 1, "b": "x y"}) == "a=1, b=x y"
    assert text_utils.fmt_args({"a": 1}, limit=4) == "a=1"
    long = text_utils.fmt_args({"path": "x" * 40}, limit=12)
    assert len(long) == 12
    assert long.endswith("…")


def test_fmt_args_never_raises_on_odd_input():
    class Odd:
        def items(self):
            raise RuntimeError("no")

        def __str__(self):
            return "odd"

    assert text_utils.fmt_args(Odd()) == "odd"  # type: ignore[arg-type]


def test_tidy_sentence_joins_word_pieces_without_inventing_spaces():
    chunks = [" O", "pen", " the", " note", "pad application."]
    assert text_utils.tidy_sentence(chunks) == "Open the notepad application."
    assert text_utils.tidy_sentence(["  a \n b  "]) == "a b"


def test_tidy_sentence_never_raises():
    assert isinstance(text_utils.tidy_sentence([object(), None]), str)
    assert isinstance(text_utils.tidy_sentence(None), str)


def test_owner_name_reads_memory_and_falls_back(monkeypatch):
    import memory.memory_manager as memory

    monkeypatch.setattr(
        memory, "load_memory", lambda: {"identity": {"name": {"value": " Ada "}}}
    )
    assert text_utils.owner_name() == "Ada"

    monkeypatch.setattr(memory, "load_memory", lambda: {"identity": {}})
    assert text_utils.owner_name() == "Owner"

    monkeypatch.setattr(
        memory, "load_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("broken")),
    )
    assert text_utils.owner_name() == "Owner"
