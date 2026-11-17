"""MCU film-accurate HUD primitives."""
from __future__ import annotations

import math
import random
from typing import List, Tuple

import pygame


class PartNode:
    def __init__(self, x, y, color):
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.tx = x
        self.ty = y
        self.color = color
        self.life = 1.0
        self.size = random.uniform(1.2, 2.2)
        self.angle = random.uniform(0, math.pi * 2)
        self.ang_vel = random.uniform(-6.0, 6.0)


class HUDPrims:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.cx = w // 2
        self.cy = h // 2
        self.t = 0.0
        self.nodes: List[PartNode] = []
        self.radar_angle = 0.0
        self.scan = 0.0

    def make_pool(self, n: int, cx: int, cy: int, color: Tuple[int, int, int]):
        self.nodes.clear()
        for _ in range(n):
            a = random.uniform(0, math.pi * 2)
            r = random.uniform(20, 140)
            x = cx + math.cos(a) * r
            y = cy + math.sin(a) * r
            nd = PartNode(x, y, color)
            nd.tx = cx
            nd.ty = cy
            self.nodes.append(nd)

    def flow_to(self, targets: List[Tuple[float, float]], k: float = 220.0, d: float = 9.0, dt: float = 0.016):
        for i, nd in enumerate(self.nodes):
            if i >= len(targets):
                break
            tx, ty = targets[i]
            ax = (tx - nd.x) * k - nd.vx * d
            ay = (ty - nd.y) * k - nd.vy * d
            nd.vx += ax * dt
            nd.vy += ay * dt
            nd.x += nd.vx * dt
            nd.y += nd.vy * dt
            nd.angle += nd.ang_vel * dt

    def draw_nodes(self, surf: pygame.Surface, alpha_mul: float = 1.0):
        for nd in self.nodes:
            a = int(255 * alpha_mul)
            col = (*nd.color, a)
            s = pygame.Surface((4, 4), pygame.SRCALPHA)
            pygame.draw.circle(s, col, (2, 2), 2)
            surf.blit(s, (int(nd.x) - 2, int(nd.y) - 2))

    def jarvis_core(self, surf: pygame.Surface, c1, c2, pulse: float, speaking: bool):
        t = self.t
        p = 1.0 + pulse * 0.22 + (0.14 if speaking else 0.0)
        # outer cage rings
        for i in range(4):
            r = int((110 + i * 18) * p)
            ang = t * (0.38 + i * 0.16) * (-1 if i % 2 == 0 else 1)
            for j in range(0, 360, 6):
                a1 = math.radians(j + ang)
                a2 = math.radians(j + 4 + ang)
                x1 = self.cx + math.cos(a1) * r
                y1 = self.cy + math.sin(a1) * r
                x2 = self.cx + math.cos(a2) * r
                y2 = self.cy + math.sin(a2) * r
                pygame.draw.line(surf, c1, (x1, y1), (x2, y2), 2)
        # waveform ribs
        for k in range(12):
            ang = t * 0.9 + k * math.pi / 6
            r1 = int(70 * p)
            r2 = int(98 * p)
            x1 = self.cx + math.cos(ang) * r1
            y1 = self.cy + math.sin(ang) * r1
            x2 = self.cx + math.cos(ang) * r2
            y2 = self.cy + math.sin(ang) * r2
            pygame.draw.line(surf, c2, (x1, y1), (x2, y2), 1)
        # arc
        pygame.draw.circle(surf, c1, (self.cx, self.cy), int(28 * p), 0)
        pygame.draw.circle(surf, (255, 255, 255), (self.cx, self.cy), int(12 * p), 0)
        # compass ticks
        for deg in range(0, 360, 10):
            a = math.radians(deg + t * 12)
            r1 = int(138 * p)
            r2 = int(146 * p)
            if deg % 30 == 0:
                r2 = int(152 * p)
            x1 = self.cx + math.cos(a) * r1
            y1 = self.cy + math.sin(a) * r1
            x2 = self.cx + math.cos(a) * r2
            y2 = self.cy + math.sin(a) * r2
            pygame.draw.line(surf, c2, (x1, y1), (x2, y2), 1)

    def friday_core(self, surf: pygame.Surface, c1, c2, pulse: float, speaking: bool):
        t = self.t
        p = 1.0 + pulse * 0.26 + (0.16 if speaking else 0.0)
        sz = int(78 * p)
        # hex honeycomb
        for ring in range(4):
            rr = sz + ring * 26
            for i in range(6):
                ang = math.radians(60 * i + t * (28 + ring * 14))
                cxh = self.cx + math.cos(ang) * rr
                cyh = self.cy + math.sin(ang) * rr
                pts = []
                for j in range(6):
                    a = math.radians(60 * j + t * 46)
                    pts.append((cxh + math.cos(a) * 14, cyh + math.sin(a) * 14))
                pygame.draw.polygon(surf, c1, pts, 2)
        # waveform
        for k in range(16):
            ang = k * math.pi / 8
            amp = 10 + 14 * math.sin(t * 4.2 + k * 0.4)
            r1 = int(58 * p)
            r2 = int((58 + amp) * p)
            x1 = self.cx + math.cos(ang) * r1
            y1 = self.cy + math.sin(ang) * r1
            x2 = self.cx + math.cos(ang) * r2
            y2 = self.cy + math.sin(ang) * r2
            pygame.draw.line(surf, c2, (x1, y1), (x2, y2), 1)
        # core
        pygame.draw.circle(surf, c1, (self.cx, self.cy), int(24 * p), 0)
        pygame.draw.circle(surf, (255, 230, 0), (self.cx, self.cy), int(10 * p), 0)
        # brackets
        for i in range(4):
            ang = math.radians(45 + 90 * i + t * 18)
            x1 = self.cx + math.cos(ang) * int(118 * p)
            y1 = self.cy + math.sin(ang) * int(118 * p)
            x2 = self.cx + math.cos(ang) * int(138 * p)
            y2 = self.cy + math.sin(ang) * int(138 * p)
            pygame.draw.line(surf, c2, (x1, y1), (x2, y2), 2)

    def ultron_core(self, surf: pygame.Surface, c1, c2, pulse: float, speaking: bool):
        t = self.t
        p = 1.0 + pulse * 0.34 + (0.22 if speaking else 0.0)
        sz = int(84 * p)
        # neural filaments
        for i in range(24):
            ang = math.radians(i * 15 + t * (16 + random.uniform(-4, 4)))
            lenv = sz + random.randint(-10, 18)
            x1 = self.cx + math.cos(ang) * int(36 * p)
            y1 = self.cy + math.sin(ang) * int(36 * p)
            x2 = self.cx + math.cos(ang) * lenv
            y2 = self.cy + math.sin(ang) * lenv
            pygame.draw.line(surf, c1, (x1, y1), (x2, y2), 2)
            if random.random() < 0.08:
                pygame.draw.circle(surf, c2, (int(x2), int(y2)), 2, 0)
        # optic
        pygame.draw.circle(surf, c1, (self.cx, self.cy), int(18 * p), 0)
        pygame.draw.circle(surf, c2, (self.cx, self.cy), int(8 * p), 0)
        # jagged brackets
        for i in range(6):
            ang = math.radians(30 + 60 * i + t * 26)
            jitter = random.uniform(-8, 8)
            x1 = self.cx + math.cos(ang) * int((126 + jitter) * p)
            y1 = self.cy + math.sin(ang) * int((126 + jitter) * p)
            x2 = self.cx + math.cos(ang) * int((146 + jitter) * p)
            y2 = self.cy + math.sin(ang) * int((146 + jitter) * p)
            pygame.draw.line(surf, c1, (x1, y1), (x2, y2), 3)

    def radar(self, surf: pygame.Surface, c1, c2):
        self.radar_angle += 120.0 * 0.016
        cxr, cyr = 170, self.h - 170
        r = 110
        pygame.draw.circle(surf, c2, (cxr, cyr), r, 1)
        for rr in [36, 72]:
            pygame.draw.circle(surf, c2, (cxr, cyr), rr, 1)
        a = math.radians(self.radar_angle)
        x2 = cxr + math.cos(a) * r
        y2 = cyr + math.sin(a) * r
        pygame.draw.line(surf, c1, (cxr, cyr), (x2, y2), 2)
        for i in range(4):
            pa = random.uniform(0, math.pi * 2)
            pr = random.uniform(10, 95)
            pygame.draw.circle(surf, c1, (int(cxr + math.cos(pa) * pr), int(cyr + math.sin(pa) * pr)), 2, 0)

    def rails(self, surf: pygame.Surface, c1, c2, left: List[str], right: List[str]):
        font = pygame.font.SysFont("consolas", 14)
        font2 = pygame.font.SysFont("consolas", 12)
        # left
        x, y = 40, 120
        for i, s in enumerate(left):
            surf.blit(font2.render(s, True, c1), (x, y + i * 16))
        # right
        x2, y2 = self.w - 320, 120
        for i, s in enumerate(right):
            surf.blit(font2.render(s, True, c1), (x2, y2 + i * 16))

    def console(self, surf: pygame.Surface, c1, c2, lines: List[str]):
        font = pygame.font.SysFont("consolas", 13)
        x, y = 40, self.h - 190
        pygame.draw.line(surf, c2, (x, y - 8), (self.w - 40, y - 8), 1)
        for i, s in enumerate(lines[-12:]):
            surf.blit(font.render(f"> {s}", True, c1), (x, y + i * 16))

    def topbar(self, surf: pygame.Surface, c1, c2, protocol: str, defcon: str):
        font = pygame.font.SysFont("consolas", 12)
        pygame.draw.line(surf, c2, (40, 60), (self.w - 40, 60), 1)
        surf.blit(font.render(f"PROTOCOL: {protocol}", True, c1), (40, 42))
        surf.blit(font.render(f"DEFCON {defcon}", True, c1), (self.w // 2 - 40, 42))
        import datetime
        surf.blit(font.render(datetime.datetime.now().strftime("%H:%M:%S UTC"), True, c1), (self.w - 200, 42))

    def corners(self, surf: pygame.Surface, c1):
        m = 18
        lw = 2
        # TL
        pygame.draw.line(surf, c1, (m, m + 36), (m, m), lw)
        pygame.draw.line(surf, c1, (m, m), (m + 36, m), lw)
        pygame.draw.line(surf, c1, (m + 12, m + 14), (m + 12, m), lw)
        pygame.draw.line(surf, c1, (m + 12, m), (m + 48, m), lw)
        # TR
        pygame.draw.line(surf, c1, (self.w - m, m + 36), (self.w - m, m), lw)
        pygame.draw.line(surf, c1, (self.w - m, m), (self.w - m - 36, m), lw)
        pygame.draw.line(surf, c1, (self.w - m - 12, m + 14), (self.w - m - 12, m), lw)
        pygame.draw.line(surf, c1, (self.w - m - 12, m), (self.w - m - 48, m), lw)
        # BL
        pygame.draw.line(surf, c1, (m, self.h - m - 36), (m, self.h - m), lw)
        pygame.draw.line(surf, c1, (m, self.h - m), (m + 36, self.h - m), lw)
        pygame.draw.line(surf, c1, (m + 12, self.h - m - 14), (m + 12, self.h - m), lw)
        pygame.draw.line(surf, c1, (m + 12, self.h - m), (m + 48, self.h - m), lw)
        # BR
        pygame.draw.line(surf, c1, (self.w - m, self.h - m - 36), (self.w - m, self.h - m), lw)
        pygame.draw.line(surf, c1, (self.w - m, self.h - m), (self.w - m - 36, self.h - m), lw)
        pygame.draw.line(surf, c1, (self.w - m - 12, self.h - m - 14), (self.w - m - 12, self.h - m), lw)
        pygame.draw.line(surf, c1, (self.w - m - 12, self.h - m), (self.w - m - 48, self.h - m), lw)

    def update(self, dt: float):
        self.t += dt
        self.scan += dt * 180.0
