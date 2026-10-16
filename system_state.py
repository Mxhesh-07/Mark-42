"""
system_state.py — lightweight desktop awareness for JARVIS.

Lets JARVIS *see* what is already open so it can continue in an existing
window instead of launching a second copy of the same app.

Public API
----------
list_open_windows(limit)  -> list[str]   visible top-level window titles
list_running_apps(limit)  -> list[str]   apps that actually own a window
is_app_open(hint)         -> bool        True if an app/window matches `hint`
focus_window(hint)        -> bool        bring a matching window to the front
describe_state(limit)     -> str         compact snapshot for the LLM prompt

Everything is best-effort: any failure returns an empty result / False and
never raises, so callers can use it without guards.
"""

from __future__ import annotations

import platform
import re

_IS_WINDOWS = platform.system() == "Windows"
_IS_MACOS = platform.system() == "Darwin"

try:  # Windows fast path
    import win32gui  # type: ignore
    import win32process  # type: ignore
    _HAS_WIN32 = True
except Exception:  # pragma: no cover - non-Windows or missing pywin32
    _HAS_WIN32 = False

try:
    import psutil  # type: ignore
    _HAS_PSUTIL = True
except Exception:  # pragma: no cover
    _HAS_PSUTIL = False

# Windows/OS chrome we never want to report as a "user app".
_WINDOW_NOISE = {
    "default ime",
    "msctfime ui",
    "program manager",
    "windows input experience",
    "microsoft text input application",
    "nvidia geforce overlay",
    "settings",
    "search",
    "taskbar",
}

# Background processes that are never the point of "what's open".
_PROC_NOISE = {
    "explorer", "svchost", "runtimebroker", "dwm", "csrss", "wininit",
    "winlogon", "services", "lsass", "conhost", "sihost", "taskhostw",
    "searchhost", "startmenuexperiencehost", "shellexperiencehost",
    "textinputhost", "applicationframehost", "systemsettings",
    "securityhealthsystray", "widgets", "widgetservice", "registry",
    "python", "pythonw", "powershell", "pwsh", "cmd", "windowsterminal",
    "nvidia", "nvcontainer", "nvtmru", "igfxem", "audiodg", "spoolsv",
}


def _clean_app_name(raw: str) -> str:
    """Turn 'msedge.exe' / 'Code - Insiders' into a tidy display label."""
    name = (raw or "").strip()
    if name.lower().endswith(".exe"):
        name = name[:-4]
    name = name.replace("_", " ").strip()
    return name


# --------------------------------------------------------------------------
# Windows enumeration
# --------------------------------------------------------------------------
def _windows_raw() -> list[tuple[int, str, int]]:
    """Return [(hwnd, title, pid)] for visible top-level windows."""
    out: list[tuple[int, str, int]] = []
    if not (_IS_WINDOWS and _HAS_WIN32):
        return out

    def _cb(hwnd, _extra):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            if not title or title.lower() in _WINDOW_NOISE:
                return
            # Skip invisible-to-user helper windows (zero-size / cloaked).
            if len(title) > 200:
                title = title[:200]
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            out.append((hwnd, title, pid))
        except Exception:
            return

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return out
    return out


def _proc_name(pid: int) -> str:
    if not (_HAS_PSUTIL and pid):
        return ""
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def list_open_windows(limit: int = 25) -> list[str]:
    """Visible top-level window titles, de-duplicated, newest order kept."""
    seen: set[str] = set()
    titles: list[str] = []
    for _hwnd, title, _pid in _windows_raw():
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
        if len(titles) >= limit:
            break
    return titles


def list_running_apps(limit: int = 20) -> list[str]:
    """Apps that own at least one visible window (i.e. truly 'open')."""
    apps: list[str] = []
    seen: set[str] = set()
    for _hwnd, _title, pid in _windows_raw():
        name = _clean_app_name(_proc_name(pid))
        if not name:
            continue
        key = name.lower()
        if key in _PROC_NOISE or key in seen:
            continue
        seen.add(key)
        apps.append(name)
        if len(apps) >= limit:
            break
    return apps


# --------------------------------------------------------------------------
# Matching / focusing
# --------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"[\s._-]+", "", (text or "").lower())


def _matches(hint: str, candidate: str) -> bool:
    h, c = _norm(hint), _norm(candidate)
    if not h or not c:
        return False
    return h in c or c in h


def is_app_open(hint: str) -> bool:
    """True if any open window title or owning process matches `hint`."""
    if not hint:
        return False
    for _hwnd, title, pid in _windows_raw():
        if _matches(hint, title) or _matches(hint, _proc_name(pid)):
            return True
    return False


def focus_window(hint: str) -> bool:
    """
    Bring the first window matching `hint` to the foreground.
    Returns True only if a matching window was found.
    """
    if not hint:
        return False

    if _IS_WINDOWS and _HAS_WIN32:
        hwnd_match: int | None = None
        for hwnd, title, pid in _windows_raw():
            if _matches(hint, title) or _matches(hint, _proc_name(pid)):
                hwnd_match = hwnd
                break
        if hwnd_match is None:
            return False

        try:
            if win32gui.IsIconic(hwnd_match):
                win32gui.ShowWindow(hwnd_match, 9)   # SW_RESTORE
            else:
                win32gui.ShowWindow(hwnd_match, 5)   # SW_SHOW
            try:
                win32gui.SetForegroundWindow(hwnd_match)
            except Exception:
                # Windows blocks focus-stealing; the Alt tap releases the lock.
                try:
                    import ctypes
                    u = ctypes.windll.user32
                    u.keybd_event(0x12, 0, 0, 0)   # Alt down
                    u.keybd_event(0x12, 0, 2, 0)   # Alt up
                    u.SetForegroundWindow(hwnd_match)
                except Exception:
                    pass
            return True
        except Exception:
            return False

    if _IS_MACOS:
        try:
            import subprocess
            script = (
                'tell application "System Events" to set frontmost of '
                f'(first process whose name contains "{hint}") to true'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

    # Linux: best-effort via wmctrl if present.
    try:
        import subprocess
        r = subprocess.run(
            ["wmctrl", "-a", hint], capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def describe_state(max_windows: int = 12, max_apps: int = 12) -> str:
    """Compact, prompt-friendly snapshot of the current desktop."""
    wins = list_open_windows(limit=max_windows)
    apps = list_running_apps(limit=max_apps)
    parts: list[str] = []
    if wins:
        parts.append("Open windows: " + " | ".join(wins))
    if apps:
        parts.append("Open apps: " + ", ".join(apps))
    return "\n".join(parts) if parts else "No notable windows or apps detected."
