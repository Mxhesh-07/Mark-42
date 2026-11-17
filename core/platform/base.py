"""No-op platform implementations (Linux/macOS/anything not Windows)."""

from __future__ import annotations


def is_windows() -> bool:
    return False


def set_mic_level(device_name: str, level: float) -> bool:
    return False


def mic_muted(device_name: str) -> bool | None:
    return None


def unmute_mic(device_name: str) -> bool:
    return False


def beep(freq: int = 800, ms: int = 200) -> bool:
    return False


def notify(title: str, message: str, duration: int = 10) -> bool:
    return False


def get_master_volume() -> float | None:
    return None


def set_master_volume(level: float) -> bool:
    return False
