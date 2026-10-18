"""Safety Gate mixin on real values (D-171 track 1).

The gate imported geometry_msgs/rclpy, so its only test needed a ROS box.
It is ROS-free now; SafetyNode's zero_twist / set_linear_sign_parameter are
replaced by plain stand-ins.
"""
import math
from types import SimpleNamespace

import pytest

from control.safety import gate
from control.safety.gate import Gate


class Stamp:
    def __init__(self, s):
        self.s = s

    def __sub__(self, other):
        return SimpleNamespace(nanoseconds=int(round((self.s - other.s) * 1e9)))

    @property
    def nanoseconds(self):
        return int(self.s * 1e9)


def twist(vx=0., wz=0., **extra):
    linear = SimpleNamespace(x=vx, y=extra.get('vy', 0.), z=0.)
    angular = SimpleNamespace(x=0., y=0., z=wz)
    return SimpleNamespace(linear=linear, angular=angular)


class FakeGate(Gate):
    def __init__(self, **params):
        self.params = {'localization_required': False, 'auto_linear_sign': True, **params}
        self.clock = 10.
        self.estop = False
        self.localization_status = None
        self.last_cmd, self.last_cmd_time = twist(.1), None
        self.cmd_linear_sign = 1.
        self._sign_t = self._sign_front0 = self._sign_flip_t = None
        self._sign_hits = 0
        self.events = []
        self.pub = SimpleNamespace(publish=lambda msg: self.events.append(('publish', msg.linear.x)))

    def zero_twist(self):
        return twist()

    def set_linear_sign_parameter(self, value):
        self.events.append(('param', value))

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def now(self):
        return Stamp(self.clock)

    def halt_with_reason(self, reason):
        self.events.append(('halt', reason))

    def _publish_zero(self):
        self.events.append('zero')

    def get_logger(self):
        return SimpleNamespace(error=lambda message: self.events.append(('log', message)))

    def engage_estop(self, why):
        raise RuntimeError('publisher gone')


def test_module_is_ros_free():
    assert 'Twist' not in gate.__dict__ and 'Parameter' not in gate.__dict__


def test_valid_command_is_cached():
    node = FakeGate()
    command = twist(.05, .2)
    node.on_cmd(command)
    assert node.last_cmd is command and node.last_cmd_time.s == 10.


@pytest.mark.parametrize('bad', [math.nan, math.inf])
def test_non_finite_command_halts_and_is_never_cached(bad):
    node = FakeGate()
    node.on_cmd(twist(.05, vy=bad))
    assert node.last_cmd.linear.x == 0. and node.last_cmd_time is None
    assert node.events == [('halt', 'invalid_command')]


def test_estop_or_lost_localization_zeroes_instead_of_caching():
    node = FakeGate()
    node.estop = True
    node.on_cmd(twist(.05))
    assert node.events == ['zero'] and node.last_cmd.linear.x == 0.
    node = FakeGate(localization_required=True)
    node.on_cmd(twist(.05))
    assert node.events == ['zero'] and node.last_cmd_time is None


def feed(node, front, vx=.05, dt=.8):
    node._auto_linear_sign(front, math.inf, vx, 0.)
    node.clock += dt
    node._auto_linear_sign(front + .05, math.inf, vx, 0.)   # driving forward, the wall receded: sign is wrong


def test_sign_flips_only_after_two_wrong_observations_then_cools_down():
    node = FakeGate()
    feed(node, .30)
    assert node.cmd_linear_sign == 1. and node._sign_hits == 1
    node.clock += .1
    feed(node, .30)
    assert node.cmd_linear_sign == -1.
    assert ('param', -1.) in node.events
    for _ in range(2):                                       # two more wrong hits within 20 s: no second flip
        node.clock += .1
        feed(node, .30)
    assert node.cmd_linear_sign == -1.
    assert [e for e in node.events if e[0] == 'param'] == [('param', -1.)]


def test_short_interval_small_motion_or_turning_never_counts():
    node = FakeGate()
    node._auto_linear_sign(.30, math.inf, .05, 0.)
    node.clock += .5
    node._auto_linear_sign(.40, math.inf, .05, 0.)            # dt < 0.70 s
    assert node._sign_hits == 0
    node._auto_linear_sign(.30, math.inf, .05, .2)            # turning resets the sample
    assert node._sign_t is None
    node._auto_linear_sign(.30, math.inf, .002, 0.)           # barely moving
    assert node._sign_t is None


def test_front_prefers_ultrasound_then_lidar_and_disable_resets():
    node = FakeGate()
    node._auto_linear_sign(.30, .50, .05, 0.)
    assert node._sign_front0 == .30
    node = FakeGate()
    node._auto_linear_sign(math.inf, .50, .05, 0.)
    assert node._sign_front0 == .50
    node = FakeGate(auto_linear_sign=False)
    node._sign_hits = 1
    node._auto_linear_sign(.30, .50, .05, 0.)
    assert node._sign_hits == 0 and node._sign_t is None


def test_stop_motors_falls_back_to_a_zero_publish():
    node = FakeGate()
    node.stop_motors()
    assert node.events == [('publish', 0.)]
