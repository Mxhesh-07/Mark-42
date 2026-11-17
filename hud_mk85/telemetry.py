"""Local telemetry bridge for the MK-LXXXV HUD.

A browser cannot read temperatures, fan speeds or volume usage, so the HUD
either stays decorative or something local tells it the truth. This is that
something: a loopback-only HTTP server with no dependencies beyond ``psutil``
(already pinned in requirements.txt) and whatever sensor tools the machine
happens to expose.

    python hud_mk85/telemetry.py            # serve on 127.0.0.1:8787
    python hud_mk85/telemetry.py --open     # ... and open the HUD as an app window

Endpoints
    /            the HUD itself (same-origin, so no CORS games needed)
    /telemetry   the snapshot as JSON (also usable from file://, CORS is open)
    /state       what JARVIS is doing right now: mic level, live transcript
    /health      liveness for scripts

Design notes
    * One background thread samples; requests only ever read a cached dict, so
      a slow ``nvidia-smi`` can never stall the page.
    * Every value that could not be measured is ``null`` and its name is listed
      in ``est``. The HUD renders ``null`` as an estimate and marks it, rather
      than passing a guess off as a measurement.
    * Loopback only, read-only, no path traversal, no writes.
    * ``/state`` is the one mutable thing and it is still loopback-only: the
      process that owns the microphone (main.py) writes it with
      ``publish(...)``, the page reads it. Nothing accepts a POST, so a web
      page you happen to have open cannot push text into the HUD.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import psutil
except Exception:  # pragma: no cover - psutil is a hard requirement in practice
    psutil = None

HERE = Path(__file__).resolve().parent
DEFAULT_PORT = 8787

# Windows: never flash a console window for the sensor probes.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_IS_WIN = os.name == "nt"


# --------------------------------------------------------------------------- #
# sensor probes
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], timeout: float) -> str:
    """Run a probe quietly and return stdout, or "" on any failure."""
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _nvidia() -> dict | None:
    """GPU name / temperature / load via nvidia-smi, if this machine has one."""
    if not shutil.which("nvidia-smi"):
        return None
    raw = _run([
        "nvidia-smi",
        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ], timeout=3)
    if not raw:
        return None
    first = raw.splitlines()[0]
    parts = [p.strip() for p in first.split(",")]
    if len(parts) < 5:
        return None

    def num(v):
        try:
            return float(v)
        except ValueError:
            return None

    return {
        "name": parts[0],
        "temp": num(parts[1]),
        "pct": num(parts[2]),
        "mem_used": num(parts[3]),
        "mem_total": num(parts[4]),
    }


def _gpu_name() -> str:
    """Adapter name for machines without nvidia-smi (integrated graphics)."""
    if _IS_WIN:
        raw = _run([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "(Get-CimInstance Win32_VideoController | "
            "Sort-Object -Property AdapterRAM -Descending | "
            "Select-Object -First 1 -ExpandProperty Name)",
        ], timeout=6)
        return raw.splitlines()[0].strip() if raw else ""
    return ""


def _initiative_guess() -> None:
    """Touch psutil's CPU counters once so the first sample is not 0%."""
    if psutil is None:
        return
    try:
        psutil.cpu_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# sampler
