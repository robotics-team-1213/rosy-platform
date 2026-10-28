"""Validate an OMX native recording config without importing or connecting hardware."""
import argparse
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or '<' in value:
        raise ValueError(f'{name} must be explicitly configured')
    return value


def _positive(value, name, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be finite and positive')
    if integer and type(value) is not int:
        raise ValueError(f'{name} must be an integer')


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('record config must be an object')
    if 'policy' in config:
        raise ValueError('policy execution is not a recording preparation option')
    if set(config) - {'robot', 'teleop', 'dataset', 'display_data', 'resume', 'play_sounds'}:
        raise ValueError('unknown recorder config field')
    if config.get('resume') is not False:
        raise ValueError('resume must be explicitly false; keep previous recordings')
    robot, leader, dataset = (config.get(key) for key in ('robot', 'teleop', 'dataset'))
    if any(not isinstance(section, dict) for section in (robot, leader, dataset)):
        raise ValueError('robot, teleop and dataset objects are required')
    if robot.get('type') == 'bi_omx_follower':
        if leader.get('type') != 'bi_omx_leader':
            raise ValueError('expected bi_omx_leader')
        _text(robot.get('id'), 'bimanual follower id')
        _text(leader.get('id'), 'bimanual leader id')
        devices = []
        for name in ('arm_a', 'arm_b'):
            child, control = robot.get(name), leader.get(name)
            if not isinstance(child, dict) or not isinstance(control, dict):
                raise ValueError('arm_a and arm_b configurations are required')
            if child.get('cameras') != {}:
                raise ValueError('bimanual cameras must be owned only by the parent robot')
            _pair(child, control)
            devices.extend((child, control))
        if len({d['port'] for d in devices}) != 4 or len({d['id'] for d in devices}) != 4:
            raise ValueError('all four arm ports and identities must be distinct')
    else:
        _pair(robot, leader)
    if dataset.get('push_to_hub') is not False or dataset.get('private') is not True:
        raise ValueError('record locally with push_to_hub=false and private=true')
    # LeRobot 0.4.4's recorder feature aggregation drops camera fields when video is false.
    if dataset.get('video', True) is not True:
        raise ValueError('dataset video must be true to preserve camera observations')
    repo_id = _text(dataset.get('repo_id'), 'dataset repo_id')
    if not re.fullmatch(r'[\w-]+/[\w.-]+', repo_id) or '..' in repo_id:
        raise ValueError('dataset repo_id must be namespace/name')
    _text(dataset.get('single_task'), 'single_task')
    root = _text(dataset.get('root'), 'dataset root')
    windows = PureWindowsPath(root)
    if not (PurePosixPath(root).is_absolute() or windows.is_absolute()):
        raise ValueError('dataset root must be absolute')
    resolved = Path(root).resolve()
    if any((p / '.git').exists() for p in (resolved, *resolved.parents)):
        raise ValueError('recording output belongs outside the source checkout')
    if '..' in PurePosixPath(root.replace('\\', '/')).parts:
        raise ValueError('dataset root must not contain parent traversal')
    if Path(root).exists():
        raise ValueError('dataset root already exists; select a new recording')
    for key in ('fps', 'num_episodes'):
        _positive(dataset.get(key), key, integer=True)
    for key in ('episode_time_s', 'reset_time_s'):
        _positive(dataset.get(key), key)
    _cameras(robot.get('cameras'), dataset['fps'])
    return config


def _pair(robot, leader):
    for device, kind in ((robot, 'omx_follower'), (leader, 'omx_leader')):
        if device.get('type') != kind:
            raise ValueError(f'expected {kind}')
        _text(device.get('id'), f'{kind} id')
        port = _text(device.get('port'), f'{kind} port')
        if not re.fullmatch(r'/dev/serial/by-id/[^/\\\s<>]+', port):
            raise ValueError('select a persistent /dev/serial/by-id/ port')
    if robot['port'] == leader['port'] or robot['id'] == leader['id']:
        raise ValueError('leader and follower must have distinct identities and ports')
    if robot.get('use_degrees') is not False or 'use_degrees' in leader:
        raise ValueError('OMX leader uses normalized units; follower use_degrees must be false')
    _positive(robot.get('max_relative_target'), 'max_relative_target')
    if robot['max_relative_target'] > 20:  # normalized units per frame; a typo must not mean unbounded steps
        raise ValueError('max_relative_target must be at most 20')


def _cameras(cameras, fps):
    if not isinstance(cameras, dict) or not cameras:
        raise ValueError('at least one configured camera is required')
    identities = set()
    for name, camera in cameras.items():
        _text(name, 'camera key')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name) or not isinstance(camera, dict):
            raise ValueError('invalid camera configuration')
        identity = camera.get('index_or_path')
        if camera.get('type') != 'opencv' or not isinstance(identity, str) or not re.fullmatch(
                r'/dev/v4l/by-id/[^/\\\s<>]+', identity):
            raise ValueError('camera requires a persistent /dev/v4l/by-id/ identity')
        if identity in identities or camera.get('fps') != fps:
            raise ValueError('camera identities must be distinct and camera fps must match dataset fps')
        identities.add(identity)
        for key in ('width', 'height', 'fps'):
            _positive(camera.get(key), f'camera {key}', integer=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    try:
        validate_config(json.loads(args.config.read_text(encoding='utf-8-sig')))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print('Config valid; device ownership, calibration, stop and actual camera timing remain unverified.')


if __name__ == '__main__':
    main()
