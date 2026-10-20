"""Automatic SIM truth requires exact execution bytes and measured object success."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT/'contracts/learning/src'), str(ROOT/'deploy/robot/omx'),
               str(ROOT/'learning/curation/omx')]


def measured_samples():
    samples = []
    for index in range(41):
        clock = 1+index/10
        xyz = (.2, 0., .015) if index == 0 else (.2, 0., .115) if index < 10 else (.2075, .0725, .025)
        samples.append({'model_id': 'infeed_block', 'clock': clock,
            'model_pose_base': dict(zip(('x_m','y_m','z_m'), xyz)),
            'gripper_position': .42 if index < 10 else 1.})
    return samples


def test_measured_judge_is_shared_with_the_native_object_task():
    from rosy.contracts.learning.sim_object_truth import judge_episode
    from sim_pick_place_task import judge_episode as native_judge
    assert native_judge is judge_episode
    result = judge_episode(measured_samples(), model='infeed_block', initial_z=.015,
                           goal=(.2075,.0725,.025), released_at=2., released=True)
    assert result['success'] is True
    assert result['lift_m'] == pytest.approx(.1)


@pytest.mark.parametrize('change', ['unknown_object','no_lift','closed','reset','not_released'])
def test_automatic_truth_never_accepts_contradictory_measurements(change):
    from rosy.contracts.learning.sim_object_truth import judge_episode
    samples = measured_samples()
    if change == 'unknown_object':
        samples[-1]['model_id'] = 'another-object'
    elif change == 'no_lift':
        for row in samples:
            row['model_pose_base']['z_m'] = .025
    elif change == 'closed':
        for row in samples:
            row['gripper_position'] = .42
    elif change == 'reset':
        samples[-1]['clock'] = 0.
    result = judge_episode(samples, model='infeed_block', initial_z=.015,
        goal=(.2075,.0725,.025), released_at=2., released=change != 'not_released')
    assert result['success'] is False


def test_explicit_companion_is_required_and_missing_bytes_fail_before_conversion(tmp_path):
    from common_episode import convert
    from test_common_episode import recorded
    source = recorded(tmp_path)
    output = tmp_path/'converted'
    with pytest.raises((ValueError, FileNotFoundError)):
        convert(source, output, sim_ground_truth=tmp_path/'missing-proof.json')
    assert not output.exists()
