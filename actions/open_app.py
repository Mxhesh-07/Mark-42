# actions/open_app.py
# MARK XXV — Cross-Platform App Launcher

import time
import subprocess
import platform
import shutil

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

# Desktop awareness lives at the project root (system_state.py).
try:
    from system_state import is_app_open, focus_window
    _STATE = True
except Exception:
    try:
        from actions.system_state import is_app_open, focus_window  # type: ignore
        _STATE = True
    except Exception:
        _STATE = False

        def is_app_open(hint: str) -> bool:  # type: ignore
            return False

        def focus_window(hint: str) -> bool:  # type: ignore
            return False

_APP_ALIASES = {
    "whatsapp":           {"Windows": "WhatsApp",               "Darwin": "WhatsApp",            "Linux": "whatsapp"},
    "chrome":             {"Windows": "chrome",                 "Darwin": "Google Chrome",       "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                 "Darwin": "Google Chrome",       "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                "Darwin": "Firefox",             "Linux": "firefox"},
    "spotify":            {"Windows": "Spotify",                "Darwin": "Spotify",             "Linux": "spotify"},
    "vscode":             {"Windows": "code",                   "Darwin": "Visual Studio Code",  "Linux": "code"},
    "visual studio code": {"Windows": "code",                   "Darwin": "Visual Studio Code",  "Linux": "code"},
    "discord":            {"Windows": "Discord",                "Darwin": "Discord",             "Linux": "discord"},
    "telegram":           {"Windows": "Telegram",               "Darwin": "Telegram",            "Linux": "telegram"},
    "instagram":          {"Windows": "Instagram",              "Darwin": "Instagram",           "Linux": "instagram"},
    "tiktok":             {"Windows": "TikTok",                 "Darwin": "TikTok",              "Linux": "tiktok"},
    "notepad":            {"Windows": "notepad.exe",            "Darwin": "TextEdit",            "Linux": "gedit"},
    "calculator":         {"Windows": "calc.exe",               "Darwin": "Calculator",          "Linux": "gnome-calculator"},
    "terminal":           {"Windows": "cmd.exe",                "Darwin": "Terminal",            "Linux": "gnome-terminal"},
    "cmd":                {"Windows": "cmd.exe",                "Darwin": "Terminal",            "Linux": "bash"},
    "explorer":           {"Windows": "explorer.exe",           "Darwin": "Finder",              "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",           "Darwin": "Finder",              "Linux": "nautilus"},
    "paint":              {"Windows": "mspaint.exe",            "Darwin": "Preview",             "Linux": "gimp"},
    "word":               {"Windows": "winword",                "Darwin": "Microsoft Word",      "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                  "Darwin": "Microsoft Excel",     "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",               "Darwin": "Microsoft PowerPoint","Linux": "libreoffice --impress"},
    "vlc":                {"Windows": "vlc",                    "Darwin": "VLC",                 "Linux": "vlc"},
    "zoom":               {"Windows": "Zoom",                   "Darwin": "zoom.us",             "Linux": "zoom"},
    "slack":              {"Windows": "Slack",                  "Darwin": "Slack",               "Linux": "slack"},
    "steam":              {"Windows": "steam",                  "Darwin": "Steam",               "Linux": "steam"},
    "task manager":       {"Windows": "taskmgr.exe",            "Darwin": "Activity Monitor",    "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",           "Darwin": "System Preferences",  "Linux": "gnome-control-center"},
    "powershell":         {"Windows": "powershell.exe",         "Darwin": "Terminal",            "Linux": "bash"},
    "edge":               {"Windows": "msedge",                 "Darwin": "Microsoft Edge",      "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                  "Darwin": "Brave Browser",       "Linux": "brave-browser"},
    "obsidian":           {"Windows": "Obsidian",               "Darwin": "Obsidian",            "Linux": "obsidian"},
    "notion":             {"Windows": "Notion",                 "Darwin": "Notion",              "Linux": "notion"},
    "blender":            {"Windows": "blender",                "Darwin": "Blender",             "Linux": "blender"},
    "capcut":             {"Windows": "CapCut",                 "Darwin": "CapCut",              "Linux": "capcut"},
    "postman":            {"Windows": "Postman",                "Darwin": "Postman",             "Linux": "postman"},
    "figma":              {"Windows": "Figma",                  "Darwin": "Figma",               "Linux": "figma"},
}


def _normalize(raw: str) -> str:
    system = platform.system()
    key    = raw.lower().strip()
    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(system, raw)
    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(system, raw)
    return raw


def _is_running(app_name: str) -> bool:
    """True if the app already has a visible window (preferred) or a matching process."""
    # Window-title match first: catches apps whose process name is generic
    # (e.g. LinkedIn running inside msedge, or UWP apps under ApplicationFrameHost).
    if _STATE:
        try:
            if is_app_open(app_name):
                return True
        except Exception:
            pass
    if not _PSUTIL:
        return False
    app_lower = app_name.lower().replace(" ", "").replace(".exe", "")
    if not app_lower:
        return False
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                proc_name = proc.info["name"].lower().replace(" ", "").replace(".exe", "")
                if not proc_name:
                    continue
                if app_lower in proc_name or proc_name in app_lower:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def _launch_windows(app_name: str) -> bool:
    try:
        import pyautogui
        pyautogui.PAUSE = 0.1
        pyautogui.press("win")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(3.0)
        return True
    except Exception as e:
        print(f"[open_app] ⚠️ Windows launch failed: {e}")
        return False

def _launch_macos(app_name: str) -> bool:
    try:
        result = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(["open", "-a", f"{app_name}.app"], capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        import pyautogui
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] ⚠️ macOS Spotlight failed: {e}")
        return False



def _launch_linux(app_name: str) -> bool:
    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-"))
    )
    if binary:
        try:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(["xdg-open", app_name], capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    try:
        desktop_name = app_name.lower().replace(" ", "-")
        subprocess.run(["gtk-launch", desktop_name], capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "Please specify which application to open."

    system   = platform.system()
    launcher = _OS_LAUNCHERS.get(system)

    if launcher is None:
        return f"Unsupported OS: {system}"

    normalized = _normalize(app_name)

    # ── Already open? Focus it instead of spawning a duplicate window. ──
    already_open = False
    try:
        already_open = _is_running(normalized) or (
            normalized != app_name and _is_running(app_name)
        )
    except Exception:
        already_open = False

    if already_open:
        focused = False
        try:
            focused = focus_window(normalized) or focus_window(app_name)
        except Exception:
            focused = False

        print(
            f"[open_app] ♻️ Already open: {app_name} "
            f"(focus={'ok' if focused else 'best-effort'})"
        )
        if player:
            player.write_log(f"[open_app] {app_name} (already open)")
        if focused:
            return f"{app_name} is already open — I've brought it to the front."
        return f"{app_name} is already running — no need to open it again."

    print(f"[open_app] 🚀 Launching: {app_name} → {normalized} ({system})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        success = launcher(normalized)

        if success:
            return f"Opened {app_name} successfully."

        if normalized != app_name:
            success = launcher(app_name)
            if success:
                return f"Opened {app_name} successfully."

        return (
            f"I tried to open {app_name}, but couldn't confirm it launched. "
            f"It may still be loading or might not be installed."
        )

    except Exception as e:
        print(f"[open_app] ❌ {e}")
        return f"Failed to open {app_name}: {e}"