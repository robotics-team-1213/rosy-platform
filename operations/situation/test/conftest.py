"""Run without installing: the service package and, for the live-Fleet test, Fleet and its contracts."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
for path in (REPO / "operations" / "situation", REPO / "operations" / "fleet", REPO / "operations" / "fleet" / "test",
             REPO / "test", REPO / "contracts" / "foundation", REPO / "middleware" / "core" / "services"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
