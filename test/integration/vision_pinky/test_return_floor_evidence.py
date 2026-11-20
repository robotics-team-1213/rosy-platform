"""D-468 positive floor observation is stronger than cliff=False."""
from dataclasses import replace
import pytest
from control.control.floor_evidence import floor_observed
from control.control.command_gate import CommandPolicy, GateInputs, GateSnapshot


@pytest.mark.parametrize('values,known',[
    ([1200,1300,1400],True),([4095,1300,1400],True),
    ([4095,4095,1400],False),([4095,4095,4095],False),
    ([],False),([1200,1300],False),([-1,1300,1400],False),
    ([True,1300,1400],False),([float('nan'),1300,1400],False)])
def test_saturation_missing_or_malformed_ir_is_not_positive_floor(values,known):
    assert floor_observed(values,fresh=True,enabled=True,cliff=False,tilt=False,pickup=False) is known


@pytest.mark.parametrize('key',['fresh','enabled','cliff','tilt','pickup'])
def test_floor_proof_requires_fresh_enabled_nonhazardous_evidence(key):
    flags=dict(fresh=True,enabled=True,cliff=False,tilt=False,pickup=False)
    flags[key]=not flags[key]
    assert not floor_observed([1200,1300,1400],**flags)


def policy(inputs):
    p=CommandPolicy('applied-rig')
    assert p.update(GateSnapshot(p.session,1,p.revision,1.,1.3,inputs))
    return p


def test_existing_cliff_false_cannot_authorize_local_return():
    p=policy(GateInputs())
    assert p.evaluate(.02,0.,1.1)[1].linear==.02
    assert not p.local_return_allowed(.02,0.,1.1)


def test_original_sensor_deadline_and_full_candidate_restriction_are_retained():
    p=policy(GateInputs(floor_observed=True))
    assert p.local_return_allowed(.02,.1,1.1)
    assert not p.local_return_allowed(.02,.1,1.31)
    p.invalidate()
    assert not p.local_return_allowed(.02,.1,1.1)


@pytest.mark.parametrize('flags',[dict(cliff=True),dict(tilt=True),dict(pickup=True),
    dict(profile_valid=False),dict(observation_failure='ir_unavailable'),
    dict(localization_ready=False),dict(can_rotate=False),dict(rear_blocked=True)])
def test_floor_flag_never_overrides_candidate_restrictions(flags):
    p=policy(replace(GateInputs(floor_observed=True),**flags))
    assert not p.local_return_allowed(-.02,.1,1.1)


def test_floor_handoff_deadline_includes_all_hazard_sensor_dependencies():
    from control.control.policy_handoff import ControlPolicyProducer
    from control.sensing.observation import Observations
    observations=Observations(max_age=.5)
    for name,t in (('ir',1.),('imu',.55),('lidar',.55)):
        observations.add(name,t)
    p=CommandPolicy('rig-a')
    producer=ControlPolicyProducer(p,observations,('ir',),p.revision)
    assert producer.publish(GateInputs(floor_observed=True),now=1.01)
    assert p.local_return_allowed(.02,0.,1.02)
    assert not p.local_return_allowed(.02,0.,1.2)


def test_positive_floor_cannot_publish_with_missing_imu_even_if_only_ir_was_configured():
    from control.control.policy_handoff import ControlPolicyProducer
    from control.sensing.observation import Observations
    observations=Observations(max_age=.5)
    observations.add('ir',1.)
    p=CommandPolicy('rig-a')
    producer=ControlPolicyProducer(p,observations,('ir',),p.revision)
    assert not producer.publish(GateInputs(floor_observed=True),now=1.01)
