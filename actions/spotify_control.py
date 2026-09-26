import time
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ================= CONFIG =================
CLIENT_ID = "0533af6d0b074f7789cf54079b8d9d29"
CLIENT_SECRET = "8f320a5c9be149fbb22a8ec57235da76"
REDIRECT_URI = "http://localhost:8888/callback"

SCOPE = "user-read-playback-state user-modify-playback-state"

# ================= AUTH =================
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    open_browser=True
))


# ================= DEVICE =================
def get_active_device():
    devices = sp.devices()["devices"]

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
        results = sp.search(q=query, type="track", limit=1)

        if not results["tracks"]["items"]:
            return f"Could not find {query}"

        track = results["tracks"]["items"][0]
        uri = track["uri"]
        name = track["name"]
        artist = track["artists"][0]["name"]

        device_id = ensure_device()
        if not device_id:
            return "Open Spotify and play something once."

        sp.start_playback(device_id=device_id, uris=[uri])

        return f"Playing {name} by {artist}"

    except Exception as e:
        return f"Spotify error: {e}"


def pause_music():
    try:
        sp.pause_playback()
        return "Music paused."
    except:
        return "Could not pause."


def resume_music():
    try:
        device_id = ensure_device()
        if not device_id:
            return "No active device."

        sp.start_playback(device_id=device_id)
        return "Resuming music."
    except:
        return "Could not resume."


def next_track():
    try:
        sp.next_track()
        return "Next track."
    except:
        return "Could not skip."


def previous_track():
    try:
        sp.previous_track()
        return "Previous track."
    except:
        return "Could not go back."


def set_volume(value: int):
    try:
        value = max(0, min(100, int(value)))
        sp.volume(value)
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

        results = sp.search(q=query, type="playlist,track", limit=1)

        if results["playlists"]["items"]:
            playlist_uri = results["playlists"]["items"][0]["uri"]
            sp.start_playback(device_id=device_id, context_uri=playlist_uri)
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
