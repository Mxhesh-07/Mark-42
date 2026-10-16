"""hologram.py — generic holographic 3D projector for J.A.R.V.I.S.

A real native OpenGL window (pygame + PyOpenGL). It renders ANY object supplied
as a "model" (a named list of primitive parts) as a glowing hologram that can be
rotated, exploded and inspected PART BY PART.

    python hologram.py --name car            # from the built-in object library
    python hologram.py --model path.json     # from a model file
    python hologram.py --prompt "a red car"  # invent one with the AI builder

Ask J.A.R.V.I.S. "show me a <thing> in hologram" and it resolves the object,
writes a model file and drives this window.

Model schema
------------
{
  "name": "Car",
  "kind": "vehicle",
  "explode": 3.0,                       # optional
  "parts": [
    {"name": "Body", "shape": "box", "size": [4.4,0.9,1.9], "pos": [0,0.9,0],
     "color": "cyan", "hot": false, "dir": [0,1,0]},

    shape: "box"     size=[sx,sy,sz]
           "sphere"  size=[rx,ry,rz]
           "cyl"     size=[r,h]   axis="x|y|z"
           "cone"    size=[r,h]   axis="x|y|z"
           "pyramid" size=[sx,sy,sz]
           "torus"   size=[R,r]   axis="x|y|z"
  ]
}
"""
import os
import sys
import json
import math
import time
import subprocess
from pathlib import Path

from OpenGL.GL import *  # noqa: F401,F403

BASE_DIR   = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
MODELS_DIR = BASE_DIR / "hologram_models"
CMD_FILE   = CONFIG_DIR / "hologram_cmd.json"
PID_FILE   = CONFIG_DIR / "hologram.pid"

# ---- OpenGL colours (0..1) ------------------------------------------------
COLORS = {
    "cyan":  (0.00, 0.65, 0.95),
    "amber": (1.00, 0.50, 0.00),
    "white": (0.85, 1.00, 1.00),
    "red":   (1.00, 0.22, 0.15),
    "green": (0.20, 1.00, 0.45),
    "blue":  (0.25, 0.50, 1.00),
    "gray":  (0.62, 0.72, 0.82),
    "gold":  (1.00, 0.80, 0.20),
    "violet":(0.70, 0.35, 1.00),
}
HOT = (0.85, 1.00, 1.00)

# ---- HUD colours (pygame RGB) --------------------------------------------
H_CYAN, H_AMBER, H_DIM, H_WHITE, H_BORDER = \
    (64, 242, 255), (255, 150, 30), (70, 120, 140), (215, 245, 255), (0, 150, 190)


def _norm(v):
    L = math.sqrt(sum(c * c for c in v)) or 1.0
    return (v[0] / L, v[1] / L, v[2] / L)


# --------------------------------------------------------------------------
#  Primitive geometry (immediate-mode GL)
# --------------------------------------------------------------------------
def _box(sx, sy, sz):
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    faces = [
        ((-hx, -hy,  hz), ( hx, -hy,  hz), ( hx,  hy,  hz), (-hx,  hy,  hz)),
        (( hx, -hy, -hz), (-hx, -hy, -hz), (-hx,  hy, -hz), ( hx,  hy, -hz)),
        (( hx, -hy,  hz), ( hx, -hy, -hz), ( hx,  hy, -hz), ( hx,  hy,  hz)),
        ((-hx, -hy, -hz), (-hx, -hy,  hz), (-hx,  hy,  hz), (-hx,  hy, -hz)),
        ((-hx,  hy,  hz), ( hx,  hy,  hz), ( hx,  hy, -hz), (-hx,  hy, -hz)),
        ((-hx, -hy, -hz), ( hx, -hy, -hz), ( hx, -hy,  hz), (-hx, -hy,  hz)),
    ]
    glBegin(GL_QUADS)
    for f in faces:
        for v in f:
            glVertex3f(*v)
    glEnd()


