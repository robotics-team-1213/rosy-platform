"""D-468 gateway admission and provider contract; sensor logic has its own tests."""
from types import SimpleNamespace
import pytest
from core.bridge.control_sensor_adapter import ControlSensorAdapter, ControlSensorConfig
from core.line_follow_wiring import bind_lane_return_motion
from control.control.command_gate import CommandPolicy, GateInputs, GateSnapshot


def adapter(mode='enforce',required=('lidar','imu','ir'),floor=True):
    a=ControlSensorAdapter()
    a.config=ControlSensorConfig.from_mapping(dict(mode=mode,required=list(required)))
    a.policy=SimpleNamespace(local_return_allowed=lambda linear,angular,now: floor)
    return a


def real_policy_adapter():
    a=ControlSensorAdapter()
    a.config=ControlSensorConfig.from_mapping(dict(mode='enforce',required=['lidar','imu','ir']))
    a.policy=CommandPolicy('rig-a')
    assert a.policy.update(GateSnapshot(a.policy.session,1,a.policy.revision,1.,1.3,
        GateInputs(floor_observed=True)))
    return a


def test_enforced_adapter_forwards_candidate_and_original_clock_to_provider():
    a=adapter()
    calls=[]
    def evaluate(linear,angular,now):
        calls.append((linear,angular,now))
        return True
    a.policy=SimpleNamespace(local_return_allowed=evaluate)
    assert a.return_sensor_allowed(1.1,.02,.1)
    assert calls == [(.02,.1,1.1)]
    a.policy=SimpleNamespace(local_return_allowed=lambda *args: False)
    assert not a.return_sensor_allowed(1.1,.02,.1)


def test_enforced_floor_proof_uses_real_policy_source_deadline():
    a=real_policy_adapter()
    assert a.return_sensor_allowed(1.1,.02,.1)
    assert not a.return_sensor_allowed(1.31,.02,.1)
    a.policy.invalidate()
    assert not a.return_sensor_allowed(1.1,.02,.1)


@pytest.mark.parametrize('mode',['off','shadow'])
def test_nondeciding_worker_cannot_authorize_return(mode):
    assert not adapter(mode).return_sensor_allowed(1.1,.02,0.)


def test_missing_ir_unknown_floor_and_closed_worker_cannot_authorize_return():
    assert not adapter(required=('lidar','imu')).return_sensor_allowed(1.1,.02,0.)
    assert not adapter(required=('ir',)).return_sensor_allowed(1.1,.02,0.)
    assert not adapter(floor=False).return_sensor_allowed(1.1,.02,0.)
    a=adapter()
    a._closed=True
    assert not a.return_sensor_allowed(1.1,.02,0.)


def test_absent_failing_or_nonboolean_provider_denies_return():
    a=adapter()
    for p in (None, SimpleNamespace(), SimpleNamespace(local_return_allowed=lambda *args: 1)):
        a.policy=p
        assert not a.return_sensor_allowed(1.1,.02,0.)
    def failure(*args): raise RuntimeError('unavailable')
    a.policy=SimpleNamespace(local_return_allowed=failure)
    assert not a.return_sensor_allowed(1.1,.02,0.)


def test_core_binds_each_return_candidate_to_both_live_proofs():
    seen=[]
    line=SimpleNamespace(return_body_clear=lambda *args:seen.append(('body',args)) or True,
                         bind_return_motion=lambda provider:setattr(line,'provider',provider))
    sensor=SimpleNamespace(return_sensor_allowed=lambda *args:seen.append(('sensor',args)) or True)
    bind_lane_return_motion(line,sensor)
    assert line.provider(1.1,.02,.1) is True
    assert seen==[('sensor',(1.1,.02,.1)),('body',(1.1,.02,.1))]
    sensor.return_sensor_allowed=lambda *args:False
    assert line.provider(1.1,.02,.1) is False
    assert len(seen)==2  # no geometric result can override a rejected sensor lease


def test_sim_time_line_clock_asks_the_policy_on_its_own_monotonic_clock():
    # Under use_sim_time the line clock is sim seconds; the worker policy window (and
    # SafetyManager) is time.monotonic. The body sweep stays on the line clock.
    seen=[]
    line=SimpleNamespace(return_body_clear=lambda *args:seen.append(('body',args)) or True,
                         bind_return_motion=lambda provider:setattr(line,'provider',provider))
    sensor=SimpleNamespace(return_sensor_allowed=lambda *args:seen.append(('sensor',args)) or True)
    bind_lane_return_motion(line,sensor,policy_clock=lambda:500.25)
    assert line.provider(12.5,.02,.1) is True
    assert seen==[('sensor',(500.25,.02,.1)),('body',(12.5,.02,.1))]


def test_sim_time_floor_proof_holds_against_a_real_policy_window():
    a=real_policy_adapter()  # window [1.0, 1.3] on the policy clock
    line=SimpleNamespace(return_body_clear=lambda *args:True,
                         bind_return_motion=lambda provider:setattr(line,'provider',provider))
    bind_lane_return_motion(line,a)
    assert line.provider(40.0,.02,.1) is False   # sim seconds outside the monotonic window
    bind_lane_return_motion(line,a,policy_clock=lambda:1.1)
    assert line.provider(40.0,.02,.1) is True
