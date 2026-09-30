"""colcon install 없이 pytest를 돌린다 (Windows/CI)."""

from __future__ import annotations

import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[2]
SRC = Path(__file__).resolve().parents[3]
TEST = Path(__file__).resolve().parent
for path in (
    SITE / "overhead",
    SITE / "fleet",
    SRC / "runtime" / "services",
    SRC / "contracts" / "foundation",
    SRC / "site" / "games",
):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
if str(TEST) not in sys.path:
    sys.path.insert(0, str(TEST))
