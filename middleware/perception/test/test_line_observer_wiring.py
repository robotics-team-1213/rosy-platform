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


def test_keep_route_context_is_subscribed_and_bound_to_both_camera_outputs():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "String, 'line/route_context', self._on_route_context" in source
    assert "route_context_seq=route_context_seq" in source
    assert "route_context_seq=route_context.seq if route_context is not None else None" in source


def test_keep_callback_binds_fresh_route_seq_to_observation_and_debug_then_expires():
    import json

    from control.route_context_input import RouteContextInput, bend_expected
    from control.sensing.perception.lane import LaneObservation, line_observation_payload

    tree = ast.parse((ROOT / 'control/line_observer_node.py').read_text(encoding='utf-8'))
    names = ('_on_camera', '_publish')
    methods = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    observed, debug, bend_inputs = [], [], []
    keeper = SimpleNamespace(last={}, _x_offset=0.0, reset=lambda: None)

    def update(*_args, **kwargs):
        bend_inputs.append(kwargs['bend_expected'])
        keeper.last = {'strategy': 'both', 'target_m': [0.25, 0.0]}
        return LaneObservation(0.0, 0.9)

    keeper.update = update
    namespace = dict(
        Image=object, String=lambda **kw: SimpleNamespace(**kw), json=json,
        image_msg_to_frame=lambda _: np.ones((16, 16, 3), np.uint8),
        visibility_reason=lambda _: 'usable', pose_if_fresh=lambda *_: None,
        _spinning_in_place=lambda _: False, KEEP_MAX_FRAME_GAP_S=0.5,
        KEEP_CMD_STALE_WARN_FRAMES=30, bend_expected=bend_expected,
        keep_debug_payload=lambda _last, _ground, _offset, **meta: meta,
        containment_payload=lambda *_args, **_kwargs: {'v': 1},
        line_observation_payload=line_observation_payload)
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<camera-route-callback>', 'exec'), namespace)
    params = dict(require_camera_controls_stable=False, camera_lane_mode='keep',
                  lane_half_width_m=0.0925, paint_source='threshold',
                  camera_ground_source='GAZEBO', lane_corner_turning=True, crosswalk_uncertainty_enabled=False)
    inbox = RouteContextInput()
    inbox.receive(json.dumps(dict(v=1, seq=7, place_id='bend-1', map_id='map-1',
                                  stamp_s=10.0, valid_until_s=10.8, kind='bend',
                                  ahead_m=[0.1, 0.4])))
    node = SimpleNamespace(
        get_parameter=lambda key: SimpleNamespace(value=params[key]),
        _route_context_input=inbox, _lane_keeper=keeper, _paint_worker=None, _drivable_steer=None,
        _cmd_twist=None, _cmd_stamp=None, _cmd_stale_frames=0, _keep_last_stamp=None,
        _ground=lambda *_: object(), _paint_for=lambda *_: (None, 'threshold'),
        _ground_label=lambda: 'NOMINAL', _ground_error=None, _paint_half_width_m=0.0125,
        _camera_mode_uses_ground=lambda: True, _stamp=lambda: 10.1,
        _publish_debug=lambda *_: None,
        observation_pub=SimpleNamespace(publish=lambda msg: observed.append(json.loads(msg.data))),
        _keep_debug_pub=SimpleNamespace(publish=lambda msg: debug.append(json.loads(msg.data))))
    node._publish = lambda *args, **kw: namespace['_publish'](node, *args, **kw)
    for stamp in (10.1, 10.6):
        msg = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=10, nanosec=int((stamp-10)*1e9))))
        namespace['_on_camera'](node, msg)
    assert bend_inputs == [True, False]
    assert [row.get('route_context_seq') for row in observed] == [7, None]
    assert [row['route_context_seq'] for row in debug] == [7, None]


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


def test_lane_corner_turning_is_on_by_robot_default_and_needs_odometry():
    config = yaml.safe_load((ROOT / "config/line_follow.yaml").read_text(encoding="utf-8"))
    params = config["/**/line_observer_node"]["ros__parameters"]
    assert params["lane_corner_turning"] is True  # D-495: junction HOLD on robots
    # D-495: keep_debug carries the flag; it is how CORE learns junction_turn support.
    keep = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "corner_turning=bool(self.get_parameter('lane_corner_turning').value)" in keep
    nominal = yaml.safe_load((ROOT.parent / "apps/device/pinky/profile/config/camera_nominal.yaml")
                             .read_text(encoding="utf-8"))
    assert params["camera_x_offset_m"] == nominal["x_offset_m"]  # URDF nominal, not 0.0
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "Odometry, 'odom'" in source
    assert "LaneCornerTracker" in source
    assert "self._corner_tracker.update(" in source
    assert "self._odom_pose, frame, ground" not in source
    # Turning is still evidence: no motion output from this node (keep reads CORE's cmd_vel, D-507 r4b).
    assert "create_publisher(Twist" not in source
    assert source.count("'cmd_vel'") == source.count("create_subscription(Twist, 'cmd_vel'") == 1


def test_edge_left_mode_runs_the_edge_follower_on_odometry_and_ground():
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    assert "LaneEdgeFollower" in source
    assert "mode == 'edge_left'" in source
    assert "self._edge_follower.update(" in source
    assert "mode in ('lane', 'edge_left', 'centre', 'keep', 'route_a', 'route_b', 'route_ab')" in source   # odom subscription (keep: D-507 pivot)
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
    assert "create_publisher(Twist" not in source


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
    builder = (ROOT / "control/route_followers.py").read_text(encoding="utf-8")
    assert "build_route_follower(mode, graph_path, route, route_start," in source
    assert "RouteCameraFollower" in builder and "RouteMapFollower" in builder
    assert "RouteHybridFollower" in builder
    assert "mode in ('lane', 'edge_left', 'centre', 'route_a', 'route_b', 'route_ab')" in source
    assert "route modes need lane_graph_path, route and route_start" in source


