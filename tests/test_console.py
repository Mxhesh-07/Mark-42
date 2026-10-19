"""Console encoding: a status glyph must never crash a command.

Regression: `python -m agent.health --full` (and `agent.audit verify`) died with
`UnicodeEncodeError` when stdout was redirected on Windows, because cp1252
cannot encode `✅`.
"""

import io
import sys

from agent import console, health


def test_enable_utf8_is_safe_on_a_capture_object(capsys):
    console.enable_utf8()
    print("[Health] ✅ ok")


def test_it_tolerates_a_stream_without_reconfigure():
    class Bare:
        def write(self, _text):
            pass

    console.enable_utf8(Bare(), Bare())


def test_it_reconfigures_a_real_text_stream(tmp_path):
    stream = io.TextIOWrapper(open(tmp_path / "out.txt", "wb"), encoding="cp1252")
    console.enable_utf8(stream)
    stream.write("[Health] ✅ ok")
    stream.close()
    assert "✅" in (tmp_path / "out.txt").read_text(encoding="utf-8")


def test_health_cli_survives_a_cp1252_redirect(tmp_path, monkeypatch):
    stream = io.TextIOWrapper(open(tmp_path / "health.txt", "wb"), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)

    assert health._cli([]) == 0
    stream.close()
    assert "self-check" in (tmp_path / "health.txt").read_text(encoding="utf-8")
