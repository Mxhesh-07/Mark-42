"""Hardware-accelerated Stark HUD desktop application using Pygame & PyOpenGL."""
from __future__ import annotations

import main_hud
from main_hud import HUDApp, JarvisUI, hud_queue
import sound_synth
from sound_synth import SoundSynth
import hud_elements
from hud_elements import (
    ARCHETYPE_THEMES,
    CoreVisualizer,
    RadarScanner,
    TelemetryGauges,
    CyberTerminal,
    ModeDock,
    HoloBanner,
)

__all__ = [
    "HUDApp",
    "JarvisUI",
    "hud_queue",
    "SoundSynth",
    "ARCHETYPE_THEMES",
    "CoreVisualizer",
    "RadarScanner",
    "TelemetryGauges",
    "CyberTerminal",
    "ModeDock",
    "HoloBanner",
]

if __name__ == "__main__":
    app = HUDApp()
    app.run()
