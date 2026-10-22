import os, json, time, math, random, threading
import queue
import tkinter as tk
from collections import deque
from PIL import Image, ImageTk, ImageDraw
import sys
from pathlib import Path
import psutil
from memory.memory_manager import load_memory

try:
    from ui.theme import font as _font
except Exception:  # pragma: no cover - frozen/standalone fallback
    def _font(size=10, *, bold=False):
        return ("Courier", size, "bold") if bold else ("Courier", size)


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    # ui/ is a package now (so ui.confirm can live beside the window code), which
    # puts this file one level below the project root.
    return Path(__file__).resolve().parent.parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

SYSTEM_NAME = "J.A.R.V.I.S"
MODEL_BADGE = "MARK XXX"

C_BG     = "#000000"
C_PRI    = "#00d4ff"
C_MID    = "#007a99"
C_DIM    = "#003344"
C_DIMMER = "#001520"
C_ACC    = "#ff6600"
C_ACC2   = "#ffcc00"
C_TEXT   = "#8ffcff"
C_PANEL  = "#010c10"
C_GREEN  = "#00ff88"
C_RED    = "#ff3333"


_ACTIVE_UI = None
THINK_MAX_LINES = 800


def jarvis_think(kind: str, text: str) -> None:
    """Global, thread-safe hook that routes an event to the THINKING pane.

    Safe to call from any thread, and from modules that must not import the
    UI directly (agents, monitors). Silently does nothing if the UI is not up.
    """
    ui = _ACTIVE_UI
    if ui is not None:
        try:
            ui.jarvis_think(kind, text)
        except Exception:
            pass


