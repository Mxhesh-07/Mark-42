"""Tier 4 W4 — the device layer (multi-device + remote).

Everything the assistant could reach used to be this one Windows PC. This adds a
registry of *other* machines and a single tool, ``devices``, over it.

Three rules shape the module:

1. **Capabilities are declared per device.** A device that does not list a
   capability does not have it, and asking for it is refused — not attempted.
2. **Some capabilities can never be quiet.** ``sms`` and ``call`` reach other
   people, so their blast radius is ``other_people`` and the permission gate
   raises them to at least ``confirm``. ``shell`` is always blocked. Both are
   enforced in ``policy._guards``, so neither a config edit nor a caller can
   widen them (see the W6/W4 hard-rule tests).
3. **A device address must be private.** The registry is checked before any
   transport runs: a public address is refused outright. ADB has no
   authentication of its own, so the only safe topology is a mesh (Tailscale /
   WireGuard) where every device dials *out* and nothing is port-forwarded.

The transports (adb, ssh, http, mqtt, serial) are lazy: nothing is imported until
a capability actually needs it, and an unavailable transport is reported as a
failure. A failure is never rendered as success.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

# A capability -> (policy floor, reversibility, blast radius).
#
# The policy floor is the *minimum* strictness the capability may have, used by
# the tests and the docs as the intent; the binding table the gate actually reads
# is `config/autonomy.json` -> actions.devices. `other_people` and `block` floors
# are additionally enforced in `policy._guards` and cannot be relaxed by config.
CAPABILITIES: dict[str, tuple[str, str, str]] = {
    "list":       ("allow",   "reversible",  "self"),
    "info":       ("allow",   "reversible",  "self"),
    "status":     ("allow",   "reversible",  "self"),
    "notify":     ("allow",   "reversible",  "local"),
    "screenshot": ("allow",   "reversible",  "local"),
    "ring":       ("allow",   "reversible",  "local"),
    "media":      ("confirm", "recoverable", "local"),
    "lock":       ("confirm", "recoverable", "local"),
    "wol":        ("confirm", "recoverable", "local"),
    "exec":       ("confirm", "permanent",   "local"),
    "sms":        ("confirm", "permanent",   "other_people"),
    "call":       ("confirm", "permanent",   "other_people"),
    "shell":      ("block",   "permanent",   "network"),
}

OTHER_PEOPLE = frozenset(name for name, spec in CAPABILITIES.items()
                         if spec[2] == "other_people")
ALWAYS_BLOCKED = frozenset(name for name, spec in CAPABILITIES.items()
                           if spec[0] == "block")

# Capabilities that make sense without naming a specific device.
REGISTRY_ACTIONS = ("list",)

TRANSPORTS = ("adb", "ssh", "http", "mqtt", "serial")

_lock = threading.RLock()


class TransportError(RuntimeError):
    """A transport could not carry the request. Never raised as success."""


# --- paths --------------------------------------------------------------------

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = get_base_dir()
CONFIG_PATH = BASE_DIR / "config" / "devices.json"

DEFAULT_CONFIG: dict = {"enabled": True, "devices": {}}


# --- the registry -------------------------------------------------------------

def load_config() -> dict:
    with _lock:
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return dict(DEFAULT_CONFIG)
        except Exception:
            return dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return dict(DEFAULT_CONFIG)
    return raw


def registry() -> dict:
    raw = load_config().get("devices")
    if not isinstance(raw, dict):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def names() -> list[str]:
    return sorted(registry())


def get(name: str) -> dict | None:
    return registry().get(str(name or "").strip())


def capabilities(name: str) -> list[str]:
    device = get(name)
    if device is None:
        return []
    declared = device.get("capabilities") or []
    if not isinstance(declared, list):
        return []
    known = [str(c).strip().lower() for c in declared]
    return [c for c in known if c in CAPABILITIES]


def describe(name: str) -> dict:
    device = get(name)
    if device is None:
        return {"device": name, "known": False, "error": f"unknown device: {name!r}"}
    return {
        "device": name,
        "known": True,
        "transport": str(device.get("transport") or ""),
        "capabilities": capabilities(name),
        "policy_key": str(device.get("policy_key") or name),
    }


def summary() -> list[dict]:
    return [describe(name) for name in names()]


def register(name: str, spec: dict) -> dict:
    """Add or replace a device in the registry. Config-shaped, never inferred."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("a device needs a name")
    if not isinstance(spec, dict):
        raise ValueError("a device spec must be an object")
    transport = str(spec.get("transport") or "").strip().lower()
    if transport not in TRANSPORTS:
        raise ValueError(f"unknown transport {transport!r}; one of {', '.join(TRANSPORTS)}")
    cfg = load_config()
    devices = dict(cfg.get("devices") or {})
    devices[name] = spec
    cfg["devices"] = devices
    _save(cfg)
    return describe(name)


