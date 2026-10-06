"""colcon install 없이 pytest 를 돌린다 (Windows/CI).

`fleet` 은 `core_common.protocol.schemas` 를 import 한다(D-18, D-126). 두 패키지 모두
소스 트리에서 바로 찾도록 sys.path 를 잡는다 — 루트 `test/conftest.py` 가
`deploy/robot/pinky_pro/release` 에 하는 것과 같은 방식이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = (Path(__file__).resolve().parents[3] / "src")

# Each entry is the *outer* ROS-package dir, so the inner Python package
# (which owns __init__.py) resolves: fleet, core_common (prod, D-126 S3),
# core_features (test_geometry.py follow_goal cross-check only, D-60).
for path in (
    SRC.parent / "operations" / "fleet",
    SRC.parent / "contracts" / "foundation",
    SRC.parent / "middleware" / "core" / "services",
    # Cell app tests import this production dependency before test_cell_compiler.
    SRC.parent / "operations" / "processes" / "palletizing" / "src",
):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)


import pytest  # noqa: E402

#: D-484: the planner and the meet geometry read the active site map. Tests use the
#: map_v2_fleet lane graph imported the same way ``--site-map-import`` does.
LANE_GRAPH = SRC.parent / "middleware" / "perception" / "map" / "map_v2_fleet" / "lane_graph.yaml"


@pytest.fixture(autouse=True)
def _active_site_map_painted():
    from fleet.meet.place import painted_from, use_painted
    from fleet.site_map import from_lane_graph

    use_painted(painted_from(from_lane_graph(LANE_GRAPH)))
    yield
    use_painted(None)
