"""colcon install 없이 pytest를 돌린다 (Windows/CI)."""

from __future__ import annotations

import sys
from pathlib import Path

CELL = Path(__file__).resolve().parents[1]
if str(CELL) not in sys.path:
    sys.path.insert(0, str(CELL))
