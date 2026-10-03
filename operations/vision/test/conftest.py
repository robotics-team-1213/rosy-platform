"""colcon install 없이 pytest를 돌린다 (Windows/CI)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "src"
TEST = Path(__file__).resolve().parent
for path in (
    REPO / "operations" / "vision",
    SRC / "site" / "fleet",
    SRC / "runtime" / "services",
    SRC / "contracts" / "foundation",
    REPO / "operations" / "apps" / "games",
):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
if str(TEST) not in sys.path:
    sys.path.insert(0, str(TEST))
