"""Fail-closed Pinky Pro commissioning session contracts."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'deploy' / 'robot' / 'pinky_pro' / 'commissioning_session.py'
CLI = ROOT / 'deploy' / 'robot' / 'pinky_pro' / 'commission-pinky.py'

SPEC = importlib.util.spec_from_file_location('commissioning_session', MODULE)
assert SPEC and SPEC.loader
commissioning = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(commissioning)


NOW = '2026-09-21T12:00:00+00:00'
REVISION = 'a' * 40
DIGEST = 'b' * 64
MCAP_DIGEST = 'c' * 64
METADATA_DIGEST = 'd' * 64
MAP_YAML_DIGEST = 'e' * 64
MAP_IMAGE_DIGEST = 'f' * 64


def _release_manifest():
    return {
        'schema_version': 1,
        'release_id': '2026.09.21-001',
        'git_revision': REVISION,
        'created_at': NOW,
        'target': {
            'board': 'raspberry-pi-5',
            'architecture': 'arm64',
            'os_family': 'raspberry-pi-os-lite',
            'os_suite': 'trixie',
        },
        'runtime': {
            'config_schema': 1,
            'data_schema': 1,
            'minimum_bootloader': None,
        },
        'containers': {
            'rosy_core': 'sha256:' + '1' * 64,
            'rosy_io': 'sha256:' + '2' * 64,
        },
        'defaults': {'runtime_mode': 'core'},
        'signing_key_id': 'rosy-release-1',
        'requires_recommissioning': True,
        'files': [{'path': 'payload.tar', 'sha256': '3' * 64}],
    }


def _session():
    return commissioning.new_session(
        robot_number=1,
        source_revision=REVISION,
        connection='ssh',
        operator='tester',
        created_at=NOW,
    )


def _g0():
    return {
        'schema_version': 1,
        'gate': 'G0',
        'captured_at': NOW,
        'source_revision': REVISION,
        'robot_number': 1,
        'outcome': 'GO',
        'evidence_files': [DIGEST],
        'artifact': {
            'manifest_verified': True,
            'signature_status': 'verified',
            'git_revision': REVISION,
            'target': {
                'board': 'raspberry-pi-5',
                'architecture': 'arm64',
                'os_family': 'raspberry-pi-os-lite',
            },
            'containers': {
                'rosy_core': 'sha256:' + '1' * 64,
                'rosy_io': 'sha256:' + '2' * 64,
            },
        },
    }


def _common(gate):
    return {
        'schema_version': 1,
        'gate': gate,
        'captured_at': NOW,
        'source_revision': REVISION,
        'robot_number': 1,
        'outcome': 'GO',
        'evidence_files': [DIGEST],
    }


def _g1():
    return {
        **_common('G1'),
        'install': {
            'exit_code': 0,
            'install_root': '/opt/rosy',
            'runtime_mode': 'core',
            'identity': {
                'robot_number': 1,
                'ros_domain_id': 41,
                'namespace': 'rosy_01',
            },
        },
    }


def _readback():
    return {
        'schema_version': 1,
        'identity': {
            'robot_number': '1',
            'ros_domain_id': '41',
            'namespace': 'rosy_01',
            'runtime_mode': 'core',
        },
        'artifact': {
            'status': 'available',
            'git_revision': REVISION,
            'containers': {
                'rosy_core': 'sha256:' + '1' * 64,
                'rosy_io': 'sha256:' + '2' * 64,
            },
            'signature': {'status': 'verified'},
        },
        'runtime': {
            'systemd': 'active',
            'core': {
                'status': 'running',
                'health': 'healthy',
                'image_match': 'verified',
            },
        },
        'ros_graph': {
            'status': 'available',
            'cmd_vel_publishers': 1,
        },
        'gates': {'device_runtime': 'GO', 'field': 'HOLD'},
    }


def _g2():
    return {**_common('G2'), 'readback': _readback()}


def _zero_sample(sequence):
    return {
        'sequence': sequence,
        'mode': 'IDLE',
        'velocity': {'linear': 0.0, 'angular': 0.0},
        'safety': {'estop': True},
    }


def _g3():
    return {
        **_common('G3'),
        'stationary': {
            'runtime_mode': 'core',
            'cmd_vel_publishers': 1,
            'duration_s': 2.0,
            'samples': [_zero_sample(index) for index in range(10)],
        },
    }


def _deadman_trial(direction, index):
    return {
        'direction': direction,
        'trial': index,
        'stop_latency_s': 0.54,
        'final_velocity': {'linear': 0.0, 'angular': 0.0},
        'passed': True,
    }


def _g4():
    return {
        **_common('G4'),
        'motor': {
            'operator': 'tester',
            'wheels_lifted': True,
            'hardware_cut_reachable': True,
            'torque_free_preflight_passed': True,
            'configured_ids': [1, 2],
            'responded_ids': [1, 2],
            'deadman_trials': [
                _deadman_trial(direction, index)
                for direction in ('forward', 'reverse', 'cw', 'ccw')
                for index in (1, 2)
            ],
        },
    }


def _g5():
    record = {
        **_common('G5'),
        'hardware': {
            'operator': 'tester',
            'runtime_mode': 'hardware',
            'cmd_vel_publishers': 1,
            'lidar': {'fresh': True, 'scan_hz': 10.2},
            'telemetry': {
                'format': 'mcap',
                'duration_s': 120.0,
                'topics': [
                    '/rosy_01/scan', '/rosy_01/odom', '/rosy_01/cmd_vel',
                    '/rosy_01/map', '/tf', '/tf_static',
                ],
                'mcap_sha256': MCAP_DIGEST,
                'metadata_sha256': METADATA_DIGEST,
            },
            'map': {
                'fresh': True,
                'map_id': 'occupancy:abc123',
                'yaml_sha256': MAP_YAML_DIGEST,
                'image_sha256': MAP_IMAGE_DIGEST,
            },
            'navigation': {
                'goal_id': 'device-smoke-001',
                'status': 'SUCCEEDED',
                'collision_observed': False,
            },
            'final_state': {
                'velocity': {'linear': 0.0, 'angular': 0.0},
                'estop': True,
            },
        },
    }
    record['evidence_files'].extend([
        MCAP_DIGEST, METADATA_DIGEST, MAP_YAML_DIGEST, MAP_IMAGE_DIGEST,
    ])
    return record


def _through(gate):
    session = _session()
    for record in (_g0(), _g1(), _g2(), _g3(), _g4(), _g5()):
        session = commissioning.record_gate(session, record)
        if record['gate'] == gate:
            return session
    raise AssertionError(gate)


def test_new_session_fixes_identity_transport_and_first_gate():
    session = _session()

    assert session == {
        'schema_version': 1,
        'session_id': 'pinky-01-20260921T120000Z',
        'created_at': NOW,
        'robot_number': 1,
        'source_revision': REVISION,
        'connection': 'ssh',
        'operator': 'tester',
        'records': {},
    }
    assert commissioning.next_gate(session) == 'G0'


@pytest.mark.parametrize('connection', ['ssh', 'console'])
def test_supported_connection_paths_round_trip(connection):
    session = commissioning.new_session(
        robot_number=61,
        source_revision=REVISION,
        connection=connection,
        operator='field-operator',
        created_at=NOW,
    )

    assert commissioning.validate_session(session) == session


@pytest.mark.parametrize('robot_number', [0, 62, True, 1.5, '1'])
def test_invalid_robot_identity_is_refused(robot_number):
    with pytest.raises(ValueError, match='robot_number'):
        commissioning.new_session(
            robot_number=robot_number,
            source_revision=REVISION,
            connection='ssh',
            operator='tester',
            created_at=NOW,
        )


def test_first_record_advances_once_and_cannot_be_overwritten():
    session = _session()

    recorded = commissioning.record_gate(session, _g0())

    assert commissioning.next_gate(recorded) == 'G1'
    assert session['records'] == {}, 'record_gate must not mutate its input'
    with pytest.raises(ValueError, match='next gate is G1'):
        commissioning.record_gate(recorded, _g0())


def test_gate_skip_is_refused_before_evidence_body_is_considered():
    skipped = dict(_g0(), gate='G2')

    with pytest.raises(ValueError, match='next gate is G0'):
        commissioning.record_gate(_session(), skipped)


def test_session_revision_and_robot_cannot_drift_inside_a_record():
    with pytest.raises(ValueError, match='source_revision'):
        commissioning.record_gate(
            _session(), dict(_g0(), source_revision='c' * 40)
        )
    with pytest.raises(ValueError, match='robot_number'):
        commissioning.record_gate(_session(), dict(_g0(), robot_number=2))


def test_complete_valid_session_reaches_no_next_gate():
    session = _through('G5')

    assert commissioning.next_gate(session) is None
    assert list(session['records']) == list(commissioning.GATES)


def test_g1_install_identity_must_be_derived_and_core_only():
    session = _through('G0')
    bad_domain = _g1()
    bad_domain['install']['identity']['ros_domain_id'] = 42
    with pytest.raises(ValueError, match='derived identity'):
        commissioning.record_gate(session, bad_domain)

    bad_mode = _g1()
    bad_mode['install']['runtime_mode'] = 'hardware'
    with pytest.raises(ValueError, match='core'):
        commissioning.record_gate(session, bad_mode)

    bool_exit = _g1()
    bool_exit['install']['exit_code'] = False
    with pytest.raises(ValueError, match='exit_code'):
        commissioning.record_gate(session, bool_exit)

    bool_identity = _g1()
    bool_identity['install']['identity']['robot_number'] = True
    with pytest.raises(ValueError, match='derived identity'):
        commissioning.record_gate(session, bool_identity)


def test_g2_readback_must_match_signed_artifact_and_device_identity():
    session = _through('G1')
    bad = _g2()
    bad['readback']['artifact']['containers']['rosy_core'] = (
        'sha256:' + '9' * 64
    )

    with pytest.raises(ValueError, match='G0 artifact'):
        commissioning.record_gate(session, bad)

    bad_gate = _g2()
    bad_gate['readback']['gates']['device_runtime'] = 'HOLD'
    with pytest.raises(ValueError, match='device_runtime'):
        commissioning.record_gate(session, bad_gate)

    boolean_publisher = _g2()
    boolean_publisher['readback']['ros_graph']['cmd_vel_publishers'] = True
    with pytest.raises(ValueError, match='publisher'):
        commissioning.record_gate(session, boolean_publisher)


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('estop', False, 'E-stop'),
        ('linear', 0.01, 'zero velocity'),
        ('angular', -0.01, 'zero velocity'),
    ],
)
def test_g3_requires_repeated_estop_and_zero_velocity(field, value, message):
    session = _through('G2')
    record = _g3()
    sample = record['stationary']['samples'][4]
    if field == 'estop':
        sample['safety']['estop'] = value
    else:
        sample['velocity'][field] = value

    with pytest.raises(ValueError, match=message):
        commissioning.record_gate(session, record)


def test_publisher_counts_reject_booleans():
    g3 = _g3()
    g3['stationary']['cmd_vel_publishers'] = True
    with pytest.raises(ValueError, match='publisher'):
        commissioning.record_gate(_through('G2'), g3)

    g5 = _g5()
    g5['hardware']['cmd_vel_publishers'] = True
    with pytest.raises(ValueError, match='publisher'):
        commissioning.record_gate(_through('G4'), g5)


def test_g4_requires_physical_acknowledgements_matching_ids_and_deadman():
    session = _through('G3')
    no_lift = _g4()
    no_lift['motor']['wheels_lifted'] = False
    with pytest.raises(ValueError, match='wheels lifted'):
        commissioning.record_gate(session, no_lift)

    missing_id = _g4()
    missing_id['motor']['responded_ids'] = [1]
    with pytest.raises(ValueError, match='configured motor IDs'):
        commissioning.record_gate(session, missing_id)

    slow_stop = _g4()
    slow_stop['motor']['deadman_trials'][0]['stop_latency_s'] = 0.8
    with pytest.raises(ValueError, match='deadman'):
        commissioning.record_gate(session, slow_stop)


def test_g5_requires_fresh_lidar_map_success_and_final_stop():
    session = _through('G4')
    stale = _g5()
    stale['hardware']['lidar']['fresh'] = False
    with pytest.raises(ValueError, match='LiDAR'):
        commissioning.record_gate(session, stale)

    moving = _g5()
    moving['hardware']['final_state']['velocity']['linear'] = 0.01
    with pytest.raises(ValueError, match='final zero'):
        commissioning.record_gate(session, moving)

    collision = _g5()
    collision['hardware']['navigation']['collision_observed'] = True
    with pytest.raises(ValueError, match='collision'):
        commissioning.record_gate(session, collision)


def test_g5_requires_bounded_raw_telemetry_and_real_map_artifacts():
    session = _through('G4')
    missing_topic = _g5()
    missing_topic['hardware']['telemetry']['topics'].remove('/rosy_01/map')
    with pytest.raises(ValueError, match='telemetry topics'):
        commissioning.record_gate(session, missing_topic)

    unbound_map = _g5()
    unbound_map['evidence_files'].remove(MAP_IMAGE_DIGEST)
    with pytest.raises(ValueError, match='map artifact'):
        commissioning.record_gate(session, unbound_map)

    too_short = _g5()
    too_short['hardware']['telemetry']['duration_s'] = 2.0
    with pytest.raises(ValueError, match='duration'):
        commissioning.record_gate(session, too_short)


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_init_status_and_checklist_support_ssh_and_console(tmp_path):
    for connection in ('ssh', 'console'):
        session_path = tmp_path / f'{connection}.json'
        created = _run_cli(
            'init', '--session', session_path, '--robot-number', 1,
            '--source-revision', REVISION, '--connection', connection,
            '--operator', 'tester', '--created-at', NOW,
        )
        assert created.returncode == 0, created.stderr
        session = json.loads(session_path.read_text(encoding='utf-8'))
        assert session['connection'] == connection

        status = _run_cli('status', '--session', session_path)
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout) == {
            'session_id': 'pinky-01-20260921T120000Z',
            'completed_gates': [],
            'next_gate': 'G0',
            'complete': False,
        }

        checklist = _run_cli('checklist', '--session', session_path)
        assert checklist.returncode == 0, checklist.stderr
        assert connection in checklist.stdout
        assert 'G0' in checklist.stdout
        assert 'does not move the robot' in checklist.stdout


def test_cli_record_hashes_raw_evidence_and_atomically_advances(tmp_path):
    session_path = tmp_path / 'session.json'
    assert _run_cli(
        'init', '--session', session_path, '--robot-number', 1,
        '--source-revision', REVISION, '--connection', 'ssh',
        '--operator', 'tester', '--created-at', NOW,
    ).returncode == 0
    manifest_path = tmp_path / 'manifest.json'
    stage_path = tmp_path / 'stage.json'
    record = _g0()
    record.pop('evidence_files')
    manifest_path.write_text(json.dumps(_release_manifest()), encoding='utf-8')
    stage_path.write_text(json.dumps({
        'ok': True,
        'code': 'STAGED',
        'release_id': '2026.09.21-001',
    }), encoding='utf-8')
    record_path = tmp_path / 'g0.json'
    record_path.write_text(json.dumps(record), encoding='utf-8')

    result = _run_cli(
        'record', '--session', session_path, '--record', record_path,
        '--evidence-file', manifest_path, '--evidence-file', stage_path,
    )

    assert result.returncode == 0, result.stderr
    saved = json.loads(session_path.read_text(encoding='utf-8'))
    expected = [
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (manifest_path, stage_path)
    ]
    assert saved['records']['G0']['evidence_files'] == expected
    assert json.loads(result.stdout)['next_gate'] == 'G1'
    assert not list(tmp_path.glob('.session.json.*.tmp'))


def test_cli_refuses_evidence_that_does_not_match_gate_claims(tmp_path):
    session_path = tmp_path / 'session.json'
    assert _run_cli(
        'init', '--session', session_path, '--robot-number', 1,
        '--source-revision', REVISION, '--connection', 'ssh',
        '--operator', 'tester', '--created-at', NOW,
    ).returncode == 0
    record = _g0()
    record.pop('evidence_files')
    record_path = tmp_path / 'g0.json'
    record_path.write_text(json.dumps(record), encoding='utf-8')
    unrelated = tmp_path / 'unrelated.json'
    unrelated.write_text(
        json.dumps({'status': 'GO', 'detail': 'self-authored'}),
        encoding='utf-8',
    )
    before = session_path.read_bytes()

    result = _run_cli(
        'record', '--session', session_path, '--record', record_path,
        '--evidence-file', unrelated,
    )

    assert result.returncode != 0
    assert 'structured evidence' in result.stderr
    assert session_path.read_bytes() == before


def test_cli_prepare_builds_valid_next_record_from_structured_body(tmp_path):
    session_path = tmp_path / 'session.json'
    assert _run_cli(
        'init', '--session', session_path, '--robot-number', 1,
        '--source-revision', REVISION, '--connection', 'ssh',
        '--operator', 'tester', '--created-at', NOW,
    ).returncode == 0
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(json.dumps(_release_manifest()), encoding='utf-8')
    stage_path = tmp_path / 'stage.json'
    stage_path.write_text(json.dumps({
        'ok': True, 'code': 'STAGED', 'release_id': '2026.09.21-001',
    }), encoding='utf-8')
    record_path = tmp_path / 'G0-record.json'

    prepared = _run_cli(
        'prepare', '--session', session_path,
        '--evidence-file', manifest_path, '--evidence-file', stage_path,
        '--record', record_path, '--captured-at', NOW,
    )

    assert prepared.returncode == 0, prepared.stderr
    record = json.loads(record_path.read_text(encoding='utf-8'))
    assert record == {key: value for key, value in _g0().items()
                      if key != 'evidence_files'}
    assert session_path.read_bytes() == session_path.read_bytes()


def test_cli_g1_derives_claims_from_install_result_and_device_readback(tmp_path):
    session_path = tmp_path / 'session.json'
    session_path.write_text(json.dumps(_through('G0')), encoding='utf-8')
    record = _g1()
    record.pop('evidence_files')
    record_path = tmp_path / 'G1-record.json'
    record_path.write_text(json.dumps(record), encoding='utf-8')
    install_path = tmp_path / 'G1-install.json'
    install_path.write_text(json.dumps({
        'ok': True,
        'code': 'ACTIVATED_CORE_ONLY',
        'release_id': '2026.09.21-001',
        'detail': 'activated core only',
    }), encoding='utf-8')
    readback = _readback()
    readback['activation'] = {'release_id': '2026.09.21-001'}
    readback_path = tmp_path / 'G2-device-readback.json'
    readback_path.write_text(json.dumps(readback), encoding='utf-8')

    result = _run_cli(
        'record', '--session', session_path, '--record', record_path,
        '--evidence-file', install_path,
        '--evidence-file', readback_path,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['next_gate'] == 'G2'


@pytest.mark.parametrize(
    ('prior_gate', 'record_factory', 'body_key'),
    [('G2', _g3, 'stationary'), ('G3', _g4, 'motor'),
     ('G4', _g5, 'hardware')],
)
def test_cli_physical_gate_body_alone_cannot_replace_raw_evidence(
        tmp_path, prior_gate, record_factory, body_key):
    session_path = tmp_path / 'session.json'
    session_path.write_text(json.dumps(_through(prior_gate)), encoding='utf-8')
    record = record_factory()
    record.pop('evidence_files')
    record_path = tmp_path / 'record.json'
    record_path.write_text(json.dumps(record), encoding='utf-8')
    body_path = tmp_path / 'body.json'
    body_path.write_text(json.dumps(record[body_key]), encoding='utf-8')

    result = _run_cli(
        'record', '--session', session_path, '--record', record_path,
        '--evidence-file', body_path,
    )

    assert result.returncode != 0
    assert 'does not support' in result.stderr
    assert json.loads(session_path.read_text(encoding='utf-8')) == _through(prior_gate)


def test_cli_g3_requires_and_accepts_all_raw_states_plus_readback(tmp_path):
    session_path = tmp_path / 'session.json'
    session_path.write_text(json.dumps(_through('G2')), encoding='utf-8')
    record = _g3()
    record.pop('evidence_files')
    record_path = tmp_path / 'record.json'
    record_path.write_text(json.dumps(record), encoding='utf-8')
    body_path = tmp_path / 'body.json'
    body_path.write_text(json.dumps(record['stationary']), encoding='utf-8')
    readback_path = tmp_path / 'readback.json'
    readback_path.write_text(json.dumps(_readback()), encoding='utf-8')
    evidence_args = ['--evidence-file', body_path,
                     '--evidence-file', readback_path]
    for sample in record['stationary']['samples']:
        state = dict(sample)
        state['seq'] = state.pop('sequence')
        path = tmp_path / f"state-{state['seq']}.json"
        path.write_text(json.dumps(state), encoding='utf-8')
        evidence_args.extend(['--evidence-file', path])

    result = _run_cli(
        'record', '--session', session_path, '--record', record_path,
        *evidence_args,
    )

    assert result.returncode == 0, result.stderr


def test_cli_g4_and_g5_require_role_bound_distinct_raw_digests(tmp_path):
    for prior_gate, record_factory, body_key in (
            ('G3', _g4, 'motor'), ('G4', _g5, 'hardware')):
        session_path = tmp_path / f'{prior_gate}.json'
        session_path.write_text(json.dumps(_through(prior_gate)), encoding='utf-8')
        record = record_factory()
        record.pop('evidence_files')
        record_path = tmp_path / f'{prior_gate}-record.json'
        record_path.write_text(json.dumps(record), encoding='utf-8')
        body_path = tmp_path / f'{prior_gate}-body.json'
        body_path.write_text(json.dumps(record[body_key]), encoding='utf-8')
        raw_paths = []
        count = 8 if body_key == 'motor' else 9
        for index in range(count):
            path = tmp_path / f'{prior_gate}-raw-{index}.txt'
            path.write_text(f'raw physical evidence {index}', encoding='utf-8')
            raw_paths.append(path)
        digests = [hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in raw_paths]
        if body_key == 'motor':
            manifest = {
                'schema_version': 1,
                'gate': 'G4',
                'trials': [dict(trial, evidence_sha256=digest)
                           for trial, digest in zip(
                               record['motor']['deadman_trials'], digests)],
            }
        else:
            record['hardware']['telemetry']['mcap_sha256'] = digests[5]
            record['hardware']['telemetry']['metadata_sha256'] = digests[6]
            record['hardware']['map']['yaml_sha256'] = digests[7]
            record['hardware']['map']['image_sha256'] = digests[8]
            record_path.write_text(json.dumps(record), encoding='utf-8')
            body_path.write_text(json.dumps(record[body_key]), encoding='utf-8')
            manifest = {
                'schema_version': 1,
                'gate': 'G5',
                'roles': {
                    role: {
                        'value': record['hardware'][role],
                        'evidence_sha256': digest,
                    }
                    for role, digest in zip(
                        ('lidar', 'telemetry', 'map', 'navigation', 'final_state'),
                        digests,
                    )
                },
            }
        manifest_path = tmp_path / f'{prior_gate}-manifest.json'
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        evidence_args = ['--evidence-file', body_path,
                         '--evidence-file', manifest_path]
        for path in raw_paths:
            evidence_args.extend(['--evidence-file', path])

        result = _run_cli(
            'record', '--session', session_path, '--record', record_path,
            *evidence_args,
        )

        assert result.returncode == 0, result.stderr


def test_cli_failure_does_not_mutate_session_or_accept_secrets(tmp_path):
    session_path = tmp_path / 'session.json'
    assert _run_cli(
        'init', '--session', session_path, '--robot-number', 1,
        '--source-revision', REVISION, '--connection', 'console',
        '--operator', 'tester', '--created-at', NOW,
    ).returncode == 0
    before = session_path.read_bytes()
    evidence_path = tmp_path / 'evidence.txt'
    evidence_path.write_text('safe output', encoding='utf-8')
    record = _g0()
    record.pop('evidence_files')
    record['operator_password'] = 'must-never-be-recorded'
    record_path = tmp_path / 'bad.json'
    record_path.write_text(json.dumps(record), encoding='utf-8')

    result = _run_cli(
        'record', '--session', session_path, '--record', record_path,
        '--evidence-file', evidence_path,
    )

    assert result.returncode != 0
    assert 'secret-like field' in result.stderr
    assert session_path.read_bytes() == before


def test_installer_marks_commissioning_tools_executable():
    installer = (ROOT / 'deploy' / 'robot' / 'pinky_pro' / 'install-pi.sh').read_text(
        encoding='utf-8'
    )

    assert '"$INSTALL_ROOT/deploy/robot/commission-pinky.py"' in installer
    assert '"$INSTALL_ROOT/deploy/robot/commissioning_session.py"' in installer


def test_first_device_runbook_is_a_complete_fail_closed_handoff():
    runbook_path = (
        ROOT / 'docs' / 'deployment' / 'pinky-pro-first-device-runbook.md'
    )
    assert runbook_path.exists()
    runbook = runbook_path.read_text(encoding='utf-8')

    for phrase in (
        'SSH path', 'Local console path', 'G0', 'G1', 'G2', 'G3', 'G4', 'G5',
        'commission-pinky.py init', 'commission-pinky.py record',
        'runtime-mode.sh down', 'E-stop', '/var/lib/rosy/commissioning',
        'camera', 'ArUco', 'homography', 'robot diameter', 'stopping distance',
        'Do not copy Gazebo', 'HOLD', 'map_260905_update_v2',
        '/var/cache/rosy/releases/${RELEASE_ID}/manifest.json',
        'ROSY_RUNTIME_MODE=motor', 'ROSY_RUNTIME_MODE=hardware',
            '/api/v1/robot/state', '/api/v1/slam/start',
            '/api/v1/safety/release', '/api/v1/safety/stop',
        '/api/v1/navigation/goal',
        'G0-connection-evidence.json', '-BatchMode', '-EvidencePath',
        'connectivity evidence only',
        'ROSY_NAVIGATION_BACKEND=slam', 'ros2 bag record', '--storage mcap',
        'G5-map.yaml', 'G5-map.pgm', 'G5-telemetry',
    ):
        assert phrase in runbook, phrase

    assert (runbook.index('### G3') < runbook.index('### G4') <
            runbook.index('### G5'))
    assert 'sudo /opt/rosy/deploy/robot/commission-pinky.py' not in runbook


def test_commissioning_runbook_is_linked_from_operator_indexes():
    expected = 'pinky-pro-first-device-runbook.md'
    for relative in (
        'docs/deployment/AGENTS.md',
        'docs/deployment/raspberry-pi-runtime.md',
        'deploy/robot/pinky_pro/AGENTS.md',
    ):
        assert expected in (ROOT / relative).read_text(encoding='utf-8'), relative


def test_physical_body_templates_are_invalid_until_measured():
    templates = (
        ROOT / 'docs' / 'deployment' /
        'pinky-pro-commissioning-body-templates.md'
    ).read_text(encoding='utf-8')

    assert '"mode": "UNMEASURED"' in templates
    assert '"stop_latency_s": null' in templates
    assert '"scan_hz": 0.0' in templates
    assert '"format": "mcap"' in templates
    assert '"mcap_sha256": "REPLACE_WITH_64_HEX"' in templates
    assert '"yaml_sha256": "REPLACE_WITH_64_HEX"' in templates
    assert 'intentionally invalid' in templates
