"""Safety Obstacles mixin decisions on real values (D-171 track 1).

The mixin imported rclpy/std_msgs/tf2_ros and had no test of its own. It is
ROS-free now: SafetyNode owns the subscriptions and lookup_odom_base(). The
pure risk subjects (observation_risk, camera_hold) have their own tests, so
here they are replaced to isolate the mixin's decisions.
"""
import json
import math
from types import SimpleNamespace

import pytest

from control.safety import obstacles
from control.safety.obstacles import Obstacles

NOW = 100.


def transform(stamp=NOW - .1, yaw_ok=True):
    q = SimpleNamespace(x=0., y=0., z=0., w=1.) if yaw_ok else SimpleNamespace(x=0., y=0., z=0., w=0.)
    return SimpleNamespace(header=SimpleNamespace(stamp=SimpleNamespace(sec=int(stamp), nanosec=int(round(stamp % 1 * 1e9)))),
                           transform=SimpleNamespace(translation=SimpleNamespace(x=1., y=2.), rotation=q))


class FakeSafety(Obstacles):
    def __init__(self, enabled=True, tf=transform(), vx=.05):
        self.params = {}
        self.tf = tf
        self.robot_r = .076
        self.last_cmd = SimpleNamespace(linear=SimpleNamespace(x=vx))
        self.init_obstacles()
        self.params.update(obstacle_tracking_enabled=enabled)

    def declare_parameter(self, name, value):
        self.params[name] = value

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def lookup_odom_base(self):
        return self.tf

    def now(self):
        return SimpleNamespace(nanoseconds=int(NOW * 1e9))


@pytest.fixture
def risk(monkeypatch):
    calls = {'result': {'action': 'clear', 'reason': ''}, 'camera': None, 'seen': []}

    def observation_risk(observation, now, pose, vx, radius, margin):
        calls['seen'].append((pose, vx, radius, margin))
        return calls['result']

    monkeypatch.setattr(obstacles, 'observation_risk', observation_risk)
    monkeypatch.setattr(obstacles, 'camera_hold', lambda observation, now: calls['camera'])
    return calls


def test_module_is_ros_free():
    for name in ('Time', 'String', 'TransformException'):
        assert name not in obstacles.__dict__


def test_init_declares_defaults_and_leaves_the_subscriptions_to_the_node():
    node = FakeSafety()                                      # no create_subscription on the stand-in
    assert node.params == {'obstacle_tracking_enabled': True, 'obstacle_tracking_margin': .02}
    assert node.obstacle_observation is None and node.camera_observation is None


def test_disabled_guard_never_holds(risk):
    risk['camera'] = 'camera_hold:person'
    assert FakeSafety(enabled=False).obstacle_tracking_hold() is None


def test_camera_hold_wins_before_any_pose_check(risk):
    risk['camera'] = 'camera_hold:person'
    assert FakeSafety(tf=None).obstacle_tracking_hold() == 'camera_hold:person'


@pytest.mark.parametrize('tf', [None, transform(stamp=NOW - .4), transform(stamp=NOW + .1), transform(yaw_ok=False)])
def test_missing_stale_future_or_invalid_pose_holds(risk, tf):
    assert FakeSafety(tf=tf).obstacle_tracking_hold() == 'obstacle_pose_unavailable'
    assert risk['seen'] == []


def test_clear_risk_passes_and_uses_the_current_pose_and_command(risk):
    assert FakeSafety().obstacle_tracking_hold() is None
    (pose, vx, radius, margin), = risk['seen']
    assert pose[:2] == (1., 2.) and math.isclose(pose[2], 0.)
    assert (vx, radius, margin) == (.05, .076, .02)


def test_replan_while_rotating_in_place_is_left_to_the_swept_footprint_checks(risk):
    risk['result'] = {'action': 'replan', 'reason': 'crossing'}
    assert FakeSafety(vx=0.).obstacle_tracking_hold() is None
    assert FakeSafety(vx=.05).obstacle_tracking_hold() == 'obstacle_replan:crossing'


def test_stop_risk_holds_with_reason(risk):
    risk['result'] = {'action': 'stop', 'reason': 'ttc'}
    assert FakeSafety().obstacle_tracking_hold() == 'obstacle_stop:ttc'


def test_malformed_observations_are_ignored(monkeypatch):
    node = FakeSafety()
    monkeypatch.setattr(obstacles, 'accept_observation', lambda value, previous, now, *rest: {'accepted': value})
    node.on_obstacle_tracks(SimpleNamespace(data='not json'))
    node.on_camera_observation(SimpleNamespace(data=None))
    assert node.obstacle_observation is None and node.camera_observation is None
    node.on_obstacle_tracks(SimpleNamespace(data=json.dumps({'tracks': []})))
    assert node.obstacle_observation == {'accepted': {'tracks': []}}
