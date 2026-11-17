"""Cinematic morph engine with particles, shake, chromatic glitch."""
from __future__ import annotations

import math
import random
from typing import List, Tuple

import pygame

from hud_primitives import PartNode


class MorphEngine:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.cx = w // 2
        self.cy = h // 2
        self.active = False
        self.phase = 0  # 0 decon 1 flux 2 asm 3 lock
        self.t = 0.0
        self.dur = 1.4
        self.nodes: List[PartNode] = []
        self.shake_x = 0
        self.shake_y = 0
        self.rgb_split = 0
        self.scan_off = 0
        self.banner = ""
        self.banner_t = 0.0

    def start(self, from_p: str, to_p: str, colors_from, colors_to):
        self.active = True
        self.phase = 0
        self.t = 0.0
        self.nodes.clear()
        c = colors_to.get("c1", (255,255,255))
        for _ in range(420):
            a = random.uniform(0, math.pi * 2)
            r = random.uniform(40, 160)
            x = self.cx + math.cos(a) * r
            y = self.cy + math.sin(a) * r
            nd = PartNode(x, y, c)
            # targets by archetype
            if to_p == "jarvis":
                ta = random.uniform(0, math.pi * 2)
                tr = random.uniform(90, 150)
                nd.tx = self.cx + math.cos(ta) * tr
                nd.ty = self.cy + math.sin(ta) * tr
            elif to_p == "friday":
                # hex targets
                ring = random.randint(2, 4)
                ang = math.radians(60 * random.randint(0, 5))
                rr = 70 + ring * 26
                nd.tx = self.cx + math.cos(ang) * rr
                nd.ty = self.cy + math.sin(ang) * rr
            else:  # ultron
                ang = math.radians(random.randint(0, 23) * 15)
                nd.tx = self.cx + math.cos(ang) * random.uniform(90, 150)
                nd.ty = self.cy + math.sin(ang) * random.uniform(90, 150)
            self.nodes.append(nd)
        if to_p == "jarvis":
            self.banner = "[ STARK INDUSTRIES // SYSTEM 4.0 // J.A.R.V.I.S. RESTORED ]"
        elif to_p == "friday":
            self.banner = "[ TACTICAL SUIT OVERRIDE // MARK L NANO-MESH // F.R.I.D.A.Y. READY ]"
        else:
            self.banner = "[ CRITICAL ANOMALY // NEURAL NETWORK DETACHED // U.L.T.R.O.N. ONLINE ]"
        self.banner_t = 0.0

    def update(self, dt: float):
        if not self.active:
            self.shake_x = self.shake_y = self.rgb_split = self.scan_off = 0
            return
        self.t += dt
        if self.t < 0.35:
            self.phase = 0
            self.shake_x = random.randint(-14, 14)
            self.shake_y = random.randint(-10, 10)
            self.rgb_split = random.randint(2, 6)
            self.scan_off = random.randint(-6, 6)
        elif self.t < 0.8:
            self.phase = 1
            self.shake_x = random.randint(-8, 8)
            self.shake_y = random.randint(-6, 6)
            self.rgb_split = random.randint(1, 4)
            self.scan_off = random.randint(-4, 4)
            # flow
            k, d = 280.0, 10.0
            for nd in self.nodes:
                ax = (nd.tx - nd.x) * k - nd.vx * d
                ay = (nd.ty - nd.y) * k - nd.vy * d
                nd.vx += ax * dt
                nd.vy += ay * dt
                nd.x += nd.vx * dt
                nd.y += nd.vy * dt
        elif self.t < 1.2:
            self.phase = 2
            self.shake_x = random.randint(-4, 4)
            self.shake_y = random.randint(-3, 3)
            self.rgb_split = random.randint(0, 2)
            self.scan_off = random.randint(-2, 2)
            k, d = 340.0, 11.0
            for nd in self.nodes:
                ax = (nd.tx - nd.x) * k - nd.vx * d
                ay = (nd.ty - nd.y) * k - nd.vy * d
                nd.vx += ax * dt
                nd.vy += ay * dt
                nd.x += nd.vx * dt
                nd.y += nd.vy * dt
        else:
            self.phase = 3
            self.shake_x = int(self.shake_x * 0.7)
            self.shake_y = int(self.shake_y * 0.7)
            self.rgb_split = max(0, self.rgb_split - 1)
            self.scan_off = max(0, self.scan_off - 1)
            self.banner_t += dt
            if self.t >= self.dur:
                self.active = False
                self.nodes.clear()

    def draw(self, surf: pygame.Surface):
        if not self.active:
            return
        for nd in self.nodes:
            a = 220
            c = (*nd.color, a)
            s = pygame.Surface((3, 3), pygame.SRCALPHA)
            pygame.draw.circle(s, c, (1, 1), 1)
            surf.blit(s, (int(nd.x) - 1, int(nd.y) - 1))
        if self.phase == 3 and self.banner_t < 1.6:
            font = pygame.font.SysFont("consolas", 16)
            txt = font.render(self.banner, True, (255, 255, 255))
            rect = txt.get_rect(center=(self.cx, self.cy - 200))
            # glow
            glow = font.render(self.banner, True, (0, 229, 255))
            g2 = glow.get_rect(center=(self.cx + 1, self.cy - 200))
            surf.blit(glow, g2)
            surf.blit(txt, rect)
