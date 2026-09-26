"""
actions/screen_processor.py — Gemini Live API — IMAGE-ONLY SESSION v8
"""

import asyncio
import base64
import io
import json
import re
import os
import sys
import time
import threading
import cv2
import mss
import mss.tools
import pyaudio
from pathlib import Path

try:
    import PIL.Image
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from google import genai
from google.genai import types

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
FORMAT              = pyaudio.paInt16
CHANNELS            = 1
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

IMG_MAX_W = 640
IMG_MAX_H = 360
JPEG_Q    = 55

SYSTEM_PROMPT = (
    "You are JARVIS from Iron Man movies. "
    "Analyze images with technical precision and intelligence. "
    "Help the user in a way they can understand — don't be overly complex. "
    "Be concise, smart, and helpful like Tony Stark's AI assistant. "
    "Respond in maximum 2 short sentences. Speed is priority. "
    "Address the user as 'sir' for a tone of respect. "
    "Ask if the user needs any further help with their problem."
)

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]

def _get_camera_index() -> int:
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if "camera_index" in cfg:
            return int(cfg["camera_index"])
    except:
        pass

    best_index = 0
    for idx in range(6):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                best_index = idx
                break

    cfg = {}
    if API_CONFIG_PATH.exists():
        with open(API_CONFIG_PATH, "r") as f:
            cfg = json.load(f)

    cfg["camera_index"] = best_index
    with open(API_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=4)

    return best_index

def _to_jpeg(img_bytes: bytes) -> bytes:
    if not _PIL_OK:
        return img_bytes
    img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img.thumbnail([IMG_MAX_W, IMG_MAX_H])
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_Q)
    return buf.getvalue()

def _capture_screenshot() -> bytes:
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
        return _to_jpeg(mss.tools.to_png(shot.rgb, shot.size))

def _capture_camera() -> bytes:
    cap = cv2.VideoCapture(_get_camera_index(), cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError("Camera failed")

    for _ in range(5):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret:
        raise RuntimeError("Capture failed")

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])
    return buf.tobytes()

class _LiveSession:

    def __init__(self):
        self._loop = None
        self._thread = None
        self._session = None
        self._out_queue = None
        self._audio_in = None
        self._ready = threading.Event()
        self._player = None
        self._pya = pyaudio.PyAudio()
        self._send_lock = None

    def start(self, player=None):
        if self._thread and self._thread.is_alive():
            return
        self._player = player
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        self._out_queue = asyncio.Queue(maxsize=30)
        self._audio_in = asyncio.Queue()
        self._send_lock = asyncio.Lock()

        client = genai.Client(api_key=_get_api_key())

        config = types.LiveConnectConfig(response_modalities=["AUDIO"])

        while True:
            try:
                async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                    self._session = session
                    self._ready.set()

                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._send_loop())
                        tg.create_task(self._recv_loop())
                        tg.create_task(self._play_loop())

            except Exception as e:
                print("Reconnect:", e)
                self._session = None
                self._ready.clear()   # ✅ FIXED
                await asyncio.sleep(2)

    async def _send_loop(self):
        while True:
            item = await self._out_queue.get()

            if self._session:
                image_bytes, mime_type, user_text = item

                async with self._send_lock:  # ✅ FIX
                    try:
                        b64 = base64.b64encode(image_bytes).decode()

                        await asyncio.wait_for(  # ✅ FIX
                            self._session.send_client_content(
                                turns={
                                    "parts": [
                                        {"inline_data": {"mime_type": mime_type, "data": b64}},
                                        {"text": user_text}
                                    ]
                                },
                                turn_complete=True
                            ),
                            timeout=15
                        )

                        await asyncio.sleep(1)  # ✅ FIX

                    except Exception as e:
                        print("Send error:", e)

    async def _recv_loop(self):
        async for response in self._session.receive():
            if response.data:
                await self._audio_in.put(response.data)

    async def _play_loop(self):
        stream = await asyncio.to_thread(
            self._pya.open,
            format=FORMAT, channels=CHANNELS,
            rate=RECEIVE_SAMPLE_RATE, output=True,
        )
        while True:
            chunk = await self._audio_in.get()
            await asyncio.to_thread(stream.write, chunk)

    def analyze(self, image_bytes, mime_type, user_text):
        asyncio.run_coroutine_threadsafe(
            self._out_queue.put((image_bytes, mime_type, user_text)),
            self._loop
        )

_live = _LiveSession()
_started = False

def screen_process(parameters, **kwargs):
    text = parameters.get("text", "")
    angle = parameters.get("angle", "screen")

    if angle == "camera":
        img = _capture_camera()
    else:
        img = _capture_screenshot()

    _live.start()
    _live.analyze(img, "image/jpeg", text)
    return True