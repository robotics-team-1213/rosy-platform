"""D-184: behavior tests of other packages stay on a frozen exception list."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_IMPORT = re.compile(r"(?m)^(?:from|import)\s+(core_features|navigation|control)(?:\.|\s|$)")

# Set equality. A new path fails, and a path that moved into its package
# stays red until it is removed from this set.
KNOWN_EXTERNAL_BEHAVIOR_TESTS = frozenset({
    "middleware/core/gateway/test/test_absorption_command_validity.py",
    "middleware/core/gateway/test/test_api.py",
    "middleware/core/gateway/test/test_battery.py",
    "middleware/core/gateway/test/test_bridge_battery_policy.py",
    # Original TF -> real StateManager pose lifetime; CORE bridge/localization seam.
    "middleware/core/gateway/test/test_bridge_map_pose.py",
    # bridge/docking_executor.py seam (split out of ros_bridge, df02d52e); same kind as
    # test_bridge_battery_policy: CORE bridge wiring driven through core_features fakes.
    "middleware/core/gateway/test/test_bridge_docking_executor.py",
    "middleware/core/gateway/test/test_control_absorption_safety.py",
    "middleware/core/gateway/test/test_control_policy_link.py",
    "middleware/core/gateway/test/test_control_sensor_adapter.py",
    # D-628 gateway admission/Safety integration; pure feature decisions stay in services/test.
    "middleware/core/gateway/test/test_drive_output_boundaries.py",
    "middleware/core/gateway/test/test_crosswalk_gate_wiring.py",
    "middleware/core/gateway/test/test_core_logic.py",
    "middleware/core/gateway/test/test_domain_model.py",
    "middleware/core/gateway/test/test_evidence.py",
    "middleware/core/gateway/test/test_fleet_agent.py",
    "middleware/core/gateway/test/test_fleet_agent_mdns.py",
    "middleware/core/gateway/test/test_initial_pose.py",
    # D-769 route prior: CORE's bridge publication checked end to end with the camera's control inbox.
    "middleware/core/gateway/test/test_lane_route_publication.py",
    "middleware/core/gateway/test/test_line_follow.py",
    "middleware/core/gateway/test/test_line_follow_api.py",
    # D-760 rev 3: gateway HTTP serialization of the real manager wait judgement.
    "middleware/core/gateway/test/test_line_regulation_wait_api.py",
    # 2026-10-12: the steering-law commit added this file and missed this list.
    # It drives LineFollowManager through the loaded drivable steer.
    "middleware/core/gateway/test/test_line_follow_drivable_law.py",
    # D-507 9 CORE config seam: line_follow.site_floor_map_id parsing in gateway wiring
    # (_line_follow_config, check_bridge_floor_basis) against the core_features config.
    "middleware/core/gateway/test/test_site_floor_declaration.py",
    # D-494 HTTP-to-CORE seam; pure junction decisions stay in services/test.
    "middleware/core/gateway/test/test_line_junction_api.py",
    # D-551 HTTP-to-CORE seam: the advice endpoint, plus the guards that the real
    # line-follow manager never reads it (import walk, identical decisions);
    # the pure AdviceStore ordering tests stay in contracts/foundation/test.
    "middleware/core/gateway/test/test_line_advice_api.py",
    # CORE HTTP-to-Host seam and atomic mode/calibration admission integration;
    # the pure mask, observer and Host configuration tests stay with their owners.
    "middleware/core/gateway/test/test_lane_perception_api.py",
    # D-468 gateway contract: original odometry time/frame must reach the real
    # line-follow manager unchanged; pure manager behavior stays in services/test.
    "middleware/core/gateway/test/test_lane_return_odometry.py",
    # CORE's return sensor adapter binds the control policy deadline and the
    # line-follow provider; the pure scan tests live in services/test.
    "middleware/core/gateway/test/test_lane_return_sensors.py",
    "middleware/core/gateway/test/test_line_follow_body_stop.py",
    "middleware/core/gateway/test/test_line_follow_ir_guard.py",
    # D-407 amendment 2026-10-10: CAMERA_LINE LOST auto-resume through the real line-follow
    # manager and its stuck-test helpers in this gateway test folder.
    "middleware/core/gateway/test/test_line_follow_lost_resume.py",
    # D-511 rev 1: the Fleet lane cue driven through the real line-follow manager in this
    # gateway test folder; the cue mixin has no core_features/test home yet.
    "middleware/core/gateway/test/test_line_follow_lane_cue.py",
    "middleware/core/gateway/test/test_line_follow_obstacle.py",
    "middleware/core/gateway/test/test_line_follow_obstacle_path.py",
    # D-407 (2026-10-02): the stuck back-off through core.bridge.traffic_gate and the
    # decision API via core_client; the pure state machine lives in core_features/test.
    "middleware/core/gateway/test/test_line_follow_stuck.py",
    "middleware/core/gateway/test/test_line_follow_stuck_api.py",
    # landed on main 2026-10-10 without its entry: stuck detection when commanded motion is zero.
    "middleware/core/gateway/test/test_line_follow_stuck_no_motion.py",
    # D-607 integration exercises the gateway traffic seam and feature progress watcher together.
    "middleware/core/gateway/test/test_line_follow_stuck_no_progress.py",
    # D-760 rev 3 item 9: CORE HTTP snapshot and line-follow responses expose the feature state.
    "middleware/core/gateway/test/test_line_regulation_wait_api.py",
    "middleware/core/gateway/test/test_navigation_readiness.py",
    # D-890 public HTTP /do -> real CORE Home reservation; Waypoint is fixture setup.
    "middleware/core/gateway/test/test_intent_home_epoch.py",
    # D-732 actual CORE API/manager wiring and native callback/stop ownership seams.
    "middleware/core/gateway/test/test_native_owner_receipts.py",
    # D-772/776 CORE composition seams: rendered station lifecycle harness, post-write
    # observation, sole writer restriction, original ROS odom adapter and real native
    # owner binding. These require gateway CoreServices/bridge/final writer together;
    # pure Budget/Ledger/motion arithmetic remains under services/test.
    "middleware/core/gateway/test/station_cycle_sim.py",
    "middleware/core/gateway/test/test_cmd_vel_observation.py",
    "middleware/core/gateway/test/test_execution_writer_fence.py",
    "middleware/core/gateway/test/test_execution_odometry.py",
    # Original ROS-to-StateManager receipt retained by actual CORE native binding.
    "middleware/core/gateway/test/test_execution_source_bootstrap.py",
    # Original map callback, private native composition and captured-parent stop seam.
    "middleware/core/gateway/test/test_execution_map_observation.py",
    # D-783 actual private native composition and sole writer map evidence seam.
    "middleware/core/gateway/test/test_execution_native_map.py",
    # D-783 actual generated ROS response serialization -> bounded domain capture;
    # pure native evidence owner tests stay under core/services/test.
    "middleware/core/gateway/test/check_native_map_capture.py",
    # D-783 actual typed CORE ROS clients / DDS -> feature evidence owner seam.
    "middleware/core/gateway/test/check_native_map_clients.py",
    "middleware/core/gateway/test/test_native_map_clients.py",
    "middleware/core/gateway/test/test_native_execution_binding.py",
    "middleware/core/gateway/test/test_safety_stop_contention.py",
    "middleware/core/gateway/test/test_safety_stop_receipts.py",
    "middleware/core/gateway/test/test_operational_journey.py",
    "middleware/core/gateway/test/test_power.py",
    "middleware/core/gateway/test/test_slam_reset.py",
    "middleware/core/gateway/test/test_sprint2.py",
    "middleware/core/gateway/test/test_swarm_integration.py",
    "middleware/core/gateway/test/test_teleop_watchdog_event.py",
    "middleware/core/gateway/test/test_traffic_api.py",
    "middleware/core/gateway/test/test_traffic_policy.py",
    "middleware/core/gateway/test/test_traffic_policy_bridge_contract.py",
    "middleware/core/gateway/test/test_vision_preview.py",
    "test/test_footprint_profiles.py",
    "test/test_nav2_profile_limits.py",
    "test/test_robot_runtime.py",
    # D-637: existing shared learning corpus moved into test/learning/perception.
    # Export/intake/signing validate artifacts with the runtime manifest/signature;
    # object/training/replay tests bind runtime classes, runners and recorded topics.
    # Keep these eight exact integration paths; scanner and set equality stay intact.
    "test/learning/perception/test_model_convert.py",
    "test/learning/perception/test_model_intake.py",
    "test/learning/perception/test_model_intake_tasks.py",
    "test/learning/perception/test_model_ncnn_intake.py",
    "test/learning/perception/test_model_sign.py",
    "test/learning/perception/test_object_boxes.py",
    "test/learning/perception/test_road_replay.py",
    "test/learning/perception/test_training_contract.py",
    # feat/lane-network-junctions, written 2026-09-23..24 alongside D-184's
    # acceptance and brought in by the main merge. They drive CORE's own
    # docking/mode wiring (core.bridge.docking_mode, services.take_docking_mode,
    # core.bridge.traffic_gate.line_clock); four go through the core_client
    # fixture, the same entanglement main deferred for test_core_logic/
    # test_line_follow_api/test_slam_reset. The pure core_features parking tests moved to
    # core_features/test instead. Pending review: keep here or split.
    "middleware/core/gateway/test/test_docking_mode_ownership.py",
    "middleware/core/gateway/test/test_docking_mode_release.py",
    "middleware/core/gateway/test/test_docking_parking_wiring.py",
    "middleware/core/gateway/test/test_line_follow_sim_clock.py",
    "middleware/core/gateway/test/test_mode_listener_isolation.py",
    # 2026-10-02: 세 파일은 각 기능 커밋(D-385 표정 지도·LiDAR 마운트·텔레옵 워치독
    # 설정)과 같이 들어왔고 목록 갱신이 빠졌다(병합 뒤 CI 빨강). 각자 core_features
    # 의 순수 결정 함수를 실측한다 — 패키지 이전 여부는 소유자 검토로 남긴다.
    "middleware/core/gateway/test/test_emotion_map.py",
    "middleware/core/gateway/test/test_lidar_mount_source.py",
    "middleware/core/gateway/test/test_teleop_watchdog_config.py",
    # 2026-10-02 D-395 Phase 2 integration: the one cross-lane contract test. It runs
    # the sensing node's pure core (control.loc_assist), CORE's relay and app, and
    # Fleet's client against each other, so it belongs to no single package.
    "middleware/core/gateway/test/test_localization_cross_lane.py",
    # D-637 moved the existing learning workflow suite here; these exercise the
    # model intake/signing/replay seams with the unchanged perception contracts.
    "test/learning/perception/test_model_convert.py",
    "test/learning/perception/test_model_intake.py",
    "test/learning/perception/test_model_intake_tasks.py",
    "test/learning/perception/test_model_ncnn_intake.py",
    "test/learning/perception/test_model_sign.py",
    "test/learning/perception/test_object_boxes.py",
    "test/learning/perception/test_road_replay.py",
    "test/learning/perception/test_training_contract.py",
})


def _found() -> set[str]:
    found = set()
    for base in (ROOT / "middleware" / "core" / "gateway" / "test", ROOT / "test"):
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
