"""colcon install 없이 pytest 를 돌린다 (Windows/CI).

`fleet` 은 `core_common.protocol.schemas` 를 import 한다(D-18, D-126). 두 패키지 모두
소스 트리에서 바로 찾도록 sys.path 를 잡는다 — 루트 `test/conftest.py` 가
`deploy/release` 에 하는 것과 같은 방식이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]

# Each entry is the *outer* ROS-package dir, so the inner Python package
# (which owns __init__.py) resolves: fleet, core_common (prod, D-126 S3),
# core_features (test_geometry.py follow_goal cross-check only, D-60).
for path in (SRC / "site" / "fleet", SRC / "contracts" / "core_common", SRC / "runtime" / "core_features"):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
