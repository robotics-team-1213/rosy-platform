"""ROS-free adaptive motion contracts for the exact v2 mapping run."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "launch" / "map_v2_traversal.py"
ROOT = Path(__file__).resolve().parents[4]


def _mod():
    spec = importlib.util.spec_from_file_location("map_v2_traversal", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_open_space_can_use_the_sim_ceiling_but_narrow_space_crawls():
    mod = _mod()
    limits = mod.TraversalLimits(robot_diameter_m=0.172, max_linear_mps=0.10)

    assert mod.adaptive_speed(1.0, 0.5, 0.0, limits) == pytest.approx(0.10)
    narrow = mod.adaptive_speed(0.13, 0.11, 0.0, limits)
    assert limits.crawl_linear_mps <= narrow < 0.10
    assert mod.adaptive_speed(0.095, 0.095, 0.0, limits) == 0.0


def test_curvature_can_only_reduce_the_clearance_speed():
    mod = _mod()
    limits = mod.TraversalLimits(robot_diameter_m=0.172, max_linear_mps=0.10)
    straight = mod.adaptive_speed(0.5, 0.3, 0.0, limits)
    bend = mod.adaptive_speed(0.5, 0.3, 4.0, limits)

    assert 0.0 < bend < straight <= limits.max_linear_mps


def test_target_behind_uses_reverse_heading_instead_of_narrow_uturn():
    mod = _mod()

    direction, error = mod.bidirectional_heading_error(math.pi)
    assert direction == -1.0
    assert error == pytest.approx(0.0, abs=1e-9)

    direction, error = mod.bidirectional_heading_error(0.4)
    assert direction == 1.0
    assert error == pytest.approx(0.4)

    direction, error = mod.bidirectional_heading_error(2.0)
    assert direction == 1.0
    assert error == pytest.approx(2.0)


def test_robust_clearance_rejects_single_lidar_outlier_but_keeps_real_wall():
    mod = _mod()

    isolated_outlier = [0.14] * 80 + [0.05]
    real_near_surface = [0.05] * 10 + [0.14] * 71

    assert mod.robust_clearance(isolated_outlier) == pytest.approx(0.14)
    assert mod.robust_clearance(real_near_surface) == pytest.approx(0.05)
    assert math.isnan(mod.robust_clearance([math.nan, math.inf, -1.0]))


def test_reverse_distance_is_geometry_and_rear_clearance_derived_not_fixed():
    mod = _mod()
    limits = mod.TraversalLimits(robot_diameter_m=0.172)

    short = mod.recovery_reverse_distance(
        front_clearance_m=0.08,
        rear_clearance_m=0.30,
        turn_sweep_radius_m=0.10,
        limits=limits,
    )
    roomy = mod.recovery_reverse_distance(
        front_clearance_m=0.03,
        rear_clearance_m=0.50,
        turn_sweep_radius_m=0.10,
        limits=limits,
    )
    constrained = mod.recovery_reverse_distance(
        front_clearance_m=0.03,
        rear_clearance_m=0.13,
        turn_sweep_radius_m=0.10,
        limits=limits,
    )

    assert 0.0 < short < roomy
    assert roomy > 0.08
    assert 0.0 <= constrained < short


def test_turn_clearance_requires_the_full_body_envelope_in_every_direction():
    mod = _mod()
    limits = mod.TraversalLimits(robot_diameter_m=0.172)

    assert mod.turn_clearance_available([0.11] * 8, limits) is True
    assert mod.turn_clearance_available([0.11] * 7 + [0.095], limits) is False
    assert mod.turn_clearance_available([0.11] * 7 + [math.nan], limits) is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01])
def test_invalid_or_negative_clearance_fails_closed(bad):
    mod = _mod()
    limits = mod.TraversalLimits(robot_diameter_m=0.172)

    assert mod.adaptive_speed(bad, 0.2, 0.0, limits) == 0.0
    assert mod.recovery_reverse_distance(0.03, bad, 0.10, limits) == 0.0


def test_mapping_route_keeps_the_pinky_envelope_clear_of_every_wall():
    mod = _mod()
    route = mod.mapping_route_world()
    walls = json.loads((
        ROOT / "src" / "runtime" / "control" / "map" / "map_260905_update_v2"
        / "reports" / "wall_geometry.json"
    ).read_text(encoding="utf-8"))

    minimum = math.inf
    for start, end in zip(route, route[1:]):
        distance = math.dist(start, end)
        samples = max(2, math.ceil(distance / 0.002) + 1)
        for index in range(samples):
            fraction = index / (samples - 1)
            point = (
                start[0] + (end[0] - start[0]) * fraction,
                start[1] + (end[1] - start[1]) * fraction,
            )
            for wall in walls:
                pose, size = wall["pose"], wall["size"]
                dx, dy = point[0] - pose[0], point[1] - pose[1]
                c, s = math.cos(pose[5]), math.sin(pose[5])
                x, y = c * dx + s * dy, -s * dx + c * dy
                clearance = math.hypot(
                    max(abs(x) - size[0] / 2, 0.0),
                    max(abs(y) - size[1] / 2, 0.0),
                )
                minimum = min(minimum, clearance)

    limits = mod.TraversalLimits(robot_diameter_m=0.172)
    assert route[0] == pytest.approx((-0.205, 0.275))
    assert minimum >= limits.hard_clearance_m
    assert any(x > 1.1 and y > 0.4 for x, y in route)
    assert any(x > 0.5 and y > 0.4 for x, y in route)
    # The route must actually traverse the lower opening and observe from
    # inside the upper-left bay; looking through the opening leaves occlusion.
    assert any(-0.66 <= x <= -0.58 and 0.06 <= y <= 0.10 for x, y in route)
    assert any(x <= -1.05 and y >= 0.40 for x, y in route)
    assert any(x <= -1.05 and y <= -0.25 for x, y in route)
    assert any(x >= 0.85 and y <= -0.05 for x, y in route)
    assert any(-0.08 <= x <= 0.02 and y <= -0.45 for x, y in route)

    observation_points = {route[index] for index in mod.mapping_observation_indices(route)}
    assert {
        (-1.100, 0.480),
        (-1.100, -0.300),
        (0.900, -0.100),
        (-0.040, -0.480),
    } <= observation_points


def test_route_start_index_accepts_connector_phase_without_skipping_bounds():
    mod = _mod()

    assert mod.route_start_index(0, 52) == 0
    assert mod.route_start_index(1, 52) == 1
    with pytest.raises(ValueError):
        mod.route_start_index(-1, 52)
    with pytest.raises(ValueError):
        mod.route_start_index(52, 52)


def test_completion_exit_waits_for_a_nonnegative_final_zero_dwell():
    mod = _mod()

    assert mod.completion_exit_ready(None, 10.0, 0.5) is False
    assert mod.completion_exit_ready(10.0, 10.49, 0.5) is False
    assert mod.completion_exit_ready(10.0, 10.5, 0.5) is True
    with pytest.raises(ValueError):
        mod.completion_exit_ready(10.0, 10.5, -0.1)


def test_runtime_runner_uses_core_navigation_input_not_final_cmd_vel():
    source = (SCRIPT.parents[1] / "scripts" / "map_v2_runner.py").read_text(
        encoding="utf-8"
    )

    assert '"nav_cmd_vel"' in source
    assert 'create_publisher(Twist, "cmd_vel"' not in source
    assert "_SCRIPT_PATH = Path(__file__).resolve()" in source
    assert "_SCRIPT_PATH.parent" in source
    assert 'parents[1] / "launch"' in source
    assert "ClockType.STEADY_TIME" in source
    assert "FRONT_SCAN_ANGLE = math.pi" in source
    assert "REAR_SCAN_ANGLE = 0.0" in source
    assert "adaptive_speed(" in source
    assert "recovery_reverse_distance(" in source
    assert 'declare_parameter("clearance_quantile", 0.30)' in source
    assert "robust_clearance(values, self.clearance_quantile)" in source
    assert "bidirectional_heading_error(error)" in source
    assert "mapping_observation_indices" in source
    assert "abs(cmd.linear.x) > 0.02" in source
    assert "hard_clearance_m + 0.015" not in source
    assert 'self.phase = "blocked"' in source
    assert "reverse_unavailable_turn_in_place" not in source
    assert 'declare_parameter("start_route_index", 1)' in source
    assert 'declare_parameter("exit_on_complete", False)' in source
    assert 'declare_parameter("completion_zero_dwell_s", 0.5)' in source
    assert 'declare_parameter("run_id", "unset")' in source
    assert '"run_id": self.run_id' in source
    assert "while rclpy.ok() and not node.exit_requested" in source


def test_runtime_runner_resets_stall_timer_after_scans_and_while_aligning():
    """Scanning or turning in place must never count as a forward-motion stall."""
    source = (SCRIPT.parents[1] / "scripts" / "map_v2_runner.py").read_text(
        encoding="utf-8"
    )
    finish_spin = source[source.index("    def finish_spin"):source.index("    def tick")]
    alignment = source[
        source.index("        if abs(drive_error) > 0.18:"):
        source.index("        moved = math.dist")
    ]

    assert "self.progress_anchor = (self.x, self.y)" in finish_spin
    assert "self.progress_time = self.now()" in finish_spin
    assert "self.progress_anchor = (self.x, self.y)" in alignment
    assert "self.progress_time = self.now()" in alignment


def test_motion_stall_timeout_uses_sim_time_not_slow_host_wall_time():
    source = (SCRIPT.parents[1] / "scripts" / "map_v2_runner.py").read_text(
        encoding="utf-8"
    )
    now_method = source[source.index("    def now"):source.index("    def on_odom")]

    assert "self.get_clock().now().nanoseconds" in now_method
    assert "time.monotonic()" not in now_method


def test_runtime_runner_controls_from_ground_truth_model_odometry():
    source = (SCRIPT.parents[1] / "scripts" / "map_v2_runner.py").read_text(
        encoding="utf-8"
    )

    assert "msg.pose.pose.position.x" in source
    assert "msg.pose.pose.position.y" in source
    assert "yaw_from_quaternion(msg.pose.pose.orientation)" in source
    assert "lookup_transform" not in source
    assert "self.route = mapping_route_world()" in source
    assert "x - origin[0]" not in source
