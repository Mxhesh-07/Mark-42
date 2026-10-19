"""Make console output safe for the glyphs this project prints.

The app is normally launched with ``-X utf8``, but the documented CLIs are not::

    python -m agent.audit verify
    python -m agent.health --full

When stdout is a real Windows console, Python already speaks UTF-16 to it, so
emoji are fine. When stdout is *redirected* (a file, a pipe, a service log) the
stream falls back to the ANSI code page — cp1252 here — and the status glyph in
``[Health] ✅ self-check passed`` raises ``UnicodeEncodeError`` and kills the
command. Reconfiguring the standard streams to UTF-8 is a two-line fix and is
correct in both cases: the console path is unchanged, and the redirected path
gets the UTF-8 the rest of the project already writes.
"""

from __future__ import annotations

import sys


def enable_utf8(*streams) -> None:
    """Best-effort UTF-8 for stdout/stderr. Never raises.

    Test capture objects and other stream stand-ins have no ``reconfigure``;
    those are skipped, because they do not encode anything.
    """
    for stream in (streams or (sys.stdout, sys.stderr)):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
