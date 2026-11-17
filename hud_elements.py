"""HUD geometric renderers for all three archetypes."""
from __future__ import annotations

import math
import random
from typing import List, Tuple

import pygame


class Particle:
    def __init__(self, x, y, vx, vy, life, color):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt
        return self.life > 0

    def draw(self, surf):
        alpha = int(255 * (self.life / self.max_life))
        color = (*self.color, alpha)
        s = pygame.Surface((3, 3), pygame.SRCALPHA)
        pygame.draw.circle(s, color, (1, 1), 1)
        surf.blit(s, (int(self.x), int(self.y)))


class HUDRenderer:
    def __init__(self, width, height):
        self.w = width
        self.h = height
        self.cx = width // 2
        self.cy = height // 2
        self.particles = []
        self.t = 0
        self.glitch_offset = 0
        self.shake_x = 0
        self.shake_y = 0

    def clear(self):
        self.particles = [p for p in self.particles if p.life > 0]

    def add_particles(self, count, color):
        for _ in range(count):
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(50, 150)
            self.particles.append(
                Particle(
                    self.cx + math.cos(angle) * 50,
                    self.cy + math.sin(angle) * 50,
                    math.cos(angle) * speed,
                    math.sin(angle) * speed,
                    random.uniform(0.5, 1.0),
                    color,
                )
            )

    def draw_reactor_jarvis(self, surf, colors, pulse, dt):
        t = self.t
        # Concentric counter-rotating rings
        for i in range(5):
            r = 80 + i * 25 + pulse * 10
            angle = t * (0.5 + i * 0.2) * (-1 if i % 2 else 1)
            # Draw ring segments
            for j in range(0, 360, 15):
                a1 = math.radians(j + angle)
                a2 = math.radians(j + 10 + angle)
                x1 = self.cx + math.cos(a1) * r
                y1 = self.cy + math.sin(a1) * r
                x2 = self.cx + math.cos(a2) * r
                y2 = self.cy + math.sin(a2) * r
                pygame.draw.line(surf, colors["primary"], (x1, y1), (x2, y2), 2)
        # Core
        pygame.draw.circle(surf, colors["primary"], (self.cx, self.cy), int(30 + pulse * 15), 0)
        pygame.draw.circle(surf, colors["accent"], (self.cx, self.cy), int(15 + pulse * 8), 0)

    def draw_reactor_friday(self, surf, colors, pulse, dt):
        t = self.t
        # Hexagonal hive
        size = 60 + pulse * 20
        for ring in range(3):
            r = size + ring * 30
            for i in range(6):
                angle = math.radians(60 * i + t * 30 * (ring + 1))
                x = self.cx + math.cos(angle) * r
                y = self.cy + math.sin(angle) * r
                # Draw hexagon
                points = []
                for j in range(6):
                    a = math.radians(60 * j + t * 50)
                    points.append((x + math.cos(a) * 12, y + math.sin(a) * 12))
                pygame.draw.polygon(surf, colors["primary"], points, 2)
        # Core
        pygame.draw.circle(surf, colors["accent"], (self.cx, self.cy), int(25 + pulse * 12), 0)

    def draw_reactor_ultron(self, surf, colors, pulse, dt):
        t = self.t
        # Fractured optic
        size = 70 + pulse * 25
        # Jagged segments
        for i in range(8):
            angle = math.radians(45 * i + t * 20)
            if random.random() < 0.1:
                angle += math.radians(random.randint(-20, 20))
            x1 = self.cx + math.cos(angle) * 40
            y1 = self.cy + math.sin(angle) * 40
            x2 = self.cx + math.cos(angle) * size
            y2 = self.cy + math.sin(angle) * size
            pygame.draw.line(surf, colors["primary"], (x1, y1), (x2, y2), 3)
        # Glowing fissure
        pygame.draw.circle(surf, colors["primary"], (self.cx, self.cy), int(20 + pulse * 10), 0)
        if pulse > 0.7:
            pygame.draw.circle(surf, colors["accent"], (self.cx, self.cy), int(10 + pulse * 5), 0)

    def draw_radar(self, surf, colors):
        r = 100
        pygame.draw.circle(surf, colors["dim"], (150, 150), r, 1)
        angle = self.t * 60
        x = 150 + math.cos(math.radians(angle)) * r
        y = 150 + math.sin(math.radians(angle)) * r
        pygame.draw.line(surf, colors["primary"], (150, 150), (x, y), 2)
        # Pings
        for i in range(3):
            px = 150 + random.randint(-60, 60)
            py = 150 + random.randint(-60, 60)
            pygame.draw.circle(surf, colors["accent"], (px, py), 3, 0)

    def draw_telemetry(self, surf, colors):
        y = self.h - 150
        for i, label in enumerate(["CPU", "RAM", "GPU", "PWR"]):
            x = 50 + i * 80
            val = 40 + random.randint(0, 30)
            pygame.draw.rect(surf, colors["dim"], (x, y, 60, 8), 1)
            pygame.draw.rect(surf, colors["primary"], (x, y, int(60 * val / 100), 8), 0)
            font = pygame.font.Font(None, 16)
            surf.blit(font.render(label, True, colors["primary"]), (x, y + 12))

    def draw_log(self, surf, colors, log_lines):
        x, y = self.w - 350, 50
        font = pygame.font.Font(None, 18)
        for i, line in enumerate(log_lines[-15:]):
            surf.blit(font.render(f"> {line}", True, colors["primary"]), (x, y + i * 20))

    def draw_banner(self, surf, colors, text):
        if not text:
            return
        font = pygame.font.Font(None, 48)
        text_surf = font.render(text, True, colors["accent"])
        rect = text_surf.get_rect(center=(self.cx, 80))
        # Glow
        for offset in [2, 1]:
            glow = font.render(text, True, colors["primary"])
            glow_rect = glow.get_rect(center=(self.cx + offset, 80))
            surf.blit(glow, glow_rect)
        surf.blit(text_surf, rect)

    def draw_glitch(self, surf):
        if self.glitch_offset == 0:
            return
        # Simple glitch effect
        pass

    def update(self, dt):
        self.t += dt
        for p in self.particles:
            p.update(dt)
        self.clear()
