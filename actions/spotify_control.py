import json
import os
import sys
import time
from pathlib import Path

import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ================= CONFIG =================
SCOPE          = "user-read-playback-state user-modify-playback-state"
DEFAULT_REDIRECT_URI = "http://localhost:8888/callback"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR       = get_base_dir()
SPOTIFY_CONFIG = BASE_DIR / "config" / "spotify_config.json"

# ================= AUTH =================
sp = None  # Spotify client is created lazily so importing has no side effects


def _load_credentials() -> tuple:
    """Reads credentials from config/spotify_config.json with env fallbacks."""
    client_id     = os.getenv("SPOTIFY_CLIENT_ID", "")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    redirect_uri  = DEFAULT_REDIRECT_URI

    try:
        if SPOTIFY_CONFIG.exists():
            with open(SPOTIFY_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            client_id     = client_id or cfg.get("client_id", "")
            client_secret = client_secret or cfg.get("client_secret", "")
            redirect_uri  = cfg.get("redirect_uri", redirect_uri)
    except Exception as e:
        print(f"[Spotify] ⚠️ Could not read config: {e}")

    return client_id, client_secret, redirect_uri


def _get_client() -> spotipy.Spotify:
    """Creates the Spotify client on first use (never at import time)."""
    global sp
    if sp is None:
        client_id, client_secret, redirect_uri = _load_credentials()
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SCOPE,
            open_browser=True
        ))
    return sp


# ================= DEVICE =================
def get_active_device():
    devices = _get_client().devices()["devices"]

    if not devices:
        return None

    for d in devices:
        if d["is_active"]:
            return d["id"]

    return devices[0]["id"]


def ensure_device():
    device_id = get_active_device()

    if device_id:
        return device_id

    print("[Spotify] Waiting for active device...")

    for _ in range(5):
        time.sleep(2)
        device_id = get_active_device()
        if device_id:
            return device_id

    return None


# ================= CORE =================
def play_song(query: str):
    if not query:
        return "No song provided."

    try:
        results = _get_client().search(q=query, type="track", limit=1)

        if not results["tracks"]["items"]:
            return f"Could not find {query}"

        track = results["tracks"]["items"][0]
        uri = track["uri"]
        name = track["name"]
        artist = track["artists"][0]["name"]

        device_id = ensure_device()
        if not device_id:
            return "Open Spotify and play something once."

        _get_client().start_playback(device_id=device_id, uris=[uri])

        return f"Playing {name} by {artist}"

    except Exception as e:
        return f"Spotify error: {e}"


def pause_music():
    try:
        _get_client().pause_playback()
        return "Music paused."
    except:
        return "Could not pause."


def resume_music():
    try:
        device_id = ensure_device()
        if not device_id:
            return "No active device."

        _get_client().start_playback(device_id=device_id)
        return "Resuming music."
    except:
        return "Could not resume."


def next_track():
    try:
        _get_client().next_track()
        return "Next track."
    except:
        return "Could not skip."


def previous_track():
    try:
        _get_client().previous_track()
        return "Previous track."
    except:
        return "Could not go back."


def set_volume(value: int):
    try:
        value = max(0, min(100, int(value)))
        _get_client().volume(value)
        return f"Volume set to {value}%"
    except:
        return "Could not change volume."


# ================= SMART PLAY =================
def smart_play(query: str):
    """
    Handles things like:
    - 'play chill music'
    - 'play sad songs'
    - 'play workout songs'
    """
    try:
        device_id = ensure_device()
        if not device_id:
            return "No active device."

        results = _get_client().search(q=query, type="playlist,track", limit=1)

        if results["playlists"]["items"]:
            playlist_uri = results["playlists"]["items"][0]["uri"]
            _get_client().start_playback(device_id=device_id, context_uri=playlist_uri)
            return f"Playing playlist for {query}"

        return play_song(query)

    except Exception as e:
        return f"Smart play error: {e}"


# ================= TOOL ENTRY =================
def spotify_control(parameters: dict, **kwargs):
    action = parameters.get("action", "play")
    query = parameters.get("query", "")
    value = parameters.get("value", 50)

    if action == "play":
        return play_song(query)

    elif action == "pause":
        return pause_music()

    elif action == "resume":
        return resume_music()

    elif action == "next":
        return next_track()

    elif action == "previous":
        return previous_track()

    elif action == "volume":
        return set_volume(value)

    elif action == "smart":
        return smart_play(query)

    return "Unknown Spotify command."
