import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def module():
    path = ROOT / 'deploy/robot/omx/record_config.py'
    assert path.is_file(), 'OMX recorder config validator is not implemented'
    spec = importlib.util.spec_from_file_location('omx_record_config', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def config(tmp_path):
    return {
        'robot': {'type': 'omx_follower', 'id': 'follower',
                  'port': '/dev/serial/by-id/follower', 'use_degrees': False,
                  'max_relative_target': 1.0,
                  'cameras': {'front': {'type': 'opencv', 'index_or_path': '/dev/v4l/by-id/camera',
                                        'width': 640, 'height': 480, 'fps': 30}}},
        'teleop': {'type': 'omx_leader', 'id': 'leader', 'port': '/dev/serial/by-id/leader'},
        'dataset': {'repo_id': 'local/omx-pick', 'root': str(tmp_path / 'recording'),
                    'single_task': 'Put the cube in the tray', 'fps': 30,
                    'num_episodes': 5, 'episode_time_s': 30, 'reset_time_s': 15,
                    'push_to_hub': False, 'private': True},
        'display_data': True, 'resume': False,
    }


def test_preparation_keeps_official_config_without_connecting(module, config):
    original = copy.deepcopy(config)
    assert module.validate_config(config) == original
    assert config == original


@pytest.mark.parametrize("linked", [False, True])
def test_recording_root_refuses_any_source_checkout(module, config, tmp_path, linked):
    checkout = tmp_path / "source"
    checkout.mkdir()
    if linked:
        (checkout / ".git").write_text("gitdir: elsewhere\n")
    else:
        (checkout / ".git").mkdir()
    config['dataset']['root'] = str(checkout / "new-recording")
    with pytest.raises(ValueError, match='outside the source checkout'):
        module.validate_config(config)
    assert not Path(config['dataset']['root']).exists()


@pytest.mark.parametrize('section,key,value', [
    ('dataset', 'push_to_hub', True), ('dataset', 'private', False),
    ('dataset', 'fps', 0), ('dataset', 'fps', True),
    ('dataset', 'root', str(Path(__file__).resolve().parents[1] / 'recording')), ('dataset', 'root', '../recording'),
    ('dataset', 'repo_id', '<org>/recording'), ('dataset', 'single_task', ''),
    ('robot', 'port', '/dev/ttyACM0'), ('robot', 'id', ''),
    ('robot', 'max_relative_target', None), ('robot', 'max_relative_target', float('nan')),
    ('teleop', 'port', '/dev/serial/by-id/follower'), ('teleop', 'use_degrees', True),
    ('robot', 'use_degrees', True),
])
def test_unsafe_or_unfilled_record_settings_are_rejected(module, config, section, key, value):
    config[section][key] = value
    with pytest.raises(ValueError):
        module.validate_config(config)


def test_existing_recording_and_policy_are_not_silently_reused(module, config):
    Path(config['dataset']['root']).mkdir()
    with pytest.raises(ValueError, match='exist'):
        module.validate_config(config)
    config['dataset']['root'] += '-new'
    config['policy'] = {'path': 'someone/model'}
    with pytest.raises(ValueError, match='policy'):
        module.validate_config(config)


def test_camera_rate_and_stable_identity_are_required(module, config):
    camera = config['robot']['cameras']['front']
    camera['fps'] = 15
    with pytest.raises(ValueError, match='camera'):
        module.validate_config(config)
    camera['fps'] = 30
    camera['index_or_path'] = 0
    with pytest.raises(ValueError, match='camera'):
        module.validate_config(config)


def test_example_is_inert_and_default_private(module):
    example = json.loads((ROOT / 'deploy/robot/omx/lerobot-record.example.json').read_text())
    assert example['dataset']['push_to_hub'] is False
    assert example['dataset']['private'] is True
    with pytest.raises(ValueError):
        module.validate_config(example)


def bimanual(config):
    robot, leader = config['robot'], config['teleop']
    config['robot'] = {'type': 'bi_omx_follower', 'id': 'two_followers', 'cameras': robot['cameras']}
    config['teleop'] = {'type': 'bi_omx_leader', 'id': 'two_leaders'}
    for name in ('arm_a', 'arm_b'):
        config['robot'][name] = {**robot, 'id': name + '_follower',
                                 'port': robot['port'] + '_' + name, 'cameras': {}}
        config['teleop'][name] = {**leader, 'id': name + '_leader', 'port': leader['port'] + '_' + name}
    return config


def test_bimanual_config_has_four_distinct_ports_and_parent_camera(module, config):
    config = bimanual(config)
    assert module.validate_config(config) == config
    config['teleop']['arm_b']['port'] = config['robot']['arm_a']['port']
    with pytest.raises(ValueError, match='distinct'):
        module.validate_config(config)


def test_bimanual_children_cannot_reopen_shared_camera(module, config):
    config = bimanual(config)
    config['robot']['arm_a']['cameras'] = config['robot']['cameras']
    with pytest.raises(ValueError, match='camera'):
        module.validate_config(config)


@pytest.mark.parametrize('paired', [False, True])
@pytest.mark.parametrize('video', [False, None, 0, 'true'])
def test_native_sdk_camera_omission_is_rejected_before_recording(module, config, paired, video):
    if paired:
        config = bimanual(config)
    config['dataset']['video'] = video
    with pytest.raises(ValueError, match='video'):
        module.validate_config(config)


@pytest.mark.parametrize('paired', [False, True])
def test_explicit_native_video_recording_remains_admissible(module, config, paired):
    if paired:
        config = bimanual(config)
    config['dataset']['video'] = True
    assert module.validate_config(config) == config
