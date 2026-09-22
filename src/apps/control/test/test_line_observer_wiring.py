"""D-143 ROS wrapper stays a sensing-only evidence publisher."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_line_observer_has_both_inputs_and_one_normalized_output():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "UInt16MultiArray, 'ir_sensor/range'" in source
    assert "Image, 'camera/front'" in source
    assert "String, 'camera/controls'" in source
    assert "String, 'line/observation'" in source
    assert "create_publisher(Twist" not in source


def test_line_observer_detector_settings_are_operator_tunable():
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["ir_calibration_enabled"] is False
    assert params["ir_black"] == [0.0, 0.0, 0.0]
    assert params["ir_white"] == [0.0, 0.0, 0.0]
    assert 1 <= params["camera_bright_threshold"] <= 254
    assert 0.0 <= params["camera_roi_top_fraction"] < 1.0
    assert params["require_camera_controls_stable"] is True


def test_package_and_launch_expose_the_line_observer():
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")
    launch = (ROOT / "launch/line_follow.launch.py").read_text(encoding="utf-8")
    assert "line_observer_node = control.line_observer_node:main" in setup
    assert "line_observer_node" in launch
    assert "line_follow.yaml" in launch
    assert "ir_adc_node = control.ir_adc_node:main" in setup
    assert "ir_adc_node" in launch


def test_camera_capture_has_a_v4l2_fallback_for_the_device_image():
    source = (ROOT / "control/camera_detect_node.py").read_text(encoding="utf-8")
    assert "camera_backend" in source
    assert "cv2.VideoCapture" in source
    assert "freeze_controls" in source
    assert "if self._line_controls_stable()" in source


def test_camera_line_evidence_uses_the_original_image_header_stamp():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "msg.header.stamp" in source
    assert "stamp=source_stamp" in source


def test_camera_lane_mode_defaults_to_single_line_and_fails_closed():
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["camera_lane_mode"] == "line"
    assert params["lane_half_width_m"] == 0.0925
    assert params["camera_roi_bottom_fraction"] == 1.0
    assert params["camera_ground_source"] == "PINKY"
    assert params["allow_simulation_ground"] is False
    # Same fail-closed zero geometry as road_observer_node.
    assert params["gazebo_camera_height_m"] == 0.0
    assert params["gazebo_camera_pitch_rad"] == 0.0
    assert params["gazebo_camera_hfov_rad"] == 0.0


def test_lane_mode_uses_the_guarded_simulation_ground():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "detect_lane_centre" in source
    assert "simulation_ground_plane" in source
    assert "'camera_ground_source'" in source
    assert "'camera_lane_mode'" in source


def test_lane_corner_turning_is_off_by_default_and_needs_odometry():
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["lane_corner_turning"] is False
    assert params["camera_x_offset_m"] == 0.0
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "Odometry, 'odom'" in source
    assert "LaneCornerTracker" in source
    assert "self._odom_pose, frame, ground" in source
    # Turning is still evidence: no motion output from this node.
    assert "Twist" not in source
    assert "'cmd_vel'" not in source


def test_edge_left_mode_runs_the_edge_follower_on_odometry_and_ground():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "LaneEdgeFollower" in source
    assert "mode == 'edge_left'" in source
    assert "self._edge_follower.update(" in source
    assert "mode in ('lane', 'edge_left')" in source   # odom subscription
    # 'line' and 'lane' branches are untouched and the default stays 'line'.
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    assert config["/**/line_observer_node"]["ros__parameters"]["camera_lane_mode"] == "line"