def _sphere(rx, ry, rz, seg=20, rings=12):
    for i in range(rings):
        lat0 = math.pi * (-0.5 + i / rings)
        lat1 = math.pi * (-0.5 + (i + 1) / rings)
        y0, r0 = math.sin(lat0), math.cos(lat0)
        y1, r1 = math.sin(lat1), math.cos(lat1)
        glBegin(GL_QUAD_STRIP)
        for j in range(seg + 1):
            lng = 2 * math.pi * j / seg
            cx, cz = math.cos(lng), math.sin(lng)
            glVertex3f(rx * cx * r0, ry * y0, rz * cz * r0)
            glVertex3f(rx * cx * r1, ry * y1, rz * cz * r1)
        glEnd()


def _cyl(r, h, axis="y", seg=22):
    hh = h * 0.5
    glBegin(GL_QUAD_STRIP)
    for j in range(seg + 1):
        a = 2 * math.pi * j / seg
        cx, cz = math.cos(a) * r, math.sin(a) * r
        if axis == "y":
            glVertex3f(cx, -hh, cz); glVertex3f(cx, hh, cz)
        elif axis == "z":
            glVertex3f(cx, cz, -hh); glVertex3f(cx, cz, hh)
        else:
            glVertex3f(-hh, cx, cz); glVertex3f(hh, cx, cz)
    glEnd()
    for sgn in (-1, 1):
        glBegin(GL_TRIANGLE_FAN)
        if axis == "y":
            glVertex3f(0, sgn * hh, 0)
        elif axis == "z":
            glVertex3f(0, 0, sgn * hh)
        else:
            glVertex3f(sgn * hh, 0, 0)
        for j in range(seg + 1):
            a = 2 * math.pi * j / seg
            cx, cz = math.cos(a) * r, math.sin(a) * r
            if axis == "y":
                glVertex3f(cx, sgn * hh, cz)
            elif axis == "z":
                glVertex3f(cx, cz, sgn * hh)
            else:
                glVertex3f(sgn * hh, cx, cz)
        glEnd()


def _cone(r, h, axis="y", seg=22):
    hh = h * 0.5
    glBegin(GL_TRIANGLE_FAN)
    if axis == "y":
        glVertex3f(0, hh, 0)
        for j in range(seg + 1):
            a = 2 * math.pi * j / seg
            glVertex3f(math.cos(a) * r, -hh, math.sin(a) * r)
    elif axis == "z":
        glVertex3f(0, 0, hh)
        for j in range(seg + 1):
            a = 2 * math.pi * j / seg
            glVertex3f(math.cos(a) * r, math.sin(a) * r, -hh)
    else:
        glVertex3f(hh, 0, 0)
        for j in range(seg + 1):
            a = 2 * math.pi * j / seg
            glVertex3f(-hh, math.cos(a) * r, math.sin(a) * r)
    glEnd()
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(*((0, -hh, 0) if axis == "y" else (0, 0, -hh) if axis == "z" else (-hh, 0, 0)))
    for j in range(seg + 1):
        a = 2 * math.pi * j / seg
        cx, cz = math.cos(a) * r, math.sin(a) * r
        if axis == "y":
            glVertex3f(cx, -hh, cz)
        elif axis == "z":
            glVertex3f(cx, cz, -hh)
        else:
            glVertex3f(-hh, cx, cz)
    glEnd()


def _pyramid(sx, sy, sz):
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    base = [(-hx, -hy, hz), (hx, -hy, hz), (hx, -hy, -hz), (-hx, -hy, -hz)]
    apex = (0, hy, 0)
    glBegin(GL_QUADS)
    for v in base:
        glVertex3f(*v)
    glEnd()
    glBegin(GL_TRIANGLES)
    for i in range(4):
        a = base[i]
        b = base[(i + 1) % 4]
        glVertex3f(*a); glVertex3f(*b); glVertex3f(*apex)
    glEnd()


def _torus(R, r, axis="y", seg=26, side=12):
    def pt(u, v):
        X = (R + r * math.cos(v)) * math.cos(u)
        Y = (R + r * math.cos(v)) * math.sin(u)
        Z = r * math.sin(v)
        if axis == "z":
            return (X, Y, Z)
        if axis == "y":
            return (X, Z, Y)
        return (Z, Y, X)
    for i in range(seg):
        u0 = 2 * math.pi * i / seg
        u1 = 2 * math.pi * (i + 1) / seg
        glBegin(GL_QUAD_STRIP)
        for j in range(side + 1):
            v = 2 * math.pi * j / side
            glVertex3f(*pt(u0, v))
            glVertex3f(*pt(u1, v))
        glEnd()


