#!/usr/bin/env python3
"""Create and advance fail-closed Pinky Pro commissioning sessions."""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from commissioning_session import (
    new_session,
    next_gate,
    record_gate,
    validate_session,
)


_SECRET_MARKERS = ('password', 'secret', 'token', 'credential')
_BODY_KEYS = {
    'G0': 'artifact',
    'G1': 'install',
    'G2': 'readback',
    'G3': 'stationary',
    'G4': 'motor',
    'G5': 'hardware',
}
_CHECKLISTS = {
    'G0': 'verify the signed native ARM64 release manifest and image digests',
    'G1': 'install to /opt/rosy in core mode and capture the derived identity',
    'G2': 'run device-readback.sh and capture its JSON without credentials',
    'G3': 'keep E-stop asserted and capture 2 seconds of stationary CORE state',
    'G4': 'lift the wheels, keep the hardware cut-off reachable, then run motor/deadman trials',
    'G5': 'lower the robot in a controlled area and capture LiDAR, map, and Nav2 evidence',
}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'cannot read JSON from {path}: {exc}') from exc


def _reject_secret_fields(value, location='record'):
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                raise ValueError(f'secret-like field is forbidden at {location}.{key}')
            _reject_secret_fields(nested, f'{location}.{key}')
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_fields(nested, f'{location}[{index}]')


def _bind_evidence(record, paths):
    gate = record.get('gate')
    body_key = _BODY_KEYS.get(gate)
    if body_key is None or body_key not in record:
        raise ValueError('record has no recognized gate body')
    expected = record[body_key]
    documents, digests = _load_evidence(paths)
    if not _evidence_supports(gate, expected, documents, digests):
        raise ValueError(f'{gate} structured evidence does not support its claims')
    return digests


def _load_evidence(paths):
    digests = []
    documents = []
    try:
        for path in paths:
            content = Path(path).read_bytes()
            digests.append(hashlib.sha256(content).hexdigest())
            try:
                structured = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            _reject_secret_fields(structured, f'evidence[{path}]')
            documents.append(structured)
    except OSError as exc:
        raise ValueError(f'cannot read evidence file {path}: {exc}') from exc
    if len(set(digests)) != len(digests):
        raise ValueError('evidence files must have unique content digests')
    return documents, digests


def _evidence_supports(gate, expected, documents, digests):
    if gate in ('G0', 'G1', 'G2'):
        return any(item == expected for item in _derive_bodies(gate, documents))
    if not any(item == expected for item in documents):
        return False
    if gate == 'G3':
        readback_ok = any(
            isinstance(item, dict) and
            isinstance(item.get('ros_graph'), dict) and
            item['ros_graph'].get('cmd_vel_publishers') ==
            expected.get('cmd_vel_publishers')
            for item in documents
        )
        raw_samples = []
        for item in documents:
            if not isinstance(item, dict):
                continue
            if all(key in item for key in ('seq', 'mode', 'velocity', 'safety')):
                raw_samples.append({
                    'sequence': item['seq'],
                    'mode': item['mode'],
                    'velocity': item['velocity'],
                    'safety': item['safety'],
                })
        return readback_ok and all(
            sample in raw_samples for sample in expected.get('samples', [])
        )
    manifest_gate = gate
    manifests = [
        item for item in documents
        if isinstance(item, dict) and item.get('schema_version') == 1 and
        item.get('gate') == manifest_gate
    ]
    digest_set = set(digests)
    if gate == 'G4':
        expected_trials = expected.get('deadman_trials', [])
        for manifest in manifests:
            trials = manifest.get('trials')
            if not isinstance(trials, list) or len(trials) != 8:
                continue
            referenced = []
            supported = []
            for trial in trials:
                if not isinstance(trial, dict):
                    continue
                digest = trial.get('evidence_sha256')
                if not isinstance(digest, str) or digest not in digest_set:
                    continue
                referenced.append(digest)
                supported.append({
                    key: trial.get(key)
                    for key in ('direction', 'trial', 'stop_latency_s',
                                'final_velocity', 'passed')
                })
            if (len(set(referenced)) == 8 and
                    all(trial in supported for trial in expected_trials)):
                return True
        return False
    if gate == 'G5':
        for manifest in manifests:
            roles = manifest.get('roles')
            if not isinstance(roles, dict) or set(roles) != {
                    'lidar', 'telemetry', 'map', 'navigation', 'final_state'}:
                continue
            referenced = []
            valid = True
            for role, expected_value in (
                    ('lidar', expected.get('lidar')),
                    ('telemetry', expected.get('telemetry')),
                    ('map', expected.get('map')),
                    ('navigation', expected.get('navigation')),
                    ('final_state', expected.get('final_state'))):
                item = roles.get(role)
                if not isinstance(item, dict):
                    valid = False
                    break
                digest = item.get('evidence_sha256')
                value = item.get('value')
                if digest not in digest_set or value != expected_value:
                    valid = False
                    break
                referenced.append(digest)
            if valid and len(set(referenced)) == 5:
                return True
        return False
    return False


