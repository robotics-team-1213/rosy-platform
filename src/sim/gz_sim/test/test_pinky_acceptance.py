"""ROS-free geometry and evidence contracts for integrated acceptance."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "launch" / "pinky_acceptance_policy.py"
COLLECTOR = ROOT / "scripts" / "pinky_acceptance.py"


def _policy():
    spec = importlib.util.spec_from_file_location("pinky_acceptance_policy", POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wall(name, x, y, sx, sy):
    return {
        "name": name,
        "pose": [x, y, 0.05, 0.0, 0.0, 0.0],
        "size": [sx, sy, 0.1],
    }


def _box_walls():
    return [
        _wall("left", 0.0, 0.5, 0.02, 1.02),
        _wall("right", 1.0, 0.5, 0.02, 1.02),
        _wall("bottom", 0.5, 0.0, 1.02, 0.02),
        _wall("top", 0.5, 1.0, 1.02, 0.02),
    ]


def test_trajectory_clearance_uses_full_pinky_radius_and_detects_overlap():
    policy = _policy()
    walls = [_wall("wall", 0.0, 0.0, 0.02, 1.0)]

    safe = policy.trajectory_clearance([(0.20, 0.0)], walls, 0.086)
    collision = policy.trajectory_clearance([(0.05, 0.0)], walls, 0.086)

    assert safe["minimum_center_to_wall_m"] == pytest.approx(0.19)
    assert safe["minimum_body_clearance_m"] == pytest.approx(0.104)
    assert safe["collision"] is False
    assert collision["collision"] is True


def test_reachable_map_metrics_separate_unknown_occupied_and_outside():
    policy = _policy()
    data = [0] * 100
    metrics = policy.reachable_map_metrics(
        data,
        width=10,
        height=10,
        resolution=0.1,
        origin_xy=(0.0, 0.0),
        walls=_box_walls(),
        spawn_xy=(0.5, 0.5),
        required_clearance_m=0.10,
        sampling_m=0.05,
    )

    assert metrics["sample_count"] > 0
    assert metrics["unknown_fraction"] == 0.0
    assert metrics["occupied_fraction"] == 0.0
    assert metrics["outside_raster_fraction"] == 0.0
    assert metrics["mapping_complete"] is True

    data[55] = -1
    incomplete = policy.reachable_map_metrics(
        data, 10, 10, 0.1, (0.0, 0.0), _box_walls(), (0.5, 0.5),
        0.10, sampling_m=0.05,
    )
    assert incomplete["unknown_fraction"] > 0.0


def test_full_raster_fidelity_is_reported_separately_from_reachability():
    policy = _policy()
    data = [0] * 100
    for row in range(10):
        for column in range(10):
            if row in (0, 9) or column in (0, 9):
                data[row * 10 + column] = 100

    fidelity = policy.map_fidelity_metrics(
        data, 10, 10, 0.1, (0.0, 0.0), _box_walls(),
        wall_sampling_m=0.02, wall_tolerance_m=0.08,
    )

    assert 0.0 <= fidelity["minimum_wall_surface_recall"] <= 1.0
    assert fidelity["minimum_wall_surface_recall"] > 0.8
    assert fidelity["phantom_fraction"] == 0.0
    assert "full_raster_fidelity_passed" in fidelity


def test_road_observation_score_only_counts_the_current_camera_sample():
    policy = _policy()

    complete = {
        "lane": {"visible": True},
        "stop_line": {"visible": True},
        "crosswalk": {"visible": True},
    }
    blank = {
        "lane": {"visible": False},
        "stop_line": {"visible": False},
        "crosswalk": {"visible": False},
    }

    assert policy.road_observation_score(complete) == 3
    assert policy.road_observation_score(blank) == 0


def test_evaluate_acceptance_fails_each_safety_or_evidence_gap_closed():
    policy = _policy()
    evidence = {
        "mapping_complete": True,
        "map_received": True,
        "reachable_mapping_complete": True,
        "minimum_body_clearance_m": 0.011,
        "collision": False,
        "camera_frames": 3,
        "line_visible": True,
        "line_confidence": 0.9,
        "line_visible_while_moving": True,
        "road_lane_visible": True,
        "stop_line_visible": True,
        "crosswalk_visible": True,
        "nav2_passed": True,
        "cmd_vel_publishers": ["/core"],
        "final_zero_stable": True,
    }

    result = policy.evaluate_acceptance(evidence, clearance_margin_m=0.01)
    assert result["passed"] is True
    assert all(result["gates"].values())

    for key in (
        "mapping_complete", "map_received", "reachable_mapping_complete",
        "line_visible_while_moving", "nav2_passed", "final_zero_stable",
    ):
        broken = dict(evidence)
        broken[key] = False
        assert policy.evaluate_acceptance(
            broken, clearance_margin_m=0.01
        )["passed"] is False

    broken = dict(evidence, cmd_vel_publishers=["/core", "/other"])
    assert policy.evaluate_acceptance(
        broken, clearance_margin_m=0.01
    )["gates"]["sole_final_cmd_vel_publisher"] is False


def test_collector_subscribes_to_one_real_graph_and_writes_atomic_json():
    source = COLLECTOR.read_text(encoding="utf-8")

    for topic in (
        "odom", "map", "camera/front", "line/observation",
        "road/observation", "mapping/status", "navigation/probe_status",
        "cmd_vel",
    ):
        assert json.dumps(topic) in source
    assert "os.replace(" in source
    assert "evaluate_acceptance(" in source
    assert "get_publishers_info_by_topic" in source
    assert "create_publisher(Twist" not in source
    assert "self.publishers" not in source
