"""Safety Hazard mixin (e-stop, cliff, tilt, pickup) on real values (D-171 track 1).

The mixin imported geometry_msgs/sensor_msgs/std_msgs and had no host test.
It is ROS-free now; SafetyNode's zero_twist / publish_text / publish_bool are
recorded, and messages are plain objects with the same fields.
"""
import math
from types import SimpleNamespace

import pytest

from control.safety import hazard
from control.safety.hazard import Hazard

PARAMS = dict(imu_angular_velocity_unit='rad_s', imu_roll0=0., imu_pitch0=0., tilt_deg=20.,
              gyro_dps=30., pickup_acc=7., cliff_enable=True, cliff_hits=2, cliff_raw_max=800,
              cliff_clear_raw=1000, cliff_mode='low')


class IrFilter:
    def push(self, raw):
        return tuple(raw)


class FakeSafety(Hazard):
    def __init__(self, **params):
        self.params = {**PARAMS, **params}
        self.events = []
        self.estop = False
        self.last_cmd = 'previous command'
        self.last_cmd_time = 'stamp'
        self.wander_cmd, self.calib_step, self.estop_pub = 'wander/cmd', 'calib/step', 'estop/state'
        self.raw_zero_pub = SimpleNamespace(publish=lambda msg: self.events.append(('raw_zero', msg)))
        self.observed = []
        self.ir_raw, self.last_ir_time, self.cliff = (), None, False
        self._ir_generation, self._ir_filtered, self._ir_f = -1, (), IrFilter()
        self.generation = 0
        self.observations = SimpleNamespace(generation=lambda name: self.generation)
        self._imu_has_g, self._imu_n = False, 0
        self.tilt = self.pickup = None
        self.ir_age = 0.
        self.timeout = .5

    def zero_twist(self):
        return 'zero'

    def publish_text(self, publisher, data):
        self.events.append((publisher, data))

    def publish_bool(self, publisher, value):
        self.events.append((publisher, value))

    def _publish_zero(self):
        self.events.append('zero_cmd')

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def get_logger(self):
        return SimpleNamespace(error=lambda m: None, warn=lambda m: self.events.append(('warn', m)))

    def observe(self, name, msg=None, valid=True):
        self.observed.append((name, valid))
        return valid

    def now(self):
        return 'now'

    def age(self, stamp):
        return self.ir_age


def text(data):
    return SimpleNamespace(data=data)


def imu(acc=(0., 0., 9.8), gyro=(0., 0., 0.), roll=0., pitch=0.):
    cr, sr, cp, sp = math.cos(roll / 2), math.sin(roll / 2), math.cos(pitch / 2), math.sin(pitch / 2)
    q = SimpleNamespace(w=cr * cp, x=sr * cp, y=cr * sp, z=-sr * sp)
    return SimpleNamespace(linear_acceleration=SimpleNamespace(x=acc[0], y=acc[1], z=acc[2]),
                           angular_velocity=SimpleNamespace(x=gyro[0], y=gyro[1], z=gyro[2]), orientation=q)


def warm(node, samples=40):
    for _ in range(samples):
        node.on_imu(imu())


def test_module_is_ros_free():
    for name in ('Twist', 'Imu', 'Bool', 'String', 'UInt16MultiArray'):
        assert name not in hazard.__dict__


def test_engage_publishes_every_stop_in_order():
    node = FakeSafety()
    node.engage_estop('test')
    assert node.estop is True and node.last_cmd == 'zero'
    assert node.events == [('wander/cmd', 'stop'), ('calib/step', 'abort'), ('raw_zero', 'zero'),
                           'zero_cmd', ('estop/state', True)]


def test_release_zeroes_and_forgets_the_last_command():
    node = FakeSafety()
    node.estop = True
    node.release_estop()
    assert node.estop is False and node.last_cmd == 'zero' and node.last_cmd_time is None
    assert node.events[-2:] == ['zero_cmd', ('estop/state', False)]


@pytest.mark.parametrize('word, engaged', [('STOP ', True), ('kill', True), ('1', True),
                                           ('release', False), ('Resume', False), ('0', False)])
def test_estop_command_words(word, engaged):
    node = FakeSafety()
    node.estop = not engaged
    node.on_estop_cmd(text(word))
    assert node.estop is engaged


