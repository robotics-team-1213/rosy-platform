"""The PPO experiment must bind to the current CAD container scene."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from container_rl_fixture import fixture as rl_fixture
from mapped_stack_fixture import container_fixture, plan
from run_catalog import normalize
from stacking_report import _belt_observed


@pytest.mark.parametrize('layers', (1, 2, 3))
def test_ppo_uses_current_cad_scene_and_bounded_independent_evaluation(layers):
    base = container_fixture(layers=layers, case='nominal')
    rl = rl_fixture(layers=layers, case='nominal')
    for key in ('cad_sha256', 'planning_scene', 'belt_center_m', 'belt_pitch_rad',
                'pickup_center_m', 'bin_origin_m', 'arm_bases_m', 'gripper'):
        assert rl.get(key) == base.get(key)
    assert len(plan(True, fixture=rl)) == 3*layers
    assert rl['max_episode_steps'] >= 600*len(plan(True, fixture=rl))
    assert rl['evaluation_seed_offset'] > 0
    config = normalize('omx-map-container-stacking-rl', {'seed': 42, 'layers': layers, 'case': 'nominal'})
    assert config['fixture'] == rl['revision']
    assert config['iterations'] == 32 and config['num_envs'] == 1


def test_cad_belt_observation_requires_downhill_travel():
    rl = rl_fixture(layers=1, case='nominal')
    direction = rl['belt_velocity_m_s']
    magnitude = sum(v*v for v in direction)**.5
    observed = [v*.018/magnitude for v in direction]
    assert _belt_observed(observed, rl)
    assert not _belt_observed([-v for v in observed], rl)
    assert not _belt_observed([0., .018, 0.], rl)


def test_cad_ppo_gets_training_runtime(monkeypatch, tmp_path):
    import run_binding
    import run_store
    import run_system

    monkeypatch.setattr(run_binding, 'load_binding', lambda path: {'data_root': str(tmp_path)})
    monkeypatch.setattr(run_store, 'RunStore', lambda path: type('Store', (), {
        'get': lambda self, run_id: {'input': {'scenario_id': 'omx-map-container-stacking-rl'}}})())
    commands = []
    monkeypatch.setattr(run_system.subprocess, 'run', lambda command, **kwargs: commands.append(command))
    run_system.System().launch('rosy-isaac-' + 'a'*32 + '.service', tmp_path/'binding', 'a'*32)
    assert '--property=RuntimeMaxSec=4200' in commands[0]
