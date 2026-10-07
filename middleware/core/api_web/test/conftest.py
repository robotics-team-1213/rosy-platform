"""Host pytest imports for the split API and gateway packages."""

import sys
from pathlib import Path

SRC = (Path(__file__).resolve().parents[4] / "src")
for path in (SRC.parent / "middleware" / "core" / "api_web", SRC.parent / "middleware" / "core" / "gateway",
             SRC.parent / "contracts" / "foundation", SRC.parent / "middleware" / "core" / "events",
             SRC.parent / "middleware" / "core" / "services", SRC.parent / "middleware" / "perception"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Browser tests here import test/browser_harness.py (opt-in flag, Chromium-safe ports).
_HARNESS = str(Path(__file__).resolve().parents[4] / "test")
if _HARNESS not in sys.path:
    sys.path.append(_HARNESS)