def forget(name: str) -> bool:
    cfg = load_config()
    devices = dict(cfg.get("devices") or {})
    if str(name) not in devices:
        return False
    devices.pop(str(name))
    cfg["devices"] = devices
    _save(cfg)
    return True


def _save(cfg: dict) -> None:
    try:
        from agent import atomic

        atomic.write_json(CONFIG_PATH, cfg, indent=2)
    except Exception as e:  # pragma: no cover - disk trouble
        print(f"[Devices] ⚠️ could not save the registry: {e}")


def reset_for_tests() -> None:
    with _lock:
        try:
            CONFIG_PATH.unlink(missing_ok=True)
        except Exception:
            pass


# --- capability checks --------------------------------------------------------

def canonical(capability) -> str:
    return str(capability or "").strip().lower()


def check(target: str, capability, params: dict | None = None) -> tuple[bool, str]:
    """``(allowed, why)`` for a capability on a device. Refuses, never guesses."""
    device = get(target)
    if device is None:
        return False, f"unknown device: {target!r}"
    cap = canonical(capability)
    if not cap:
        return False, "a capability name is required"
    if cap not in CAPABILITIES:
        return False, f"unknown capability: {capability!r}"
    if cap not in capabilities(target):
        return False, f"{target!r} does not expose the {cap!r} capability"
    return True, "ok"


def blast_radius(capability) -> str:
    spec = CAPABILITIES.get(canonical(capability))
    return spec[2] if spec else "network"


def reversibility(capability) -> str:
    spec = CAPABILITIES.get(canonical(capability))
    return spec[1] if spec else "recoverable"


def reaches_other_people(capability) -> bool:
    return canonical(capability) in OTHER_PEOPLE


# --- addresses ----------------------------------------------------------------

_CGNAT = ipaddress.ip_network("100.64.0.0/10")     # Tailscale / carrier-grade NAT


def address_allowed(address: str) -> tuple[bool, str]:
    """A device address must be private. ADB over a public address is a backdoor.

    Accepts private, loopback and carrier-grade-NAT (Tailscale) ranges, and a
    hostname only if *every* address it resolves to is in one of those ranges.
    """
    text = str(address or "").strip()
    if not text:
        return False, "no address"
    host = text.rsplit(":", 1)[0] if text.count(":") == 1 else text
    host = host.strip("[]")

    def _ok(ip: ipaddress._BaseAddress) -> bool:
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip in _CGNAT)

    try:
        return (True, "private address") if _ok(ipaddress.ip_address(host)) \
            else (False, "public address refused: never expose a device to the internet")
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False, f"cannot resolve {host!r}"
    if not infos:
        return False, f"cannot resolve {host!r}"
    for info in infos:
        try:
            if not _ok(ipaddress.ip_address(info[4][0])):
                return False, (f"{host!r} resolves to a public address; "
                               "use a private mesh (Tailscale/WireGuard)")
        except ValueError:
            return False, f"unexpected address for {host!r}"
    return True, "private address"


# --- transports ---------------------------------------------------------------

def _have(command: str) -> bool:
    return shutil.which(command) is not None