def test_route_ab_builds_the_hybrid_with_the_paint_map_beside_the_graph():
    """route_ab is built like route_b: the paint map is loaded from the
    lane_graph_path directory (the map_v2_fleet bundle), and the overlay
    maps route_ab to the route follower."""
    source = (ROOT / "control/line_observer_node.py").read_text(encoding="utf-8")
    build = (ROOT / "control/route_followers.py").read_text(encoding="utf-8")
    assert "PaintMap.from_bundle(os.path.dirname(graph_path))" in build
    assert "RouteHybridFollower if mode == 'route_ab'" in build
    assert "camera_lane_mode in ('route_a', 'route_b', 'route_ab')" in source
    assert "mode in ('route_a', 'route_b', 'route_ab'):" in source
    assert "'route_ab': self._route_follower," in source


@pytest.mark.parametrize('source,enabled,sim_time,admitted', [
    ('PINKY', False, False, False),
    ('NOMINAL', True, True, False),
    ('GAZEBO', False, True, False),
    ('GAZEBO', True, False, False),
    ('GAZEBO', True, True, True),
])
def test_route_prototype_node_needs_simulation_context(source, enabled, sim_time, admitted):
    """Execute the ROS wrapper method without ROS so alternate configs cannot open route mode."""
    tree = ast.parse((ROOT / 'control/line_observer_node.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == '_build_route_follower')
    built, warnings = object(), []
    params = {'camera_ground_source': source, 'allow_simulation_ground': enabled,
              'use_sim_time': sim_time, 'lane_graph_path': str(ROOT / 'map/map_v2_fleet/lane_graph.yaml'),
              'route': ['west:r', 'ring_s:f'], 'route_start': [-1.15, -0.511, 0.0],
              'camera_x_offset_m': 0.03317}
    node = SimpleNamespace(get_parameter=lambda name: SimpleNamespace(value=params[name]),
                           get_logger=lambda: SimpleNamespace(warning=warnings.append))
    namespace = {'simulation_ground_allowed': lambda **kw: (
        kw['source'] == 'GAZEBO' and kw['simulation_enabled'] and kw['use_sim_time']),
        'yaml': yaml, 'build_route_follower': lambda *a, **kw: built}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<route-admission>', 'exec'), namespace)
    follower = namespace['_build_route_follower'](node, 'route_a')
    assert (follower is built) is admitted
    if not admitted:
        assert warnings and 'simulation' in warnings[0].lower()


def test_route_prototype_latches_invisible_after_simulation_context_changes():
    """A once-admitted route must not keep its old follower under new ground geometry."""
    tree = ast.parse((ROOT / 'control/line_observer_node.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == '_on_camera')
    target, calls, publications, qualities, warnings = object(), [], [], [], []
    params = {'require_camera_controls_stable': False, 'camera_lane_mode': 'route_a',
              'camera_ground_source': 'GAZEBO', 'allow_simulation_ground': True,
              'use_sim_time': True, 'camera_bright_threshold': 180,
              'lane_half_width_m': 0.0925, 'camera_roi_top_fraction': 0.4,
              'camera_roi_bottom_fraction': 1.0, 'camera_washed_fraction': 0.4}
    def ground(*_):
        if params['camera_ground_source'] == 'NOMINAL':
            raise ValueError('missing physical calibration')
        return object()
    follower = SimpleNamespace(update=lambda *a, **kw: calls.append(a) or target, last={})
    node = SimpleNamespace(get_parameter=lambda name: SimpleNamespace(value=params[name]),
                           get_logger=lambda: SimpleNamespace(warning=lambda *a, **kw: warnings.append(a)),
                           _camera_controls_stable=True, _paint_worker=None, _route_follower=follower,
                           _ground=ground, _odom_pose=(0., 0., 0.), _odom_stamp=1.,
                           _publish=lambda _source, value, **kw: (publications.append(value),
                                                                  qualities.append(kw.get('quality'))),
                           _publish_debug=lambda *a: None)
    namespace = {'Image': object, 'image_msg_to_frame': lambda _: np.zeros((8, 8, 3), np.uint8),
                 'visibility_reason': lambda _: 'usable', 'pose_if_fresh': lambda *a: (0., 0., 0.),
                 'simulation_ground_allowed': lambda **kw: (
                     kw['source'] == 'GAZEBO' and kw['simulation_enabled'] and kw['use_sim_time'])}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<route-frame>', 'exec'), namespace)
    msg = SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=1, nanosec=0)))
    namespace['_on_camera'](node, msg)
    assert publications == [target] and len(calls) == 1
    follower.last['reason'] = 'washed'
    namespace['_on_camera'](node, msg)
    assert publications[-1] is None and qualities[-1] == dict(valid=False, reason='overexposed')
    follower.last.clear()
    params['camera_ground_source'] = 'NOMINAL'
    namespace['_on_camera'](node, msg)
    assert publications == [target, None, None] and len(calls) == 2
    assert node._route_follower is None and warnings
    params['camera_ground_source'] = 'GAZEBO'
    namespace['_on_camera'](node, msg)
    assert publications == [target, None, None, None] and len(calls) == 2