def _derive_bodies(gate, documents):
    bodies = []
    if gate == 'G0':
        stages = [
            item for item in documents
            if isinstance(item, dict) and item.get('ok') is True and
            item.get('code') == 'STAGED' and
            isinstance(item.get('release_id'), str)
        ]
        manifests = [
            item for item in documents
            if isinstance(item, dict) and
            isinstance(item.get('release_id'), str) and
            isinstance(item.get('git_revision'), str) and
            isinstance(item.get('target'), dict) and
            isinstance(item.get('containers'), dict)
        ]
        for stage in stages:
            for manifest in manifests:
                target = manifest['target']
                derived = {
                    'manifest_verified': True,
                    'signature_status': 'verified',
                    'git_revision': manifest['git_revision'],
                    'target': {
                        'board': target.get('board'),
                        'architecture': target.get('architecture'),
                        'os_family': target.get('os_family'),
                    },
                    'containers': manifest['containers'],
                }
                if stage['release_id'] == manifest['release_id']:
                    bodies.append(derived)
        return bodies
    if gate == 'G1':
        installs = [
            item for item in documents
            if isinstance(item, dict) and item.get('ok') is True and
            item.get('code') == 'ACTIVATED_CORE_ONLY' and
            isinstance(item.get('release_id'), str)
        ]
        readbacks = [
            item for item in documents
            if isinstance(item, dict) and isinstance(item.get('identity'), dict)
            and isinstance(item.get('activation'), dict)
        ]
        for install in installs:
            for readback in readbacks:
                identity = readback['identity']
                activation = readback['activation']
                try:
                    derived_identity = {
                        'robot_number': int(identity['robot_number']),
                        'ros_domain_id': int(identity['ros_domain_id']),
                        'namespace': identity['namespace'],
                    }
                except (KeyError, TypeError, ValueError):
                    continue
                derived = {
                    'exit_code': 0,
                    'install_root': '/opt/rosy',
                    'runtime_mode': identity.get('runtime_mode'),
                    'identity': derived_identity,
                }
                if install['release_id'] == activation.get('release_id'):
                    bodies.append(derived)
        return bodies
    if gate == 'G2':
        for item in documents:
            if (isinstance(item, dict) and item.get('schema_version') == 1 and
                    all(key in item for key in (
                        'identity', 'artifact', 'runtime', 'ros_graph', 'gates'))):
                bodies.append(item)
        return bodies
    return bodies


