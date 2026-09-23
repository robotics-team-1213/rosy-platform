"""D-184: behavior tests of other packages stay on a frozen exception list."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_IMPORT = re.compile(r"(?m)^(?:from|import)\s+(core_features|navigation|control)(?:\.|\s|$)")

# Set equality. A new path fails, and a path that moved into its package
# stays red until it is removed from this set.
KNOWN_EXTERNAL_BEHAVIOR_TESTS = frozenset({
    "src/core/core/test/test_absorption_command_validity.py",
    "src/core/core/test/test_api.py",
    "src/core/core/test/test_battery.py",
    "src/core/core/test/test_bridge_battery_policy.py",
    "src/core/core/test/test_control_absorption_safety.py",
    "src/core/core/test/test_control_policy_link.py",
    "src/core/core/test/test_control_sensor_adapter.py",
    "src/core/core/test/test_core_logic.py",
    "src/core/core/test/test_domain_model.py",
    "src/core/core/test/test_evidence.py",
    "src/core/core/test/test_fleet_agent.py",
    "src/core/core/test/test_initial_pose.py",
    "src/core/core/test/test_line_follow.py",
    "src/core/core/test/test_line_follow_api.py",
    "src/core/core/test/test_navigation_readiness.py",
    "src/core/core/test/test_operational_journey.py",
    "src/core/core/test/test_power.py",
    "src/core/core/test/test_slam_reset.py",
    "src/core/core/test/test_sprint2.py",
    "src/core/core/test/test_swarm_integration.py",
    "src/core/core/test/test_teleop_watchdog_event.py",
    "src/core/core/test/test_traffic_api.py",
    "src/core/core/test/test_traffic_policy.py",
    "src/core/core/test/test_traffic_policy_bridge_contract.py",
    "src/core/core/test/test_vision_preview.py",
    "test/test_footprint_profiles.py",
    "test/test_nav2_profile_limits.py",
    "test/test_robot_runtime.py",
})


def _found() -> set[str]:
    found = set()
    for base in (ROOT / "src" / "core" / "core" / "test", ROOT / "test"):
        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if _IMPORT.search(text):
                found.add(path.relative_to(ROOT).as_posix())
    return found


def test_external_behavior_tests_match_the_frozen_set():
    found = _found()
    assert found == set(KNOWN_EXTERNAL_BEHAVIOR_TESTS), (
        f"new: {sorted(found - KNOWN_EXTERNAL_BEHAVIOR_TESTS)}, "
        f"stale: {sorted(KNOWN_EXTERNAL_BEHAVIOR_TESTS - found)}"
    )
