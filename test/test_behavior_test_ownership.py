"""D-184: behavior tests of other packages stay on a frozen exception list."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_IMPORT = re.compile(r"(?m)^(?:from|import)\s+(core_features|navigation|control)(?:\.|\s|$)")

# Set equality. A new path fails, and a path that moved into its package
# stays red until it is removed from this set.
KNOWN_EXTERNAL_BEHAVIOR_TESTS = frozenset({
    "src/runtime/gateway/test/test_absorption_command_validity.py",
    "src/runtime/gateway/test/test_api.py",
    "src/runtime/gateway/test/test_battery.py",
    "src/runtime/gateway/test/test_bridge_battery_policy.py",
    # bridge/docking_executor.py seam (split out of ros_bridge, df02d52e); same kind as
    # test_bridge_battery_policy: CORE bridge wiring driven through core_features fakes.
    "src/runtime/gateway/test/test_bridge_docking_executor.py",
    "src/runtime/gateway/test/test_control_absorption_safety.py",
    "src/runtime/gateway/test/test_control_policy_link.py",
    "src/runtime/gateway/test/test_control_sensor_adapter.py",
    "src/runtime/gateway/test/test_core_logic.py",
    "src/runtime/gateway/test/test_domain_model.py",
    "src/runtime/gateway/test/test_evidence.py",
    "src/runtime/gateway/test/test_fleet_agent.py",
    "src/runtime/gateway/test/test_fleet_agent_mdns.py",
    "src/runtime/gateway/test/test_initial_pose.py",
    "src/runtime/gateway/test/test_line_follow.py",
    "src/runtime/gateway/test/test_line_follow_api.py",
    # CORE HTTP-to-Host seam and atomic mode/calibration admission integration;
    # the pure mask, observer and Host configuration tests stay with their owners.
    "src/runtime/gateway/test/test_lane_perception_api.py",
    "src/runtime/gateway/test/test_line_follow_body_stop.py",
    "src/runtime/gateway/test/test_line_follow_ir_guard.py",
    "src/runtime/gateway/test/test_line_follow_obstacle.py",
    "src/runtime/gateway/test/test_line_follow_obstacle_path.py",
    # D-407 (2026-10-02): the stuck back-off through core.bridge.traffic_gate and the
    # decision API via core_client; the pure state machine lives in core_features/test.
    "src/runtime/gateway/test/test_line_follow_stuck.py",
    "src/runtime/gateway/test/test_line_follow_stuck_api.py",
    "src/runtime/gateway/test/test_navigation_readiness.py",
    "src/runtime/gateway/test/test_operational_journey.py",
    "src/runtime/gateway/test/test_power.py",
    "src/runtime/gateway/test/test_slam_reset.py",
    "src/runtime/gateway/test/test_sprint2.py",
    "src/runtime/gateway/test/test_swarm_integration.py",
    "src/runtime/gateway/test/test_teleop_watchdog_event.py",
    "src/runtime/gateway/test/test_traffic_api.py",
    "src/runtime/gateway/test/test_traffic_policy.py",
    "src/runtime/gateway/test/test_traffic_policy_bridge_contract.py",
    "src/runtime/gateway/test/test_vision_preview.py",
    "test/test_footprint_profiles.py",
    "test/test_nav2_profile_limits.py",
    "test/test_robot_runtime.py",
    # feat/lane-network-junctions, written 2026-09-23..24 alongside D-184's
    # acceptance and brought in by the main merge. They drive CORE's own
    # docking/mode wiring (core.bridge.docking_mode, services.take_docking_mode,
    # core.bridge.traffic_gate.line_clock); four go through the core_client
    # fixture, the same entanglement main deferred for test_core_logic/
    # test_line_follow_api/test_slam_reset. The pure core_features parking tests moved to
    # core_features/test instead. Pending review: keep here or split.
    "src/runtime/gateway/test/test_docking_mode_ownership.py",
    "src/runtime/gateway/test/test_docking_mode_release.py",
    "src/runtime/gateway/test/test_docking_parking_wiring.py",
    "src/runtime/gateway/test/test_line_follow_sim_clock.py",
    "src/runtime/gateway/test/test_mode_listener_isolation.py",
    # 2026-10-02: 세 파일은 각 기능 커밋(D-385 표정 지도·LiDAR 마운트·텔레옵 워치독
    # 설정)과 같이 들어왔고 목록 갱신이 빠졌다(병합 뒤 CI 빨강). 각자 core_features
    # 의 순수 결정 함수를 실측한다 — 패키지 이전 여부는 소유자 검토로 남긴다.
    "src/runtime/gateway/test/test_emotion_map.py",
    "src/runtime/gateway/test/test_lidar_mount_source.py",
    "src/runtime/gateway/test/test_teleop_watchdog_config.py",
    # 2026-10-02 D-395 Phase 2 integration: the one cross-lane contract test. It runs
    # the sensing node's pure core (control.loc_assist), CORE's relay and app, and
    # Fleet's client against each other, so it belongs to no single package.
    "src/runtime/gateway/test/test_localization_cross_lane.py",
})


def _found() -> set[str]:
    found = set()
    for base in (ROOT / "src" / "runtime" / "gateway" / "test", ROOT / "test"):
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
