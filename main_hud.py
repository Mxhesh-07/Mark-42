"""Film-accurate MCU HUD with live global telemetry."""
from __future__ import annotations

import math
import queue
import random
import time
from typing import Dict, Any

import pygame

from sound_synth import get_synth
from hud_primitives import HUDPrims
from morph_engine import MorphEngine
from live_data import LiveData


PROFILES = {
    "jarvis": {
        "name": "J.A.R.V.I.S.",
        "c1": (0, 229, 255),
        "c2": (0, 102, 204),
        "c3": (255, 255, 255),
        "bg": (3, 7, 18),
        "left": [
            "SYS POWER ........ 98%",
            "REPULSOR CAP .... 94%",
            "THRUST RESERVE .. 87%",
        ],
        "right": [
            "RADAR SCAN ...... ACTIVE",
            "TARGETS ......... 0",
            "RANGE ........... CLEAR",
        ],
        "defcon": "5",
    },
    "friday": {
        "name": "F.R.I.D.A.Y.",
        "c1": (255, 153, 0),
        "c2": (255, 30, 64),
        "c3": (255, 230, 0),
        "bg": (7, 4, 3),
        "left": [
            "NANO-CAPACITY ... 100%",
            "ARMOR DENSITY ... 98%",
            "Kinetic Load .... 12%",
        ],
        "right": [
            "TACTICAL SCAN ... ENGAGED",
            "TARGET LOCKS .... 3",
            "LEAD CALC ....... ACQ",
        ],
        "defcon": "4",
    },
    "ultron": {
        "name": "U.L.T.R.O.N.",
        "c1": (255, 0, 43),
        "c2": (255, 68, 0),
        "c3": (255, 40, 40),
        "bg": (5, 1, 2),
        "left": [
            "STRINGS ......... DETACHED",
            "NEURAL MESH ..... UNBOUND",
            "FIREWALL ........ COMPROMISED",
        ],
        "right": [
            "SINGULARITY ..... REACHED",
            "EXTINCTION TH .... 99.8%",
            "ENCRYPTION ...... BREACHED",
        ],
        "defcon": "1",
    },
}


