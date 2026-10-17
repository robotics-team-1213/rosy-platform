"""Installed original measurements never become fresh through file/cache/restart reads."""
import asyncio
import importlib
import importlib.util
import json
import os
import sqlite3

import pytest

from test_charge_store import store
from test_charge_policy import battery


def module():
    name = 'fleet.server.charge_source'
    assert importlib.util.find_spec(name) is not None, 'installed charging fact source is missing'
    return importlib.import_module(name)


def setup(tmp_path):
    api = module()
    _, tasks = store(tmp_path)
    tmp_path.chmod(0o700)
    path = tmp_path/'facts.json'
    now, mono = [100.], [10.]
    body = dict(robot_id='robot-1', battery_id='pack-1', boot_id='boot-1',
        source_id='measurements', source_epoch='source-boot-1', sequence=1,
        map_id='floor', map_revision='map-1', odom_epoch='odom-1', mode='IDLE',
        safety_latched=False, dock_state='UNDOCKED', measured_linear_m_s=0.,
        measured_angular_rad_s=0., still_since=98., captured_at=100., valid_until=102.,
        battery_energy=battery(captured_at=100., valid_until=102.).model_dump())
    profile = api.ChargeFactProfile(robot_id='robot-1', battery_id='pack-1', source_id='measurements',
        source_epoch='source-boot-1', map_id='floor', map_revision='map-1', writer_uid=os.getuid(),
        max_age_s=2., still_s=1., linear_limit_m_s=.01, angular_limit_rad_s=.02)
    def publish(value=body):
        candidate = tmp_path/'next.json'
        candidate.write_text(json.dumps(value), encoding='utf-8')
        candidate.chmod(0o600)
        candidate.replace(path)
    publish()
    def reader():
        return api.ChargeFactSource(path=path, tasks=tasks, profile=profile,
            clock=lambda: now[0], monotonic=lambda: mono[0])
    return reader, reader(), body, publish, path, now, mono, tasks


def read(source):
    return asyncio.run(source.snapshot('robot-1'))


def test_source_preserves_original_age_and_derives_only_a_measured_boundary(tmp_path):
    _, source, body, _, _, now, mono, _ = setup(tmp_path)
    first = read(source)
    assert first['captured_at'] == 100. and first['valid_until'] == 102.
    assert first['battery_energy'] == body['battery_energy']
    assert first['safe_work_boundary'] is True and first['odom_epoch'] == 'odom-1'
    now[0], mono[0] = 100.5, 10.5
    assert read(source) == first


@pytest.mark.parametrize('change', [dict(mode='NAVIGATION'), dict(safety_latched=True),
    dict(still_since=None), dict(still_since=99.5), dict(measured_linear_m_s=.02),
    dict(measured_angular_rad_s=.03)])
def test_unmeasured_or_moving_boundary_never_becomes_safe(tmp_path, change):
    _, source, body, publish, *_ = setup(tmp_path)
    publish(body | change)
    assert read(source)['safe_work_boundary'] is False


@pytest.mark.parametrize('change', [dict(robot_id='other'), dict(battery_id='other'),
    dict(source_id='other'), dict(source_epoch='other'), dict(map_id='other'),
    dict(map_revision='other'), dict(captured_at=100.1), dict(valid_until=99.),
    dict(still_since=100.1), dict(mode='FLYING'), dict(measured_linear_m_s=float('nan')),
    dict(charge_budget={}), dict(command='move'), dict(sequence=True)])
def test_unapproved_scope_time_commands_or_nonfinite_fields_are_unavailable(tmp_path, change):
    _, source, body, publish, *_ = setup(tmp_path)
    publish(body | change)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)


@pytest.mark.parametrize('mutation', ['value', 'expiry', 'battery_expiry', 'sequence_backwards'])
def test_same_capture_payload_changes_and_sequence_replay_are_rejected(tmp_path, mutation):
    _, source, body, publish, _, now, mono, _ = setup(tmp_path)
    read(source)
    now[0], mono[0] = 100.1, 10.1
    body = json.loads(json.dumps(body))
    if mutation == 'value':
        body['measured_linear_m_s'] = .1
    elif mutation == 'expiry':
        body['valid_until'] = 103.
    elif mutation == 'battery_expiry':
        body['sequence'], body['captured_at'] = 2, 100.1
        body['battery_energy']['valid_until'] = 103.
    else:
        body['sequence'] = 0
    publish(body)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)


def test_monotonic_expiry_cannot_be_renewed_by_repeated_reads_or_utc_lag(tmp_path):
    _, source, _, _, _, now, mono, _ = setup(tmp_path)
    read(source)
    now[0], mono[0] = 100.1, 12.1
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)


def test_exported_snapshot_cannot_outlive_original_monotonic_lease(tmp_path):
    _, source, _, _, _, now, mono, _ = setup(tmp_path)
    read(source)
    now[0], mono[0] = 100.1, 11.9
    value = read(source)
    assert value['captured_at'] == 100.
    assert value['valid_until'] <= 100.2+1e-6


