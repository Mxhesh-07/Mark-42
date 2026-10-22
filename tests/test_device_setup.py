"""Tier 1.6 — microphone discovery and gain, tested without real hardware."""

from __future__ import annotations

import numpy as np

from jarvis import device_setup


class FakeStream:
    def __init__(self, peak: int):
        self.peak = peak
        self.closed = False

    def read(self, frames, exception_on_overflow=True):
        return (np.full(frames, self.peak, dtype=np.int16)).tobytes()

    def close(self):
        self.closed = True


class FakePA:
    def __init__(self, devices, default=None, peak=500):
        self.devices = devices
        self.default = default
        self.peak = peak
        self.opened = []

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def get_default_input_device_info(self):
        if self.default is None:
            raise OSError("no default")
        return {"index": self.default}

    def open(self, **kwargs):
        index = kwargs["input_device_index"]
        self.opened.append(index)
        return FakeStream(self.peak)


class FakeAudioModule:
    def __init__(self, pa):
        self.pa = pa

    def open_pyaudio(self):
        return self.pa

    def close(self, _pa):
        return None


def _devices():
    return [
        {"name": "Stereo Mix (Realtek)", "maxInputChannels": 2, "hostApi": 0},
        {"name": "Microphone Array (Realtek)", "maxInputChannels": 1, "hostApi": 0},
        {"name": "USB Microphone", "maxInputChannels": 1, "hostApi": 2},
    ]


def test_virtual_endpoints_are_never_chosen():
    pa = FakePA(_devices(), default=1)
    spec = device_setup.CaptureSpec()
    assert device_setup.pick_input_device({}, spec, FakeAudioModule(pa)) == 1
    assert 0 not in pa.opened


def test_default_device_is_used_when_it_captures_sound():
    pa = FakePA(_devices(), default=1)
    spec = device_setup.CaptureSpec()
    assert device_setup.pick_input_device({}, spec, FakeAudioModule(pa)) == 1


def test_a_silent_default_falls_through_to_a_live_mic():
    pa = FakePA(_devices(), default=1)
    spec = device_setup.CaptureSpec()

    class Silent(FakePA):
        def open(self, **kwargs):
            index = kwargs["input_device_index"]
            self.opened.append(index)
            return FakeStream(0 if index == 1 else 500)

    quiet = Silent(_devices(), default=1)
    assert device_setup.pick_input_device({}, spec, FakeAudioModule(quiet)) == 2


def test_config_can_pin_an_index_or_a_name():
    pa = FakePA(_devices(), default=1)
    spec = device_setup.CaptureSpec()
    module = FakeAudioModule(pa)
    assert device_setup.pick_input_device(
        {"input_device": 2}, spec, module) == 2
    assert device_setup.pick_input_device(
        {"input_device": "array"}, spec, module) == 1


def test_unknown_pinned_name_falls_back_to_auto_detection():
    pa = FakePA(_devices(), default=1)
    spec = device_setup.CaptureSpec()
    messages = []
    result = device_setup.pick_input_device(
        {"input_device": "not-a-mic"}, spec, FakeAudioModule(pa),
        printer=messages.append,
    )
    assert result == 1
    assert any("not-a-mic" in line for line in messages)


def test_a_broken_stream_is_rejected_not_treated_as_loud():
    spec = device_setup.CaptureSpec()
    pa = FakePA(_devices(), default=1, peak=spec.bad_peak)
    assert device_setup.device_peak(pa, 1, spec, seconds=0.01) == -1


def test_device_name_and_mic_level_fail_soft(monkeypatch):
    pa = FakePA(_devices(), default=1)
    assert device_setup.device_name(1, FakeAudioModule(pa)) == (
        "Microphone Array (Realtek)")
    assert device_setup.device_name(None, FakeAudioModule(pa)) == ""
    assert device_setup.apply_mic_level("x", 0.5,
                                        printer=lambda _m: None) in (True, False)


def test_audio_config_missing_file_is_an_empty_dict(tmp_path):
    assert device_setup.load_audio_config(tmp_path) == {}
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "audio.json").write_text(
        '{"input_device": "array"}', encoding="utf-8")
    assert device_setup.load_audio_config(tmp_path)["input_device"] == "array"
