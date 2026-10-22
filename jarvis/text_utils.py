"""Small text helpers shared by the entry point and the tool runner."""

from __future__ import annotations


def fmt_args(args: dict, limit: int = 90) -> str:
    """Compact single-line form of tool arguments for the THINKING pane."""
    try:
        s = ", ".join(f"{k}={v}" for k, v in args.items())
    except Exception:
        s = str(args)
    s = " ".join(str(s).split())
    return s if len(s) <= limit else s[:limit - 1] + "…"


def tidy_sentence(chunks) -> str:
    """Join streaming transcription fragments into one clean sentence.

    Gemini Live emits the transcript word-piece by word-piece (" O", "pen",
    " the", " note", "pad application."), so the fragments must be concatenated
    verbatim and only then have their whitespace collapsed — joining with a space
    would turn "note" + "pad" into "note pad".
    """
    try:
        return " ".join("".join(str(c) for c in chunks).split())
    except Exception:
        return ""


def owner_name() -> str:
    """The user's name from memory, else a neutral fallback.

    Used as the default label when a voice is enrolled without an explicit name.
    """
    try:
        from memory.memory_manager import load_memory

        entry = (load_memory().get("identity", {}) or {}).get("name")
        name = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass
    return "Owner"
