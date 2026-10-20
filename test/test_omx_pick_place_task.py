"""Independent object success must require lift, release and measured settling."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'deploy/robot/omx'))


def observations():
    def sample(clock, z=0.025):
        return {'model_id': 'infeed_block', 'clock': clock,
                'model_pose_base': {'x_m': 0.1725, 'y_m': 0.0425, 'z_m': z},
                'gripper_position': 1.0}
    return [sample(0., 0.015), sample(0.2, 0.055)] + [
        sample(1. + i * 0.1) for i in range(23)]


def judge(samples=None, *, released=True):
    from sim_pick_place_task import judge_episode
    return judge_episode(samples if samples is not None else observations(),
                         model='infeed_block', initial_z=0.015,
                         goal=(0.1725, 0.0425, 0.025), released_at=1., released=released)


def test_independent_lift_release_and_two_second_settle_succeed():
    result = judge()
    assert result['success'] is True
    assert result['lift_m'] == pytest.approx(0.04)
    assert result['stable_sim_s'] >= 2.
    assert result['xy_error_m'] == pytest.approx(0.)


def test_a_placed_but_never_lifted_block_is_not_a_pick():
    samples = observations()[2:]
    assert judge(samples)['success'] is False


def test_attached_or_unreleased_object_cannot_pass():
    assert judge(released=False)['success'] is False


@pytest.mark.parametrize('mutation', ['short', 'moving', 'closed', 'wrong_model', 'clock_reset', 'nan'])
def test_bad_or_incomplete_measurements_never_pass(mutation):
    samples = deepcopy(observations())
    if mutation == 'short':
        samples = samples[:15]
    elif mutation == 'moving':
        for i, sample in enumerate(samples[2:]):
            sample['model_pose_base']['x_m'] += (i % 2) * 0.006
    elif mutation == 'closed':
        for sample in samples[2:]:
            sample['gripper_position'] = 0.4
    elif mutation == 'wrong_model':
        samples[-1]['model_id'] = 'another_block'
    elif mutation == 'clock_reset':
        samples[-1]['clock'] = 0.
    else:
        samples[-1]['model_pose_base']['x_m'] = float('nan')
    assert judge(samples)['success'] is False


def test_named_native_task_uses_existing_isolated_launcher_and_explicit_approvals():
    from native_sim_prepare import run_script
    script = run_script('/candidate', experiment='pick-place')
    assert '/candidate/deploy/robot/omx/sim_pick_place_task.py' in script
    assert '--approve-isolated-simulation --approve-startup-home' in script
    assert '$OMX_NATIVE_STATE/pick-place' in script
    with pytest.raises(ValueError):
        run_script('/candidate', experiment='arbitrary-command')


def test_readiness_client_joins_the_same_isolated_domain_as_its_children(tmp_path, monkeypatch):
    import g2_common
    import g2_ports
    import g2_runner
    from sim_pick_place_task import run
    monkeypatch.delenv('ROS_DOMAIN_ID', raising=False)
    monkeypatch.setattr(g2_ports, 'isolation_guard', lambda _root: None)
    child_domains = []

    class Children:
        def __init__(self, directory):
            pass

        def start(self, name, command, *, env):
            child_domains.append(env['ROS_DOMAIN_ID'])

        def close(self):
            return True

    def readiness(**kwargs):
        assert child_domains == ['77', '77']
        assert os.environ.get('ROS_DOMAIN_ID') == child_domains[0]
        raise RuntimeError('stop after readiness probe')

    monkeypatch.setattr(g2_runner, 'Children', Children)
    monkeypatch.setattr(g2_common, 'controller_readiness', readiness)
    destination = tmp_path / 'run'
    assert run(destination) == 1
    assert json.loads((destination / 'result.json').read_text())['error'] == 'RuntimeError: stop after readiness probe'