def _extents(part):
    s = part["size"]
    sh = part["shape"]
    if sh in ("box", "pyramid", "sphere"):
        return (s[0] / 2, s[1] / 2, s[2] / 2)
    if sh in ("cyl", "cone"):
        r, h = s[0], s[1] / 2
        ax = part.get("axis", "y")
        return (r, h, r) if ax == "y" else (r, r, h) if ax == "z" else (h, r, r)
    if sh == "torus":
        R, r = s[0], s[1]
        ax = part.get("axis", "y")
        return (R + r, R + r, r) if ax == "z" else (R + r, r, R + r)
    return (0.5, 0.5, 0.5)


# --------------------------------------------------------------------------
#  Viewer
# --------------------------------------------------------------------------
class Viewer:
    def __init__(self, model, autorotate=True, start_exploded=False):
        import pygame
        self.pygame = pygame
        pygame.init()
        pygame.font.init()
        try:
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4)
        except Exception:
            pass
        self.w, self.h = 1180, 780
        self._set_mode()
        pygame.display.set_caption("J.A.R.V.I.S  —  Holographic Projector")

        self.yaw, self.pitch, self.zoom = -26.0, 8.0, 1.0
        self.autorotate = autorotate
        self.labels = True
        self.pulse = 0.0
        self.selected = 0
        self.explode = 1.0
        self.explode_target = 1.0 if start_exploded else 0.0

        self.hud = None
        self.hud_tex = None
        self._fonts = {}
        self.clock = pygame.time.Clock()
        self.dragging = False
        self.mouse_moved = 0
        self._pick_req = None
        self._cmd_check = 0.0
        self.running = True

        self.parts = []
        self.model = {"name": "Object", "parts": []}
        self.offset = (0.0, 0.0, 0.0)
        self.radius = 8.0
        self.load(model, animate=False)
        self._write_pid()

    # ---- window / context ------------------------------------------------
    def _set_mode(self):
        import pygame
        pygame.display.set_mode((self.w, self.h),
                                pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE)
        glViewport(0, 0, self.w, self.h)
        glClearColor(0.0, 0.012, 0.022, 1.0)

    def _write_pid(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            PID_FILE.write_text(str(os.getpid()))
        except Exception:
            pass

    def _clear_pid(self):
        try:
            if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except Exception:
            pass

    # ---- model loading ---------------------------------------------------
    def load(self, model, animate=True):
        self.model = model or {"name": "Object", "parts": []}
        self.parts = list(self.model.get("parts", [])) or [
            {"name": "Cube", "shape": "box", "size": [2, 2, 2], "pos": [0, 0, 0]}
        ]
        for p in self.parts:
            p.setdefault("color", "cyan")
            p.setdefault("hot", False)
            p.setdefault("axis", "y")
            if "dir" not in p:
                p["dir"] = _norm(p.get("pos", [0, 1, 0]))
        mn = [1e9, 1e9, 1e9]
        mx = [-1e9, -1e9, -1e9]
        for p in self.parts:
            ex, ey, ez = _extents(p)
            pos = p.get("pos", [0, 0, 0])
            for k, e in enumerate((ex, ey, ez)):
                mn[k] = min(mn[k], pos[k] - e)
                mx[k] = max(mx[k], pos[k] + e)
        cen = [(mn[k] + mx[k]) * 0.5 for k in range(3)]
        self.offset = (-cen[0], -cen[1], -cen[2])
        self.radius = max(2.0, max((mx[k] - mn[k]) for k in range(3)) * 0.5
                          + max(abs(mn[1]), abs(mx[1])) * 0.2)
        base = max(3.0, float(self.model.get("explode", 0)) or 0.0)
        self._base_explode = base or self.radius * 0.85
        self.selected = 0
        if animate:
            self.explode = 1.0
            self.explode_target = 0.0
        else:
            self.explode = 0.0
        return self.model.get("name", "Object")

    def _geom(self, part):
        glPushMatrix()
        px, py, pz = part.get("pos", [0, 0, 0])
        dx, dy, dz = part["dir"]
        off = self.explode * self._base_explode
        glTranslatef(px + dx * off + self.offset[0],
                     py + dy * off + self.offset[1],
                     pz + dz * off + self.offset[2])
        if "rot" in part:
            glRotatef(part["rot"][0], 1, 0, 0)
            glRotatef(part["rot"][1], 0, 1, 0)
            glRotatef(part["rot"][2], 0, 0, 1)
        sh = part["shape"]
        s = part["size"]
        ax = part.get("axis", "y")
        if sh == "box":
            _box(*s)
        elif sh == "sphere":
            _sphere(*s)
        elif sh == "cyl":
            _cyl(s[0], s[1], ax)
        elif sh == "cone":
            _cone(s[0], s[1], ax)
        elif sh == "pyramid":
            _pyramid(*s)
        elif sh == "torus":
            _torus(s[0], s[1], ax)
        glPopMatrix()

    def _camera(self):
        from OpenGL.GLU import gluPerspective, gluLookAt
        glViewport(0, 0, self.w, self.h)
        glMatrixMode(GL_PROJECTION); glLoadIdentity()
        gluPerspective(45.0, self.w / max(1, self.h), 0.1, 800.0)
        glMatrixMode(GL_MODELVIEW); glLoadIdentity()
        dist = (self.radius * 3.1 + self.explode * self._base_explode * 0.9) * self.zoom
        gluLookAt(0.0, self.radius * 0.15, dist, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)
        glRotatef(self.pitch, 1, 0, 0)
        glRotatef(self.yaw, 0, 1, 0)

    def _draw_grid(self):
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        y = -self.radius * 1.05
        ext = int(self.radius * 1.6) + 4
        glLineWidth(1.0)
        glBegin(GL_LINES)
        for i in range(-ext, ext + 1):
            glColor4f(0.0, 0.8, 1.0, 0.5) if i == 0 else glColor4f(0.0, 0.5, 0.72, 0.13)
            glVertex3f(i * 1.5, y, -ext * 1.5); glVertex3f(i * 1.5, y, ext * 1.5)
            glVertex3f(-ext * 1.5, y, i * 1.5); glVertex3f(ext * 1.5, y, i * 1.5)
        glEnd()

    def _color_of(self, i, p, alpha_scale=1.0):
        if p.get("hot"):
            return HOT
        return COLORS.get(p.get("color", "cyan"), COLORS["cyan"])

    def _render_scene(self):
        glEnable(GL_DEPTH_TEST)
        glDepthMask(False)
        glEnable(GL_BLEND)
        glDisable(GL_CULL_FACE)

        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        for i, p in enumerate(self.parts):
            c = self._color_of(i, p)
            if p.get("hot"):
                a = 0.55
            elif i == self.selected:
                c, a = COLORS["amber"], 0.45 + 0.35 * self.pulse
            else:
                a = 0.13
            glColor4f(c[0], c[1], c[2], a)
            self._geom(p)

        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        glLineWidth(1.6)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        for i, p in enumerate(self.parts):
            c = self._color_of(i, p)
            if p.get("hot"):
                a = 0.95
            elif i == self.selected:
                c, a = COLORS["amber"], 1.0
            else:
                a = 0.5
            glColor4f(c[0], c[1], c[2], a)
            self._geom(p)

        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        glDepthMask(True)

    def _do_pick(self, mx, my):
        glClearColor(0, 0, 0, 1)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glDisable(GL_BLEND)
        glDepthMask(True)
        glEnable(GL_DEPTH_TEST)
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        self._camera()
        for i, p in enumerate(self.parts):
            c = i + 1
            glColor3ub(c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)
            self._geom(p)
        glFlush()
        x = max(0, min(self.w - 1, int(mx)))
        y = max(0, min(self.h - 1, int(self.h - my - 1)))
        buf = bytes(glReadPixels(x, y, 1, 1, GL_RGB, GL_UNSIGNED_BYTE))
        val = buf[0] | (buf[1] << 8) | (buf[2] << 16)
        return (val - 1) if val > 0 else -1

    # ---- HUD -------------------------------------------------------------
    def _font(self, size, bold=False):
        import pygame
        key = (size, bold)
        if key not in self._fonts:
            try:
                self._fonts[key] = pygame.font.SysFont("consolas", size, bold=bold)
            except Exception:
                self._fonts[key] = pygame.font.Font(None, size)
        return self._fonts[key]

    def _text(self, s, size, color, x, y, anchor="tl", bold=False):
        img = self._font(size, bold).render(s, True, color)
        amap = {"tl": "topleft", "tr": "topright", "tc": "midtop", "center": "center"}
        self.hud.blit(img, img.get_rect(**{amap.get(anchor, anchor): (x, y)}))

    def _build_hud(self):
        import pygame
        if self.hud is None or self.hud.get_size() != (self.w, self.h):
            self.hud = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        hud = self.hud
        hud.fill((0, 0, 0, 0))
        W, H = self.w, self.h
        name = self.model.get("name", "Object")

        def panel(rect):
            pygame.draw.rect(hud, (0, 12, 18, 205), rect)
            pygame.draw.rect(hud, H_BORDER, rect, 1)

        pygame.draw.rect(hud, (0, 10, 16, 235), (0, 0, W, 56))
        pygame.draw.line(hud, H_BORDER, (0, 56), (W, 56), 1)
        self._text(name.upper(), 20, H_CYAN, 18, 8, bold=True)
        self._text(f"HOLOGRAPHIC  PROJECTION   *   {self.model.get('kind','object')}", 12, H_DIM, 20, 34)
        self._text(time.strftime("%H:%M:%S"), 20, H_CYAN, W - 18, 14, anchor="tr", bold=True)

        lx, ly, lw, lh = 16, 74, 250, H - 150
        panel((lx, ly, lw, lh))
        self._text("PARTS", 14, H_CYAN, lx + 12, ly + 8, bold=True)
        self._text(f"{len(self.parts)} parts", 11, H_DIM, lx + lw - 12, ly + 11, anchor="tr")
        row_h, head = 21, ly + 34
        max_rows = max(1, (lh - 44) // row_h)
        top = self.selected - max_rows + 1 if self.selected >= max_rows else 0
        for r in range(max_rows):
            i = top + r
            if i >= len(self.parts):
                break
            p = self.parts[i]
            y = head + r * row_h
            sel = (i == self.selected)
            if sel:
                pygame.draw.rect(hud, (60, 34, 0, 210), (lx + 6, y - 2, lw - 12, row_h - 2))
                pygame.draw.rect(hud, H_AMBER, (lx + 6, y - 2, lw - 12, row_h - 2), 1)
            col = H_AMBER if sel else (H_WHITE if p.get("hot") else H_CYAN)
            self._text(f"{i+1:02d}", 12, H_DIM if not sel else H_AMBER, lx + 12, y)
            dot = "*" if p.get("hot") else ("[]" if p["shape"] == "box" else "(o)" if p["shape"] == "sphere"
                                            else "||" if p["shape"] in ("cyl", "cone") else "^" if p["shape"] == "pyramid" else "(O)")
            self._text(f"{dot} {p['name']}", 13, col, lx + 40, y)

        sw, sx = 236, W - 252
        panel((sx, 74, sw, 150))
        self._text("STATUS", 14, H_CYAN, sx + 12, 82, bold=True)
        rows = [("EXPLODE", f"{int(round(self.explode*100))}%"),
                ("ROTATION", "AUTO" if self.autorotate else "MANUAL"),
                ("SELECTED", self.parts[self.selected]["name"]),
                ("PARTS", str(len(self.parts))),
                ("FPS", f"{int(self.clock.get_fps())}")]
        for k, (a, b) in enumerate(rows):
            yy = 108 + k * 22
            self._text(a, 12, H_DIM, sx + 12, yy)
            self._text(b, 13, H_AMBER if a == "SELECTED" else H_WHITE, sx + sw - 12, yy, anchor="tr")

        pygame.draw.rect(hud, (0, 10, 16, 235), (0, H - 52, W, 52))
        pygame.draw.line(hud, H_BORDER, (0, H - 52), (W, H - 52), 1)
        self._text("DRAG rotate  |  WHEEL zoom  |  CLICK select  |  E explode  |  "
                   "SPACE auto-rotate  |  UP/DOWN parts  |  R reset  |  ESC close",
                   12, H_DIM, W // 2, H - 34, anchor="center")

        for yy in range(0, H, 3):
            pygame.draw.line(hud, (0, 0, 0, 26), (0, yy), (W, yy))

    def _blit_hud(self):
        import pygame
        data = pygame.image.tostring(self.hud, "RGBA", True)
        if not self.hud_tex:
            self.hud_tex = glGenTextures(1)
        glDisable(GL_DEPTH_TEST)
        glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
        glOrtho(0, self.w, self.h, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
        glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, self.hud_tex)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, self.w, self.h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glColor4f(1, 1, 1, 1)
        glBegin(GL_QUADS)
        glTexCoord2f(0, 1); glVertex2f(0, 0)
        glTexCoord2f(1, 1); glVertex2f(self.w, 0)
        glTexCoord2f(1, 0); glVertex2f(self.w, self.h)
        glTexCoord2f(0, 0); glVertex2f(0, self.h)
        glEnd()
        glDisable(GL_TEXTURE_2D)
        glMatrixMode(GL_PROJECTION); glPopMatrix()
        glMatrixMode(GL_MODELVIEW); glPopMatrix()
        glEnable(GL_DEPTH_TEST)

    # ---- commands --------------------------------------------------------
    def _resolve(self, cmd):
        """Return a model dict from a command's model/name/prompt."""
        if cmd.get("model"):
            try:
                return json.loads(Path(cmd["model"]).read_text(encoding="utf-8"))
            except Exception as e:
                print("[hologram] model file error:", e)
        if cmd.get("name"):
            try:
                import hologram_models
                return hologram_models.get_model(cmd["name"])
            except Exception as e:
                print("[hologram] library error:", e)
        if cmd.get("prompt"):
            try:
                import hologram_gen
                m = hologram_gen.generate(cmd["prompt"])
                if m:
                    return m
            except Exception as e:
                print("[hologram] gen error:", e)
        return None

    def _apply_command(self, cmd):
        act = str(cmd.get("action", "")).lower()
        if act in ("load", "show", "display"):
            m = self._resolve(cmd)
            if m:
                self.load(m, animate=True)
        elif act in ("explode", "explode_view"):
            self.explode_target = 1.0
        elif act in ("assemble", "reassemble"):
            self.explode_target = 0.0
        elif act == "toggle_explode":
            self.explode_target = 0.0 if self.explode_target > 0.5 else 1.0
        elif act in ("show_part", "select", "focus"):
            n = str(cmd.get("part", "")).strip().lower()
            for i, p in enumerate(self.parts):
                if p["name"].lower() == n or n in p["name"].lower():
                    self.selected = i
                    break
            if cmd.get("explode", act != "select"):
                self.explode_target = 1.0
        elif act == "autorotate":
            self.autorotate = bool(cmd.get("value", True))
        elif act == "reset":
            self.yaw, self.pitch, self.zoom = -26.0, 8.0, 1.0
            self.explode_target = 0.0
            self.selected = 0
        elif act == "quit":
            self.running = False
        if "explode" in cmd and act in ("load", "show", "display"):
            self.explode_target = 1.0 if cmd["explode"] else 0.0
        if cmd.get("autorotate") is not None and act == "load":
            self.autorotate = bool(cmd["autorotate"])

    def _poll_commands(self):
        try:
            if CMD_FILE.exists():
                self._apply_command(json.loads(CMD_FILE.read_text(encoding="utf-8")))
                CMD_FILE.unlink()
        except Exception:
            pass

    # ---- main loop -------------------------------------------------------
    def run(self):
        import pygame
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.VIDEORESIZE:
                    self.w, self.h = max(640, event.w), max(480, event.h)
                    self._set_mode()
                elif event.type == pygame.KEYDOWN:
                    self._on_key(event)
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self.dragging = True; self.mouse_moved = 0
                    elif event.button == 4:
                        self.zoom = max(0.5, self.zoom - 0.08)
                    elif event.button == 5:
                        self.zoom = min(2.6, self.zoom + 0.08)
                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        self.dragging = False
                        if self.mouse_moved < 6:
                            self._pick_req = event.pos
                elif event.type == pygame.MOUSEMOTION:
                    if self.dragging:
                        dx, dy = event.rel
                        self.yaw = (self.yaw + dx * 0.45) % 360
                        self.pitch = max(-85, min(85, self.pitch + dy * 0.35))
                        self.mouse_moved += abs(dx) + abs(dy)
                elif event.type == pygame.MOUSEWHEEL:
                    self.zoom = max(0.5, min(2.6, self.zoom - event.y * 0.08))

            now = time.time()
            if now - self._cmd_check > 0.25:
                self._cmd_check = now
                self._poll_commands()

            if self.autorotate and not self.dragging:
                self.yaw = (self.yaw + 0.35) % 360
            self.explode += (self.explode_target - self.explode) * 0.09
            self.pulse = 0.5 + 0.5 * math.sin(now * 5.0)

            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            if self._pick_req:
                mx, my = self._pick_req
                self._pick_req = None
                idx = self._do_pick(mx, my)
                if idx >= 0:
                    self.selected = idx
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

            self._camera()
            self._draw_grid()
            self._render_scene()
            self._build_hud()
            self._blit_hud()
            pygame.display.flip()
            self.clock.tick(60)

        self._clear_pid()
        pygame.quit()

    def _on_key(self, e):
        import pygame
        k = e.key
        if k in (pygame.K_ESCAPE, pygame.K_q):
            self.running = False
        elif k == pygame.K_e:
            self.explode_target = 0.0 if self.explode_target > 0.5 else 1.0
        elif k == pygame.K_SPACE:
            self.autorotate = not self.autorotate
        elif k == pygame.K_r:
            self.yaw, self.pitch, self.zoom = -26.0, 8.0, 1.0
            self.explode_target = 0.0
            self.selected = 0
        elif k == pygame.K_l:
            self.labels = not self.labels
        elif k in (pygame.K_DOWN, pygame.K_n):
            self.selected = (self.selected + 1) % len(self.parts)
        elif k in (pygame.K_UP, pygame.K_p):
            self.selected = (self.selected - 1) % len(self.parts)


# --------------------------------------------------------------------------
#  J.A.R.V.I.S. control helpers
# --------------------------------------------------------------------------
def is_running():
    if not PID_FILE.exists():
        return False
    try:
        import psutil
        return psutil.pid_exists(int(PID_FILE.read_text().strip()))
    except Exception:
        return False


def send_command(cmd: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CMD_FILE.write_text(json.dumps(cmd), encoding="utf-8")


def launch(model_path=None, name=None, prompt=None, part=None, explode=None, autorotate=None):
    """Open the projector (or command the running one). Returns a status string."""
    if is_running():
        cmd = {}
        if model_path:
            cmd["action"] = "load"; cmd["model"] = str(model_path)
        elif name:
            cmd["action"] = "load"; cmd["name"] = name
        elif prompt:
            cmd["action"] = "load"; cmd["prompt"] = prompt
        if part:
            cmd["action"] = "show_part"; cmd["part"] = part
        if explode is not None:
            cmd["explode"] = explode
        if autorotate is not None:
            cmd["autorotate"] = autorotate
        if cmd:
            send_command(cmd)
        return "commanded"
    args = [sys.executable, str(Path(__file__).resolve())]
    if model_path:
        args += ["--model", str(model_path)]
    elif name:
        args += ["--name", str(name)]
    elif prompt:
        args += ["--prompt", str(prompt)]
    if explode:
        args.append("--explode")
    if autorotate is False:
        args.append("--no-rotate")
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008  # DETACHED_PROCESS
    subprocess.Popen(args, cwd=str(BASE_DIR), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return "launched"


def _load_for_cli(name=None, model=None, prompt=None):
    if model:
        return json.loads(Path(model).read_text(encoding="utf-8"))
    if name:
        import hologram_models
        return hologram_models.get_model(name)
    if prompt:
        import hologram_gen
        m = hologram_gen.generate(prompt)
        if m:
            return m
    return {"name": "Cube", "parts": [{"name": "Cube", "shape": "box", "size": [2, 2, 2], "pos": [0, 0, 0]}]}


def main():
    name = model = prompt = None
    exploded, rotate = False, True
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--name", "--model", "--prompt") and i + 1 < len(argv):
            if a == "--name":
                name = argv[i + 1]
            elif a == "--model":
                model = argv[i + 1]
            else:
                prompt = argv[i + 1]
            i += 2
            continue
        if a == "--explode":
            exploded = True
        elif a == "--no-rotate":
            rotate = False
        i += 1
    Viewer(_load_for_cli(name, model, prompt), autorotate=rotate, start_exploded=exploded).run()


if __name__ == "__main__":
    main()
