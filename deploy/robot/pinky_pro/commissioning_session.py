#!/usr/bin/env python3
"""Ordered, fail-closed Pinky Pro commissioning evidence sessions."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone


SCHEMA_VERSION = 1
GATES = ('G0', 'G1', 'G2', 'G3', 'G4', 'G5')
_REVISION = re.compile(r'^[0-9a-f]{40}$')
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_IMAGE_DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
_SESSION_FIELDS = {
    'schema_version', 'session_id', 'created_at', 'robot_number',
    'source_revision', 'connection', 'operator', 'records',
}
_COMMON_RECORD_FIELDS = {
    'schema_version', 'gate', 'captured_at', 'source_revision',
    'robot_number', 'outcome', 'evidence_files',
}


def _copy(value):
    try:
        return json.loads(json.dumps(
            value, sort_keys=True, separators=(',', ':'), allow_nan=False,
        ))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError('commissioning evidence must be finite JSON') from exc


def _timestamp(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be an RFC3339 timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{field} must be an RFC3339 timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f'{field} must include a UTC offset')
    return parsed.astimezone(timezone.utc)


def _robot_number(value):
    if type(value) is not int or not 1 <= value <= 61:
        raise ValueError('robot_number must be an integer from 1 through 61')
    return value


def _source_revision(value):
    if not isinstance(value, str) or not _REVISION.fullmatch(value):
        raise ValueError('source_revision must be a full lowercase Git revision')
    return value


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a non-empty string')
    return value.strip()


def _evidence_files(value):
    if (not isinstance(value, list) or not value or
            not all(isinstance(item, str) and _SHA256.fullmatch(item)
                    for item in value)):
        raise ValueError('evidence_files must contain SHA-256 digests')
    if len(set(value)) != len(value):
        raise ValueError('evidence_files must not contain duplicate digests')


def _number(value, field, *, minimum=None, maximum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value)):
        raise ValueError(f'{field} must be a finite number')
    numeric = float(value)
    if minimum is not None and numeric < minimum:
        raise ValueError(f'{field} must be at least {minimum}')
    if maximum is not None and numeric > maximum:
        raise ValueError(f'{field} must be at most {maximum}')
    return numeric


def _integer(value, field, *, minimum=None, maximum=None):
    if type(value) is not int:
        raise ValueError(f'{field} must be an integer')
    if minimum is not None and value < minimum:
        raise ValueError(f'{field} must be at least {minimum}')
    if maximum is not None and value > maximum:
        raise ValueError(f'{field} must be at most {maximum}')
    return value


def _zero_velocity(value, field):
    if not isinstance(value, dict) or set(value) != {'linear', 'angular'}:
        raise ValueError(f'{field} must contain linear and angular velocity')
    linear = _number(value['linear'], f'{field}.linear')
    angular = _number(value['angular'], f'{field}.angular')
    if linear != 0.0 or angular != 0.0:
        raise ValueError(f'{field} must report zero velocity')


def _validate_g0(record, session):
    expected = _COMMON_RECORD_FIELDS | {'artifact'}
    if set(record) != expected:
        raise ValueError('G0 evidence fields are incomplete or unknown')
    artifact = record['artifact']
    if not isinstance(artifact, dict) or set(artifact) != {
        'manifest_verified', 'signature_status', 'git_revision',
        'target', 'containers',
    }:
        raise ValueError('G0 artifact evidence is incomplete')
    if artifact['manifest_verified'] is not True:
        raise ValueError('G0 manifest must be verified')
    if artifact['signature_status'] != 'verified':
        raise ValueError('G0 signature must be verified')
    if artifact['git_revision'] != session['source_revision']:
        raise ValueError('G0 artifact source_revision mismatch')
    target = artifact['target']
    if target != {
        'board': 'raspberry-pi-5',
        'architecture': 'arm64',
        'os_family': 'raspberry-pi-os-lite',
    }:
        raise ValueError('G0 artifact target must be Raspberry Pi 5 arm64 Lite')
    containers = artifact['containers']
    if (not isinstance(containers, dict) or
            set(containers) != {'rosy_core', 'rosy_io'} or
            not all(isinstance(value, str) and _IMAGE_DIGEST.fullmatch(value)
                    for value in containers.values())):
        raise ValueError('G0 requires immutable core and IO image digests')


def _validate_g1(record, session):
    if set(record) != _COMMON_RECORD_FIELDS | {'install'}:
        raise ValueError('G1 evidence fields are incomplete or unknown')
    install = record['install']
    if not isinstance(install, dict) or set(install) != {
            'exit_code', 'install_root', 'runtime_mode', 'identity'}:
        raise ValueError('G1 install evidence is incomplete')
    if _integer(install['exit_code'], 'G1 exit_code') != 0:
        raise ValueError('G1 installer exit_code must be zero')
    if install['install_root'] != '/opt/rosy':
        raise ValueError('G1 install_root must be /opt/rosy')
    if install['runtime_mode'] != 'core':
        raise ValueError('G1 must install in core runtime mode')
    number = session['robot_number']
    expected_identity = {
        'robot_number': number,
        'ros_domain_id': 40 + number,
        'namespace': f'rosy_{number:02d}',
    }
    identity = install['identity']
    if (not isinstance(identity, dict) or set(identity) != set(expected_identity) or
            type(identity.get('robot_number')) is not int or
            type(identity.get('ros_domain_id')) is not int or
            identity != expected_identity):
        raise ValueError('G1 derived identity does not match the robot number')


def _validate_g2(record, session):
    if set(record) != _COMMON_RECORD_FIELDS | {'readback'}:
        raise ValueError('G2 evidence fields are incomplete or unknown')
    readback = record['readback']
    if not isinstance(readback, dict):
        raise ValueError('G2 readback evidence must be an object')

    number = session['robot_number']
    identity = readback.get('identity')
    expected_identity = {
        'robot_number': str(number),
        'ros_domain_id': str(40 + number),
        'namespace': f'rosy_{number:02d}',
        'runtime_mode': 'core',
    }
    if identity != expected_identity:
        raise ValueError('G2 readback identity does not match derived identity')

    artifact = readback.get('artifact')
    g0_artifact = session['records']['G0']['artifact']
    if (not isinstance(artifact, dict) or
            artifact.get('status') != 'available' or
            artifact.get('git_revision') != session['source_revision'] or
            artifact.get('containers') != g0_artifact['containers'] or
            not isinstance(artifact.get('signature'), dict) or
            artifact['signature'].get('status') != 'verified'):
        raise ValueError('G2 readback does not match the G0 artifact')

    runtime = readback.get('runtime')
    core = runtime.get('core') if isinstance(runtime, dict) else None
    if (not isinstance(runtime, dict) or runtime.get('systemd') != 'active' or
            not isinstance(core, dict) or core.get('status') != 'running' or
            core.get('health') != 'healthy' or
            core.get('image_match') != 'verified'):
        raise ValueError('G2 core runtime is not active, healthy, and verified')
    graph = readback.get('ros_graph')
    if (not isinstance(graph, dict) or graph.get('status') != 'available' or
            type(graph.get('cmd_vel_publishers')) is not int or
            graph.get('cmd_vel_publishers') != 1):
        raise ValueError('G2 requires exactly one cmd_vel publisher')
    gates = readback.get('gates')
    if not isinstance(gates, dict) or gates.get('device_runtime') != 'GO':
        raise ValueError('G2 device_runtime gate must be GO')


def _validate_g3(record, session):
    if set(record) != _COMMON_RECORD_FIELDS | {'stationary'}:
        raise ValueError('G3 evidence fields are incomplete or unknown')
    stationary = record['stationary']
    if not isinstance(stationary, dict) or set(stationary) != {
            'runtime_mode', 'cmd_vel_publishers', 'duration_s', 'samples'}:
        raise ValueError('G3 stationary evidence is incomplete')
    if stationary['runtime_mode'] != 'core':
        raise ValueError('G3 must run in core runtime mode')
    if (type(stationary['cmd_vel_publishers']) is not int or
            stationary['cmd_vel_publishers'] != 1):
        raise ValueError('G3 requires exactly one cmd_vel publisher')
    _number(stationary['duration_s'], 'G3 duration_s', minimum=2.0)
    samples = stationary['samples']
    if not isinstance(samples, list) or len(samples) < 10:
        raise ValueError('G3 requires at least 10 stationary samples')
    sequences = []
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {
                'sequence', 'mode', 'velocity', 'safety'}:
            raise ValueError('G3 stationary sample is incomplete')
        sequence = sample['sequence']
        if type(sequence) is not int or sequence < 0:
            raise ValueError('G3 sample sequence must be a non-negative integer')
        sequences.append(sequence)
        if sample['mode'] != 'IDLE':
            raise ValueError('G3 mode must remain IDLE')
        safety = sample['safety']
        if not isinstance(safety, dict) or safety.get('estop') is not True:
            raise ValueError('G3 E-stop must remain asserted')
        if set(safety) != {'estop'}:
            raise ValueError('G3 safety sample contains unknown fields')
        _zero_velocity(sample['velocity'], 'G3 zero velocity')
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        raise ValueError('G3 sample sequences must be ordered and unique')


def _validate_g4(record, session):
    if set(record) != _COMMON_RECORD_FIELDS | {'motor'}:
        raise ValueError('G4 evidence fields are incomplete or unknown')
    motor = record['motor']
    if not isinstance(motor, dict) or set(motor) != {
            'operator', 'wheels_lifted', 'hardware_cut_reachable',
            'torque_free_preflight_passed', 'configured_ids',
            'responded_ids', 'deadman_trials'}:
        raise ValueError('G4 motor evidence is incomplete')
    _text(motor['operator'], 'G4 operator')
    if motor['wheels_lifted'] is not True:
        raise ValueError('G4 requires a wheels lifted acknowledgement')
    if motor['hardware_cut_reachable'] is not True:
        raise ValueError('G4 requires a reachable hardware cut-off')
    if motor['torque_free_preflight_passed'] is not True:
        raise ValueError('G4 torque-free preflight must pass')

    configured = motor['configured_ids']
    responded = motor['responded_ids']
    for value, field in ((configured, 'configured_ids'),
                         (responded, 'responded_ids')):
        if (not isinstance(value, list) or not value or
                any(type(item) is not int or item <= 0 for item in value) or
                len(set(value)) != len(value)):
            raise ValueError(f'G4 {field} must contain unique positive integers')
    if sorted(configured) != sorted(responded):
        raise ValueError('G4 all configured motor IDs must respond')

    trials = motor['deadman_trials']
    if not isinstance(trials, list):
        raise ValueError('G4 deadman trials must be a list')
    seen = set()
    for trial in trials:
        if not isinstance(trial, dict) or set(trial) != {
                'direction', 'trial', 'stop_latency_s', 'final_velocity',
                'passed'}:
            raise ValueError('G4 deadman trial is incomplete')
        direction = trial['direction']
        index = trial['trial']
        if direction not in ('forward', 'reverse', 'cw', 'ccw'):
            raise ValueError('G4 deadman direction is invalid')
        if type(index) is not int or index not in (1, 2):
            raise ValueError('G4 requires deadman trials 1 and 2')
        seen.add((direction, index))
        _number(trial['stop_latency_s'], 'G4 deadman stop latency',
                minimum=0.0, maximum=0.65)
        _zero_velocity(trial['final_velocity'], 'G4 deadman final velocity')
        if trial['passed'] is not True:
            raise ValueError('G4 deadman trial must pass')
    expected = {
        (direction, index)
        for direction in ('forward', 'reverse', 'cw', 'ccw')
        for index in (1, 2)
    }
    if seen != expected or len(trials) != len(expected):
        raise ValueError('G4 requires two deadman trials in every direction')


def _validate_g5(record, session):
    if set(record) != _COMMON_RECORD_FIELDS | {'hardware'}:
        raise ValueError('G5 evidence fields are incomplete or unknown')
    hardware = record['hardware']
    if not isinstance(hardware, dict) or set(hardware) != {
            'operator', 'runtime_mode', 'cmd_vel_publishers', 'lidar',
            'telemetry', 'map',
            'navigation', 'final_state'}:
        raise ValueError('G5 hardware evidence is incomplete')
    _text(hardware['operator'], 'G5 operator')
    if hardware['runtime_mode'] != 'hardware':
        raise ValueError('G5 requires hardware runtime mode')
    if (type(hardware['cmd_vel_publishers']) is not int or
            hardware['cmd_vel_publishers'] != 1):
        raise ValueError('G5 requires exactly one cmd_vel publisher')

    lidar = hardware['lidar']
    if (not isinstance(lidar, dict) or set(lidar) != {'fresh', 'scan_hz'} or
            lidar['fresh'] is not True):
        raise ValueError('G5 requires fresh LiDAR evidence')
    _number(lidar['scan_hz'], 'G5 LiDAR scan_hz', minimum=0.001)

    telemetry = hardware['telemetry']
    if not isinstance(telemetry, dict) or set(telemetry) != {
            'format', 'duration_s', 'topics', 'mcap_sha256',
            'metadata_sha256'}:
        raise ValueError('G5 telemetry evidence is incomplete')
    if telemetry['format'] != 'mcap':
        raise ValueError('G5 telemetry format must be mcap')
    _number(
        telemetry['duration_s'], 'G5 telemetry duration',
        minimum=30.0, maximum=1800.0,
    )
    topics = telemetry['topics']
    if (not isinstance(topics, list) or not topics or
            not all(isinstance(topic, str) and topic.startswith('/')
                    for topic in topics) or len(set(topics)) != len(topics)):
        raise ValueError('G5 telemetry topics are invalid')
    required_topics = ('/scan', '/odom', '/cmd_vel', '/map', '/tf', '/tf_static')
    if any(not any(topic == required or topic.endswith(required)
                   for topic in topics) for required in required_topics):
        raise ValueError('G5 telemetry topics are incomplete')
    evidence_digests = set(record['evidence_files'])
    telemetry_digests = {
        telemetry['mcap_sha256'], telemetry['metadata_sha256']
    }
    if (not all(isinstance(digest, str) and _SHA256.fullmatch(digest)
                for digest in telemetry_digests) or
            not telemetry_digests <= evidence_digests):
        raise ValueError('G5 telemetry artifacts must be evidence-bound')

    map_evidence = hardware['map']
    expected_map_keys = {
        'fresh', 'map_id', 'yaml_sha256', 'image_sha256'
    }
    if (not isinstance(map_evidence, dict) or
            set(map_evidence) != expected_map_keys or
            map_evidence['fresh'] is not True):
        raise ValueError('G5 requires a fresh map')
    _text(map_evidence['map_id'], 'G5 map_id')
    map_digests = {
        map_evidence['yaml_sha256'], map_evidence['image_sha256']
    }
    if (not all(isinstance(digest, str) and _SHA256.fullmatch(digest)
                for digest in map_digests) or
            not map_digests <= evidence_digests):
        raise ValueError('G5 map artifacts must be evidence-bound')

    navigation = hardware['navigation']
    if not isinstance(navigation, dict) or set(navigation) != {
            'goal_id', 'status', 'collision_observed'}:
        raise ValueError('G5 navigation evidence is incomplete')
    _text(navigation['goal_id'], 'G5 goal_id')
    if navigation['status'] != 'SUCCEEDED':
        raise ValueError('G5 navigation must succeed')
    if navigation['collision_observed'] is not False:
        raise ValueError('G5 collision evidence must remain false')

    final_state = hardware['final_state']
    if not isinstance(final_state, dict) or set(final_state) != {
            'velocity', 'estop'}:
        raise ValueError('G5 final state is incomplete')
    _zero_velocity(final_state['velocity'], 'G5 final zero velocity')
    if final_state['estop'] is not True:
        raise ValueError('G5 final E-stop must be asserted')


_VALIDATORS = {
    'G0': _validate_g0,
    'G1': _validate_g1,
    'G2': _validate_g2,
    'G3': _validate_g3,
    'G4': _validate_g4,
    'G5': _validate_g5,
}


def new_session(*, robot_number, source_revision, connection, operator,
                created_at=None):
    """Create a blank session bound to one robot and one source revision."""

    robot_number = _robot_number(robot_number)
    source_revision = _source_revision(source_revision)
    if connection not in ('ssh', 'console'):
        raise ValueError('connection must be ssh or console')
    operator = _text(operator, 'operator')
    created_at = created_at or datetime.now(timezone.utc).isoformat(
        timespec='seconds'
    )
    parsed = _timestamp(created_at, 'created_at')
    session_id = f'pinky-{robot_number:02d}-{parsed:%Y%m%dT%H%M%SZ}'
    return {
        'schema_version': SCHEMA_VERSION,
        'session_id': session_id,
        'created_at': created_at,
        'robot_number': robot_number,
        'source_revision': source_revision,
        'connection': connection,
        'operator': operator,
        'records': {},
    }


def validate_session(session):
    """Return a defensive copy of a valid ordered session."""

    session = _copy(session)
    if (set(session) != _SESSION_FIELDS or
            type(session.get('schema_version')) is not int or
            session.get('schema_version') != 1):
        raise ValueError('session fields or schema_version are invalid')
    _text(session['session_id'], 'session_id')
    _timestamp(session['created_at'], 'created_at')
    _robot_number(session['robot_number'])
    _source_revision(session['source_revision'])
    if session['connection'] not in ('ssh', 'console'):
        raise ValueError('connection must be ssh or console')
    _text(session['operator'], 'operator')
    if not isinstance(session['records'], dict):
        raise ValueError('records must be an object')
    completed = list(session['records'])
    if completed != list(GATES[:len(completed)]):
        raise ValueError('records must contain an ordered G0-G5 prefix')
    for gate in completed:
        _validate_record(session['records'][gate], session, gate)
    return session


def next_gate(session):
    session = validate_session(session)
    count = len(session['records'])
    return GATES[count] if count < len(GATES) else None


def _validate_record(record, session, expected_gate):
    if not isinstance(record, dict):
        raise ValueError(f'{expected_gate} evidence must be an object')
    if record.get('gate') != expected_gate:
        raise ValueError(f'gate must be {expected_gate}')
    if (type(record.get('schema_version')) is not int or
            record.get('schema_version') != SCHEMA_VERSION):
        raise ValueError(f'{expected_gate} schema_version is invalid')
    _timestamp(record.get('captured_at'), 'captured_at')
    if record.get('source_revision') != session['source_revision']:
        raise ValueError('record source_revision does not match the session')
    if (type(record.get('robot_number')) is not int or
            record.get('robot_number') != session['robot_number']):
        raise ValueError('record robot_number does not match the session')
    if record.get('outcome') != 'GO':
        raise ValueError('only a GO record can advance commissioning')
    _evidence_files(record.get('evidence_files'))
    validator = _VALIDATORS.get(expected_gate)
    if validator is None:
        raise ValueError(f'{expected_gate} validator is not implemented')
    validator(record, session)


def record_gate(session, record):
    """Append exactly the next GO record without mutating either input."""

    session = validate_session(session)
    record = _copy(record)
    expected = next_gate(session)
    if expected is None:
        raise ValueError('commissioning is already complete')
    if record.get('gate') != expected:
        raise ValueError(f'next gate is {expected}')
    _validate_record(record, session, expected)
    session['records'][expected] = record
    return session
