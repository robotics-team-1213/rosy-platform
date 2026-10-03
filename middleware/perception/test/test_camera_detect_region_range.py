"""D-423: camera_detect_node's LiDAR region range, through the node's own method, without ROS.

The rclpy shell is stubbed only so the module imports; the method under test
touches nothing of ROS but its parameters, so a namespace stands in for the node.
"""
import importlib
import math
import sys
import types
from pathlib import Path

import pytest
import yaml

from control.sensing import lidar as lidar_module

from control.sensing.body import LIDAR_X
from control.sensing.lidar import NOSE_YAW
from control.sensing.perception.camera_ground import nominal_ground_plane

PROFILE = yaml.safe_load((Path(__file__).resolve().parents[3] / "middleware" / "apps" / "device" / "pinky" / "profile"
                          / "config" / "camera_nominal.yaml").read_text(encoding="utf-8"))
PARAMS = {'region_lidar_max_age_s': 0.3, 'region_lidar_tolerance_m': 0.05,
          'region_lidar_tolerance_ratio': 0.2}


@pytest.fixture
def node_module(monkeypatch):
    if 'rclpy' not in sys.modules:
        stubs = {
            'rclpy': types.ModuleType('rclpy'),
            'rclpy.node': types.SimpleNamespace(Node=object),
            # QoSProfile is built at import (D-411 recorder flag), so it must be callable.
            'rclpy.qos': types.SimpleNamespace(
                DurabilityPolicy=types.SimpleNamespace(TRANSIENT_LOCAL=None), QoSProfile=lambda **_: None,
                ReliabilityPolicy=types.SimpleNamespace(RELIABLE=None, BEST_EFFORT=None),
                qos_profile_sensor_data=None),
            'sensor_msgs': types.ModuleType('sensor_msgs'),
            'sensor_msgs.msg': types.SimpleNamespace(CompressedImage=None, Image=None, LaserScan=None),
            'std_msgs': types.ModuleType('std_msgs'),
            'std_msgs.msg': types.SimpleNamespace(Bool=None, Float32=None, String=None),
        }
        for name, module in stubs.items():
            monkeypatch.setitem(sys.modules, name, module)
    # Import fresh against the stubs and leave no stub-bound module behind for other tests.
    loaded = ('control.camera_detect_node', 'control.camera_region_range', 'control.executor_choice')
    saved = {name: sys.modules.pop(name) for name in loaded if name in sys.modules}
    yield importlib.import_module('control.camera_detect_node')
    for name in loaded:
        sys.modules.pop(name, None)
    sys.modules.update(saved)


def fake_node(scan, ground):
    return types.SimpleNamespace(
        _scan=scan, _lidar_nose=NOSE_YAW, _camera_x_m=PROFILE['x_offset_m'],
        _ground=ground, _nominal_ground=ground,
        get_parameter=lambda name: types.SimpleNamespace(value=PARAMS[name]))