# --------------------------------------------------------------------------- #
class Sampler:
    """Collects a snapshot on a background thread, read by HTTP handlers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict = {"ok": False, "ts": 0.0}
        self._gpu = None
        self._gpu_name = ""
        self._disks: list[dict] = []
        self._usb: list[dict] = []
        self._top_cache: list[dict] = []
        self._conns: int | None = None
        self._prev_net = None
        self._prev_net_ts = None
        self._stop = threading.Event()
        _initiative_guess()

    # -- helpers ----------------------------------------------------------- #
    @staticmethod
    def _volumes() -> tuple[list[dict], list[dict]]:
        """Fixed and removable volumes, with real usage."""
        disks: list[dict] = []
        usb: list[dict] = []
        if psutil is None:
            return disks, usb
        try:
            parts = psutil.disk_partitions(all=False)
        except Exception:
            return disks, usb
        for part in parts:
            opts = (part.opts or "").lower()
            # Skip optical drives and empty card readers: querying them can
            # block for seconds and they have no meaningful usage.
            if "cdrom" in opts:
                continue
            try:
                usage = shutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            if not usage.total:
                continue
            total = usage.total / (1024 ** 3)
            used = usage.used / (1024 ** 3)
            entry = {
                "letter": part.device.rstrip("\\/") or part.mountpoint,
                "mount": part.mountpoint,
                "fs": part.fstype,
                "total": round(total, 1),
                "used": round(used, 1),
                "free": round(usage.free / (1024 ** 3), 1),
                # Both sides of this division must be in the same unit: the
                # ratio comes from the raw byte counts, not the GB rounding,
                # otherwise it silently collapses to 0.
                "pct": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
                "removable": ("removable" in opts) or ("floppy" in opts),
            }
            if entry["removable"]:
                usb.append(entry)
            else:
                disks.append(entry)

        def _key(d):
            return d["letter"].upper()

        disks.sort(key=_key)
        usb.sort(key=_key)
        return disks, usb

    def _net_rates(self) -> dict | None:
        if psutil is None:
            return None
        try:
            now = time.time()
            counters = psutil.net_io_counters()
            prev, prev_ts = self._prev_net, self._prev_net_ts
            self._prev_net, self._prev_net_ts = counters, now
            if prev is None or prev_ts is None:
                return {"rx": 0.0, "tx": 0.0, "unit": "KB/s"}
            dt = max(now - prev_ts, 1e-6)
            rx = max(counters.bytes_recv - prev.bytes_recv, 0) / dt / 1024
            tx = max(counters.bytes_sent - prev.bytes_sent, 0) / dt / 1024
            return {"rx": round(rx, 1), "tx": round(tx, 1), "unit": "KB/s"}
        except Exception:
            return None

    def _top(self) -> list[dict]:
        if psutil is None:
            return []
        # Idle/system pseudo-processes report the machine's spare capacity as
        # "CPU", which lands at hundreds of percent and would sit at the top of
        # this list forever. They are not applications; drop them.
        skip = {
            "system idle process", "idle", "system", "registry",
            "memory compression", "secure system",
        }
        threads = psutil.cpu_count(logical=True) or 1
        out = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                info = proc.info
                name = (info.get("name") or "").strip()
                if not name or name.lower() in skip or info.get("pid") in (0, 4):
                    continue
                # psutil reports 100% per fully-used core; scale it to a share
                # of the whole machine so one busy app cannot read as 600%.
                share = float(info.get("cpu_percent") or 0.0) / threads
                out.append({
                    "name": name[:28],
                    "cpu": round(share, 1),
                    "mem": round(float(info.get("memory_percent") or 0.0), 1),
                })
        except Exception:
            return []
        out.sort(key=lambda d: (d["cpu"], d["mem"]), reverse=True)
        return out[:3]

    # -- snapshot ---------------------------------------------------------- #
    def _core(self) -> dict:
        """The cheap half: everything that can be read in a couple of ms."""
        data: dict = {"ok": True, "ts": round(time.time(), 3)}

        # -- cpu -----------------------------------------------------------
        try:
            per = psutil.cpu_percent(interval=None, percpu=True)
            pct = round(sum(per) / len(per), 1) if per else 0.0
            freq = psutil.cpu_freq()
            data["cpu"] = {
                "pct": pct,
                "per": [round(v, 1) for v in per],
                "cores": psutil.cpu_count(logical=False) or len(per),
                "threads": psutil.cpu_count(logical=True) or len(per),
                "freq": round(freq.current) if freq else None,
            }
        except Exception:
            data["cpu"] = {"pct": 0.0, "per": [], "cores": 0, "threads": 0, "freq": None}

        # -- memory --------------------------------------------------------
        try:
            mem = psutil.virtual_memory()
            data["mem"] = {
                "pct": round(mem.percent, 1),
                "used": round(mem.used / 1024 ** 3, 1),
                "total": round(mem.total / 1024 ** 3, 1),
            }
        except Exception:
            data["mem"] = {"pct": 0.0, "used": 0.0, "total": 0.0}

        # -- gpu (values come from the slow thread) -------------------------
        gpu = dict(self._gpu) if self._gpu else {
            "name": self._gpu_name or "GRAPHICS", "temp": None, "pct": None,
            "mem_used": None, "mem_total": None,
        }
        data["gpu"] = gpu
        data["temps"] = {"gpu": gpu.get("temp"), "cpu": None}
        data["fans"] = {"aux": None, "cpu": None}

        # -- network / system ----------------------------------------------
        data["net"] = self._net_rates()
        try:
            data["procs"] = len(psutil.pids())
            data["uptime"] = round(time.time() - psutil.boot_time())
        except Exception:
            data["procs"] = 0
            data["uptime"] = 0

        try:
            bat = psutil.sensors_battery()
            data["battery"] = ({"pct": round(bat.percent), "plugged": bool(bat.power_plugged)}
                               if bat else None)
        except Exception:
            data["battery"] = None

        # Stored volumes are refreshed by the slow thread.
        data["disks"] = list(self._disks)
        data["usb"] = list(self._usb)
        data["top"] = list(self._top_cache)
        data["conns"] = self._conns

        # -- provenance -----------------------------------------------------
        est = []
        if data["temps"]["cpu"] is None:
            est.append("cpu_temp")
        if data["temps"]["gpu"] is None:
            est.append("gpu_temp")
        if data["fans"]["cpu"] is None:
            est.append("fans")
        data["est"] = est
        return data

    def _heavy(self) -> None:
        """The slow half: subprocesses and a full process scan (seconds)."""
        gpu = _nvidia()
        if gpu:
            self._gpu = gpu
        elif not self._gpu_name:
            self._gpu_name = _gpu_name()
        self._disks, self._usb = self._volumes()
        self._top_cache = self._top()

        # Established TCP sessions; the proximity scope plots these as
        # "contacts". Connection enumeration is slow on Windows, hence here.
        try:
            conns = psutil.net_connections(kind="inet")
            self._conns = sum(1 for c in conns if c.status == psutil.CONN_ESTABLISHED)
        except Exception:
            self._conns = None

    def one(self, *, slow: bool = True) -> dict:
        """Single-shot snapshot (used by tests/CLI, not by the server)."""
        if psutil is None:
            return {"ok": False, "ts": time.time(), "error": "psutil missing"}
        if slow or not self._gpu:
            self._heavy()
        return self._core()

    # -- threads ------------------------------------------------------------ #
    def start(self, period: float = 1.0, slow_period: float = 5.0) -> None:
        def fast_loop():
            while not self._stop.is_set():
                try:
                    snap = self._core()
                except Exception as e:  # never let the thread die
                    snap = {"ok": False, "ts": time.time(), "error": str(e)}
                with self._lock:
                    self._data = snap
                self._stop.wait(period)

        def slow_loop():
            first = True
            while not self._stop.is_set():
                try:
                    self._heavy()
                except Exception:
                    pass
                # Rebuild once immediately so the first paint is not empty.
                if first:
                    first = False
                    try:
                        with self._lock:
                            self._data = self._core()
                    except Exception:
                        pass
                self._stop.wait(slow_period if not first else 0.15)

        threading.Thread(target=fast_loop, name="telemetry-fast", daemon=True).start()
        threading.Thread(target=slow_loop, name="telemetry-slow", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def prime(self, *, slow: bool = False) -> dict:
        """Take one snapshot and store it, so the first request has data."""
        snap = self.one(slow=slow)
        with self._lock:
            self._data = snap
        return snap

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._data)


# --------------------------------------------------------------------------- #
# voice state (written by main.py, read by /state)
# --------------------------------------------------------------------------- #
# The HUD is a display, not the assistant, so this is deliberately tiny: a
# handful of signals plus the two lines of the current exchange. Anything the
# page shows beyond this comes from the conversation itself.
_VOICE_LOCK = threading.Lock()
_VOICE: dict = {
    "status": "OFFLINE",     # OFFLINE | IDLE | LISTEN | THINK | SPEAK
    "mic": 0.0,              # 0..1 microphone level, already gain-normalised
    "speaking": False,
    "thinking": False,
    "you": "",               # last thing the user said
    "jarvis": "",            # what JARVIS is saying / last said
    "turn": 0,               # completed exchanges since launch
    "persona": "jarvis",     # jarvis | friday | ultron (the HUD's palette)
    "ts": 0.0,               # last publish, seconds since the epoch
}


def publish(**kw) -> dict:
    """Update the voice state and return the merged copy.

    Unknown keys are ignored rather than stored, so a typo in a caller cannot
    grow the payload or leak arbitrary fields to the page.
    """
    with _VOICE_LOCK:
        for key, value in kw.items():
            if key in _VOICE:
                _VOICE[key] = value
        _VOICE["ts"] = round(time.time(), 3)
        return dict(_VOICE)


def voice() -> dict:
    with _VOICE_LOCK:
        return dict(_VOICE)


def reset_voice() -> None:
    """Back to the launch state (tests, and a restart inside one process)."""
    with _VOICE_LOCK:
        _VOICE.update({
            "status": "OFFLINE", "mic": 0.0, "speaking": False,
            "thinking": False, "you": "", "jarvis": "", "turn": 0,
            "persona": "jarvis", "ts": 0.0,
        })


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    sampler: Sampler
    server_version = "MK85-telemetry"

    def log_message(self, fmt, *args):  # keep the console readable
        path = self.path or ""
        # The page polls these several times a second; logging each one would
        # bury the assistant's own output.
        if "/telemetry" not in path and "/state" not in path:
            sys.stderr.write("[telemetry] %s\n" % (fmt % args))

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError):
                pass

    def _file(self, rel: str):
        # Resolve inside the HUD directory only; refuse anything that escapes.
        target = (HERE / rel).resolve()
        try:
            target.relative_to(HERE)
        except ValueError:
            return self._send(403, b"forbidden", "text/plain")
        if not target.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or target.suffix in (".js", ".css", ".html"):
            ctype += "; charset=utf-8"
        return self._send(200, target.read_bytes(), ctype)

    def do_GET(self):  # noqa: N802 - stdlib naming
        path = urllib.parse.urlparse(self.path).path
        if path in ("/telemetry", "/telemetry/"):
            body = json.dumps(self.sampler.snapshot(), separators=(",", ":")).encode()
            return self._send(200, body, "application/json")
        if path in ("/state", "/state/"):
            body = json.dumps(voice(), separators=(",", ":")).encode()
            return self._send(200, body, "application/json")
        if path == "/health":
            snap = self.sampler.snapshot()
            body = json.dumps({"ok": True, "data": bool(snap.get("ok"))}).encode()
            return self._send(200, body, "application/json")
        if path in ("/", "/index.html"):
            return self._file("index.html")
        return self._file(path.lstrip("/"))

    do_HEAD = do_GET

    def _refuse_write(self):
        """Only the owning process may push state.

        The body is drained before the refusal: answering an unread request
        makes Windows reset the connection, so a well-behaved client would see
        a socket error instead of this JSON error.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length > 0:
            try:
                self.rfile.read(min(length, 1 << 20))
            except OSError:
                pass
        body = b'{"error":"read-only endpoint; state is pushed in-process"}'
        return self._send(405, body, "application/json", {"Allow": "GET, HEAD"})

    do_POST = _refuse_write
    do_PUT = _refuse_write
    do_DELETE = _refuse_write
    do_PATCH = _refuse_write


