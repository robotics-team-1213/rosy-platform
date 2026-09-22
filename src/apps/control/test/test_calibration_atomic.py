"""CalibrationAtomic decisions on real values (D-171 track 1).

The mixin used to import std_msgs, so host pytest could only AST-extract its
methods. It is now ROS-free: a plain subclass stands in for the node, and the
module's own ``time`` is replaced the same way the sim rig replaces it.
"""
import json
from types import SimpleNamespace

import pytest

from control import calibration_atomic
from control.calibration_atomic import CalibrationAtomic


class Clock:
    def __init__(self, now):
        self.now = now

    def monotonic(self):
        return self.now


class FakeNode(CalibrationAtomic):
    def __init__(self, phase='collecting'):
        self.phase = phase
        self.trial_geometry_revision = None
        self.geometry_revision = None
        self.geometry_profile = None
        self.geometry_received = None
        self.gate_decision = None
        self.applied_profile = None
        self.profile_revision = 'rev-1'
        self.profile_session = 'session-1'
        self.runtime_ready = True
        self.runtime_healthy_since = 1.
        self.events = []
        self.ros_now_s = 100.

    def zero(self):
        self.events.append('zero')

    def stop_wander(self):
        self.events.append('stop_wander')

    def publish(self):
        self.events.append('publish')

    def finish(self, ok, message):
        self.events.append(('finish', ok, message))

    def get_clock(self):
        return SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=int(self.ros_now_s * 1e9)))


@pytest.fixture
def clock(monkeypatch):
    fake = Clock(50.)
    monkeypatch.setattr(calibration_atomic, 'time', fake)
    return fake


def msg(value):
    return SimpleNamespace(data=json.dumps(value))


def profile(revision='geom-A', turn_clear=.2, valid=True):
    return msg({'valid': valid, 'revision': revision, 'effective': {'turn_clear': turn_clear}})


def test_module_is_ros_free():
    assert 'std_msgs' not in calibration_atomic.__dict__
    assert not hasattr(calibration_atomic, 'String')


@pytest.mark.parametrize('message', [
    profile(valid=False), profile(revision=''), profile(turn_clear=0.), profile(turn_clear=float('inf')),
    SimpleNamespace(data='not json'), msg([1, 2]), msg({'valid': True, 'revision': 'x'}),
])
def test_invalid_safety_profile_clears_geometry(clock, message):
    node = FakeNode()
    node.on_safety_profile(profile())
    node.on_safety_profile(message)
    assert node.geometry_revision is None and node.geometry_profile is None


def test_ready_robot_stops_when_safety_geometry_changes(clock):
    node = FakeNode(phase='ready')
    node.on_safety_profile(profile('geom-A'))
    assert node.trial_geometry_revision == 'geom-A'          # legacy certificate binds once
    node.events.clear()
    node.on_safety_profile(profile('geom-B'))
    assert node.runtime_ready is False and node.runtime_healthy_since is None
    assert node.events == ['zero', 'stop_wander', 'publish']
    assert 'differs from verified identity' in node.message


def test_changed_geometry_during_a_trial_fails_the_calibration(clock):
    node = FakeNode(phase='validating_motion')
    node.trial_geometry_revision = 'geom-A'
    node.on_safety_profile(profile('geom-B'))
    assert node.events == [('finish', False, 'Safety geometry changed; recalibration required')]


@pytest.mark.parametrize('age, fresh', [(-.2, False), (-.1, True), (0., True), (.25, True), (.3, False)])
def test_gate_decision_freshness_window(clock, age, fresh):
    node = FakeNode()
    fields = dict(requested_v=.1, requested_omega=0., safe_v=.1, safe_omega=0., issued_s=node.ros_now_s - age)
    node.on_gate_decision(msg(fields))
    assert (node.gate_decision is not None) is fresh
    if fresh:
        assert node.gate_decision[0] == pytest.approx(clock.now + .25 - max(0., age))


def test_trial_gate_reason_order(clock):
    node = FakeNode(phase='validating_motion')
    assert node.trial_gate_reason(clock.now) == 'Fresh effective safety profile required'
    node.on_safety_profile(profile())
    assert node.trial_gate_reason(clock.now) == 'Fresh final safety command evidence required'
    node.on_gate_decision(msg(dict(requested_v=.1, requested_omega=0., safe_v=.05, safe_omega=0.,
                                   issued_s=node.ros_now_s)))
    assert node.trial_gate_reason(clock.now) == 'Safety modified the trial command; response cannot be calibrated'
    node.on_gate_decision(msg(dict(requested_v=.1, requested_omega=0., safe_v=.1, safe_omega=0.,
                                   issued_s=node.ros_now_s)))
    node._trial_request = (clock.now - 1., .2, 0.)            # an older, different request
    assert node.trial_gate_reason(clock.now) == 'Final safety command does not acknowledge the calibration request'
    node._trial_request = (clock.now - 1., .1, 0.)
    assert node.trial_gate_reason(clock.now) is None


def test_trial_gate_is_only_evidence_outside_trials(clock):
    node = FakeNode(phase='collecting')
    node.on_safety_profile(profile())
    node.on_gate_decision(msg(dict(requested_v=.1, requested_omega=0., safe_v=0., safe_omega=0.,
                                   issued_s=node.ros_now_s)))
    assert node.trial_gate_reason(clock.now) is None


def test_settings_applied_needs_fresh_matching_acknowledgement(clock):
    node = FakeNode()
    assert node.settings_applied() is False
    node.on_applied(msg({'applied': True, 'revision': 'rev-1', 'session': 'session-1'}))
    assert node.settings_applied() is True
    clock.now += 1.6
    assert node.settings_applied() is False                   # older than 1.5 s
    node.on_applied(msg({'applied': True, 'revision': 'rev-0', 'session': 'session-1'}))
    assert node.settings_applied() is False                   # another revision
    node.on_applied(msg({'applied': 'yes'}))
    assert node.applied_profile is None