class JarvisUI:
    _recording = False

    @classmethod
    def set_recording(cls, on: bool, reason: str = ""):
        cls._recording = bool(on)
        try:
            from agent import audit

            audit.record("recording_state", enabled=cls._recording, detail=reason)
        except Exception:
            pass

    @classmethod
    def recording_indicator(cls):
        try:
            from agent import recording

            ind = recording.indicator()
            ind["recording"] = cls._recording
            return ind
        except Exception:
            return {"recording": cls._recording, "consented": False, "visible": True}
    def __init__(self, face_path, size=None):
        global _ACTIVE_UI
        _ACTIVE_UI = self
        # Producer threads only touch this queue; the Tk thread drains it.
        # (Calling root.after() from a worker thread can block forever if
        # no event loop is running, so never do that.)
        self._think_q = queue.Queue()

        # T3.21: DPI awareness must be set before the first Tk window exists.
        try:
            from ui.layout import dpi_awareness, apply_window
            dpi_awareness()
        except Exception:
            apply_window = None

        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S — MARK XXX")
        self.root.resizable(False, False)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 984)
        H  = min(sh, 816)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.root.configure(bg=C_BG)

        # T3.18: restore a saved size/position, clamped to this desktop.
        if apply_window is not None:
            try:
                apply_window(self.root, sw, sh)
                geo = self.root.winfo_geometry()
                if "x" in geo:
                    size, _, pos = geo.partition("+")
                    w_txt, _, h_txt = size.partition("x")
                    if w_txt.isdigit() and h_txt.isdigit():
                        W, H = int(w_txt), int(h_txt)
            except Exception:
                pass

        self.W = W
        self.H = H

        self.FACE_SZ = min(int(H * 0.54), 400)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.13) + self.FACE_SZ // 2

        self.speaking     = False
        self.mic_level    = 0.0
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.tick         = 0
        self.scan_angle   = 0.0
        self.scan2_angle  = 180.0
        self.rings_spin   = [0.0, 120.0, 240.0]
        self.pulse_r      = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text  = "INITIALISING"
        self.status_blink = True
        self._stream_buf  = ""

        self.typing_queue = deque()
        self.is_typing    = False
        self.agent_states = {
        "Planner": "IDLE",
        "Memory": "ACTIVE",
        "Browser": "IDLE",
        "Executor": "IDLE"
    }

        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._load_face(face_path)

        self.bg = tk.Canvas(self.root, width=W, height=H,
                            bg=C_BG, highlightthickness=0)
        self.bg.place(x=0, y=0)
        self.create_dashboard_panels()

        try:
            from ui.layout_spec import Metrics
            self.metrics = Metrics.from_size(W, H)
        except Exception:
            self.metrics = None

        LW     = int(W * 0.72)
        LH     = 138
        GAP    = 10
        LOG_W  = int(LW * 0.52)
        THINK_W = LW - LOG_W - GAP
        LX     = (W - LW) // 2
        LY     = H - LH - 36
        if self.metrics is not None:
            LW, LH, GAP = (self.metrics.content_width, self.metrics.log_height,
                           self.metrics.gap)
            LOG_W, THINK_W = self.metrics.log_width, self.metrics.think_width
            LX, LY = self.metrics.left_x, self.metrics.panes_y

        self.log_frame = tk.Frame(self.root, bg=C_PANEL,
                                  highlightbackground=C_MID,
                                  highlightthickness=1)
        self.log_frame.place(x=LX, y=LY, width=LOG_W, height=LH)
        self.log_text = tk.Text(self.log_frame, fg=C_TEXT, bg=C_PANEL,
                                insertbackground=C_TEXT, borderwidth=0,
                                wrap="word", font=_font(10), padx=10, pady=6)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self.log_text.tag_config("you", foreground="#e8e8e8")
        self.log_text.tag_config("ai",  foreground=C_PRI)
        self.log_text.tag_config("sys", foreground=C_ACC2)
        # T3.28: logs are selectable and copyable even while read-only.
        try:
            from ui.widgets import enable_copy
            enable_copy(self.log_text)
        except Exception:
            pass

        # ---- THINKING pane: steps by default, raw detail on demand ----
        self.think_raw = False
        self.think_frame = tk.Frame(self.root, bg=C_PANEL,
                                    highlightbackground=C_MID,
                                    highlightthickness=1)
        self.think_frame.place(x=LX + LOG_W + GAP, y=LY,
                               width=THINK_W, height=LH)

        hdr = tk.Frame(self.think_frame, bg="#00080d", height=24)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="◈ THINKING", fg=C_PRI, bg="#00080d",
                 font=_font(10, bold=True)).pack(side="left", padx=(9, 0))
        tk.Button(hdr, text="⌫", command=self._clear_thinking, fg=C_MID,
                  bg="#00080d", activebackground="#003344", font=_font(9),
                  bd=0, relief="flat", padx=7, cursor="hand2"
                  ).pack(side="right", padx=(0, 5))
        self.think_mode_btn = tk.Button(
            hdr, text="STEPS", command=self._toggle_think_mode,
            fg=C_ACC2, bg="#00080d", activebackground="#003344",
            font=_font(8, bold=True), bd=0, relief="flat", padx=7, cursor="hand2"
        )
        self.think_mode_btn.pack(side="right", padx=5)

        self.think_text = tk.Text(self.think_frame, fg=C_TEXT, bg=C_PANEL,
                                  insertbackground=C_TEXT, borderwidth=0,
                                  wrap="word", font=_font(9), padx=9, pady=4)
        self.think_text.pack(fill="both", expand=True)
        self.think_text.configure(state="disabled")
        self.think_text.tag_config("in",   foreground="#e8e8e8")
        self.think_text.tag_config("tool", foreground=C_PRI)
        self.think_text.tag_config("out",  foreground=C_TEXT)
        self.think_text.tag_config("err",  foreground=C_RED)
        self.think_text.tag_config("sys",  foreground=C_ACC2)
        self.think_text.tag_config("raw",  foreground="#2f5f70", elide=True)
        try:
            from ui.widgets import enable_copy
            enable_copy(self.think_text)
        except Exception:
            pass
        self._poll_think()

        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._screenshot_mode = False
        self.on_text_input = None
        try:
            # T3.10 / T3.15 / T3.30: the three controls that must be reachable
            # without hunting through menus.
            self.root.bind("<F9>", lambda _e: self.engage_kill_switch("hotkey F9"))
            self.root.bind("<F8>", lambda _e: self.show_audit())
            self.root.bind("<F10>", lambda _e: self.toggle_screenshot_mode())
            self.root.bind("<F7>", lambda _e: self.open_settings())
            self.root.bind("<F6>", lambda _e: self.show_notifications())
            self.root.bind("<F11>", lambda _e: self.show_debug_overlay())
            self.root.bind("<Control-Shift-T>",
                           lambda _e: self.toggle_always_on_top())
            self.root.bind("<Control-Shift-M>", lambda _e: self.minimize_window())
            self.root.bind("<Control-k>", lambda _e: self.open_composer())
            self.root.bind("<Control-h>", lambda _e: self.open_transcript())
            # T3.14: Escape closes transient windows, so the HUD is usable
            # without a mouse.
            self.root.bind("<Escape>", lambda _e: self._close_transient())
        except Exception:
            pass

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """T3.18/T3.23: composed shutdown, then exit. Errors never block closing."""
        try:
            from ui import splash
            splash.shutdown(self)
        except Exception:
            try:
                from ui.layout import save_window
                save_window(self.root)
            except Exception:
                pass
        try:
            os._exit(0)
        except Exception:
            self.root.destroy()
        
    def update_mic_level(self, level):
        self.mic_level = max(0.0, min(1.0, level))

    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    def _animate(self):
        self.tick += 1
        t   = self.tick
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo  = random.uniform(138, 182)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo  = random.uniform(50, 68)
            self.last_t = now

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo  - self.halo_a) * sp

        for i, spd in enumerate([1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        self.scan_angle  = (self.scan_angle  + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        if t % 40 == 0:
            self.status_blink = not self.status_blink

        self._draw()
        # T3.6: paced animation. 16 ms is ~60 fps; an iconified window drops to
        # 4 fps instead of burning a core redrawing something nobody sees.
        delay = 16
        try:
            if self.root.state() == "iconic":
                delay = 250
        except Exception:
            pass
        self.root.after(delay, self._animate)

    def _draw(self):
        c    = self.bg
        W, H = self.W, self.H
        t    = self.tick
        FCX  = self.FCX
        FCY  = self.FCY
        FW   = self.FACE_SZ
        c.delete("all")

        for x in range(0, W, 44):
            for y in range(0, H, 44):
                c.create_rectangle(x, y, x+1, y+1, fill=C_DIMMER, outline="")

        for r in range(int(FW * 0.54), int(FW * 0.28), -22):
            frac = 1.0 - (r - FW * 0.28) / (FW * 0.26)
            ga   = max(0, min(255, int(self.halo_a * 0.09 * frac)))
            gh   = f"{ga:02x}"
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                          outline=f"#00{gh}ff", width=2)

        for pr in self.pulse_r:
            pa = max(0, int(220 * (1.0 - pr / (FW * 0.72))))
            r  = int(pr)
            c.create_oval(FCX-r, FCY-r, FCX+r, FCY+r,
                          outline=self._ac(0, 212, 255, pa), width=2)

        for idx, (r_frac, w_ring, arc_l, gap) in enumerate([
                (0.47, 3, 110, 75), (0.39, 2, 75, 55), (0.31, 1, 55, 38)]):
            ring_r = int(FW * r_frac)
            base_a = self.rings_spin[idx]
            a_val  = max(0, min(255, int(self.halo_a * (1.0 - idx * 0.18))))
            col    = self._ac(0, 212, 255, a_val)
            for s in range(360 // (arc_l + gap)):
                start = (base_a + s * (arc_l + gap)) % 360
                c.create_arc(FCX-ring_r, FCY-ring_r, FCX+ring_r, FCY+ring_r,
                             start=start, extent=arc_l,
                             outline=col, width=w_ring, style="arc")

        sr      = int(FW * 0.49)
        scan_a  = min(255, int(self.halo_a * 1.4))
        arc_ext = 70 if self.speaking else 42
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan_angle, extent=arc_ext,
                     outline=self._ac(0, 212, 255, scan_a), width=3, style="arc")
        c.create_arc(FCX-sr, FCY-sr, FCX+sr, FCY+sr,
                     start=self.scan2_angle, extent=arc_ext,
                     outline=self._ac(255, 100, 0, scan_a // 2), width=2, style="arc")

        t_out = int(FW * 0.495)
        t_in  = int(FW * 0.472)
        a_mk  = self._ac(0, 212, 255, 155)
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 5
            c.create_line(FCX + t_out * math.cos(rad), FCY - t_out * math.sin(rad),
                          FCX + inn  * math.cos(rad), FCY - inn  * math.sin(rad),
                          fill=a_mk, width=1)

        ch_r = int(FW * 0.50)
        gap  = int(FW * 0.15)
        ch_a = self._ac(0, 212, 255, int(self.halo_a * 0.55))
        for x1, y1, x2, y2 in [
                (FCX - ch_r, FCY, FCX - gap, FCY), (FCX + gap, FCY, FCX + ch_r, FCY),
                (FCX, FCY - ch_r, FCX, FCY - gap), (FCX, FCY + gap, FCX, FCY + ch_r)]:
            c.create_line(x1, y1, x2, y2, fill=ch_a, width=1)

        blen = 22
        bc   = self._ac(0, 212, 255, 200)
        hl = FCX - FW // 2; hr = FCX + FW // 2
        ht = FCY - FW // 2; hb = FCY + FW // 2
        for bx, by, sdx, sdy in [(hl, ht, 1, 1), (hr, ht, -1, 1),
                                   (hl, hb, 1, -1), (hr, hb, -1, -1)]:
            c.create_line(bx, by, bx + sdx * blen, by,            fill=bc, width=2)
            c.create_line(bx, by, bx,               by + sdy * blen, fill=bc, width=2)

        if self._has_face:
            # ===== Circular Voice Spectrum =====

            bars = 64

            for i in range(bars):

                angle = (360 / bars) * i

                rad = math.radians(angle)

                level = max(0.05, self.mic_level)

                length = (
                    8
                    + level * 25
                    + math.sin(time.time() * 4 + i * 0.3) * 5
    )

                inner_r = int(FW * 0.54)
                outer_r = inner_r + length

                x1 = FCX + inner_r * math.cos(rad)
                y1 = FCY - inner_r * math.sin(rad)

                x2 = FCX + outer_r * math.cos(rad)
                y2 = FCY - outer_r * math.sin(rad)

                self.bg.create_line(
                    x1, y1,
                    x2, y2,
                    fill=C_PRI,
                    width=2
                )
            fw = int(FW * self.scale)
            if (self._face_scale_cache is None or
                    abs(self._face_scale_cache[0] - self.scale) > 0.004):
                scaled = self._face_pil.resize((fw, fw), Image.BILINEAR)
                tk_img = ImageTk.PhotoImage(scaled)
                self._face_scale_cache = (self.scale, tk_img)
            c.create_image(FCX, FCY, image=self._face_scale_cache[1])
        else:
            orb_r = int(FW * 0.27 * self.scale)
            for i in range(7, 0, -1):
                r2   = int(orb_r * i / 7)
                frac = i / 7
                ga   = max(0, min(255, int(self.halo_a * 1.1 * frac)))
                c.create_oval(FCX-r2, FCY-r2, FCX+r2, FCY+r2,
                              fill=self._ac(0, int(65*frac), int(120*frac), ga),
                              outline="")
            c.create_text(FCX, FCY, text=SYSTEM_NAME,
                          fill=self._ac(0, 212, 255, min(255, int(self.halo_a * 2))),
                          font=_font(14, bold=True))

        HDR = 62
        c.create_rectangle(0, 0, W, HDR, fill="#00080d", outline="")
        c.create_line(0, HDR, W, HDR, fill=C_MID, width=1)
        c.create_text(W // 2, 22, text=SYSTEM_NAME,
                      fill=C_PRI, font=_font(18, bold=True))
        c.create_text(W // 2, 44, text="Just A Rather Very Intelligent System",
                      fill=C_MID, font=_font(9))
        c.create_text(16, 31,    text=MODEL_BADGE,
                      fill=C_DIM, font=_font(9), anchor="w")
        c.create_text(W - 16, 31, text=time.strftime("%H:%M:%S"),
                      fill=C_PRI, font=_font(14, bold=True), anchor="e")


        sy = FCY + FW // 2 + 45
        if self.speaking:
            stat, sc = "● SPEAKING", C_ACC
        else:
            sym = "●" if self.status_blink else "○"
            stat, sc = f"{sym} {self.status_text}", C_PRI

        c.create_text(W // 2, sy, text=stat,
                      font=("Consolas", 12, "bold"), fill=sc)

        wy = sy + 22
        N  = 32
        BH = 18
        bw = 8
        total_w = N * bw
        wx0 = (W - total_w) // 2
        for i in range(N):

            level = max(0.05, min(1.0, self.mic_level))

            wave = (
                math.sin(t * 0.15 + i * 0.45)
                * level
            )

            hb = int(
                3 + abs(wave) * BH
            )

            col = C_PRI if hb > BH * 0.5 else C_MID

            bx = wx0 + i * bw

            c.create_rectangle(
                bx,
                wy + BH - hb,
                bx + bw - 1,
                wy + BH,
                fill=col,
                outline=""
            )

        c.create_rectangle(0, H - 28, W, H, fill="#00080d", outline="")
        c.create_line(0, H - 28, W, H - 28, fill=C_DIM, width=1)
        c.create_text(W // 2, H - 14, fill=C_DIM, font=_font(8),
                      text="FatihMakes Industries  ·  CLASSIFIED  ·  MARK XXX")

    def write_log(self, text: str):
        try:
            from ui.transcript import split_speaker
            role, body = split_speaker(text)
            if body:
                if getattr(self, "_transcript", None) is None:
                    from ui.transcript import Transcript
                    self._transcript = Transcript()
                self._transcript.add(role, body)
        except Exception:
            pass
        self.typing_queue.append(text)
        tl = text.lower()
        self.status_text = ("PROCESSING" if tl.startswith("you:")
                            else "RESPONDING" if tl.startswith("ai:")
                            else self.status_text)
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking:
                self.status_text = "ONLINE"
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        tag  = "you" if tl.startswith("you:") else "ai" if tl.startswith("ai:") else "sys"
        self.log_text.configure(state="normal")
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(8, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(25, self._start_typing)

    def start_speaking(self):
        self.speaking    = True
        self.status_text = "SPEAKING"
        try:
            from ui import cues
            cues.play("speaking")
        except Exception:
            pass

    def stop_speaking(self):
        self.speaking    = False
        self.status_text = "ONLINE"

    def _api_keys_exist(self):
        return API_FILE.exists()

    def wait_for_api_key(self):
        """Block until API key is saved (called from main thread before starting JARVIS)."""
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self):
        # T3.3: the panel lives in ui/setup.py; the HUD only keeps the handle.
        try:
            from ui import setup
            self.setup_frame, self.gemini_entry = setup.build(self)
        except Exception:
            self.setup_frame = None
            self.gemini_entry = None
            self.write_log("SYS: setup panel unavailable — add config/api_keys.json")

    def _save_api_keys(self):
        # The setup panel saves itself; kept for callers that still call this.
        if getattr(self, "gemini_entry", None) is None:
            return
        try:
            from ui import setup
            if setup.save_key(self.gemini_entry.get()):
                self.setup_frame.destroy()
                self._api_key_ready = True
                self.status_text = "ONLINE"
                self.write_log("SYS: Systems initialised. JARVIS online.")
        except Exception:
            pass

    def create_dashboard_panels(self):

        panel_bg = "#05141c"

        self.task_frame = tk.Frame(
            self.root,
            bg=panel_bg,
            highlightbackground="#00d4ff",
            highlightthickness=2
        )
        self.task_frame.place(
            x=15,
            y=80,
            width=180,
            height=140
        )
        tk.Label(
            self.task_frame,
            text="TASKS",
            fg=C_PRI,
            bg=panel_bg,
            font=_font(11, bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        self.task_label = tk.Label(
            self.task_frame,
            text="Waiting...",
            fg=C_TEXT,
            bg=panel_bg,
            justify="left",
            font=_font(9)
        )
        self.task_label.pack(anchor="w", padx=10)
        self.memory_frame = tk.Frame(
                self.root,
                bg=panel_bg,
                highlightbackground="#00d4ff",
                highlightthickness=2
            )
        self.memory_frame.place(
                x=self.W - 195,
                y=80,
                width=180,
                height=140
            )
        self.memory_frame.config(
            highlightbackground="#00d4ff",
            highlightthickness=2
                )


        tk.Label(
            self.memory_frame,
            text="MEMORY",
            fg=C_PRI,
            bg=panel_bg,
            font=_font(11, bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        self.memory_label = tk.Label(
            self.memory_frame,
            text="No Context",
            fg=C_TEXT,
            bg=panel_bg,
            justify="left",
            font=_font(9)
        )
        self.memory_label.pack(anchor="w", padx=10)

        self.agent_frame = tk.Frame(
            self.root,
            bg=panel_bg,
            highlightbackground="#00d4ff",
            highlightthickness=2
        )
        self.agent_frame.place(
            x=15,
            y=240,
            width=180,
            height=140
        )

        tk.Label(
            self.agent_frame,
            text="AGENTS",
            fg=C_PRI,
            bg=panel_bg,
            font=_font(11, bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        self.agent_label = tk.Label(
            self.agent_frame,
            text=
            "Planner : ACTIVE\n"
            "Memory  : ACTIVE\n"
            "Browser : IDLE\n"
            "Executor: IDLE",
            fg=C_TEXT,
            bg=panel_bg,
            justify="left",
            font=_font(9)
        )
        self.agent_label.pack(anchor="w", padx=10)

        self.system_frame = tk.Frame(
            self.root,
            bg=panel_bg,
            highlightbackground="#00d4ff",
            highlightthickness=2
        )
        self.system_frame.place(
            x=self.W-195,
            y=240,
            width=180,
            height=140
        )

        tk.Label(
            self.system_frame,
            text="SYSTEM",
            fg=C_PRI,
            bg=panel_bg,
            font=_font(11, bold=True)
        ).pack(anchor="w", padx=10, pady=5)

        self.system_label = tk.Label(
            self.system_frame,
            text="Loading...",
            fg=C_TEXT,
            bg=panel_bg,
            justify="left",
            font=_font(9)
        )
        self.system_label.pack(anchor="w", padx=10)

        # T3.13: provider/model/mode/queue strip. Users otherwise blame a
        # fallback model for slowness without seeing that it happened.
        self.status_strip_label = tk.Label(
            self.root, text="", fg=C_DIM, bg=C_BG,
            font=_font(8), anchor="w",
        )
        status_geo = (self.metrics.pane("status") if self.metrics is not None
                      else {"x": 15, "y": self.H - 20,
                            "width": self.W - 30, "height": 14})
        self.status_strip_label.place(**status_geo)
        self._refresh_status_strip()

        self.update_dashboard()
        self.refresh_memory_panel()
        self.update_agent_panel()

        # T3.26: the dashboard labels are terse on purpose; tooltips carry the
        # explanation without adding permanent chrome.
        try:
            from ui.widgets import Tooltip
            Tooltip(self.task_label, "Current plan steps. Cancelled steps are marked ⊘.")
            Tooltip(self.memory_label, "What JARVIS remembers. Stored locally in memory/.")
            if hasattr(self, "agent_label"):
                Tooltip(self.agent_label, "Per-agent state: ○ idle, ◉ active, ◈ thinking.")
        except Exception:
            pass


    def update_dashboard(self):

        try:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent

            self.system_label.config(
                text=
                f"CPU : {cpu}%\n"
                f"RAM : {ram}%\n"
                f"STATUS : ONLINE"
            )
        except Exception as e:
                print("Dashboard Error:", e)

        self.root.after(1000, self.update_dashboard)


    def _refresh_status_strip(self):
        """T3.13: refresh slowly; quota/provider lookups must not run at 60fps."""
        try:
            text = self.status_strip()
            if text:
                self.status_strip_label.config(text=text)
        except Exception:
            pass
        try:
            self.root.after(5000, self._refresh_status_strip)
        except Exception:
            pass

    def set_tasks(self, tasks):
        tasks = list(tasks or [])
        if not tasks:
            try:
                from ui.widgets import empty_state
                text = empty_state("tasks")
            except Exception:
                text = "No tasks yet."
        else:
            text = "\n".join(tasks)
        self.task_label.config(text=text)


    def set_memory(self, text):
        self.memory_label.config(text=text)
    
    def refresh_memory_panel(self):
        # T3.5: memory lives on disk; read it off the UI thread and apply the
        # result on the Tk thread. A slow/failing disk can no longer freeze the
        # animation, and one refresh cannot overlap the next.
        if not getattr(self, "_memory_refreshing", False):
            self._memory_refreshing = True

            def work():
                try:
                    memory = load_memory()
                except Exception:
                    memory = {}
                try:
                    self.root.after(0, lambda: self._apply_memory(memory))
                except Exception:
                    self._memory_refreshing = False

            try:
                threading.Thread(target=work, daemon=True,
                                 name="MemoryPanel").start()
            except Exception:
                self._memory_refreshing = False

        try:
            self.root.after(8000, self.refresh_memory_panel)
        except Exception:
            pass

    def _apply_memory(self, memory):
        try:
            name = (
                (memory or {}).get("identity", {})
                .get("name", {})
                .get("value", "Unknown")
            )

            project = (
                (memory or {}).get("projects", {})
                .get("main_project", {})
                .get("value", "None")
            )

            if not name or name == "Unknown":
                try:
                    from ui.widgets import empty_state
                    text = empty_state("memory")
                except Exception:
                    text = "User: Unknown\nProject: None"
            else:
                text = f"User: {name}\nProject: {project}"
            self.memory_label.config(text=text)
        except Exception:
            pass
        finally:
            self._memory_refreshing = False


    def set_agent_status(self, text):
        self.agent_label.config(text=text)
     
    def update_agent_panel(self):

        txt = ""

        for agent, status in self.agent_states.items():

            symbol = {
            "ACTIVE": "◉",
            "RUNNING": "◉",
            "DONE": "✓",
            "IDLE": "○",
            "THINKING": "◈"
        }.get(status, "○")

        txt += f"{symbol} {agent:<8}: {status}\n"

        self.agent_label.config(text=txt)

        self.root.after(
            500,
            self.update_agent_panel
           
        )

        

    def set_agent(self, name, state):

        if name in self.agent_states:
            self.agent_states[name] = state

    # ================= TIER 3 SHELL HELPERS =================

    def show_notifications(self, limit: int = 20) -> None:
        """T3.12: notification centre digest in the thinking pane."""
        try:
            from ui import notifications
            lines = notifications.notification_lines(limit)
            summary = notifications.digest()
        except Exception:
            lines, summary = [], "notifications unavailable"
        self.jarvis_think("sys", summary)
        for line in lines:
            self.jarvis_think("notify", line)

    def _close_transient(self) -> None:
        """T3.14: Escape closes any Toplevel we opened, not the HUD."""
        try:
            for child in self.root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()
        except Exception:
            pass

    def show_debug_overlay(self) -> None:
        """T3.29: one-key diagnostic dump (no secrets, no screenshot)."""
        try:
            from ui import support
            state = support.status_snapshot()
        except Exception:
            state = {}
        lines = [f"{key}: {value}" for key, value in sorted(state.items())]
        lines.append(f"tick: {getattr(self, 'tick', 0)}")
        lines.append(f"typing queue: {len(getattr(self, 'typing_queue', ()))}")
        lines.append(f"think queue: {len(getattr(self, '_think_q', ()) or ())}")
        lines.append(f"mic level: {getattr(self, 'mic_level', 0):.3f}")
        for line in lines:
            self.jarvis_think("sys", line)

    def toggle_click_through(self) -> bool:
        """T3.19: let clicks pass through the floating HUD."""
        want = not getattr(self, "_click_through", False)
        try:
            from ui.layout import set_click_through
            ok = set_click_through(self.root, want)
        except Exception:
            ok = False
        if ok:
            self._click_through = want
            self.jarvis_think("sys", f"click-through {'on' if want else 'off'}")
        else:
            self.jarvis_think("err", "click-through is Windows-only")
        return self._click_through if ok else False

    def set_opacity(self, value: float) -> bool:
        try:
            from ui.layout import set_opacity
            return set_opacity(self.root, value)
        except Exception:
            return False

    def minimize_window(self) -> bool:
        """T3.1: keyboard/window management without editing code."""
        try:
            from ui import window
            return window.minimize(self.root)
        except Exception:
            return False

    def toggle_always_on_top(self) -> bool:
        try:
            from ui import window
            return window.toggle_always_on_top(self.root)
        except Exception:
            return False

    def snap_window(self, corner: str) -> bool:
        try:
            from ui import window
            return window.move_to(self.root, corner)
        except Exception:
            return False

    def submit_text(self, text: str) -> bool:
        """T3.7: hand typed text to the live session (main wires this up)."""
        callback = getattr(self, "on_text_input", None)
        if callable(callback):
            try:
                callback(str(text))
                return True
            except Exception as exc:
                self.jarvis_think("err", f"text input failed: {exc}")
                return False
        self.jarvis_think("sys", "text input is not connected")
        return False

    def open_composer(self):
        """T3.7: floating text composer."""
        try:
            from ui import composer_view
            return composer_view.build(self)
        except Exception as exc:
            self.jarvis_think("err", f"composer unavailable: {exc}")
            return None

    def open_transcript(self):
        """T3.8: transcript viewer with search and export."""
        try:
            from ui import transcript_view
            return transcript_view.build(self)
        except Exception as exc:
            self.jarvis_think("err", f"transcript unavailable: {exc}")
            return None

    def hologram_status(self) -> str:
        """T3.20: one line for the projector's state."""
        try:
            from ui import hologram_control
            return hologram_control.status_line()
        except Exception:
            return "hologram: unavailable"

    def hologram_launch(self, name: str | None = None, *,
                        prompt: str | None = None) -> dict:
        try:
            from ui import hologram_control
            result = hologram_control.launch(name, prompt=prompt)
        except Exception as exc:
            result = {"ok": False, "reason": str(exc)}
        kind = "sys" if result.get("ok") else "err"
        self.jarvis_think(kind, f"hologram launch: {result}")
        return result

    def hologram_close(self) -> dict:
        try:
            from ui import hologram_control
            result = hologram_control.close()
        except Exception as exc:
            result = {"ok": False, "reason": str(exc)}
        self.jarvis_think("sys" if result.get("ok") else "err",
                          f"hologram close: {result}")
        return result

    def status_strip(self) -> str:
        """T3.13: provider/model/quota/mode/queue as one line."""
        try:
            from ui import support
            return support.status_text()
        except Exception:
            return ""

    def show_audit(self, limit: int = 40) -> None:
        """T3.15: recent audit entries in the thinking pane."""
        try:
            from ui import support
            lines = support.audit_lines(limit)
        except Exception:
            lines = []
        if not lines:
            self.jarvis_think("sys", "audit: no entries")
            return
        for line in lines:
            self.jarvis_think("audit", line)

    def kill_switch_engaged(self) -> bool:
        try:
            from ui import support
            return bool(support.kill_state().get("engaged"))
        except Exception:
            return True

    def engage_kill_switch(self, reason: str = "HUD") -> None:
        """T3.10: surface the existing policy kill switch. Engaging is safe."""
        try:
            from ui import support
            result = support.engage_kill(reason)
            self.jarvis_think("policy", f"kill switch engaged: {result.get('reason', reason)}")
        except Exception as exc:
            self.jarvis_think("policy", f"kill switch failed (actions still blocked): {exc}")

    def release_kill_switch(self) -> None:
        """Releasing asks first — it re-enables actions."""
        try:
            from tkinter import messagebox
            from ui import support
            if not messagebox.askyesno("Release kill switch",
                                       "Re-enable autonomous actions?"):
                return
            support.release_kill()
            self.jarvis_think("policy", "kill switch released")
        except Exception as exc:
            self.jarvis_think("policy", f"kill switch release failed: {exc}")

    def set_screenshot_mode(self, on: bool) -> bool:
        """T3.30: hide chrome for README captures. Best-effort, reversible."""
        self._screenshot_mode = bool(on)
        frames = [getattr(self, name, None)
                  for name in ("log_frame", "think_frame")]
        frames = [f for f in frames if f is not None]
        if on:
            self._place_memory = {}
            for frame in frames:
                try:
                    self._place_memory[str(frame)] = frame.place_info()
                    frame.place_forget()
                except Exception:
                    pass
        else:
            for frame in frames:
                info = getattr(self, "_place_memory", {}).get(str(frame))
                if not info:
                    continue
                try:
                    kwargs = {}
                    for key in ("x", "y", "width", "height"):
                        value = info.get(key)
                        if value not in ("", None):
                            kwargs[key] = int(value)
                    frame.place(**kwargs)
                except Exception:
                    pass
        return self._screenshot_mode

    def toggle_screenshot_mode(self) -> bool:
        return self.set_screenshot_mode(not getattr(self, "_screenshot_mode", False))

    def open_settings(self):
        """T3.2: theme, cues, kill switch and status in one small window."""
        try:
            from ui import settings
            return settings.build(self)
        except Exception as exc:
            self.jarvis_think("err", f"settings unavailable: {exc}")
            return None

    def stream_jarvis_text(self, text: str):
        """Called as each text chunk arrives from Gemini."""
        self.root.after(0, self._append_jarvis_text, text)

    def _append_jarvis_text(self, text: str):
        # status_text doubles as the status enum (ONLINE/PROCESSING/
        # SPEAKING), so only accumulate while we're already previewing a
        # reply — otherwise start a fresh buffer. Cap it so a long reply
        # can't grow without bound.
        if not self.status_text.startswith("Jarvis: "):
            self._stream_buf = ""
        self._stream_buf += text
        self.status_text = "Jarvis: " + self._stream_buf[-100:]

    # ================= THINKING PANE =================

    @staticmethod
    def _clip(text, limit: int) -> str:
        s = " ".join(str(text).split())
        return s if len(s) <= limit else s[: limit - 1] + "…"

    def jarvis_think(self, kind: str, text: str):
        """Thread-safe: queue an event for the THINKING pane.

        kind: "tool" | "args" | "result" | "err" | "in" | "sys"
        Safe to call from any thread — this never touches Tk directly.
        """
        try:
            self._think_q.put((kind, str(text)))
        except Exception:
            pass

    def _poll_think(self):
        """Tk-thread drain of the thinking queue (runs on the event loop)."""
        try:
            while True:
                try:
                    kind, text = self._think_q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._think_event(kind, text)
                except Exception:
                    pass
        finally:
            try:
                self.root.after(40, self._poll_think)
            except Exception:
                pass

    def _think_event(self, kind, text):
        try:
            one = " ".join(str(text).split())
            ts  = time.strftime("%H:%M:%S")
            if kind == "tool":
                self._think_insert("tool", f"[{ts}] ▸ {self._clip(one, 170)}")
            elif kind == "args":
                # raw detail — hidden while the pane is in STEPS mode
                self._think_insert("raw", f"        {self._clip(one, 500)}")
            elif kind == "in":
                self._think_insert("in", f"[{ts}] ✦ {self._clip(one, 170)}")
            elif kind == "result":
                self._think_insert("out", f"[{ts}] → {self._clip(one, 130)}")
                if len(one) > 130:
                    self._think_insert("raw", f"        {self._clip(one, 4000)}")
            elif kind == "err":
                self._think_insert("err", f"[{ts}] ✕ {self._clip(one, 250)}")
                if len(one) > 250:
                    self._think_insert("raw", f"        {self._clip(one, 4000)}")
            else:
                self._think_insert("sys", f"[{ts}] {self._clip(one, 170)}")
        except Exception:
            pass

    def _think_insert(self, tag: str, line: str):
        w = self.think_text
        try:
            at_end = w.yview()[1] >= 0.999   # only follow the tail if we were there
        except Exception:
            at_end = True

        w.configure(state="normal")
        w.insert(tk.END, line + "\n", tag)
        try:
            total = int(w.index("end-1c").split(".")[0])
            if total > THINK_MAX_LINES:
                w.delete("1.0", f"{total - THINK_MAX_LINES + 1}.0")
        except Exception:
            pass
        w.configure(state="disabled")
        if at_end:
            w.see(tk.END)

    def _toggle_think_mode(self):
        """Switch between STEPS (clean) and RAW (everything) detail."""
        self.think_raw = not self.think_raw
        self.think_text.tag_config("raw", elide=not self.think_raw)
        self.think_mode_btn.config(
            text="RAW" if self.think_raw else "STEPS",
            fg=C_ACC if self.think_raw else C_ACC2
        )

    def _clear_thinking(self):
        w = self.think_text
        w.configure(state="normal")
        w.delete("1.0", tk.END)
        w.configure(state="disabled")
        self._think_insert("sys", f"[{time.strftime('%H:%M:%S')}] ◌  cleared")

    