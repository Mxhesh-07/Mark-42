"""Tier 1.5 — platform adapters with no-op fallbacks.

The core used to import Windows-only packages at module scope, so `import main`
on Linux failed before any feature was reached. Adapters keep those imports
lazy and localised; an unsupported platform gets a clean "not available" instead
of an ImportError.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    from core.platform.win import (  # noqa: F401
        beep, get_master_volume, is_windows, notify, set_master_volume,
        set_mic_level,
    )
else:
    from core.platform.base import (  # noqa: F401
        beep, get_master_volume, is_windows, notify, set_master_volume,
        set_mic_level,
    )
