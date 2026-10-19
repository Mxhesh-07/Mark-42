# 0014 — Devices is reach, and reach is the last thing to add

**Status:** accepted (2026-10-20)

## Context

Until now the assistant could only touch the machine it ran on. Reaching a phone
or a laptop is genuinely useful, and the obvious way to do it — ADB over the LAN,
an inbound port, a password in a config file — is also the way projects like this
become an open door. ADB has no authentication of its own.

This is W4, deliberately built **after** the behaviour layers (W1–W3, W5, W6), on
the stated principle that reach without behaviour just adds surface area.

## Decision

`agent/devices.py` exposes one tool, `devices`, with `list`, `status` and `run`,
over a registry in the gitignored `config/devices.json`.

1. **A capability is declared per device.** `capabilities()` filters the
   declaration to the known set, and `check()` refuses anything the device does
   not declare. A refusal is a value, not an exception — the caller is a language
   model, and it needs to be able to *report* the refusal.
2. **Two rules are not configurable.** `policy._guards` runs them after the table
   lookup and before the role cap, so no config edit, caller or attendance can
   widen them:
   * `sms` / `call` have blast radius `other_people`, so an `allow` in the config
     is raised to `confirm`. The invariant is that the *decision* is never
     `allow`, so no unattended path can ever send silently.
   * `shell` is always a hard `block`.
3. **A device address must be private.** `address_allowed()` accepts private,
   loopback and carrier-grade-NAT (Tailscale `100.64.0.0/10`) addresses, and a
   hostname only when every address it resolves to is in one of those ranges. A
   public address is refused before any transport runs. The registry's
   `address` is never port-forwarded, and the tool refuses to help you do it.
4. **Transports are lazy.** adb/ssh/http/mqtt/serial import nothing until a
   capability needs them; an unavailable one raises `TransportError`, and the
   result is `{"ok": false, ...}`. A transport bug is caught and reported as a
   failure too. Nothing here can render a failure as a success.
5. **Subprocesses are argv lists.** The adb and ssh transports build a fixed
   `argv` per capability and never use `shell=True`; no model-supplied text is
   interpolated into a command line, only into a single argument.
6. **The registry is state, not config.** It is gitignored, with a tracked
   `config/devices.example.json` template.

The registry can also be edited by hand and is re-read per call, so adding a
device does not need a restart.

## Consequences

- `judgement.classify` now refines `devices` by capability, so W2 scores an
  `sms` at `permanent` / `other_people` — the highest risk class — and offers the
  concrete alternative ("I can show you the exact message and number before
  anything sends").
- The remote topology the layer is designed for is a Tailscale/WireGuard mesh:
  every device dials *out*, no inbound ports, mutual auth. If phone access must
  survive this PC being off, the relay belongs on `cloud_jarvis.py`, not here.
- mDNS/SSDP discovery is **not** implemented (it needs a zeroconf library);
  `discover()` is the registry, and the example file documents the intent. That
  is a known, stated gap rather than a silent one.