def start(port: int = DEFAULT_PORT, period: float = 1.0,
          *, prime: bool = True) -> tuple[ThreadingHTTPServer, Sampler]:
    """Bind and serve in a background thread; return (server, sampler).

    Called by ``main()`` below and by JARVIS itself when it launches the HUD,
    so the page and the assistant share one process and one state dict.
    Raises OSError if the port is taken - the caller decides what to do.
    """
    sampler = Sampler()
    # Prime once so the very first request already has numbers; the threads
    # then take over without the page ever seeing an empty snapshot.
    if prime:
        sampler.prime()
    sampler.start(period)

    Handler.sampler = sampler
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="telemetry-http",
                     daemon=True).start()
    return httpd, sampler


def serve(port: int = DEFAULT_PORT, period: float = 1.0) -> None:
    httpd, sampler = start(port, period)

    url = f"http://127.0.0.1:{port}/"
    print(f"[MK85] telemetry on http://127.0.0.1:{port}/telemetry")
    print(f"[MK85] HUD at          {url}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[MK85] stopping")
    finally:
        sampler.stop()
        httpd.shutdown()
        httpd.server_close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MK-LXXXV HUD telemetry bridge")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--period", type=float, default=1.0, help="sample period, seconds")
    ap.add_argument("--open", action="store_true", help="open the HUD as a Chrome app window")
    args = ap.parse_args(argv)

    if args.open:
        threading.Thread(
            target=lambda: (time.sleep(0.8), webbrowser.open(
                f"http://127.0.0.1:{args.port}/")),
            daemon=True,
        ).start()
    try:
        serve(args.port, args.period)
    except OSError as e:
        print(f"[MK85] cannot bind 127.0.0.1:{args.port}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
