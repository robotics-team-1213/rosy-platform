"""Semantic road observer is sensing-only and calibration-aware."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_road_observer_has_camera_inputs_and_one_evidence_output():
    source = (ROOT / "control/road_observer_node.py").read_text(
        encoding="utf-8")
    assert "Image, 'camera/front'" in source
    assert "String, 'camera/controls'" in source
    assert "String, 'road/observation'" in source
    assert "CompressedImage, 'camera/preview/compressed'" in source
    assert "cv2.imencode('.jpg'" in source
    assert "road_observation_payload" in source
    assert "create_publisher(Twist" not in source
    assert "cmd_vel" not in source


def test_road_observer_binds_map_scene_and_fail_closed_ground_profile():
    config = yaml.safe_load(
        (ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/road_observer_node"]["ros__parameters"]
    assert params["map_id"] == "map_260905_update_v2"
    assert params["scene_revision"] == "road-scene-v1"
    assert params["camera_homography_enabled"] is False
    assert params["camera_homography_path"] == ""
    assert params["camera_ground_mode"] == "homography"
    assert params["allow_simulation_ground"] is False
    assert 1 <= params["bright_threshold"] <= 254
    assert 0.0 < params["horizontal_min_fraction"] < 1.0
    assert params["dashboard_preview_fps"] == 2.0
    assert params["dashboard_preview_max_width"] == 640
    assert params["dashboard_preview_max_bytes"] == 512000
    assert params["dashboard_source"] == "PINKY"
    assert params["require_camera_controls_stable"] is True


def test_package_and_launch_expose_road_observer():
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    launch = (ROOT / "launch/line_follow.launch.py").read_text(
        encoding="utf-8")
    assert "road_observer_node = control.road_observer_node:main" in setup
    assert "road_observer_node" in launch
    assert "line_follow.yaml" in launch


def test_road_observer_uses_source_header_stamp_and_validated_homography():
    source = (ROOT / "control/road_observer_node.py").read_text(
        encoding="utf-8")
    assert "msg.header.stamp" in source
    assert "load_homography_profile" in source
    assert ".eligible" in source
    assert "camera_homography_enabled" in source
    assert "time.monotonic()" in source
    assert "RoadPreviewConfig" in source
    assert "depth=1, reliability=ReliabilityPolicy.BEST_EFFORT" in source


def test_road_observer_has_an_explicit_gazebo_only_ground_mode():
    source = (ROOT / "control/road_observer_node.py").read_text(
        encoding="utf-8")
    assert "simulation_ground_plane" in source
    assert "camera_ground_mode" in source
    assert "gazebo_camera_height_m" in source
    assert "gazebo_camera_pitch_rad" in source
    assert "gazebo_camera_hfov_rad" in source
    assert "source=self._preview_config.source" in source
    assert "allow_simulation_ground" in source
    assert "self.get_parameter('use_sim_time').value" in source
    assert "use_sim_time=use_sim_time" in source


def test_road_observer_scene_context_is_off_and_sensing_only():
    source = (ROOT / "control/road_observer_node.py").read_text(
        encoding="utf-8")
    assert "SceneContextMatcher" in source
    assert "default_scene_context_store" in source
    assert "declare_parameter('scene_context_enabled', False)" in source
    assert "_scene_matcher.reset()" in source
    assert "context_id=context.context_id" in source
    assert "cmd_vel" not in source
    assert "create_publisher(Twist" not in source

    config = yaml.safe_load(
        (ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/road_observer_node"]["ros__parameters"]
    assert params["scene_context_enabled"] is False
    assert params["scene_context_enter_frames"] >= 1
    assert params["scene_context_exit_frames"] >= 1
    assert 0.0 < params["scene_context_min_confidence"] <= 1.0
