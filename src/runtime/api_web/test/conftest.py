"""Host pytest imports for the split API and gateway packages."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
for path in (SRC / "runtime" / "api_web", SRC / "runtime" / "gateway",
             SRC / "contracts" / "foundation", SRC / "runtime" / "events",
             SRC / "runtime" / "services", SRC / "runtime" / "sensing"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
