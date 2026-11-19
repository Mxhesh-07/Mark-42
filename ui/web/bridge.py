"""Loopback HTTP bridge for the J.A.R.V.I.S. web HUD.

The browser is a view, not the brain. Python keeps owning the microphone, the
Gemini Live session and the tools; this module gives the page a same-origin way
to watch that state and to send the things a HUD is allowed to send:
typed text, stop, mute, and quit.

    GET  /                 the HUD (ui/web/static/)
    GET  /api/state        the state board + telemetry as JSON
    GET  /api/telemetry    just the machine readings
    GET  /health           liveness for scripts
    POST /api/command      {"kind": "text"|"stop"|"mute"|"ping"|"quit", ...}

Design notes
    * Binds 127.0.0.1 only, and rejects requests whose Host header is not the
      loopback address it was asked on. A page on another origin therefore
      cannot talk to it even if it guesses the port.
    * No CORS headers are ever sent. A cross-origin JSON POST would need a
      preflight, which is never answered, so the command endpoint is not
      reachable from other sites.
    * Commands are queued, never executed on the HTTP thread. The Tk thread
      drains them so the assistant is only ever mutated from one place.
    * Telemetry is sampled on its own thread and cached, so a slow sensor can
      never stall a page request.
    * The page polls /api/state. When those polls stop after the HUD has been
      seen, the browser was closed (or crashed), so the UI thread shuts the
      runtime down. A reload is shorter than HUD_MISSING_S and is safe.
"""

from __future__ import annotations

import json
import os
import threading
import time
import queue
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8790
STATIC_DIR = Path(__file__).resolve().parent / "static"

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8",
}

_MAX_BODY = 8 * 1024

# The HUD polls every 50 ms (600 ms in a hidden tab). A gap this long means the
# tab is gone, not merely throttled. Set JARVIS_HUD_QUIT_ON_CLOSE=0 to keep the
# old "HUD is only a view" behaviour.
HUD_MISSING_S = 5.0


# --------------------------------------------------------------------------- #
# telemetry
# --------------------------------------------------------------------------- #
class Telemetry:
    """CPU / memory / load / uptime, refreshed on a background thread."""

    def __init__(self, interval: float = 2.0):
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._data: dict = {"ready": False}
        self._gpu_at = 0.0
        self._gpu: dict | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="jarvis-telemetry",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> dict:
        return dict(self._data)

    def _run(self) -> None:
        try:
            import psutil
        except Exception:
            self._data = {"ready": False, "error": "psutil unavailable"}
            return
        psutil.cpu_percent(None)          # first call primes the counter
        while not self._stop.is_set():
            data: dict = {"ready": True, "ts": time.time()}
            try:
                data["cpu"] = round(psutil.cpu_percent(None), 1)
                data["cores"] = psutil.cpu_count(logical=True) or 0
                mem = psutil.virtual_memory()
                data["mem"] = round(mem.percent, 1)
                data["mem_used_gb"] = round((mem.total - mem.available) / 1e9, 1)
                data["mem_total_gb"] = round(mem.total / 1e9, 1)
                try:
                    data["load"] = round(psutil.getloadavg()[0], 2)
                except Exception:
                    data["load"] = round(data["cpu"] / 100.0 * (data["cores"] or 1), 2)
                data["procs"] = len(psutil.pids())
                data["uptime"] = int(time.time() - psutil.boot_time())
                try:
                    disk = psutil.disk_usage(os.path.abspath(os.sep))
                    data["disk"] = round(disk.percent, 1)
                except Exception:
                    pass
                try:
                    bat = psutil.sensors_battery()
                    if bat is not None:
                        data["battery"] = round(bat.percent)
                        data["plugged"] = bool(bat.power_plugged)
                except Exception:
                    pass
                data["gpu"] = self._sample_gpu()
                self._data = data
            except Exception as e:      # psutil on a locked-down box
                self._data = {"ready": False, "error": str(e)[:120]}
            self._stop.wait(self.interval)

    def _sample_gpu(self) -> dict | None:
        """nvidia-smi, at most every 6 s. Absent GPU is a normal answer."""
        now = time.time()
        if now - self._gpu_at < 6.0:
            return self._gpu
        self._gpu_at = now
        try:
            import subprocess
            flags = 0x08000000 if os.name == "nt" else 0
            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2.5,
                creationflags=flags,
            )
            if out.returncode != 0 or not out.stdout.strip():
                self._gpu = None
                return None
            first = out.stdout.strip().splitlines()[0]
            util, used, total, temp = [p.strip() for p in first.split(",")[:4]]
            self._gpu = {"util": float(util), "mem_used": float(used),
                         "mem_total": float(total), "temp": float(temp)}
        except Exception:
            self._gpu = None
        return self._gpu


