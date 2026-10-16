"""Safety Bumper mixin (lidar sectors + ultrasound) on real values (D-171 track 1).

The mixin imported sensor_msgs/std_msgs/rclpy/tf2_ros. It is ROS-free now:
SafetyNode's stamp_time / lookup_base_from are stand-ins here, and scans are
plain objects shaped like the local RPLidar C1 (720 beams, 40 m range_max,
wall-clock stamp) so the real sector/frontier subjects run.
"""
import math
from types import SimpleNamespace

import pytest

from control.safety import bumper
from control.safety.bumper import Bumper, parse_us_range

PARAMS = dict(lidar_use_tf=False, lidar_yaw_offset=0., scan_ignore_m=.02, footprint_guard_enabled=False)


def stamp(s=2_000_000_000.25):
    return SimpleNamespace(sec=int(s), nanosec=int(round(s % 1 * 1e9)))


def scan(distance=.5, beams=720, range_max=40., frame='laser'):
    return SimpleNamespace(header=SimpleNamespace(stamp=stamp(), frame_id=frame),
                           ranges=[distance] * beams, angle_min=-math.pi, angle_increment=2 * math.pi / beams,
                           range_min=.05, range_max=range_max)


def us(value, min_range=.02, max_range=4.):
    return SimpleNamespace(range=value, min_range=min_range, max_range=max_range)


class FakeSafety(Bumper):
    def __init__(self, tf=None, **params):
        self.params = {**PARAMS, **params}
        self.tf = tf
        self.events, self.observed = [], []
        self.accept = True
        self.us_scale, self.us_invalid_hold, self._us_invalid = 1., 3, 0
        self.us_front, self.last_us_time = float('inf'), None
        self.half_w, self.robot_r, self.open_max = math.pi / 4, .076, .40
        self._scan_drop = self._scan_ok = 0
        self.lidar_front, self.lidar_rear, self.last_scan_time = float('inf'), float('inf'), None
        self.ages = {}
        self.timeout = .5
        self.fresh = set()
        self.observations = SimpleNamespace(fresh=lambda name, now: name in self.fresh)

    def observe(self, name, msg=None, valid=True):
        self.observed.append((name, valid))
        return valid and self.accept

    def now(self):
        return 'now'

    def age(self, stamp):
        return self.ages.get(stamp, 1e9)

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def has_parameter(self, name):
        return False

    def get_logger(self):
        return SimpleNamespace(warn=lambda message, **kw: self.events.append(message))

    def stamp_time(self, value):
        return ('time', value.sec, value.nanosec)

    def lookup_base_from(self, frame_id, value):
        if self.tf is None:
            raise ValueError('frame laser does not exist')
        return self.tf


def mount_tf(x=.03, y=0.):
    return SimpleNamespace(transform=SimpleNamespace(translation=SimpleNamespace(x=x, y=y, z=.1),
                                                     rotation=SimpleNamespace(x=0., y=0., z=0., w=1.)))


def test_module_is_ros_free():
    for name in ('LaserScan', 'Range', 'Float32', 'Time', 'TransformException'):
        assert name not in bumper.__dict__


@pytest.mark.parametrize('value, expected', [(.30, .30), (0., None), (-.03, None), (.02, None),
                                             (.0201, None), (4.2, None), (math.nan, None), (.10, .10)])
def test_parse_us_range(value, expected):
    assert parse_us_range(us(value)) == expected


def test_us_holds_through_short_dropouts_then_goes_open():
    node = FakeSafety()
    node.on_us(us(.30))
    assert node.us_front == .30 and node.last_us_time == 'now'
    for _ in range(2):
        node.on_us(us(0.))
    assert node.us_front == .30                              # fewer than us_invalid_hold misses
    node.on_us(us(0.))
    assert node.us_front == float('inf')


def test_rejected_valid_us_sample_changes_nothing():
    node = FakeSafety()
    node.accept = False
    node.on_us(us(.30))
    assert node.us_front == float('inf') and node.last_us_time is None


def test_remote_scans_are_dropped():
    node = FakeSafety()
    node.on_scan(scan(beams=640, range_max=12.))
    assert node._scan_drop == 1 and node.last_scan_time is None and node.events


def test_scan_without_mount_tf_invalidates_lidar():
    node = FakeSafety(tf=None, lidar_use_tf=True)
    node.lidar_mount = (1., 1.)
    node.last_scan_time = 'old'
    node.on_scan(scan())
    assert node.observed == [('lidar', False)]
    assert node.last_scan_time is None and node.lidar_mount is None and node.lidar_yaw_source == 'missing_tf'
    assert node.events == ['drop scan without mount TF: frame laser does not exist']


def test_scan_missing_frame_id_is_treated_like_missing_tf():
    node = FakeSafety(tf=mount_tf(), lidar_use_tf=True)
    node.on_scan(scan(frame=''))
    assert node.lidar_yaw_source == 'missing_tf' and node.events == ['drop scan without mount TF: Missing scan frame']


def test_scan_with_mount_tf_records_mount_and_sectors():
    node = FakeSafety(tf=mount_tf(), lidar_use_tf=True)
    node.on_scan(scan(.5))
    assert node.lidar_yaw_source == 'tf:laser' and node.lidar_mount == (.03, 0.)
    # D-424: front/rear are the body-strip ranges; a .5 m ring reads just under .5 at the strip edge.
    assert node.lidar_front == pytest.approx(.5, abs=.02) and node.lidar_rear == pytest.approx(.5, abs=.02)
    assert node.lidar_measurement_time == ('time', 2_000_000_000, 250_000_000)
    assert node.lidar_rotation_points and node.last_scan_time == 'now' and node._scan_ok == 1


def test_parameter_mounted_scan_uses_the_yaw_offset():
    node = FakeSafety(lidar_yaw_offset=.2)
    node.on_scan(scan(.5))
    assert node.lidar_yaw == .2 and node.lidar_yaw_source == 'parameter' and node.lidar_mount is None
    assert node.lidar_rotation_clearance is None


def test_distances_follow_freshness():
    node = FakeSafety()
    node.lidar_front, node.lidar_rear, node.us_front = .5, .7, .3
    node.last_scan_time, node.last_us_time = 'scan', 'us'
    assert node.front_distance() == float('inf')
    node.ages = {'scan': .1}
    assert node.front_distance() == .5 and node.lidar_distance() == .5 and node.rear_distance() == .7
    node.ages = {'scan': .1, 'us': .1}
    assert node.front_distance() == .3
    assert node.us_distance() == float('inf') and node.sensors_ok() is False
    node.fresh = {'us', 'lidar'}
    assert node.us_distance() == .3 and node.sensors_ok() is True
