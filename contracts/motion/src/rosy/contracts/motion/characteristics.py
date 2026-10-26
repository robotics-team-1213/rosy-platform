"""Versioned measured load domains; validation and storage never admit motion."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import re

import math

def _fields(value, names, label):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        raise ValueError(f"{label}: expected fields {names}")
    return value


def _number(value, label, *, positive=False):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label}: expected finite numeric measurement")
    if positive and value <= 0:
        raise ValueError(f"{label}: measurement outside allowed range")
    return value


def _vector(value, size, label):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{label}: expected {size} measurements")
    return [_number(item, label) for item in value]


def _range(value, label):
    low, high = _vector(value, 2, label)
    if low >= high:
        raise ValueError(f"{label}: minimum must be below maximum")
    return low, high

SCHEMA = 'rosy.omx-motion-characteristics.v1'
BINDING_FIELDS = ('device_id owner_id motor_group hardware_profile_revision calibration_revision robot_model_sha256 '
                  'installation_revision tool_revision assist_mechanism_revision')
MAX_BYTES = 1_000_000
_NAME = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 512:
        raise ValueError(f'{label}: expected bounded nonempty text')
    return value


def _count(value, label, maximum=1000000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{label}: expected positive bounded integer')
    return value


def _bounds(value, label, *, nonnegative=False):
    low, high = _vector(value, 2, label)
    if low > high or (nonnegative and low < 0):
        raise ValueError(f'{label}: invalid closed interval')
    return low, high


def _joint_map(value, names, label):
    return _fields(value, ' '.join(names), label)


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False, ensure_ascii=True)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ValueError('expected finite JSON data') from exc


def document_digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def validate_characteristics(document):
    """Return a detached validated copy; evidence references remain unverified assertions."""
    data = json.loads(_canonical(document))
    _fields(data, 'schema revision status binding measured_at evidence_ref joints monitor envelopes', 'characteristics')
    if data['schema'] != SCHEMA or data['status'] not in ('draft', 'measured'):
        raise ValueError('unsupported characteristics schema or status')
    _text(data['revision'], 'revision')
    binding = _fields(data['binding'], BINDING_FIELDS, 'binding')
    draft = data['status'] == 'draft'
    for key, value in binding.items():
        if draft and value is None:
            continue
        _text(value, f'binding.{key}')
        if key == 'robot_model_sha256' and re.fullmatch('[0-9a-f]{64}', value) is None:
            raise ValueError('binding.robot_model_sha256: expected lowercase SHA256')
    for key in ('device_id', 'owner_id'):
        if binding[key] is not None and not _NAME.fullmatch(binding[key]):
            raise ValueError(f'binding.{key}: invalid identifier')
    group = binding['motor_group']
    if group is not None and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', group) is None:
        raise ValueError('binding.motor_group: invalid measured group')
    if data['measured_at'] is not None or not draft:
        _text(data['measured_at'], 'measured_at')
        if date.fromisoformat(data['measured_at']).isoformat() != data['measured_at']:
            raise ValueError('measured_at: expected YYYY-MM-DD')
    if data['evidence_ref'] is not None or not draft:
        _text(data['evidence_ref'], 'evidence_ref')
    joints = data['joints']
    if not isinstance(joints, dict) or len(joints) > 32:
        raise ValueError('joints: expected bounded joint map')
    if not joints:
        if draft and data['monitor'] is None and data['envelopes'] == []:
            return data
        raise ValueError('joints: missing measurements')
    seen = set()
    for name, joint in joints.items():
        if not _NAME.fullmatch(name) or len(name) > 64:
            raise ValueError('invalid joint name')
        _fields(joint, 'motor_id motor_model raw_zero rad_per_raw position_rad '
                'velocity_rad_s acceleration_rad_s2', name)
        motor_id = _count(joint['motor_id'], 'motor_id', 253)
        if motor_id in seen:
            raise ValueError('duplicate motor identity')
        seen.add(motor_id)
        _text(joint['motor_model'], 'motor_model')
        _number(joint['raw_zero'], 'raw_zero')
        if _number(joint['rad_per_raw'], 'rad_per_raw') == 0:
            raise ValueError('rad_per_raw: must be nonzero')
        _range(joint['position_rad'], 'position_rad')
        for field in ('velocity_rad_s', 'acceleration_rad_s2'):
            _number(joint[field], field, positive=True)
    _validate_monitor(data['monitor'], joints)
    envelopes = data['envelopes']
    if not isinstance(envelopes, list) or not 1 <= len(envelopes) <= 128:
        raise ValueError('envelopes: expected bounded nonempty list')
    seen = set()
    for envelope in envelopes:
        _validate_envelope(envelope, joints)
        if envelope['id'] in seen:
            raise ValueError('duplicate envelope id')
        seen.add(envelope['id'])
    return data


def _validate_monitor(monitor, joints):
    _fields(monitor, 'max_age_s max_gap_s tracking_duration_s oscillation_window_s '
            'oscillation_cycles joints', 'monitor')
    for key in ('max_age_s', 'max_gap_s', 'tracking_duration_s', 'oscillation_window_s'):
        _number(monitor[key], f'monitor.{key}', positive=True)
    cycles = _count(monitor['oscillation_cycles'], 'oscillation_cycles', 1000)
    if monitor['max_gap_s'] > monitor['oscillation_window_s'] / (4 * cycles):
        raise ValueError('monitor cadence cannot resolve requested oscillations')
    for value in _joint_map(monitor['joints'], joints, 'monitor.joints').values():
        _fields(value, 'error_rad clear_error_rad oscillation_amplitude_rad', 'monitor.joint')
        for key in value:
            _number(value[key], key, positive=True)
        if value['clear_error_rad'] >= value['error_rad']:
            raise ValueError('monitor clear threshold must be below trigger threshold')


def _validate_envelope(e, joints):
    _fields(e, 'id evidence_ref position_rad max_velocity_rad_s max_acceleration_rad_s2 payload_mass_kg '
            'payload_com_min_m payload_com_max_m temperature_c voltage_v max_motion_s max_hold_s '
            'max_cycles min_cycle_interval_s measured_tracking_error_rad', 'envelope')
    for field in ('id', 'evidence_ref'):
        _text(e[field], f'envelope.{field}')
    for name, limits in joints.items():
        ranges = _joint_map(e['position_rad'], joints, 'envelope.position_rad')
        low, high = _range(ranges[name], 'envelope.position_rad')
        if low < limits['position_rad'][0] or high > limits['position_rad'][1]:
            raise ValueError('envelope position exceeds hardware profile limits')
        for key, hard in (('max_velocity_rad_s', 'velocity_rad_s'),
                          ('max_acceleration_rad_s2', 'acceleration_rad_s2')):
            value = _joint_map(e[key], joints, key)[name]
            if _number(value, key, positive=True) > limits[hard]:
                raise ValueError(f'envelope {key} exceeds hardware profile limits')
    _bounds(e['payload_mass_kg'], 'payload_mass_kg', nonnegative=True)
    minimum = _vector(e['payload_com_min_m'], 3, 'payload_com_min_m')
    maximum = _vector(e['payload_com_max_m'], 3, 'payload_com_max_m')
    if any(lo > hi for lo, hi in zip(minimum, maximum)):
        raise ValueError('invalid payload COM bounds')
    _bounds(e['temperature_c'], 'temperature_c')
    if _bounds(e['voltage_v'], 'voltage_v')[0] <= 0:
        raise ValueError('voltage must be positive')
    for key in ('max_motion_s', 'max_hold_s'):
        _number(e[key], key, positive=True)
    for key in ('min_cycle_interval_s', 'measured_tracking_error_rad'):
        if _number(e[key], key) < 0:
            raise ValueError(f'{key}: expected nonnegative value')
    _count(e['max_cycles'], 'max_cycles')


def characteristics_digest(document):
    return document_digest(validate_characteristics(document))