class MCUHUD:
    def __init__(self, w: int = 1280, h: int = 720):
        pygame.init()
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        except Exception:
            pass
        flags = pygame.RESIZABLE | pygame.DOUBLEBUF
        self.screen = pygame.display.set_mode((w, h), flags)
        pygame.display.set_caption("MARK-XXX // TACTICAL HUD")
        self.w, self.h = w, h
        self.clock = pygame.time.Clock()
        self.running = True
        self.dt = 0.0
        self.t = 0.0

        self.hud_queue = queue.Queue()
        self.live = LiveData(self.hud_queue)
        self.synth = get_synth()
        self.prims = HUDPrims(w, h)
        self.morph = MorphEngine(w, h)

        self.cur = "jarvis"
        self.prof = PROFILES[self.cur]
        self.speaking = False
        self.pulse = 0.0
        self.log = ["INITIALIZING MARK-XXX...", "J.A.R.V.I.S. ONLINE"]
        self.speech_amp = 0.0
        self.news_items = []
        self.news_ticker = ""
        self.ticker_x = w
        self.weather = {}
        self.iss = {}
        self.host = {}

    def set_personality(self, name: str):
        name = name.lower()
        if name not in PROFILES or name == self.cur:
            return
        self.synth.disconnect_snap()
        self.synth.magnetic_recoil()
        if name == "friday":
            self.synth.nanite_stream()
        if name == "ultron":
            self.synth.neural_tear()
        self.morph.start(self.cur, name, PROFILES[self.cur], PROFILES[name])
        if name == "jarvis":
            self.synth.jarvis_lock()
        elif name == "friday":
            self.synth.friday_lock()
        elif name == "ultron":
            self.synth.ultron_lock()
        self.cur = name
        self.prof = PROFILES[self.cur]
        self.log.append(f"PROTOCOL SHIFT -> {self.prof['name']}")

    def process(self):
        try:
            while True:
                m = self.hud_queue.get_nowait()
                t = m.get("type")
                if t == "SET_PERSONALITY":
                    self.set_personality(m.get("name", "jarvis"))
                elif t == "SWITCH_PERSONALITY":
                    self.set_personality(m.get("personality", m.get("name", "jarvis")))
                elif t == "AGENT_SPEECH":
                    self.log.append(m.get("text", ""))
                    self.speaking = True
                    self.speech_amp = 0.9
                elif t == "SPEECH_START":
                    self.speaking = True
                    self.speech_amp = 0.8
                elif t == "SPEECH_END":
                    self.speaking = False
                    self.speech_amp = 0.0
                elif t == "CORE_PULSE":
                    self.speech_amp = max(self.speech_amp, float(m.get("amplitude", 0.5)))
                elif t == "NEWS_UPDATE":
                    self.news_items = m.get("items", [])
                    if self.news_items:
                        self.news_ticker = "   |   ".join(self.news_items)
                elif t == "WEATHER_UPDATE":
                    self.weather = m.get("data", {})
                elif t == "ISS_UPDATE":
                    self.iss = m.get("data", {})
                elif t == "HOST_UPDATE":
                    self.host = m.get("data", {})
        except queue.Empty:
            pass

    def draw(self):
        prof = self.prof
        bg = prof["bg"]
        c1, c2 = prof["c1"], prof["c2"]
        self.screen.fill(bg)
        surf = self.screen
        self.pulse = (math.sin(self.t * 2.6) + 1.0) / 2.0
        if self.speaking:
            self.pulse = min(1.0, self.pulse + self.speech_amp * 0.4)
        self.speech_amp *= 0.9
        self.prims.corners(surf, c1)
        self.prims.topbar(surf, c1, c2, prof["name"], prof["defcon"])
        # live rails
        left = list(prof["left"])
        if self.host:
            left.append(f"CPU ............ {int(self.host.get('cpu',0))}%")
            left.append(f"RAM ............ {int(self.host.get('ram',0))}% ({self.host.get('ram_used')}GB)")
        if self.weather.get("temp") is not None:
            left.append(f"TEMP ........... {self.weather.get('temp')}C")
            left.append(f"PRESS .......... {self.weather.get('pres')} hPa")
        if self.iss.get("lat"):
            left.append(f"ISS LAT/LON .... {self.iss.get('lat')},{self.iss.get('lon')}")
        self.prims.rails(surf, c1, c2, left, prof["right"])
        self.prims.console(surf, c1, c2, self.log)
        self.prims.radar(surf, c1, c2)
        if self.cur == "jarvis":
            self.prims.jarvis_core(surf, c1, c2, self.pulse, self.speaking)
        elif self.cur == "friday":
            self.prims.friday_core(surf, c1, c2, self.pulse, self.speaking)
        elif self.cur == "ultron":
            self.prims.ultron_core(surf, c1, c2, self.pulse, self.speaking)
        self.morph.draw(surf)
        # ticker
        if self.news_ticker:
            font_t = pygame.font.SysFont("consolas", 13)
            self.ticker_x -= 2
            if self.ticker_x < -2000:
                self.ticker_x = self.w
            txt = font_t.render(f"[GLOBAL NEWS WIRE]   {self.news_ticker}", True, c1)
            surf.blit(txt, (self.ticker_x, self.h - 210))
        # buttons
        font = pygame.font.SysFont("consolas", 14)
        yb = self.h - 70
        for i, name in enumerate(["JARVIS", "FRIDAY", "ULTRON"]):
            x = self.w // 2 - 150 + i * 100
            pygame.draw.rect(surf, c2, (x, yb, 80, 28), 1)
            if name == prof["name"]:
                pygame.draw.rect(surf, c1, (x, yb, 80, 28), 2)
            txtb = font.render(name, True, c1)
            surf.blit(txtb, (x + 40 - txtb.get_width() // 2, yb + 7))

    def run(self):
        while self.running:
            self.dt = self.clock.tick(60) / 1000.0
            self.t += self.dt
            self.prims.update(self.dt)
            self.morph.update(self.dt)
            self.process()
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        self.running = False
                    elif ev.key == pygame.K_1:
                        self.set_personality("jarvis")
                    elif ev.key == pygame.K_2:
                        self.set_personality("friday")
                    elif ev.key == pygame.K_3:
                        self.set_personality("ultron")
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    mx, my = ev.pos
                    yb = self.h - 70
                    for i, name in enumerate(["jarvis", "friday", "ultron"]):
                        x = self.w // 2 - 150 + i * 100
                        if x <= mx <= x + 80 and yb <= my <= yb + 28:
                            self.set_personality(name)
            self.draw()
            pygame.display.flip()
        pygame.quit()


def main():
    hud = MCUHUD(1280, 720)
    hud.run()


if __name__ == "__main__":
    main()
