"""Windows implementations. Every import is local so importing this module on
Windows without pycaw/comtypes installed still succeeds and returns False.
"""

from __future__ import annotations


def is_windows() -> bool:
    return True


def _endpoint_volume():
    from ctypes import cast, POINTER

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume)), IAudioEndpointVolume


def set_mic_level(device_name: str, level: float) -> bool:
    """Set the capture level of the first input device matching `device_name`."""
    try:
        from ctypes import cast, POINTER

        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        enum = AudioUtilities.GetDeviceEnumerator()
        needle = str(device_name or "").lower()
        for dev in AudioUtilities.GetAllDevices(data_flow=1):
            if needle and needle in dev.FriendlyName.lower():
                imm = enum.GetDevice(dev.id)
                iface = imm.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = cast(iface, POINTER(IAudioEndpointVolume))
                vol.SetMute(0, None)
                vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(level))), None)
                return True
        return False
    except Exception:
        return False


def beep(freq: int = 800, ms: int = 200) -> bool:
    try:
        import winsound

        winsound.Beep(int(freq), int(ms))
        return True
    except Exception:
        return False


def notify(title: str, message: str, duration: int = 10) -> bool:
    try:
        from win10toast import ToastNotifier

        ToastNotifier().show_toast(str(title), str(message),
                                   duration=int(duration), threaded=False)
        return True
    except Exception:
        return False


def get_master_volume() -> float | None:
    try:
        vol, _ = _endpoint_volume()
        return float(vol.GetMasterVolumeLevelScalar())
    except Exception:
        return None


def set_master_volume(level: float) -> bool:
    try:
        vol, _ = _endpoint_volume()
        vol.SetMasterVolumeLevelScalar(max(0.0, min(1.0, float(level))), None)
        return True
    except Exception:
        return False
