"""One-shot COM helper for :mod:`core.platform.win`.

Run as a *child process*, never imported by the app. pycaw/comtypes objects have
to be created and released on the same COM-initialised thread; when they are
created on an ``asyncio.to_thread`` worker and collected later elsewhere, the
release goes through a dead vtable and the interpreter dies with an access
violation in ``_ctypes.pyd`` - no traceback, the assistant just stops answering.

Quarantining the work in a child means the worst case is that this process exits
non-zero, the parent returns False, and JARVIS keeps talking.

Usage:
    python -X utf8 _com_child.py mic <device-name> <level>
    python -X utf8 _com_child.py mic-unmute <device-name>
    python -X utf8 _com_child.py mic-mute <device-name>      # prints 1 / 0
    python -X utf8 _com_child.py get
    python -X utf8 _com_child.py set <level>
"""

from __future__ import annotations

import sys


def _endpoint_volume():
    """The default speaker's volume interface.

    pycaw returns an ``AudioDevice`` wrapper these days, which exposes
    ``EndpointVolume``; older builds returned the raw ``IMMDevice``, hence the
    fallback. (The previous in-process helper only knew the raw form, so master
    volume silently returned ``None`` on this machine.)
    """
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    device = AudioUtilities.GetSpeakers()
    volume = getattr(device, "EndpointVolume", None)
    if volume is not None:
        return volume
    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def _run(argv: list[str]) -> int:
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    CoInitialize()
    try:
        op = argv[1] if len(argv) > 1 else ""

        if op in ("mic", "mic-unmute", "mic-mute"):
            name = (argv[2] if len(argv) > 2 else "").lower()
            enum = AudioUtilities.GetDeviceEnumerator()
            for dev in AudioUtilities.GetAllDevices(data_flow=1):
                if not name or name not in dev.FriendlyName.lower():
                    continue
                device = enum.GetDevice(dev.id)
                interface = device.Activate(
                    IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = cast(interface, POINTER(IAudioEndpointVolume))
                if op == "mic-mute":
                    print("1" if vol.GetMute() else "0")
                elif op == "mic-unmute":
                    vol.SetMute(0, None)
                    print("ok")
                else:
                    level = max(0.0, min(1.0, float(argv[3])))
                    vol.SetMute(0, None)     # a muted endpoint captures nothing
                    vol.SetMasterVolumeLevelScalar(level, None)
                    print("ok")
                return 0
            return 1

        if op == "get":
            vol = _endpoint_volume()
            print(f"{float(vol.GetMasterVolumeLevelScalar()):.4f}")
            return 0

        if op == "set":
            level = max(0.0, min(1.0, float(argv[2])))
            vol = _endpoint_volume()
            vol.SetMasterVolumeLevelScalar(level, None)
            print("ok")
            return 0

        return 2
    finally:
        try:
            CoUninitialize()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(_run(sys.argv))
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(1)
