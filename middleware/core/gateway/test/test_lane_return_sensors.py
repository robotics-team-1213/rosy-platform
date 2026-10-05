"""D-468 gateway admission and provider contract; sensor logic has its own tests."""
from types import SimpleNamespace
import pytest
from core.bridge.control_sensor_adapter import ControlSensorAdapter, ControlSensorConfig


def adapter(mode='enforce',required=('lidar','imu','ir'),floor=True):
    a=ControlSensorAdapter()
    a.config=ControlSensorConfig.from_mapping(dict(mode=mode,required=list(required)))
    a.policy=SimpleNamespace(local_return_allowed=lambda linear,angular,now: floor)
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
    for p in (None,SimpleNamespace(local_return_allowed=lambda *args:1)):
        a.policy=p
        assert not a.return_sensor_allowed(1.1,.02,0.)
    def failure(*args): raise RuntimeError('unavailable')
    a.policy=SimpleNamespace(local_return_allowed=failure)
    assert not a.return_sensor_allowed(1.1,.02,0.)
