import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy/robot/omx'))
import teleop_speed as ts  # noqa: E402
from guarded_device import PROFILE_ACC, PROFILE_VEL  # noqa: E402


def test_each_stage_fixes_tracking_limit_servo_profile_and_acceleration():
    # vel raw = ceil(1.1 * stage / 1.374); acc raw = ceil(vel * 1.374 / 0.15 / 21.4577)
    assert ts.STAGES == {
        30: {'track_deg_s': 30.0, 'profile_vel': 25, 'profile_acc': 11, 'accel_deg_s2': 30.0, 'brake_deg_s2': 245.0},
        45: {'track_deg_s': 45.0, 'profile_vel': 37, 'profile_acc': 16, 'accel_deg_s2': 60.0, 'brake_deg_s2': 690.0},
        60: {'track_deg_s': 60.0, 'profile_vel': 49, 'profile_acc': 21, 'accel_deg_s2': 90.0, 'brake_deg_s2': 1640.0},
    }
    for stage, row in ts.STAGES.items():
        assert row['profile_vel'] * 1.374 >= 1.1 * stage - 1e-9  # at least 10 % faster than the tracking limit
        assert row['profile_vel'] * 1.374 / (row['profile_acc'] * 21.4577) <= 0.15 + 1e-9  # reaches it within 0.15 s
        assert PROFILE_VEL[0] <= row['profile_vel'] <= PROFILE_VEL[1] and PROFILE_ACC[0] <= row['profile_acc'] <= PROFILE_ACC[1]  # guard range unchanged


@pytest.mark.parametrize('content', [None, 'not json', '[]', '{"stage": 25}', '{"stage": "30"}', '{"stage": 30.0}', '{"stage": true}', '{"stage": 90}', '{}'])
def test_a_missing_or_bad_declaration_is_the_current_behaviour(tmp_path, content):
    path = tmp_path / 'teleop-speed-arm_s.json'
    if content is not None:
        path.write_text(content)
    assert ts.read_stage(path) is None
    assert ts.summary(None) == {'stage': None, 'track_deg_s': 25.0, 'accel_deg_s2': 10.0, 'brake_deg_s2': 200.0}


def test_a_valid_declaration_is_read(tmp_path):
    path = tmp_path / 'teleop-speed-arm_s.json'
    for stage in (30, 45, 60):
        path.write_text(json.dumps({'stage': stage}))
        assert ts.read_stage(path) == stage and ts.summary(stage)['profile_vel'] == ts.STAGES[stage]['profile_vel']
    assert ts.stage_from_env({ts.ENV: '45'}) == 45 and ts.stage_from_env({ts.ENV: '50'}) is None and ts.stage_from_env({}) is None


def test_apply_to_caps_changes_only_the_profile_and_not_the_input():
    caps = {11: {'pwm_limit': 300, 'profile_acc': 8, 'profile_vel': 20}, 16: {'pwm_limit': 300, 'current_limit': 250}}
    out = ts.apply_to_caps(caps, 45)
    assert out == {11: {'pwm_limit': 300, 'profile_acc': 16, 'profile_vel': 37}, 16: {'pwm_limit': 300, 'current_limit': 250, 'profile_acc': 16, 'profile_vel': 37}}
    assert caps[11]['profile_vel'] == 20 and 'profile_vel' not in caps[16]
