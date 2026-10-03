"""D-143 ROS wrapper stays a sensing-only evidence publisher."""

from pathlib import Path
import ast
from types import SimpleNamespace

import pytest

import yaml
import numpy as np


ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('brightness,reason', [(30, 'low_light'), (255, 'overexposed')])
def test_invalid_exposure_resets_keeper_and_worker_before_publishing_invisible(brightness, reason):
    from control.sensing.perception.camera_visibility import visibility_reason
    tree = ast.parse((ROOT / 'control/line_observer_node.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_on_camera')
    namespace = dict(Image=object, image_msg_to_frame=lambda _: np.full((16, 16, 3), brightness, np.uint8),
                     visibility_reason=visibility_reason)
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<camera-callback>', 'exec'), namespace)
    resets, publications = [], []
    node = SimpleNamespace(get_parameter=lambda _: SimpleNamespace(value=False),
        _lane_keeper=SimpleNamespace(reset=lambda: resets.append('keeper')),
        _between_keeper=SimpleNamespace(reset=lambda: resets.append('between')),
        _paint_worker=SimpleNamespace(reset=lambda: resets.append('worker')),
        _keep_last_stamp=9., _publish=lambda *args, **kwargs: publications.append((args, kwargs)),
        _publish_debug=lambda *_: None)
    msg = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=10, nanosec=0)))
    namespace['_on_camera'](node, msg)
    assert resets == ['keeper', 'between', 'worker'] and node._keep_last_stamp is None
    assert publications == [(('CAMERA_LINE', None), dict(stamp=10., quality=dict(valid=False, reason=reason)))]


@pytest.mark.parametrize('geometry', ['NOMINAL', 'GAZEBO', 'HOMOGRAPHY'])
def test_camera_geometry_source_keeps_the_motion_observation_wire_contract(geometry):
    from control.sensing.perception.lane import LaneObservation, line_observation_payload
    tree = ast.parse((ROOT / 'control/line_observer_node.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_ground_label')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<ground-label>', 'exec'), namespace)
    node = SimpleNamespace(get_parameter=lambda _: SimpleNamespace(value=geometry))
    # Sim/geometry provenance belongs in debug evidence; the motor observation
    # accepts only the NOMINAL restriction marker or no marker.
    payload = line_observation_payload('CAMERA_LINE', 1.0, LaneObservation(0, .9),
                                       ground=namespace['_ground_label'](node))
    assert payload['visible'] and payload['confidence'] == .9


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
    assert "self._corner_tracker.update(" in source
    assert "self._odom_pose, frame, ground" not in source
    # Turning is still evidence: no motion output from this node.
    assert "Twist" not in source
    assert "'cmd_vel'" not in source


def test_edge_left_mode_runs_the_edge_follower_on_odometry_and_ground():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "LaneEdgeFollower" in source
    assert "mode == 'edge_left'" in source
    assert "self._edge_follower.update(" in source
    assert "mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab')" in source   # odom subscription
    # 'line' and 'lane' branches are untouched and the default stays 'line'.
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    assert config["/**/line_observer_node"]["ros__parameters"]["camera_lane_mode"] == "line"


def test_edge_left_drops_odometry_whose_stamp_is_stale():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "msg.header.stamp" in source.split("def _on_odom", 1)[1]
    assert "pose_if_fresh(" in source
    assert "self._odom_stamp" in source


def test_modes_fixed_at_startup_are_read_only_parameters():
    """The edge follower and the odom subscription are built at startup, so
    switching mode later would silently run the wrong pipeline."""
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "from rcl_interfaces.msg import ParameterDescriptor" in source
    assert ("self.declare_parameter('camera_lane_mode', 'line', _READ_ONLY)" in source)
    assert ("self.declare_parameter('lane_corner_turning', False, _READ_ONLY)" in source)
    assert "_READ_ONLY = ParameterDescriptor(read_only=True)" in source


def test_corner_turning_in_lane_mode_also_rejects_stale_odometry():
    """A dead odom topic must not steer an APPROACH/TURN manoeuvre either."""
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "self._odom_pose, frame, ground" not in source
    assert source.count("pose_if_fresh(self._odom_pose, self._odom_stamp") == 5


def test_centre_mode_uses_the_boundary_tracker_with_fresh_odometry():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "LaneBoundaryTracker" in source
    assert "mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab')" in source
    assert "self._centre_tracker.update(" in source
    assert source.count("pose_if_fresh(self._odom_pose, self._odom_stamp") == 5


def test_debug_overlay_is_off_by_default_and_publishes_only_an_image():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["debug_overlay"] is False
    assert "CompressedImage, 'line/debug/compressed'" in source
    assert "render_debug(" in source
    assert "Twist" not in source and "'cmd_vel'" not in source


def test_debug_overlay_failures_never_stop_line_observation():
    """A render/encode bug in the overlay, or a missing/broken
    debug_lane_graph at startup, must not lose line/observation (D-143):
    rclpy re-raises an uncaught callback exception out of spin, and main()
    only catches KeyboardInterrupt."""
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    publish_debug = source.split("def _publish_debug", 1)[1].split("\n    def _on_odom", 1)[0]
    assert "try:" in publish_debug
    assert "except Exception" in publish_debug
    assert "throttle_duration_sec=5.0" in publish_debug
    init_body = source.split("def __init__", 1)[1].split("\n    def _ground", 1)[0]
    assert "except (OSError, yaml.YAMLError)" in init_body
    assert "self._debug_graph = None" in init_body


def test_route_modes_need_a_graph_and_a_route():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["lane_graph_path"] == ""
    assert params["route"] == []
    assert params["route_start"] == []
    assert "RouteCameraFollower" in source and "RouteMapFollower" in source
    assert "RouteHybridFollower" in source
    assert "mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab')" in source
    assert "route modes need lane_graph_path, route and route_start" in source


def test_route_ab_builds_the_hybrid_with_the_paint_map_beside_the_graph():
    """route_ab is built like route_b: the paint map is loaded from the
    lane_graph_path directory (the map_v2_fleet bundle), and the overlay
    maps route_ab to the route follower."""
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    build = source.split("def _build_route_follower", 1)[1].split("\n    def _ground", 1)[0]
    assert "PaintMap.from_bundle(os.path.dirname(graph_path))" in build
    assert "RouteHybridFollower(" in build
    assert "camera_lane_mode in ('route_a', 'route_b', 'route_ab')" in source
    assert "mode in ('route_a', 'route_b', 'route_ab'):" in source
    assert "'route_ab': self._route_follower," in source