# --------------------------------------------------------------------------- #
# command queue
# --------------------------------------------------------------------------- #
class Commands:
    """A bounded queue of page requests, drained on the UI thread."""

    KINDS = {"text", "stop", "mute", "ping", "confirm", "quit"}
    DECISIONS = {"approve", "deny", "always"}

    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=32)

    def push(self, kind: str, **payload) -> bool:
        kind = str(kind or "").strip().lower()
        if kind not in self.KINDS:
            return False
        if kind == "text":
            text = str(payload.get("text", "")).strip()
            if not text or len(text) > 4000:
                return False
            payload = {"text": text}
        elif kind == "mute":
            payload = {"on": bool(payload.get("on"))}
        elif kind == "confirm":
            # A decision, not a boolean, so "always" survives the round trip.
            decision = str(payload.get("decision", "")).strip().lower()
            if decision not in self.DECISIONS:
                decision = "approve" if payload.get("allow") is True else "deny"
            payload = {"id": str(payload.get("id", ""))[:40],
                       "decision": decision}
        else:
            payload = {}
        try:
            self._q.put_nowait({"kind": kind, **payload})
            return True
        except queue.Full:
            return False

    def drain(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class _Handler(BaseHTTPRequestHandler):
    server_version = "JarvisHUD/1.0"
    protocol_version = "HTTP/1.1"

    # injected by Bridge.start()
    bridge: "Bridge"

    # -- plumbing -------------------------------------------------------- #
    def log_message(self, fmt, *args):   # noqa: A003 - stdlib signature
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        if not host:
            return False
        name = host.rsplit(":", 1)[0]
        return name in (HOST, "localhost", "[::1]")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True                      # same-origin fetch / curl
        return origin.rstrip("/").lower() in self.bridge.origins

    def _send(self, code: int, body: bytes, ctype: str,
              cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _error(self, code: int, message: str) -> None:
        self._json({"ok": False, "error": message}, code)

    # -- routes ---------------------------------------------------------- #
    def do_GET(self):                    # noqa: N802 - stdlib naming
        if not self._host_ok():
            self._error(HTTPStatus.FORBIDDEN, "loopback only")
            return
        path = self.path.split("?", 1)[0]
        if path in ("/health", "/api/health"):
            self._json({"ok": True, "rev": self.bridge.state.rev})
            return
        if path == "/api/state":
            self.bridge.note_hud()
            board = self.bridge.state.snapshot()
            board["telemetry"] = self.bridge.telemetry.snapshot()
            board["ok"] = True
            self._json(board)
            return
        if path == "/api/telemetry":
            self._json(self.bridge.telemetry.snapshot())
            return
        if path == "/favicon.ico" and not (self.bridge.static_dir / "favicon.ico").exists():
            self._send(204, b"", "image/x-icon")
            return
        if path in ("", "/"):
            path = "/index.html"
        self._serve_static(path)

    def do_HEAD(self):                   # noqa: N802
        self.do_GET()

    def do_POST(self):                   # noqa: N802
        if not self._host_ok():
            self._error(HTTPStatus.FORBIDDEN, "loopback only")
            return
        if not self._origin_ok():
            self._error(HTTPStatus.FORBIDDEN, "origin not allowed")
            return
        path = self.path.split("?", 1)[0]
        if path != "/api/command":
            self._error(HTTPStatus.NOT_FOUND, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            self._error(HTTPStatus.BAD_REQUEST, "bad body")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("object expected")
        except Exception:
            self._error(HTTPStatus.BAD_REQUEST, "invalid json")
            return
        kind = payload.pop("kind", "")
        if not self.bridge.commands.push(kind, **payload):
            self._error(HTTPStatus.BAD_REQUEST, "unsupported command")
            return
        self._json({"ok": True})

    # -- files ------------------------------------------------------------ #
    def _serve_static(self, path: str) -> None:
        rel = path.lstrip("/")
        root = self.bridge.static_dir.resolve()
        try:
            target = (root / rel).resolve()
            if not str(target).startswith(str(root) + os.sep) and target != root:
                self._error(HTTPStatus.FORBIDDEN, "outside root")
                return
        except Exception:
            self._error(HTTPStatus.BAD_REQUEST, "bad path")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            body = target.read_bytes()
        except OSError:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "read failed")
            return
        ctype = _MIME.get(target.suffix.lower(), "application/octet-stream")
        # The page is served fresh; vendored libraries may be cached briefly.
        cache = "no-cache" if target.suffix.lower() in (".html", ".js", ".css") \
            else "public, max-age=86400"
        self._send(200, body, ctype, cache)


class _Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind a port that is already
    # listening, and requests then land on whichever socket wins. An exclusive
    # bind is what makes the "try the next port" loop below meaningful.
    allow_reuse_address = False
    daemon_threads = True

    def handle_error(self, request, client_address):
        """A poller that closed its tab is not a server error.

        The HUD polls /api/state ~20 times a second; killing or reloading the
        browser leaves sockets that reset mid-read. socketserver prints a full
        traceback for each via handle_error, which buried real failures in
        noise. Real exceptions still surface through the normal logger.
        """
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class Bridge:
    def __init__(self, state, *, host: str = HOST, port: int = PORT,
                 static_dir: Path | str = STATIC_DIR):
        self.state = state
        self.host = host
        self.port = int(port)
        self.static_dir = Path(static_dir)
        self.commands = Commands()
        self.telemetry = Telemetry()
        self.httpd: _Server | None = None
        self.origins: set[str] = set()
        self._thread: threading.Thread | None = None
        self._presence_lock = threading.Lock()
        self._hud_seen = False
        self._last_hud_seen = 0.0
        flag = os.environ.get("JARVIS_HUD_QUIT_ON_CLOSE", "1").strip().lower()
        self.quit_on_close = flag not in ("0", "false", "no", "off")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def note_hud(self) -> None:
        """Called on each /api/state poll: the HUD is alive and watching."""
        with self._presence_lock:
            self._hud_seen = True
            self._last_hud_seen = time.monotonic()

    def hud_lost(self) -> bool:
        """True when a HUD that was open has stopped polling."""
        if not self.quit_on_close:
            return False
        with self._presence_lock:
            if not self._hud_seen:
                return False
            return (time.monotonic() - self._last_hud_seen) > HUD_MISSING_S

    def start(self) -> "Bridge":
        """Bind the first free port. Raises OSError if every candidate is taken."""
        last: Exception | None = None
        for offset in range(0, 10):
            port = self.port + offset
            try:
                httpd = _Server((self.host, port), _Handler)
            except OSError as e:
                last = e
                continue
            httpd.daemon_threads = True
            _Handler.bridge = self
            self.httpd = httpd
            # port 0 means "any free port"; read back what the OS chose.
            self.port = httpd.server_address[1]
            self.origins = {f"http://{self.host}:{self.port}", f"http://localhost:{self.port}"}
            self._thread = threading.Thread(target=httpd.serve_forever,
                                            kwargs={"poll_interval": 0.2},
                                            name="jarvis-bridge", daemon=True)
            self._thread.start()
            self.telemetry.start()
            return self
        raise OSError(f"no free HUD port in {self.port}..{self.port + 9}: {last}")

    def stop(self) -> None:
        self.telemetry.stop()
        httpd = self.httpd
        self.httpd = None
        if httpd is not None:
            try:
                httpd.shutdown()
                httpd.server_close()
            except Exception:
                pass


if __name__ == "__main__":
    # Front-end work without the assistant: a simulated state board so the page
    # can be opened and driven on its own.  python -m ui.web.bridge
    import math
    import sys
    import webbrowser

    from ui.web.state import WebState

    board = WebState()
    bridge = Bridge(board).start()
    board.update(connected=True, status="STANDBY", memory="Mode: Voice\nContext: Active",
                 tasks=["✓ Listen", "⟳ Understand", "□ Execute"],
                 agent={"name": "Planner", "state": "IDLE"})
    board.log("Jarvis: Interface preview. The assistant is not running.")
    if "--confirm" in sys.argv:
        # Front-end work on the approval modal without a tool call behind it.
        board.update(confirm={
            "id": "preview",
            "summary": "delete C:/Users/you/Desktop/draft-final.docx",
            "target": "C:\\Users\\you\\Desktop\\draft-final.docx",
            "risk": 0.62, "reversibility": "permanent", "blast_radius": "local",
            "opinion": "The file is outside the last backup window.",
            "buttons": [
                {"id": "deny", "label": "Deny", "default": True},
                {"id": "approve", "label": "Approve once", "default": False},
                {"id": "always", "label": "Always allow this", "default": False},
            ],
            "timeout_s": 30.0, "expires": time.time() + 30.0,
            "narrowable": True,
        })
    print(f"JARVIS HUD preview: {bridge.url}  (Ctrl+C to stop)", flush=True)
    if "--open" in sys.argv:
        webbrowser.open(bridge.url)
    try:
        i = 0
        while True:
            i += 1
            time.sleep(0.05)
            board.update(mic=round(abs(math.sin(i / 22.0)) * 0.35, 3),
                         status="LISTEN" if i % 220 > 160 else "STANDBY")
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
