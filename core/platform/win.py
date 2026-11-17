"""Windows implementations. Every import is local so importing this module on
Windows without pycaw/comtypes installed still succeeds and returns False.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def is_windows() -> bool:
    return True


def _run_com(*args: str) -> str | None:
    """Run one COM operation in a short-lived child process.

    COM objects are only safe to release on the thread that created them, and
    only when that thread has called ``CoInitialize``. pycaw objects touched
    from an ``asyncio`` worker thread crashed the interpreter natively (access
    violation inside ``_ctypes.pyd``) when they were collected later. A child
    process has exactly one thread, is COM-initialised, and dies alone if COM
    misbehaves - so the parent only ever sees "ok" or ``None``.
    """
    script = Path(__file__).with_name("_com_child.py")
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", str(script), *args],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    lines = (proc.stdout or "").strip().splitlines()
    return lines[-1].strip() if lines else None


def set_mic_level(device_name: str, level: float) -> bool:
    """Set the capture level of the first input device matching `device_name`.

    A muted endpoint captures digital silence no matter what the level says, so
    applying a level also unmutes it. That is the only place this module changes
    a mute switch; callers that do not want it must not set a level.
    """
    try:
        wanted = str(device_name or "")
        value = max(0.0, min(1.0, float(level)))
    except Exception:
        return False
    return _run_com("mic", wanted, f"{value}") == "ok"


def mic_muted(device_name: str) -> bool | None:
    """True when the capture endpoint is muted, False when live, None unknown."""
    wanted = str(device_name or "")
    if not wanted:
        return None
    state = _run_com("mic-mute", wanted)
    if state == "1":
        return True
    if state == "0":
        return False
    return None


def unmute_mic(device_name: str) -> bool:
    """Clear the capture endpoint's mute switch, leaving its level alone."""
    wanted = str(device_name or "")
    if not wanted:
        return False
    return _run_com("mic-unmute", wanted) == "ok"


def beep(freq: int = 800, ms: int = 200) -> bool:
    try:
        import winsound

        winsound.Beep(int(freq), int(ms))
        return True
    except Exception:
        return False


def notify(title: str, message: str, duration: int = 10) -> bool:
    try:
        from win10toast import ToastNotifier

        ToastNotifier().show_toast(str(title), str(message),
                                   duration=int(duration), threaded=False)
        return True
    except Exception:
        return False


def get_master_volume() -> float | None:
    try:
        out = _run_com("get")
        return float(out) if out else None
    except Exception:
        return None


def set_master_volume(level: float) -> bool:
    try:
        value = max(0.0, min(1.0, float(level)))
    except Exception:
        return False
    return _run_com("set", f"{value}") == "ok"