def _have_module(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def _require_adb() -> str:
    exe = shutil.which("adb")
    if not exe:
        raise TransportError("the 'adb' transport needs platform-tools on PATH")
    return exe


def _require_ssh() -> str:
    exe = shutil.which("ssh")
    if not exe:
        raise TransportError("the 'ssh' transport needs an ssh client on PATH")
    return exe


def _run(argv: list[str], timeout: float = 15.0) -> tuple[bool, str]:
    """Run a fixed argv (never a shell string) and capture the outcome."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, shell=False)
    except FileNotFoundError:
        raise TransportError(f"{argv[0]!r} is not executable")
    except subprocess.TimeoutExpired:
        raise TransportError(f"{argv[0]!r} timed out after {timeout:.0f}s")
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    return proc.returncode == 0, out[:2000]


def _adb(device: dict, capability: str, params: dict) -> str:
    exe = _require_adb()
    address = str(device.get("address") or "")
    if not address:
        raise TransportError("this device has no address")
    if capability == "info":
        argv = [exe, "-s", address, "shell", "getprop", "ro.product.model"]
    elif capability == "status":
        argv = [exe, "-s", address, "get-state"]
    elif capability == "ring":
        argv = [exe, "-s", address, "shell", "cmd", "telephony", "ring"]
    elif capability == "lock":
        argv = [exe, "-s", address, "shell", "input", "keyevent", "26"]
    elif capability == "notify":
        argv = [exe, "-s", address, "shell", "cmd", "notification", "post",
                "-t", str(params.get("title") or "JARVIS"),
                str(params.get("text") or params.get("message") or "")]
    elif capability in ("sms", "call"):
        number = str(params.get("number") or params.get("to") or "")
        if not number:
            raise TransportError(f"{capability} needs a number")
        if capability == "call":
            argv = [exe, "-s", address, "shell", "am", "start", "-a",
                    "android.intent.action.CALL", "-d", f"tel:{number}"]
        else:
            argv = [exe, "-s", address, "shell", "service", "call", "isms", "7",
                    "s16", address, "s16", number,
                    "s16", str(params.get("text") or params.get("message") or "")]
    elif capability == "screenshot":
        argv = [exe, "-s", address, "exec-out", "screencap", "-p"]
    else:
        raise TransportError(f"the adb transport cannot do {capability!r}")
    ok, detail = _run(argv)
    if not ok:
        raise TransportError(detail or "adb reported a failure")
    return detail or "ok"


def _ssh(device: dict, capability: str, params: dict) -> str:
    exe = _require_ssh()
    address = str(device.get("address") or "")
    if not address:
        raise TransportError("this device has no address")
    if capability == "status":
        argv = [exe, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", address,
                "uname -a || ver"]
    elif capability == "exec":
        command = str(params.get("command") or params.get("cmd") or "")
        if not command:
            raise TransportError("exec needs a command")
        argv = [exe, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", address, command]
    else:
        raise TransportError(f"the ssh transport cannot do {capability!r}")
    ok, detail = _run(argv)
    if not ok:
        raise TransportError(detail or "ssh reported a failure")
    return detail or "ok"


def _http(device: dict, capability: str, params: dict) -> str:
    import urllib.request

    address = str(device.get("address") or "")
    if not address:
        raise TransportError("this device has no address")
    base = address if address.startswith(("http://", "https://")) else f"http://{address}"
    url = f"{base.rstrip('/')}/{capability}"
    body = json.dumps(params or {}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.read().decode("utf-8", "replace")[:2000] or "ok"
    except Exception as e:
        raise TransportError(f"http transport failed: {e}")


def _mqtt(device: dict, capability: str, params: dict) -> str:
    if not _have_module("paho.mqtt.client"):
        raise TransportError("the 'mqtt' transport needs the paho-mqtt package")
    raise TransportError("the 'mqtt' transport is configured but not wired to a broker here")


def _serial(device: dict, capability: str, params: dict) -> str:
    if not _have_module("serial"):
        raise TransportError("the 'serial' transport needs the pyserial package")
    raise TransportError("the 'serial' transport is configured but not wired to a port here")


_TRANSPORTS = {"adb": _adb, "ssh": _ssh, "http": _http,
               "mqtt": _mqtt, "serial": _serial}


def transport_available(name: str) -> bool:
    name = str(name or "").strip().lower()
    if name == "adb":
        return _have("adb")
    if name == "ssh":
        return _have("ssh")
    if name == "http":
        return True
    if name == "mqtt":
        return _have_module("paho.mqtt.client")
    if name == "serial":
        return _have_module("serial")
    return False


# --- the one entry point ------------------------------------------------------

def dispatch(action: str, target: str = "", cmd: str = "", **params) -> dict:
    """``devices(action, target, cmd, **params)`` -> a JSON-able result.

    Never raises for an expected failure: the caller is a language model, and it
    needs to *see* a failure to report it instead of inventing success.
    """
    action = str(action or "list").strip().lower()

    if not load_config().get("enabled", True):
        return _fail("the device layer is disabled in config/devices.json")

    if action in REGISTRY_ACTIONS:
        return {"ok": True, "action": "list", "devices": summary()}

    if action not in ("status", "run"):
        return _fail(f"unknown action {action!r}; use list, status or run")

    target = str(target or "").strip()
    capability = canonical(cmd) or ("status" if action == "status" else "")
    if not target:
        return _fail("a target device is required")
    if not capability:
        return _fail("a capability (cmd) is required")

    ok, why = check(target, capability)
    if not ok:
        return _fail(why, device=target, capability=capability)

    device = get(target) or {}
    transport = str(device.get("transport") or "").strip().lower()
    if transport not in _TRANSPORTS:
        return _fail(f"unknown transport {transport!r}", device=target)

    if capability in ALWAYS_BLOCKED:
        return _fail(f"the {capability!r} capability is always blocked",
                     device=target, capability=capability)

    address = str(device.get("address") or "")
    allowed, address_why = address_allowed(address)
    if not allowed:
        return _fail(address_why, device=target, capability=capability)

    try:
        detail = _TRANSPORTS[transport](device, capability, params)
    except TransportError as e:
        return _fail(str(e), device=target, capability=capability, transport=transport)
    except Exception as e:                      # a transport bug is still a failure
        return _fail(f"{transport} transport error: {e}", device=target,
                     capability=capability, transport=transport)

    return {"ok": True, "device": target, "capability": capability,
            "transport": transport, "detail": detail}


def _fail(reason: str, **extra) -> dict:
    result = {"ok": False, "error": reason}
    result.update(extra)
    return result


def render(result: dict) -> str:
    """A one-line human summary of a dispatch result."""
    if not result.get("ok"):
        return f"devices: failed — {result.get('error')}"
    if "devices" in result:
        rows = result["devices"]
        if not rows:
            return "devices: none registered"
        return "devices: " + "; ".join(
            f"{r['device']} ({r.get('transport') or '?'}: "
            f"{', '.join(r.get('capabilities') or []) or 'none'})" for r in rows)
    return (f"devices: {result.get('device')} {result.get('capability')} ok — "
            f"{result.get('detail') or ''}").strip()


def status() -> dict:
    return {
        "enabled": bool(load_config().get("enabled", True)),
        "path": str(CONFIG_PATH),
        "count": len(names()),
        "devices": summary(),
        "capabilities": {name: {"reversibility": spec[1], "blast_radius": spec[2],
                                "policy_floor": spec[0]}
                         for name, spec in sorted(CAPABILITIES.items())},
        "transports": {name: transport_available(name) for name in TRANSPORTS},
    }


def _cli(argv=None) -> int:
    from agent import console

    console.enable_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "run":
        target = argv[1] if len(argv) > 1 else ""
        cmd = argv[2] if len(argv) > 2 else ""
        print(render(dispatch("run", target=target, cmd=cmd)))
        return 0
    print(json.dumps(status(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
