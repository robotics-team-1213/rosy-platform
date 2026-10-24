"""D-854 Policy Runner: stage timing, unit refusal, CORE target decoding; a real LeRobot 0.4.4 ACT round trip."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations/robots/omx/src'))
from rosy.integrations.robots.omx import policy_runner as runner  # noqa: E402

PYTHON = Path(os.environ.get('ROSY_OMX_LEROBOT_PYTHON',
                            str(Path.home() / 'rosy-test/venvs/omx-lerobot-0.4.4/bin/python')))


class Adapter:
    joint_names = ['joint1', 'joint2']
    unit = 'ros_joint_rad'

    def __init__(self, output=(0.1, 0.2)):
        self.output, self.seen = list(output), []

    def preprocess(self, observation, task):
        self.seen.append((observation, task))
        return observation

    def infer(self, batch):
        return self.output

    def postprocess(self, action):
        return action


class Target:
    joint_names = ['joint1', 'joint2']
    unit = 'ros_joint_rad'

    def __init__(self):
        self.sent = []

    def observe(self):
        return {'positions': [0.0, 0.0], 'images': {}}

    def submit(self, positions):
        self.sent.append(positions)


def ticking(step_ns=10):
    now = [0]
    def clock():
        now[0] += step_ns
        return now[0]
    return clock


def test_step_times_every_stage_and_submits_named_targets():
    adapter, target = Adapter(), Target()
    times = runner.step(adapter, target, runner.ActionSpace('ros_joint_rad', 'ros_joint_rad'), 'pick', clock=ticking())
    assert list(times) == list(runner.STAGES) and set(times.values()) == {10}
    assert target.sent == [{'joint1': 0.1, 'joint2': 0.2}] and adapter.seen[0][1] == 'pick'


def test_undefined_unit_conversion_is_refused():
    with pytest.raises(ValueError):
        runner.ActionSpace('lerobot_norm_v1', 'ros_joint_rad')
    with pytest.raises(ValueError):
        runner.ActionSpace('degrees', 'degrees')


@pytest.mark.parametrize('fault', ['adapter_unit', 'target_unit', 'joint_order'])
def test_mismatched_binding_never_observes_or_submits(fault):
    adapter, target = Adapter(), Target()
    space = runner.ActionSpace('ros_joint_rad', 'ros_joint_rad')
    if fault == 'adapter_unit':
        adapter.unit = 'lerobot_norm_v1'  # a normalized checkpoint must never be sent to CORE as rad
    elif fault == 'target_unit':
        target.unit = 'lerobot_norm_v1'
    else:
        target.joint_names = ['joint2', 'joint1']
    target.observe = lambda: pytest.fail('observed before the binding check')
    with pytest.raises(ValueError):
        runner.step(adapter, target, space, '')
    assert target.sent == []


def test_output_must_match_installed_joints():
    assert runner.check_output([0.1, 0.2], ['a', 'b']) == [0.1, 0.2]
    for bad in ([0.1], [0.1, float('nan')]):
        with pytest.raises(ValueError):
            runner.check_output(bad, ['a', 'b'])


def test_failure_never_submits():
    class Broken(Adapter):
        def infer(self, batch):
            raise RuntimeError('model failed')
    target = Target()
    with pytest.raises(RuntimeError):
        runner.step(Broken(), target, runner.ActionSpace('ros_joint_rad', 'ros_joint_rad'), '')
    assert target.sent == []


def test_measure_reports_quantiles_and_first_step():
    report = runner.measure(Adapter(), Target(), runner.ActionSpace('ros_joint_rad', 'ros_joint_rad'), '', warmup=2, steps=100,
                            clock=ticking())
    assert report['steps'] == 100 and report['first_step']['infer'] == 10
    assert report['stages']['end_to_end'] == dict(p50=50, p95=50, p99=50, max=50, mean=50)
    assert runner.summarize([{s: v for s in runner.STAGES} for v in range(1, 101)])['infer']['p99'] == 99
    with pytest.raises(ValueError):
        runner.summarize([])


def test_core_target_decodes_installed_cameras_in_order():
    front, top = bytes(range(12)), bytes(range(12, 24))
    class Client:
        is_connected = True
        info = {'joint_names': ['joint2', 'joint1']}
        def get_observation(self):
            return {'positions': {'joint1': 0.1, 'joint2': 0.2},
                    'cameras': [{'name': 'front', 'shape': [3, 2, 2], 'rgb_base64': base64.b64encode(front).decode()},
                                {'name': 'top', 'shape': [3, 2, 2], 'rgb_base64': base64.b64encode(top).decode()}]}
    target = runner.CoreArmTarget(Client())
    assert target.joint_names == ['joint2', 'joint1'] and target.unit == 'ros_joint_rad'
    observation = target.observe()
    assert observation['positions'] == [0.2, 0.1]
    assert list(observation['images']) == ['front', 'top']
    assert observation['images']['top'].shape == (2, 2, 3) and observation['images']['top'].tobytes() == top
    assert observation['images']['top'].flags.writeable
    Client.is_connected = False
    with pytest.raises(ValueError):
        runner.CoreArmTarget(Client())


@pytest.mark.skipif(not PYTHON.is_file(), reason='isolated LeRobot 0.4.4 environment not configured')
def test_lerobot_adapter_runs_a_saved_act_checkpoint(tmp_path):
    script = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1])/'integrations/robots/omx/src'))
import torch
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.act.configuration_act import ACTConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors
from rosy.integrations.robots.omx import policy_runner as runner
torch.set_num_threads(2)
out = Path(sys.argv[2])
def build(steps, ensemble=None):
    config = ACTConfig(temporal_ensemble_coeff=ensemble,input_features={'observation.state': PolicyFeature(FeatureType.STATE, (2,)),
        'observation.images.front': PolicyFeature(FeatureType.VISUAL, (3, 8, 8))},
        output_features={'action': PolicyFeature(FeatureType.ACTION, (2,))},
        chunk_size=4, n_action_steps=steps, dim_model=64, n_heads=4, dim_feedforward=256,
        n_encoder_layers=1, n_decoder_layers=1, use_vae=False, dropout=0., pretrained_backbone_weights=None,
        device='cpu')
    path = out / f'act-{steps}-{ensemble}'
    ACTPolicy(config).save_pretrained(path)
    stats = {'observation.state': {'mean': torch.zeros(2), 'std': torch.ones(2)},
             'action': {'mean': torch.zeros(2), 'std': torch.ones(2)},
             'observation.images.front': {'mean': torch.full((3, 1, 1), .5), 'std': torch.full((3, 1, 1), .5)}}
    pre, post = make_pre_post_processors(config, dataset_stats=stats)
    pre.save_pretrained(path); post.save_pretrained(path)
    return str(path)
single, queued, ensembled = build(1), build(4), build(1, ensemble=0.01)
kw = dict(joint_names=['joint1', 'joint2'], cameras=['front'], unit='ros_joint_rad')
adapter = runner.LeRobotAdapter(single, 'cpu', **kw)
target = runner.SyntheticTarget(['joint1', 'joint2'], {'front': (8, 8)}, 'ros_joint_rad')
report = runner.measure(adapter, target, runner.ActionSpace('ros_joint_rad', 'ros_joint_rad'), 'pick', warmup=1, steps=3)
assert report['stages']['infer']['p50'] > 0
def refused(path, **extra):
    try:
        runner.LeRobotAdapter(path, 'cpu', **kw, **extra)
    except ValueError:
        return True
    return False
assert refused(queued), 'queued actions must be refused without the bench override'
assert refused(ensembled), 'temporal ensembling must be refused'
assert refused(single, allowed_types=frozenset({'smolvla'})), 'a type outside the allowed set must be refused'
assert refused(single, allowed_types=frozenset({'act', 'diffusion'})), 'only known bench types may be allowed'
bench = runner.LeRobotAdapter(queued, 'cpu', single_step_override=True, **kw)
assert (bench.n_action_steps, bench.saved_n_action_steps) == (1, 4)
assert bench.policy._action_queue.maxlen == 1  # the override reached the loaded policy, not just the attribute
print(json.dumps(report['stages']['end_to_end']))
'''
    result = subprocess.run([str(PYTHON), '-c', script, str(ROOT), str(tmp_path)], capture_output=True,
                            text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-3000:]
    assert json.loads(result.stdout.strip().splitlines()[-1])['p50'] > 0
