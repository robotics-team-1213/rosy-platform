"""CalibrationRelocationAdapter gates on real values (D-171 track 1).

The adapter used to import geometry_msgs/std_msgs, so no host test reached
it. It is ROS-free now; a plain subclass stands in for the calibration node.
"""
from types import SimpleNamespace

import pytest

from control import calibration_relocation
from control.calibration_relocation import CalibrationRelocationAdapter

RIG_ENV = {'ROS_DOMAIN_ID': '227', 'GZ_PARTITION': 'pinky_calmap227'}
RIG_PARAMS = dict(calibration_relocation_enabled=True, calibration_rotation=True,
                  calibration_round_trip=True, use_sim_time=True)


class FakeNode(CalibrationRelocationAdapter):
    def __init__(self, **params):
        self.params = {**RIG_PARAMS, **params}
        self.events = []
        self.round_trip = SimpleNamespace(done=True)
        self.relocation = None
        self.calibration_origin = None
        self.geometry_revision = 'geom-A'
        self.baseline = SimpleNamespace(latest=lambda name: (1., 2., .3))
        self.wander_state = ('stopped', 0.)
        self.phase = 'validating_motion'
        self.blocked = None

    def get_parameter(self, name):
        return SimpleNamespace(value=self.params[name])

    def rotation_eligibility(self, now, allow_front_blocked=False):
        return self.blocked

    def stop_wander(self):
        self.events.append('stop_wander')

    def drive_trial(self, linear=0., angular=0.):
        self.events.append(('drive', linear, angular))

    def zero(self):
        self.events.append('zero')

    def publish(self):
        self.events.append('publish')

    def finish(self, ok, message, phase=None):
        self.events.append(('finish', ok, message))


@pytest.fixture
def rig_env(monkeypatch):
    for key, value in RIG_ENV.items():
        monkeypatch.setenv(key, value)


def test_module_is_ros_free():
    assert not hasattr(calibration_relocation, 'Twist')
    assert not hasattr(calibration_relocation, 'String')


def test_relocation_is_released_only_in_the_isolated_rig(rig_env, monkeypatch):
    assert FakeNode().relocation_enabled()
    for name in RIG_PARAMS:
        assert not FakeNode(**{name: False}).relocation_enabled(), name
    monkeypatch.setenv('ROS_DOMAIN_ID', '0')
    assert not FakeNode().relocation_enabled()
    monkeypatch.setenv('ROS_DOMAIN_ID', '227')
    monkeypatch.setenv('GZ_PARTITION', 'field')
    assert not FakeNode().relocation_enabled()


def test_relocation_never_starts_on_a_real_robot(monkeypatch):
    monkeypatch.delenv('ROS_DOMAIN_ID', raising=False)
    node = FakeNode()
    assert node.begin_relocation(10.) is False
    assert node.events == [] and node.relocation is None


def test_begin_stops_wander_then_zeroes_before_seeking_space(rig_env):
    node = FakeNode()
    assert node.begin_relocation(10.) is True
    assert node.events[:2] == ['stop_wander', 'zero']
    assert node.phase == 'relocating_calibration'
    assert node.calibration_origin == (1., 2., .3)
    assert node.trial_geometry_revision == 'geom-A'
    assert node.relocation_wait == pytest.approx(10.4)


@pytest.mark.parametrize('blocked, verified, before, expected', [
    ('rotation clear already', True, False, False),   # eligible space: no relocation needed
    (None, False, False, False),                       # translation not verified yet
    (None, False, True, True),                         # explicit pre-translation probe
])
def test_begin_preconditions(rig_env, blocked, verified, before, expected):
    node = FakeNode()
    node.blocked = blocked
    node.round_trip = SimpleNamespace(done=verified)
    assert node.begin_relocation(10., before_translation=before) is expected


def test_relocation_holds_zero_until_wander_confirms_stop_then_fails(rig_env):
    node = FakeNode()
    node.begin_relocation(10.)
    node.wander_state = ('explore', 10.5)
    node.events.clear()
    node.tick_relocation(11.)
    assert node.events == ['zero']
    node.tick_relocation(12.1)
    assert node.events[-1] == ('finish', False, 'Wander must remain stopped during calibration relocation')
    assert not any(isinstance(e, tuple) and e[0] == 'drive' for e in node.events)
