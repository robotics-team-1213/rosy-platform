"""D-949: the D-766 ratchet rows are a refactoring queue, ordered by size.

Every set below is checked by equality against the measured ratchet rows, like
``KNOWN_VIOLATIONS`` elsewhere: a new member fails, and a member that left the band
fails until it is removed here, so the sets only shrink.
"""

import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "harness"))
import size_limits  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RATCHET, _SAFETY = size_limits.parse_ratchet((ROOT / size_limits.RATCHET).read_text(encoding="utf-8"))

#: Tier 1 (D-949 1): product files of 1,000 lines or more are split now. Only a split already
#: committed on another branch may stay here until that branch lands.
TIER1_IN_FLIGHT: set[str] = set()   # empty: console.py landed at 634 lines (2026-11-01)
#: Tier 2 (D-949 2): 800-999 lines. The next change that edits one of these splits it first.
TIER2_QUEUE = {
    "web/components.css", "fleet/fleet/server/missions/mission_store.py", "robot_ui/robot/app.js",
    "core/gateway/core/bridge/ros_bridge.py", "deploy/robot/pinky_pro/native/rosy-ssh-access.py",
    "simulation/gazebo/scripts/lane_live_view.html", "fleet/fleet/server/auth/enrollment.py",
    "tools/harness/rosy_harness.py", "drive/motion_limits/adapter/node.py", "fleet/fleet/server/app.py",
    "drive/behaviors/line_follow/manager.py", "web/ui.js",
}
#: D-949 3: test files over their 1,500-line limit, split by screen or subject in follow-up work.
TEST_QUEUE = {
    "test/test_fleet_console_browser.py", "test/test_dashboard_browser.py", "test/test_sd_writer_contract.py",
    "middleware/robot_ui/pilot/test/test_pilot_browser.py", "test/test_rosy_face.py",
    "operations/fleet/test/test_trip_runner.py", "middleware/core/events/test/test_audit.py",
}
#: D-949 4: size units over 10,000 lines; each needs a dated split plan before it is cut.
UNIT_QUEUE = {"control", "perception/front_camera/perception"}

_CODE = size_limits.CODE_SUFFIXES | size_limits.WEB_SUFFIXES


def _kind(key: str) -> str:
    if PurePosixPath(key).suffix not in _CODE:
        return "unit"
    return "test" if size_limits.is_test(key) else "product"


def _rows(kind: str, low: int, high: float = float("inf")) -> set[str]:
    return {key for key, count in RATCHET.items() if _kind(key) == kind and low <= count < high}


def test_no_product_file_of_1000_lines_or_more_stays_in_the_ratchet():
    assert _rows("product", 1000) == TIER1_IN_FLIGHT


def test_the_800_line_queue_only_shrinks():
    assert _rows("product", 800, 1000) == TIER2_QUEUE


def test_the_oversized_test_queue_only_shrinks():
    assert _rows("test", size_limits.TEST_LIMIT + 1) == TEST_QUEUE


def test_the_oversized_unit_queue_only_shrinks():
    assert _rows("unit", size_limits.UNIT_LIMIT + 1) == UNIT_QUEUE


def test_the_tier_sets_do_not_overlap():
    sets = (TIER1_IN_FLIGHT, TIER2_QUEUE, TEST_QUEUE, UNIT_QUEUE)
    assert sum(map(len, sets)) == len(set().union(*sets))
