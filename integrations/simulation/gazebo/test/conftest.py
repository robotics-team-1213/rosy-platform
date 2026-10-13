"""Host pytest bootstrap for this suite."""

import sys
from pathlib import Path

# Browser tests here import test/browser_harness.py (opt-in flag, Chromium-safe ports).
_HARNESS = str(Path(__file__).resolve().parents[4] / "test")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)

# Camera-ground launch contracts must also run when collected without the perception suite.
_PERCEPTION = str(Path(__file__).resolve().parents[4] / 'middleware' / 'perception')
if _PERCEPTION not in sys.path:
    sys.path.insert(0, _PERCEPTION)

# Standalone launch tests use the committed CORE defaults and operator overlay loader.
_FOUNDATION = str(Path(__file__).resolve().parents[4] / 'contracts' / 'foundation')
if _FOUNDATION not in sys.path:
    sys.path.insert(0, _FOUNDATION)
