"""Live global telemetry: RSS news, weather, ISS, psutil host stats."""
from __future__ import annotations

import json
import random
import threading
import time
from datetime import datetime
from queue import Queue
from typing import Dict, Any

import feedparser
import psutil
import requests


class LiveData:
    def __init__(self, out_q: Queue):
        self.out_q = out_q
        self.running = True
        self.news = []
        self.weather = {}
        self.iss = {}
        self.host = {}
        self.ticker_idx = 0
        self._start()

    def _start(self):
        threading.Thread(target=self._news_loop, daemon=True).start()
        threading.Thread(target=self._weather_loop, daemon=True).start()
        threading.Thread(target=self._iss_loop, daemon=True).start()
        threading.Thread(target=self._host_loop, daemon=True).start()

    def _news_loop(self):
        feeds = [
            "https://feeds.reuters.com/reuters/topNews",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://hnrss.org/frontpage",
        ]
        while self.running:
            try:
                items = []
                for url in feeds:
                    try:
                        d = feedparser.parse(url)
                        for e in d.entries[:6]:
                            title = e.get("title", "")
                            if title:
                                items.append(title)
                    except Exception:
                        continue
                if items:
                    self.news = items[:18]
                    self.out_q.put({"type": "NEWS_UPDATE", "items": list(self.news)})
                time.sleep(300)
            except Exception:
                time.sleep(60)

    def _weather_loop(self):
        while self.running:
            try:
                # Try IP geolocation + open-meteo (free)
                try:
                    r = requests.get("https://ipapi.co/json/", timeout=5)
                    data = r.json()
                    lat = data.get("latitude", 12.97)
                    lon = data.get("longitude", 77.59)
                except Exception:
                    lat, lon = 12.97, 77.59
                try:
                    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m,pressure_msl"
                    r2 = requests.get(url, timeout=5)
                    cur = r2.json().get("current", {})
                    self.weather = {
                        "temp": cur.get("temperature_2m"),
                        "hum": cur.get("relative_humidity_2m"),
                        "wind": cur.get("wind_speed_10m"),
                        "pres": cur.get("pressure_msl"),
                        "lat": lat,
                        "lon": lon,
                    }
                    self.out_q.put({"type": "WEATHER_UPDATE", "data": dict(self.weather)})
                except Exception:
                    pass
                time.sleep(600)
            except Exception:
                time.sleep(120)

    def _iss_loop(self):
        while self.running:
            try:
                r = requests.get("http://api.open-notify.org/iss-now.json", timeout=5)
                d = r.json()
                pos = d.get("iss_position", {})
                self.iss = {"lat": pos.get("latitude"), "lon": pos.get("longitude"), "ts": d.get("timestamp")}
                self.out_q.put({"type": "ISS_UPDATE", "data": dict(self.iss)})
                time.sleep(10)
            except Exception:
                time.sleep(30)

    def _host_loop(self):
        while self.running:
            try:
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()
                net = psutil.net_io_counters()
                self.host = {
                    "cpu": cpu,
                    "ram": mem.percent,
                    "ram_used": round(mem.used / (1024**3), 1),
                    "ram_total": round(mem.total / (1024**3), 1),
                    "net_sent": net.bytes_sent,
                    "net_recv": net.bytes_recv,
                }
                self.out_q.put({"type": "HOST_UPDATE", "data": dict(self.host)})
                time.sleep(2)
            except Exception:
                time.sleep(5)