def scan_msg(stamp, ahead_m):
    n = 720
    ranges = [float('inf')] * n
    ranges[n // 2] = ahead_m                       # scan angle pi = the robot's forward
    sec = int(stamp)
    return types.SimpleNamespace(
        header=types.SimpleNamespace(stamp=types.SimpleNamespace(sec=sec, nanosec=int((stamp - sec) * 1e9))),
        ranges=ranges, angle_min=0.0, angle_increment=2 * math.pi / n, range_min=0.05, range_max=12.0)


def above_horizon_region():
    return [{'bbox_xyxy': [140, 20, 180, 70], 'distance_m': None, 'range_source': None}]


def test_fresh_scan_ranges_an_off_floor_region_from_the_lidar(node_module):
    ground = nominal_ground_plane(source='NOMINAL', allowed=True, width_px=320, height_px=240,
                                  profile=PROFILE)
    node = fake_node(scan_msg(1.8e9, 0.6), ground)
    out = node_module.CameraDetectNode._lidar_ranged(node, above_horizon_region(), 1.8e9 + 0.1)
    assert out[0]['range_source'] == 'L'
    assert out[0]['distance_m'] == pytest.approx(0.6 + LIDAR_X - PROFILE['x_offset_m'], abs=1e-6)


@pytest.mark.parametrize('case', ['stale', 'no_scan', 'not_nominal', 'no_plane'])
def test_regions_pass_through_when_the_lidar_cannot_be_trusted(node_module, case):
    ground = nominal_ground_plane(source='NOMINAL', allowed=True, width_px=320, height_px=240,
                                  profile=PROFILE)
    node = fake_node(scan_msg(1.8e9, 0.6), ground)
    stamp = 1.8e9
    if case == 'stale':
        stamp += 0.5
    elif case == 'no_scan':
        node._scan = None
    elif case == 'not_nominal':
        node._ground = object()                    # e.g. the pinhole or homography model
    else:
        node._ground = node._nominal_ground = None
    regions = above_horizon_region()
    assert node_module.CameraDetectNode._lidar_ranged(node, regions, stamp) is regions


class FakeLogger:
    def __init__(self):
        self.lines = []

    def info(self, text, **_):
        self.lines.append(('info', text))

    def warn(self, text, **_):
        self.lines.append(('warn', text))


def startup_node(tmp_path, **params):
    profile_path = tmp_path / 'camera_nominal.yaml'
    profile_path.write_text(yaml.safe_dump(PROFILE), encoding='utf-8')
    values = {'nominal_camera_profile_path': str(profile_path), 'allow_nominal_ground': True,
              'width': 320, 'height': 240, 'camera_pitch_rad_override': math.nan,
              'camera_height_m_override': math.nan, 'lidar_yaw_offset_override': math.nan,
              'region_lidar_range': True, 'accept_simulation_scans': False}
    values.update(params)
    logger = FakeLogger()
    subscriptions = []
    node = types.SimpleNamespace(
        _ground_mode=values.pop('mode', 'nominal'), _scan=None, _scan_rejected_logged=False,
        _lidar_nose=None, _on_scan=None, get_logger=lambda: logger,
        get_parameter=lambda name: types.SimpleNamespace(value=values[name]),
        create_subscription=lambda *args: subscriptions.append(args))
    node.logger, node.subscriptions = logger, subscriptions
    return node


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv('ROSY_CALIBRATION_ROOT', str(tmp_path / 'store'))
    monkeypatch.setenv('ROSY_CALIBRATION_ROBOT', 'rosy-test')
    monkeypatch.setattr(lidar_module, '_simulation_scans', False)


@pytest.mark.parametrize('allow,expect_plane', [(False, False), (True, True)])
def test_load_nominal_ground_needs_the_second_opt_in(node_module, tmp_path, isolated_store, allow, expect_plane):
    node = startup_node(tmp_path, allow_nominal_ground=allow)
    plane, camera_x = node_module.CameraDetectNode._load_nominal_ground(node)
    assert (plane is not None) is expect_plane
    assert camera_x == PROFILE['x_offset_m']
    if expect_plane:
        assert plane.pitch_rad == pytest.approx(PROFILE['pitch_rad'])
    else:
        assert any(level == 'warn' and 'refused' in text for level, text in node.logger.lines)


def test_load_nominal_ground_is_off_outside_nominal_mode(node_module, tmp_path, isolated_store):
    node = startup_node(tmp_path, mode='pinhole')
    assert node_module.CameraDetectNode._load_nominal_ground(node) == (None, None)


def test_operator_pitch_override_reaches_the_plane(node_module, tmp_path, isolated_store):
    node = startup_node(tmp_path, camera_pitch_rad_override=math.radians(11.2))
    plane, _ = node_module.CameraDetectNode._load_nominal_ground(node)
    assert plane.pitch_rad == pytest.approx(math.radians(11.2))
    assert any('operator override pitch_rad' in text for _, text in node.logger.lines)


def test_lidar_subscription_needs_the_nominal_plane(node_module, tmp_path, isolated_store):
    node = startup_node(tmp_path)
    node._nominal_ground = None
    node_module.CameraDetectNode._start_region_lidar(node)
    assert node.subscriptions == [] and node._lidar_nose is None
    assert any(level == 'warn' and 'not subscribed' in text for level, text in node.logger.lines)


def test_lidar_subscription_with_the_plane_and_an_operator_yaw(node_module, tmp_path, isolated_store):
    node = startup_node(tmp_path, lidar_yaw_offset_override=math.radians(182.0))
    node._nominal_ground, _ = node_module.CameraDetectNode._load_nominal_ground(node)
    node_module.CameraDetectNode._start_region_lidar(node)
    assert len(node.subscriptions) == 1 and node.subscriptions[0][1] == 'scan'
    assert node._lidar_nose == pytest.approx(math.radians(182.0))
    assert lidar_module._simulation_scans is False


def test_simulation_scans_only_on_request(node_module, tmp_path, isolated_store):
    node = startup_node(tmp_path, accept_simulation_scans=True)
    node._nominal_ground, _ = node_module.CameraDetectNode._load_nominal_ground(node)
    node_module.CameraDetectNode._start_region_lidar(node)
    assert lidar_module._simulation_scans is True


def test_rejected_scans_are_reported_once(node_module, tmp_path, isolated_store):
    node = startup_node(tmp_path)
    remote = scan_msg(100.0, 0.6)                  # sim-time stamp: not this robot's C1
    for _ in range(3):
        node_module.CameraDetectNode._on_scan(node, remote)
    warnings = [text for level, text in node.logger.lines if level == 'warn']
    assert node._scan is None and len(warnings) == 1 and 'accept_simulation_scans' in warnings[0]
