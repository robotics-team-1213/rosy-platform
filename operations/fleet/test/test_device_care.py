"""Durable source-bound care records; advice never grants motion authority."""
import copy
from pathlib import Path
import runpy
import sqlite3
import threading
import sys
from unittest.mock import patch

import pytest

from fleet.server.device_profiles import DeviceProfileStore
from fleet.server.device_care import DeviceCareStore


def monitor_report(*, stamp=100., attention=False):
    from rosy.contracts.motion.characteristics import characteristics_digest
    root = Path(__file__).resolve().parents[3]
    # The cross-owner fixture loads the adapter explicitly; Fleet does not depend on its runtime.
    with patch.object(sys, 'path', [str(root / 'middleware/devices/omx/adapter'), *sys.path]):
        from omx_adapter.load_monitor import LoadMonitor
    fixture = runpy.run_path(str(root / 'middleware/devices/omx/adapter/test/load_motion_fixtures.py'))
    document = fixture['characteristics']()
    document['binding']['device_id'] = 'arm-one'
    monitor = LoadMonitor(
        document, fixture['request'](document), accepted_digest=characteristics_digest(document),
        candidate_id='direct', command_id='command-fixture', started_at=stamp,
        session_id='00000000-0000-4000-8000-000000000001')
    report = (monitor.unavailable('feedback_gap', now=stamp + .01) if attention else
              monitor.observe(fixture['health'](document), captured_at=stamp + .01, now=stamp + .01,
                              context=document['binding']))
    return document, report


def _store(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    profiles = DeviceProfileStore(path)
    for device in ('arm-one', 'arm-two'):
        profiles.put_profile(device, {'display_name': device, 'device_kind': 'manipulator'}, updated_by='alice')
    return path, DeviceCareStore(path)


def care(source='source-one'):
    return {'source_kind': 'arm', 'source_id': source, 'caution': '2·3번 관절 하중 주의', 'characteristics': None}


def test_persistence_and_source_uniqueness(tmp_path):
    path, store = _store(tmp_path)
    store.put('arm-one', care(), actor='alice')
    store.add_event('arm-one', {'kind': 'fault', 'text': '처짐 관찰'}, actor='alice')
    restored = DeviceCareStore(path)
    assert restored.by_source('arm', 'source-one')['device_id'] == 'arm-one'
    assert restored.get('arm-one')['events'][0]['text'] == '처짐 관찰'
    with pytest.raises(ValueError):
        store.put('arm-two', care(), actor='bob')
    assert store.get('arm-one')['caution'] == care()['caution']
    assert store.get('arm-two')['source_id'] is None


@pytest.mark.parametrize('change', [
    {'caution': []}, {'source_kind': 'camera'},
    {'source_id': '../arm'}, {'characteristics': {'schema': 'wrong'}}])
def test_invalid_replacement_preserves_previous(tmp_path, change):
    _, store = _store(tmp_path)
    store.put('arm-one', care(), actor='alice')
    before = store.get('arm-one')
    invalid = copy.deepcopy(care()) | change
    with pytest.raises(ValueError):
        store.put('arm-one', invalid, actor='alice')
    assert store.get('arm-one') == before


def test_missing_profile_and_unbound_reports_rejected(tmp_path):
    _, store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.put('missing', care(), actor='alice')
    with pytest.raises(ValueError):
        store.ingest('arm-one', 'wrong-source', {}, now=100)
    assert store.get('arm-one')['latest_analysis'] is None


def test_real_monitor_output_duplicate_age_restart_and_rebind(tmp_path):
    path, store = _store(tmp_path)
    document, report = monitor_report()
    store.put('arm-one', care() | {'characteristics': document}, actor='alice')
    store.ingest('arm-one', 'source-one', report, now=100.02)
    assert store.get('arm-one', now=100.03)['latest_analysis']['fresh']
    assert store.ingest('arm-one', 'source-one', report, now=101)['duplicate']
    assert not DeviceCareStore(path).get('arm-one', now=101)['latest_analysis']['fresh']
    assert store.get('arm-one', now=101)['latest_analysis']['assessed_at'] == report['assessed_at']
    changed = copy.deepcopy(report)
    changed['command_id'] = 'same-stamp-different-content'
    with pytest.raises(ValueError):
        store.ingest('arm-one', 'source-one', changed, now=101)
    _, warning = monitor_report(stamp=102, attention=True)
    store.ingest('arm-one', 'source-one', warning, now=102.02)
    store.ingest('arm-one', 'source-one', warning, now=103)
    assert len(store.get('arm-one')['events']) == 1
    store.put('arm-one', care('other-source') | {'characteristics': document}, actor='alice')
    assert store.get('arm-one')['latest_analysis'] is None
    assert len(store.get('arm-one')['events']) == 1
    with pytest.raises(ValueError):
        store.ingest('arm-one', 'source-one', warning, now=103)


@pytest.mark.parametrize('change', [
    {'context': {}}, {'characteristics_sha256': 'b' * 64},
    {'motion_admitted': True}, {'automatic_recovery_enabled': True}, {'assessed_at': 105},
    {'status': 'observing', 'reasons': ['feedback_gap']}, {'joint_captured_at': {}},
    {'errors_rad': {'unknown_joint': 0}}, {'request_sha256': 'bad'}, {'new_joint_samples': []}])
def test_rejected_report_cannot_replace_last_observation(tmp_path, change):
    _, store = _store(tmp_path)
    document, report = monitor_report()
    store.put('arm-one', care() | {'characteristics': document}, actor='alice')
    store.ingest('arm-one', 'source-one', report, now=100.02)
    before = store.get('arm-one', now=100.02)
    invalid = copy.deepcopy(report) | change
    with pytest.raises(ValueError):
        store.ingest('arm-one', 'source-one', invalid, now=100.02)
    assert store.get('arm-one', now=100.02) == before


def test_care_replacement_holds_write_lock_before_reading_old_binding(tmp_path, monkeypatch):
    path, store = _store(tmp_path)
    store.put('arm-one', care(), actor='alice')
    reading, release = threading.Event(), threading.Event()
    connect = store._connect
    errors = []

    def instrumented():
        db = connect()

        def trace(sql):
            if sql.startswith('SELECT * FROM fleet_device_care WHERE') and not reading.is_set():
                reading.set()
                release.wait(5)
        db.set_trace_callback(trace)
        return db

    monkeypatch.setattr(store, '_connect', instrumented)

    def save():
        try:
            store.put('arm-one', care() | {'caution': '변경\n주의사항'}, actor='alice')
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=save)
    worker.start()
    try:
        assert reading.wait(5)
        with sqlite3.connect(path, timeout=.05) as competing:
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                competing.execute('UPDATE fleet_device_care SET source_id=? WHERE device_id=?', ('other', 'arm-one'))
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not errors
    assert store.get('arm-one')['caution'] == '변경\n주의사항'
