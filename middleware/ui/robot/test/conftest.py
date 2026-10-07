"""Host pytest bootstrap for this suite."""

import sys
from pathlib import Path

# Browser tests here import test/browser_harness.py (opt-in flag, Chromium-safe ports).
_HARNESS = str(Path(__file__).resolve().parents[4] / "test")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
