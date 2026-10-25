"""The existing passive serial owner publishes truthful health, including a latched fault."""
import importlib.util
import json
from pathlib import Path

import pytest

from core_common.motor_health import read_motor_health_snapshot

ROOT = Path(__file__).resolve().parents[1]


def producer():
    spec = importlib.util.spec_from_file_location('passive_health', ROOT / 'deploy/robot/omx/passive_motor_health.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value.PassiveMotorHealth


def rows():
    return [dict(id=i, model_number=1060 if i < 14 else 1200, position_raw=2048,
        goal_position_raw=2048, present_pwm_raw=-391 if i == 12 else 0, pwm_limit_raw=400,
        temperature=43, temperature_limit=70, voltage_raw=116, min_voltage_raw=60, max_voltage_raw=140,
        hardware_error=32 if i == 12 else 0, torque_enabled=0) for i in range(11, 17)]


def test_fault32_is_published_without_any_device_access_and_never_cleared_by_end(tmp_path):
    path = tmp_path / 'health.json'
    owner = producer()(path, 'arm_a')
    owner.sample(rows(), captured_at=100., elapsed=.1)
    health, capture = read_motor_health_snapshot(path, 'arm_a', now=100.1)
    assert capture == 100 and health.status == 'fault' and health.evidence == 'disconnected'
    assert health.motors[1].hardware_error == 32 and health.motors[1].fault
    assert health.motors[1].joint == 'joint2' and health.motors[1].torque_enabled is False
    assert health.motors[1].pwm == -391 and health.motors[1].voltage_v == 11.6
    owner.end()
    ended, _ = read_motor_health_snapshot(path, 'arm_a', now=103.)
    assert ended.status == 'fault' and ended.motors[1].sample_age_s == 3
    assert '/dev/' not in path.read_text()
    with pytest.raises(ValueError):
        read_motor_health_snapshot(path, 'arm_b', now=103.)


@pytest.mark.parametrize('invalid', ['stale', 'model', 'missing', 'nan', 'zero_cap', 'negative_cap'])
def test_incomplete_untrusted_samples_do_not_publish(tmp_path, invalid):
    path = tmp_path / 'health.json'
    owner, sample = producer()(path, 'arm_a'), rows()
    if invalid == 'model':
        sample[0]['model_number'] = 1200
    elif invalid == 'missing':
        sample.pop()
    elif invalid == 'nan':
        sample[0]['temperature'] = float('nan')
    elif invalid in ('zero_cap', 'negative_cap'):
        sample[0]['pwm_limit_raw'] = 0 if invalid == 'zero_cap' else -1
    with pytest.raises((ValueError, KeyError)):
        owner.sample(sample, captured_at=100., elapsed=.3 if invalid == 'stale' else .1)
    assert not path.exists()
