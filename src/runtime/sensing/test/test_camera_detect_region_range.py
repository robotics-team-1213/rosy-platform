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

from control.sensing.body import LIDAR_X
from control.sensing.lidar import NOSE_YAW
from control.sensing.perception.camera_ground import nominal_ground_plane

PROFILE = yaml.safe_load((Path(__file__).resolve().parents[3] / "products" / "pinky_pro" / "profile"
                          / "config" / "camera_nominal.yaml").read_text(encoding="utf-8"))
PARAMS = {'region_lidar_max_age_s': 0.3, 'region_lidar_tolerance_m': 0.05,
          'region_lidar_tolerance_ratio': 0.2}


@pytest.fixture
def node_module(monkeypatch):
    if 'rclpy' not in sys.modules:
        stubs = {
            'rclpy': types.ModuleType('rclpy'),
            'rclpy.node': types.SimpleNamespace(Node=object),
            'rclpy.qos': types.SimpleNamespace(DurabilityPolicy=None, QoSProfile=None,
                                               ReliabilityPolicy=None, qos_profile_sensor_data=None),
            'sensor_msgs': types.ModuleType('sensor_msgs'),
            'sensor_msgs.msg': types.SimpleNamespace(CompressedImage=None, Image=None, LaserScan=None),
            'std_msgs': types.ModuleType('std_msgs'),
            'std_msgs.msg': types.SimpleNamespace(Bool=None, Float32=None, String=None),
        }
        for name, module in stubs.items():
            monkeypatch.setitem(sys.modules, name, module)
    # Import fresh against the stubs and leave no stub-bound module behind for other tests.
    loaded = ('control.camera_detect_node', 'control.executor_choice')
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