def test_unknown_estop_command_changes_nothing():
    node = FakeSafety()
    node.on_estop_cmd(text('maybe'))
    assert node.estop is False and node.events[0][0] == 'warn'


def test_ir_validity():
    node = FakeSafety()
    node.on_ir(SimpleNamespace(data=[100, 200, 300, 999]))
    assert node.ir_raw == (100, 200, 300) and node.observed[-1] == ('ir', True)
    node.on_ir(SimpleNamespace(data=[100, 0, 300]))
    assert node.observed[-1] == ('ir', False)
    node.on_ir(SimpleNamespace(data=[100, 200]))
    assert node.observed[-1] == ('ir', False)


def test_dead_imu_and_missing_gravity_never_raise_tilt_or_pickup():
    node = FakeSafety()
    node.on_imu(imu(acc=(0., 0., 0.)))
    assert node.tilt is False and node.pickup is False and node.observed[-1] == ('imu', False)
    node.on_imu(imu(acc=(0., 0., 3.)))                      # never saw ~1 g
    assert node._imu_has_g is False and node.observed[-1] == ('imu', False)


def test_imu_dropping_to_zero_after_warmup_is_not_a_pickup():
    node = FakeSafety()
    warm(node)
    node.on_imu(imu(acc=(0., 0., 0.)))                      # 0xa0 failure after a healthy start
    assert node.pickup is False and node.tilt is False and node.observed[-1] == ('imu', False)


def test_forty_sample_warmup_before_any_verdict():
    node = FakeSafety()
    warm(node, 39)
    assert node.tilt is False and node.observed[-1] == ('imu', False)
    node.on_imu(imu())
    assert node.tilt is False and node.pickup is False and node.observed[-1] == ('imu', True)


def test_non_unit_quaternion_or_unknown_unit_is_invalid():
    node = FakeSafety()
    msg = imu()
    msg.orientation.w = 2.
    node.on_imu(msg)
    assert node.observed[-1] == ('imu', False) and node._imu_n == 0
    node = FakeSafety(imu_angular_velocity_unit='rpm')
    node.on_imu(imu())
    assert node.observed[-1] == ('imu', False)


def test_tilt_needs_angle_with_spin_or_a_clear_margin():
    node = FakeSafety()
    warm(node)
    node.on_imu(imu(roll=math.radians(22)))                # angled, not spinning, within 1.2x
    assert node.tilt is False
    node.on_imu(imu(roll=math.radians(22), gyro=(math.radians(40), 0., 0.)))
    assert node.tilt is True
    node.on_imu(imu(roll=math.radians(25)))                # beyond 1.2x on its own
    assert node.tilt is True


def test_pickup_is_low_total_acceleration():
    node = FakeSafety()
    warm(node)
    node.on_imu(imu(acc=(0., 0., 6.5)))
    assert node.pickup is True
    node.on_imu(imu())
    assert node.pickup is False


def cliff_node(raw, **params):
    node = FakeSafety(**params)
    node.ir_raw = raw
    node.generation += 1
    return node


def test_low_mode_cliff_needs_two_real_hits_and_holds_with_hysteresis():
    assert cliff_node((500, 600, 1500)).ir_looks_like_cliff() is True
    assert cliff_node((500, 1500, 1500)).ir_looks_like_cliff() is False
    node = cliff_node((900, 950, 1500))                     # between trigger 800 and clear 1000
    assert node.ir_looks_like_cliff() is False
    node.cliff = True
    assert node.ir_looks_like_cliff() is True               # already a cliff: hold until > 1000


def test_saturated_or_disabled_or_silent_ir_never_invents_a_cliff():
    assert cliff_node((4095, 4095, 100)).ir_looks_like_cliff() is False
    lifted = cliff_node((4095, 4095, 100))
    lifted.cliff = True                                     # two saturated sensors release a held cliff
    assert lifted.ir_looks_like_cliff() is False
    assert cliff_node((100, 100, 100), cliff_enable=False).ir_looks_like_cliff() is False
    node = cliff_node((100, 100, 100))
    node.ir_age = 1.
    node.cliff = False
    assert node.ir_looks_like_cliff() is False              # stale IR keeps the last verdict


def test_high_mode_inverts_the_comparison():
    assert cliff_node((900, 950, 100), cliff_mode='high').ir_looks_like_cliff() is True
    assert cliff_node((100, 200, 950), cliff_mode='high').ir_looks_like_cliff() is False
