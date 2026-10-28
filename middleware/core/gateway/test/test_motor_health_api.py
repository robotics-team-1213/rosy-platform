"""Native owner evidence reaches the authenticated read-only API without hardware."""
import importlib.util
import json
from pathlib import Path
import time
from uuid import uuid4

import pytest


def source(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[4]
    spec = importlib.util.spec_from_file_location('health_source', root / 'deploy/robot/omx/motor_health.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    spec = importlib.util.spec_from_file_location('health_fakes', root / 'test/test_omx_motor_health.py')
    fakes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fakes)
    state, session = tmp_path / 'current.json', str(uuid4())
    for key, value in {'ROSY_OMX_MONITOR_STATE': str(state), 'ROSY_OMX_MONITOR_OWNER': 'omx-cell',
                       'ROSY_OMX_MONITOR_SESSION': session, 'ROSY_MOTOR_HEALTH_FILE': str(state),
                       'ROSY_MOTOR_HEALTH_OWNER': 'omx-cell'}.items():
        monkeypatch.setenv(key, value)
    monitor = module.MotorHealth(tmp_path / 'private.jsonl')
    motion = fakes.motion()
    monitor.admit(motion)
    monitor.sample(motion, dict.fromkeys(fakes.NAMES, 2028), dict.fromkeys(fakes.NAMES, 0), 10.0)
    return monitor, motion, state, session


def test_source_snapshot_to_authenticated_route_and_lifecycle(core_client, tmp_path, monkeypatch):
    monitor, motion, path, session = source(tmp_path, monkeypatch)
    client, _ = core_client()
    assert client.get('/api/v1/motors/health').status_code == 401
    headers = {'Authorization': 'Bearer rosy-dev-viewer'}
    response = client.get('/api/v1/motors/health', headers=headers)
    assert response.status_code == 200
    row = response.json()
    assert row['evidence'] == 'fresh' and row['status'] == 'active'
    assert row['owner_id'] == 'omx-cell' and row['session_id'] == session
    assert len(row['motors']) == 5 and row['motors'][1]['id'] == 12
    assert '/dev/' not in response.text and 'usb_port' not in response.text
    monitor.fault(motion, OSError('/dev/serial/by-id/private-device failed'))
    monitor.end()
    row = client.get('/api/v1/motors/health', headers=headers).json()
    assert row['status'] == 'fault' and row['evidence'] != 'fresh'
    assert '/dev/' not in json.dumps(row) and row['stop_reasons']


@pytest.mark.parametrize('invalid', ['owner', 'session', 'future', 'malformed', 'oversize', 'symlink'])
def test_reader_rejects_wrong_binding_and_untrusted_file(tmp_path, monkeypatch, invalid):
    from core_api_web.api.motor_health import read_motor_health
    _, _, path, session = source(tmp_path, monkeypatch)
    row = json.loads(path.read_text())
    if invalid == 'owner':
        row['owner_id'] = 'another-cell'
    elif invalid == 'session':
        monkeypatch.setenv('ROSY_MOTOR_HEALTH_SESSION', str(uuid4()))
    elif invalid == 'future':
        row['observed_at'] = time.time() + 20
    elif invalid == 'malformed':
        row['session_id'] = 'not-a-uuid'
    elif invalid == 'oversize':
        path.write_text(' ' * 300_000)
    elif invalid == 'symlink':
        target = path.with_name('other.json')
        path.rename(target)
        path.symlink_to(target)
    if invalid not in ('oversize', 'symlink'):
        path.write_text(json.dumps(row))
    result = read_motor_health()
    assert result.evidence == 'unavailable' and result.status == 'unavailable'


def test_stale_and_ended_evidence_never_becomes_fresh(tmp_path, monkeypatch):
    from core_api_web.api.motor_health import read_motor_health
    monitor, _, path, _ = source(tmp_path, monkeypatch)
    row = json.loads(path.read_text())
    row['observed_at'] -= 3
    for motor in row['motors']:
        motor['observed_at'] -= 3
    path.write_text(json.dumps(row))
    assert read_motor_health().evidence == 'delayed'
    monitor.end()
    result = read_motor_health()
    assert result.status == 'ended' and result.evidence == 'disconnected'


def test_no_configured_source_is_unavailable_without_fabricated_motors(monkeypatch):
    from core_api_web.api.motor_health import read_motor_health
    monkeypatch.delenv('ROSY_MOTOR_HEALTH_FILE', raising=False)
    assert read_motor_health().motors == []
    assert read_motor_health().evidence == 'unavailable'


@pytest.mark.parametrize('change', [{'status': 'unavailable'}, {'motors': []}, {'owner_id': None},
                                   {'session_id': 'bad'}, {'sample_age_s': 3}])
def test_dto_rejects_misleading_fresh_evidence(tmp_path, monkeypatch, change):
    from core_api_web.api.motor_health import read_motor_health
    from core_common.protocol.motor_health import MotorHealthResponse
    from pydantic import ValidationError
    source(tmp_path, monkeypatch)
    valid = read_motor_health().model_dump()
    with pytest.raises(ValidationError):
        MotorHealthResponse(**{**valid, **change})


def test_partial_shared_owner_coverage_is_not_fresh(tmp_path, monkeypatch):
    from core_api_web.api.motor_health import read_motor_health
    monitor, arm, path, _ = source(tmp_path, monkeypatch)
    arm.label = 'arm_b'
    monitor.admit(arm)
    assert read_motor_health().evidence == 'unavailable'
    monitor.sample(arm, dict.fromkeys(arm.active, 2028), dict.fromkeys(arm.active, 0), 10.0)
    assert read_motor_health().evidence == 'fresh'
    assert len(read_motor_health().motors) == 10


def test_parent_finalize_requires_exact_session_and_retains_source_age(tmp_path, monkeypatch):
    monitor, motion, path, session = source(tmp_path, monkeypatch)
    finish = monitor.publish.__globals__['finish_snapshot']
    before = json.loads(path.read_text())['observed_at']
    with pytest.raises(ValueError, match='binding mismatch'):
        finish(path, 'omx-cell', str(uuid4()), safe_end=True)
    monitor.fault(motion, ValueError('overload risk'))
    finish(path, 'omx-cell', session, safe_end=False)
    fault = json.loads(path.read_text())
    assert fault['status'] == 'fault'
    assert fault['stop_reasons'] == ['overload risk', 'cleanup unconfirmed']
    finish(path, 'omx-cell', session, safe_end=True)
    row = json.loads(path.read_text())
    assert row['status'] == 'fault' and row['observed_at'] == before
