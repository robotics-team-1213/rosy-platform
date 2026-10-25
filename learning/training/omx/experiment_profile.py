"""Learning-only arm/camera setup; no device admission or inferred calibration."""
import copy
import hashlib
import json
import math
import re
import struct


def _text(value, label, *, identifier=False):
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value) > 2048 or any(ord(char) < 32 for char in value)):
        raise ValueError(f'{label}: nonempty text required')
    if identifier and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError(f'{label}: invalid identifier')
    return value


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise ValueError(f'{label}: fields differ from learning profile schema')


def _distinct(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f'{label}: duplicate identity')


def validate_profile(document):
    _fields(document, 'schema name mode task arms cameras', 'profile')
    if document['schema'] not in ('rosy.omx.learning-profile/1', 'rosy.omx.learning-profile/2'):
        raise ValueError('unsupported learning profile schema')
    _text(document['name'], 'name')
    _text(document['task'], 'task')
    if document['mode'] not in ('independent', 'cooperative'):
        raise ValueError('unknown learning mode')
    arms, cameras = document['arms'], document['cameras']
    if not isinstance(arms, list) or not 1 <= len(arms) <= 32:
        raise ValueError('one to 32 explicitly identified arms required')
    arm_ids = []
    for arm in arms:
        fields = 'id joint_names units' + (' action_limits' if document['schema'].endswith('/2') else '')
        _fields(arm, fields, 'arm')
        arm_ids.append(_text(arm['id'], 'arm id', identifier=True))
        joints = arm['joint_names']
        if not isinstance(joints, list) or not 1 <= len(joints) <= 64:
            raise ValueError('explicit ordered joints required')
        for joint in joints:
            _text(joint, 'joint name', identifier=True)
        _distinct(joints, 'joint names within arm')
        if arm['units'] not in ('rad', 'degrees', 'normalized_-100_100'):
            raise ValueError('unknown arm units')
        if document['schema'].endswith('/2'):
            limits = arm['action_limits']
            if not isinstance(limits, list) or len(limits) != len(joints):
                raise ValueError('one declared action range per ordered joint required')
            for pair in limits:
                if (not isinstance(pair, list) or len(pair) != 2
                        or any(type(n) not in (int, float) or abs(n) > 1e6 or not math.isfinite(n) for n in pair)
                        or pair[0] >= pair[1]):
                    raise ValueError('finite increasing declared action limits required')
                lower, upper = (struct.unpack('f', struct.pack('f', n))[0] for n in pair)
                if not lower < upper:
                    raise ValueError('declared action limits must remain distinct at float32 precision')
    _distinct(arm_ids, 'arm ids')
    if not isinstance(cameras, list) or not 1 <= len(cameras) <= 64:
        raise ValueError('one to 64 declared cameras required')
    for camera in cameras:
        _fields(camera, 'id input_key arm_id role source_identity placement shape purposes', 'camera')
        for key in ('id', 'role', 'placement'):
            _text(camera[key], f'camera {key}', identifier=True)
        _text(camera['source_identity'], 'camera source')
        if (not isinstance(camera['input_key'], str)
                or not re.fullmatch(r'observation\.images\.[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',
                                    camera['input_key'])):
            raise ValueError('explicit camera model input key required')
        if camera['arm_id'] is not None and camera['arm_id'] not in arm_ids:
            raise ValueError('camera references unknown arm')
        shape = camera['shape']
        if (not isinstance(shape, list) or len(shape) != 3 or shape[0] != 3
                or any(type(size) is not int or not 1 <= size <= 4096 for size in shape)):
            raise ValueError('RGB CHW camera shape required')
        purposes = camera['purposes']
        allowed = ('policy', 'record', 'reward', 'evaluation', 'monitor')
        if (not isinstance(purposes, list) or not purposes
                or any(purpose not in allowed for purpose in purposes)):
            raise ValueError('unknown camera purpose')
        _distinct(purposes, 'camera purposes')
    for key in ('id', 'input_key', 'source_identity'):
        _distinct([camera[key] for camera in cameras], f'camera {key}')
    if not policy_cameras(document):
        raise ValueError('at least one policy camera required')
    return copy.deepcopy(document)


def action_names(profile):
    return [f"{arm['id']}/{joint}" for arm in profile['arms'] for joint in arm['joint_names']]


def action_bounds(profile):
    checked = validate_profile(profile)
    if checked['schema'] != 'rosy.omx.learning-profile/2':
        raise ValueError('continuous learning requires declared action limits in profile schema2')
    return [pair for arm in checked['arms'] for pair in arm['action_limits']]


def policy_cameras(profile):
    return [camera['input_key'] for camera in profile['cameras'] if 'policy' in camera['purposes']]


def profile_revision(profile):
    raw = json.dumps(validate_profile(profile), sort_keys=True, separators=(',', ':'),
                     ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()