def _atomic_write(path, value, *, refuse_existing=False, expected_bytes=None):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and destination.exists():
        raise ValueError(f'session already exists: {destination}')
    payload = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False,
    ) + '\n'
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', newline='\n',
                prefix=f'.{destination.name}.', suffix='.tmp',
                dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if refuse_existing and destination.exists():
            raise ValueError(f'session already exists: {destination}')
        if expected_bytes is not None:
            try:
                current = destination.read_bytes()
            except FileNotFoundError:
                current = None
            if current != expected_bytes:
                raise ValueError('session changed concurrently; retry from status')
        os.replace(temporary, destination)
        temporary = None
        if os.name == 'posix':
            flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0)
            directory_fd = os.open(destination.parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def _session_lock(path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock_path = destination.with_name(f'.{destination.name}.lock')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ValueError(f'cannot safely open session lock: {exc}') from exc
    with os.fdopen(descriptor, 'r+b') as handle:
        metadata = os.fstat(handle.fileno())
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError('session lock must be a regular file')
        if os.name == 'posix' and metadata.st_uid != os.geteuid():
            raise ValueError('session lock must be owned by the current user')
        if metadata.st_size == 0:
            handle.write(b'0')
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            else:
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            if os.name == 'posix':
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _status(session):
    validated = validate_session(session)
    following = next_gate(validated)
    return {
        'session_id': validated['session_id'],
        'completed_gates': list(validated['records']),
        'next_gate': following,
        'complete': following is None,
    }


def _print_json(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _init(args):
    session = new_session(
        robot_number=args.robot_number,
        source_revision=args.source_revision,
        connection=args.connection,
        operator=args.operator,
        created_at=args.created_at,
    )
    with _session_lock(args.session):
        _atomic_write(args.session, session, refuse_existing=True)
    _print_json(_status(session))


def _status_command(args):
    _print_json(_status(_read_json(args.session)))


def _record(args):
    with _session_lock(args.session):
        try:
            before = Path(args.session).read_bytes()
            session = validate_session(json.loads(before))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'cannot read JSON from {args.session}: {exc}') from exc
        record = _read_json(args.record)
        _reject_secret_fields(record)
        if not isinstance(record, dict):
            raise ValueError('record must be a JSON object')
        record = dict(record)
        record['evidence_files'] = _bind_evidence(record, args.evidence_file)
        advanced = record_gate(session, record)
        _atomic_write(args.session, advanced, expected_bytes=before)
    _print_json(_status(advanced))


def _prepare(args):
    session = validate_session(_read_json(args.session))
    gate = next_gate(session)
    if gate is None:
        raise ValueError('commissioning is already complete')
    if gate in ('G0', 'G1', 'G2'):
        if not args.evidence_file or args.body is not None:
            raise ValueError(
                f'{gate} prepare requires raw --evidence-file inputs and no --body'
            )
        documents, _ = _load_evidence(args.evidence_file)
        bodies = _derive_bodies(gate, documents)
        unique = {
            json.dumps(item, sort_keys=True, separators=(',', ':')): item
            for item in bodies
        }
        if len(unique) != 1:
            raise ValueError(
                f'{gate} evidence must derive exactly one unambiguous gate body'
            )
        body = next(iter(unique.values()))
    else:
        if args.body is None:
            raise ValueError(f'{gate} prepare requires an operator-attested --body')
        body = _read_json(args.body)
        _reject_secret_fields(body, f'{gate} body')
    captured_at = args.captured_at or datetime.now(timezone.utc).isoformat(
        timespec='seconds'
    )
    record = {
        'schema_version': 1,
        'gate': gate,
        'captured_at': captured_at,
        'source_revision': session['source_revision'],
        'robot_number': session['robot_number'],
        'outcome': 'GO',
        _BODY_KEYS[gate]: body,
    }
    candidate = dict(record, evidence_files=['0' * 64])
    record_gate(session, candidate)
    _atomic_write(args.record, record, refuse_existing=True)
    _print_json({'gate': gate, 'record': str(args.record), 'validated': True})


def _checklist(args):
    session = validate_session(_read_json(args.session))
    gate = next_gate(session)
    print(f"Connection: {session['connection']}")
    if gate is None:
        print('Commissioning session is complete. Keep the evidence directory immutable.')
        return
    print(f'Next gate: {gate} - {_CHECKLISTS[gate]}')
    print('This command only reports the checklist and does not move the robot.')


def _parser():
    parser = argparse.ArgumentParser(
        description='Fail-closed Pinky Pro commissioning evidence recorder.'
    )
    commands = parser.add_subparsers(dest='command', required=True)

    init = commands.add_parser('init', help='create a new immutable-identity session')
    init.add_argument('--session', required=True, type=Path)
    init.add_argument('--robot-number', required=True, type=int)
    init.add_argument('--source-revision', required=True)
    init.add_argument('--connection', required=True, choices=('ssh', 'console'))
    init.add_argument('--operator', required=True)
    init.add_argument('--created-at')
    init.set_defaults(handler=_init)

    status = commands.add_parser('status', help='show completed and next gates')
    status.add_argument('--session', required=True, type=Path)
    status.set_defaults(handler=_status_command)

    record = commands.add_parser('record', help='validate and atomically append one gate')
    record.add_argument('--session', required=True, type=Path)
    record.add_argument('--record', required=True, type=Path)
    record.add_argument(
        '--evidence-file', required=True, action='append', type=Path,
        help='raw evidence file to bind by SHA-256; repeat for multiple files',
    )
    record.set_defaults(handler=_record)

    prepare = commands.add_parser(
        'prepare', help='build and validate the next record from a gate body'
    )
    prepare.add_argument('--session', required=True, type=Path)
    prepare.add_argument('--body', type=Path)
    prepare.add_argument('--evidence-file', action='append', type=Path)
    prepare.add_argument('--record', required=True, type=Path)
    prepare.add_argument('--captured-at')
    prepare.set_defaults(handler=_prepare)

    checklist = commands.add_parser('checklist', help='show the next safe operator step')
    checklist.add_argument('--session', required=True, type=Path)
    checklist.set_defaults(handler=_checklist)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        args.handler(args)
    except (OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
