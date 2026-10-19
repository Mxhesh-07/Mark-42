"""Health, readiness and status surface (Tier 2 B4 / C4).

Three questions, three answers:

  /health   is the process alive and are its subsystems usable?   (self-check)
  /ready    may the assistant take a new request right now?
  /status   a full JSON dump: policy, breakers, queue depth, degradation,
            metrics, memory size, kill switch.

The endpoint is bound to loopback only and is read-only, so it is safe to leave
running. Nothing secret is included: keys are reported as present/absent.

``python -m agent.health`` prints the same JSON once, which is what a startup
self-check needs without opening a socket.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import time

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8799
MIN_FREE_BYTES = 1 * 1024 * 1024 * 1024   # 1 GB


def _ok(detail: str = "", **extra) -> dict:
    return {"ok": True, "detail": detail, **extra}


def _bad(detail: str, **extra) -> dict:
    return {"ok": False, "detail": detail, **extra}


# --- individual checks --------------------------------------------------------

def check_policy() -> dict:
    try:
        from agent import policy

        pol = policy.load_policy()
        if not isinstance(pol, dict):
            return _bad("policy is not an object")
        if not pol.get("tools") and not pol.get("actions"):
            return _bad("policy lists no tools")
        return _ok("policy loaded", kill_switch=policy.kill_requested())
    except Exception as e:
        return _bad(f"policy unreadable: {e}")


def check_config() -> dict:
    try:
        from memory import config_manager

        if config_manager.config_exists():
            return _ok("api keys present")
        return _bad("no config/api_keys.json yet")
    except Exception as e:
        return _bad(f"config unreadable: {e}")


def check_keys() -> dict:
    """Are placeholders still in place?  Never echoes the value."""
    try:
        from memory import config_manager

        keys = config_manager.load_api_keys() or {}
        present = [k for k, v in keys.items() if str(v).strip()]
        if not present:
            return _bad("no API keys set")
        placeholders = [k for k in present if _looks_like_placeholder(keys[k])]
        if placeholders:
            return _bad(f"placeholder value in {', '.join(placeholders)}")
        return _ok(f"{len(present)} key(s) set")
    except Exception as e:
        return _bad(f"keys unreadable: {e}")


def _looks_like_placeholder(value) -> bool:
    text = str(value).strip().lower()
    if not text:
        return True
    return text in {"your_api_key_here", "changeme", "todo", "xxx", "sk-xxx"} or \
        text.startswith("your_") or text.startswith("<")


def check_disk() -> dict:
    try:
        from agent import audit

        root = str(audit.BASE_DIR)
        usage = shutil.disk_usage(root)
        if usage.free < MIN_FREE_BYTES:
            return _bad(f"only {usage.free // (1024 * 1024)} MB free")
        return _ok("disk space", free_mb=usage.free // (1024 * 1024))
    except Exception as e:
        return _bad(f"disk check failed: {e}")


def check_breaker() -> dict:
    try:
        from agent import breaker

        open_names = breaker.open_names()
        if open_names:
            return _bad(f"open: {', '.join(open_names)}")
        return _ok("no circuit breakers open")
    except Exception as e:
        return _bad(f"breaker state unreadable: {e}")


def check_memory() -> dict:
    try:
        from memory import sql_memory

        stats = sql_memory.stats()
        return _ok("memory readable", **stats)
    except Exception as e:
        return _bad(f"memory unreadable: {e}")


def check_mic() -> dict:
    """Optional: only meaningful when PyAudio and a device exist.

    PortAudio creation is serialized through :mod:`agent.audio`, because a
    concurrent ``PyAudio()`` can crash the process rather than raise.
    """
    try:
        from agent import audio
    except Exception:
        return _ok("mic check skipped (PyAudio not installed)", skipped=True)
    instance = None
    try:
        instance = audio.open_pyaudio()
    except ImportError:
        return _ok("mic check skipped (PyAudio not installed)", skipped=True)
    except Exception as e:
        return _bad(f"mic probe failed: {e}")
    try:
        if instance.get_device_count() < 1:
            return _bad("no input device")
        default = instance.get_default_input_device_info()
        return _ok("input device present", device=default.get("name"))
    except Exception as e:
        return _bad(f"mic probe failed: {e}")
    finally:
        audio.close(instance)


def probe_audio() -> dict:
    """The microphone probe on its own, for an explicit readiness check.

    Deliberately *not* part of the startup self-check: it is the only check that
    initialises a C library, so it is run on demand rather than from a
    background thread during import.
    """
    return check_mic()


def check_model() -> dict:
    """Optional: is at least one provider reachable? Uses a cheap HEAD/DNS."""
    try:
        import socket

        socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=3).close()
        return _ok("model endpoint reachable")
    except Exception as e:
        return _bad(f"model endpoint unreachable: {e}")


def checks(full: bool = False, audio: bool | None = None) -> dict:
    """Run the subsystem checks.

    ``full``   also probe the network (a cheap connect; safe from a thread).
    ``audio``  also probe the microphone. Defaults to ``full`` for backward
               compatibility, but callers on a background thread must pass
               ``audio=False``: this is the one check that initialises PortAudio.
    """
    if audio is None:
        audio = full
    result = {
        "policy": check_policy(),
        "config": check_config(),
        "keys": check_keys(),
        "disk": check_disk(),
        "breaker": check_breaker(),
        "memory": check_memory(),
    }
    if full:
        result["model"] = check_model()
    if audio:
        result["mic"] = check_mic()
    return result


def self_check(full: bool = False, audio: bool | None = None) -> dict:
    """B4: run at startup, log the outcome, keep going regardless."""
    started = time.perf_counter()
    result = checks(full=full, audio=audio)
    failed = {name: c["detail"] for name, c in result.items()
              if not c["ok"] and not c.get("skipped")}
    outcome = {
        "ok": not failed,
        "failed": failed,
        "checks": result,
        "took_ms": round((time.perf_counter() - started) * 1000.0, 2),
    }
    if failed:
        summary = "; ".join(f"{k}: {v}" for k, v in failed.items())
        print(f"[Health] ⚠️ self-check: {summary}")
    else:
        skipped = [k for k, c in result.items() if c.get("skipped")]
        note = f" ({len(skipped)} skipped)" if skipped else ""
        print(f"[Health] ✅ self-check passed in {outcome['took_ms']:.0f} ms{note}")
    try:
        from agent import audit

        audit.record("self_check", outcome="ok" if outcome["ok"] else "warn",
                     detail="; ".join(f"{k}: {v}" for k, v in failed.items()) or "all checks passed")
    except Exception:
        pass
    return outcome


# --- readiness ----------------------------------------------------------------

def ready() -> dict:
    """May a new request start right now?"""
    reasons: list[str] = []
    try:
        from agent import degrade, policy

        if policy.kill_requested():
            reasons.append("kill switch engaged")
        if not degrade.allows_tools():
            reasons.append(f"degraded to {degrade.level()}")
    except Exception as e:
        reasons.append(f"readiness probe failed: {e}")
    return {"ready": not reasons, "reasons": reasons}


# --- the aggregate view -------------------------------------------------------

def status() -> dict:
    out: dict = {"ts": time.time()}
    try:
        from agent import policy

        out["policy"] = policy.status()
    except Exception as e:
        out["policy"] = {"error": str(e)}
    try:
        from agent import breaker

        out["breakers"] = breaker.snapshot()
    except Exception as e:
        out["breakers"] = {"error": str(e)}
    try:
        from agent import degrade

        out["degradation"] = degrade.status()
    except Exception as e:
        out["degradation"] = {"error": str(e)}
    try:
        from agent import metrics

        out["metrics"] = metrics.snapshot()
    except Exception as e:
        out["metrics"] = {"error": str(e)}
    try:
        from agent import task_queue

        # Read the singleton directly: status must never have the side effect
        # of starting the worker threads.
        queue = getattr(task_queue, "_queue", None)
        out["queue"] = {
            "depth": len(getattr(queue, "_queue", []) or []),
            "active": getattr(queue, "_active_count", 0),
            "started": bool(getattr(task_queue, "_queue_started", False)),
        }
    except Exception as e:
        out["queue"] = {"error": str(e)}
    try:
        from memory import sql_memory

        out["memory"] = sql_memory.stats()
    except Exception as e:
        out["memory"] = {"error": str(e)}
    out["ready"] = ready()
    return out


# --- HTTP surface -------------------------------------------------------------

def _handler_factory(payload_fn):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        server_version = "JarvisHealth/1.0"

        def _send(self, code: int, body: str, content_type: str = "application/json") -> None:
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:   # noqa: N802 - stdlib naming
            try:
                code, body, ctype = payload_fn(self.path)
            except Exception as e:
                code, body, ctype = 500, json.dumps({"error": str(e)}), "application/json"
            self._send(code, body, ctype)

        def log_message(self, *args) -> None:   # keep the console clean
            return

    return Handler


def routes() -> dict:
    """Path -> (status_code, body, content_type). Exposed for tests."""

    def _json(code, obj):
        return code, json.dumps(obj, indent=2, default=str), "application/json"

    def _health(query: str = ""):
        result = checks(audio="full" in query)
        failed = {k: v for k, v in result.items() if not v["ok"] and not v.get("skipped")}
        return _json(200 if not failed else 503, {"ok": not failed, "checks": result})

    def _ready(_query: str = ""):
        result = ready()
        return _json(200 if result["ready"] else 503, result)

    def _status(_query: str = ""):
        return _json(200, status())

    def _metrics(_query: str = ""):
        from agent import metrics as metrics_mod

        return 200, metrics_mod.render(), "text/plain; version=0.0.4"

    return {
        "/": (lambda _query="": _json(200, {"service": "jarvis", "endpoints":
                                            ["/health", "/ready", "/status", "/metrics"]})),
        "/health": _health,
        "/ready": _ready,
        "/status": _status,
        "/metrics": _metrics,
    }


def resolve(path: str):
    route, _, query = str(path or "").partition("?")
    route = route.rstrip("/") or "/"
    table = routes()
    if route in table:
        return table[route](query)
    return 404, json.dumps({"error": "not found", "path": path}), "application/json"


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
    """Start the read-only HTTP surface on a daemon thread. Returns the server."""
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer((host, port), _handler_factory(resolve))
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="JarvisHealth")
    thread.start()
    return server


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--serve" in argv:
        port = DEFAULT_PORT
        for i, arg in enumerate(argv):
            if arg == "--port" and i + 1 < len(argv):
                port = int(argv[i + 1])
        server = serve(port=port)
        print(f"health endpoint on http://{DEFAULT_HOST}:{port}")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            server.shutdown()
        return 0
    full = "--full" in argv
    # A one-shot CLI owns the process, so the audio probe is safe here.
    outcome = self_check(full=full, audio="--no-audio" not in argv and full)
    print(json.dumps(outcome, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