def test_clock_read_gaps_never_add_lifetime_with_independent_epochs(tmp_path):
    _, source, body, publish, _, now, mono, _ = setup(tmp_path)
    now[0], mono[0] = 1_700_000_000., 900_000.
    body.update(captured_at=now[0], valid_until=now[0]+2., still_since=now[0]-2.)
    body['battery_energy'].update(captured_at=now[0], valid_until=now[0]+2.)
    publish(body)
    def delayed_utc():
        mono[0] += .05
        return now[0]
    source.clock = delayed_utc
    started = mono[0]
    value = read(source)
    assert value['valid_until']-now[0] <= 2.-(mono[0]-started)+1e-6


def test_new_motion_envelope_cannot_renew_unchanged_battery_lease(tmp_path):
    _, source, body, publish, _, now, mono, _ = setup(tmp_path)
    read(source)
    now[0], mono[0] = 100.1, 11.9
    body.update(sequence=2, captured_at=100.1, valid_until=102.1)
    publish(body)
    assert read(source)['valid_until'] <= 100.2+1e-6
    now[0], mono[0] = 100.2, 12.1
    body.update(sequence=3, captured_at=100.2, valid_until=102.2)
    publish(body)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)
    body['battery_energy'].update(captured_at=100.2, valid_until=102.2)
    publish(body)
    assert read(source)['captured_at'] == 100.2


@pytest.mark.parametrize('which', ['utc', 'monotonic'])
def test_clock_reversal_latches_old_source_unavailable(tmp_path, which):
    _, source, _, _, _, now, mono, _ = setup(tmp_path)
    read(source)
    (now if which == 'utc' else mono)[0] -= .1
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)
    now[0], mono[0] = 100.2, 10.2
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)


def test_restart_requires_new_motion_and_battery_capture_before_use(tmp_path):
    factory, source, body, publish, _, now, mono, _ = setup(tmp_path)
    read(source)
    fresh = factory()
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(fresh)
    now[0], mono[0] = 100.1, 10.1
    body.update(sequence=2, captured_at=100.1, valid_until=102.1)
    publish(body)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(fresh)
    body['battery_energy'].update(captured_at=100.1, valid_until=102.1)
    publish(body)
    assert read(fresh)['captured_at'] == 100.1


def test_observed_expired_or_broken_file_needs_new_publication(tmp_path):
    _, source, body, publish, path, now, mono, _ = setup(tmp_path)
    read(source)
    path.write_text('{', encoding='utf-8')
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)
    publish(body)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)
    now[0], mono[0] = 100.1, 10.1
    body.update(sequence=2, captured_at=100.1, valid_until=102.1)
    body['battery_energy'].update(captured_at=100.1, valid_until=102.1)
    publish(body)
    assert read(source)['captured_at'] == 100.1


def test_reconfiguring_age_or_file_path_cannot_reset_source_watermark(tmp_path):
    _, source, _, _, path, now, mono, tasks = setup(tmp_path)
    read(source)
    moved = tmp_path/'moved.json'
    path.replace(moved)
    changed = module().ChargeFactSource(path=moved, tasks=tasks,
        profile=source.profile.model_copy(update={'max_age_s': 3.}),
        clock=lambda: now[0], monotonic=lambda: mono[0])
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(changed)


def test_observed_utc_expiry_requires_new_original_measurements(tmp_path):
    _, source, body, publish, _, now, mono, _ = setup(tmp_path)
    read(source)
    now[0], mono[0] = 102.1, 12.1
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)
    body['valid_until'] = 200.
    body['battery_energy']['valid_until'] = 200.
    publish(body)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)
    body.update(sequence=2, captured_at=102.1, valid_until=104.1)
    body['battery_energy'].update(captured_at=102.1, valid_until=104.1)
    publish(body)
    assert read(source)['captured_at'] == 102.1


def test_inplace_write_during_read_never_returns_partial_measurements(tmp_path, monkeypatch):
    _, source, _, _, path, *_ = setup(tmp_path)
    original_read = os.read
    def concurrent_write(fd, length):
        payload = original_read(fd, length)
        path.write_bytes(payload+b' ')
        return payload
    monkeypatch.setattr(os, 'read', concurrent_write)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)


@pytest.mark.parametrize('fault', ['duplicate', 'oversize', 'symlink', 'file_mode', 'directory_mode', 'writer_uid'])
def test_file_integrity_and_approved_writer_directory_are_required(tmp_path, fault):
    _, source, body, _, path, *_ = setup(tmp_path)
    if fault == 'duplicate':
        path.write_text(json.dumps(body)[:-1]+',"sequence":1}', encoding='utf-8')
    elif fault == 'oversize':
        path.write_text(' '*70000, encoding='utf-8')
    elif fault == 'symlink':
        original = tmp_path/'original.json'
        path.rename(original)
        path.symlink_to(original)
    elif fault == 'file_mode':
        path.chmod(0o666)
    elif fault == 'directory_mode':
        tmp_path.chmod(0o777)
    else:
        source.profile = source.profile.model_copy(update={'writer_uid': os.getuid()+1})
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)


def test_watermark_storage_failure_never_returns_measurements(tmp_path, monkeypatch):
    _, source, _, _, _, _, _, tasks = setup(tmp_path)
    def unavailable():
        raise sqlite3.OperationalError('SIM disk failure')
    monkeypatch.setattr(tasks, '_connect', unavailable)
    with pytest.raises(ValueError, match='CHARGE_SOURCE_UNAVAILABLE'):
        read(source)
