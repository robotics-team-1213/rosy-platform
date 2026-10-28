"""Real SQLite transactions keep preview approval separate from tracking."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import json
from pathlib import Path
import sqlite3

import pytest

from core_common.protocol.measured_calibration import bundle_digest
from fleet.server.tracking_calibration import TrackingCalibrationStore

VECTOR = Path(__file__).resolve().parents[3] / 'test/fixtures/protocol/measured-calibration.v1.json'
NOW = 1790000000.
LIMITS = {'p95_m': .01, 'max_m': .02}


def measured():
    value = json.loads(VECTOR.read_text())
    value['evidence_kind'] = 'measured'  # Simulated operator claim; never field evidence.
    value['digest'] = bundle_digest(value)
    return value


def store(path):
    return importlib.import_module('fleet.server.measured_calibration_store').MeasuredCalibrationStore(path)


def approve(s, **kw):
    return s.approve(measured(), expected_revision=kw.get('expected_revision'),
                     approved_by='operator-1', approved_at=NOW, limits=LIMITS)


def test_approval_survives_restart_and_does_not_change_tracking(tmp_path):
    path = tmp_path/'calibrations.sqlite3'
    parent = TrackingCalibrationStore(path)
    row = approve(parent.preview)
    assert parent.get('ceiling_north') is None
    assert row['persistent'] is True and row['use'] == 'preview-only'
    other = store(path)
    assert other.get('ceiling_north') == row
    assert other.revoke('ceiling_north', expected_revision=row['calibration_revision'],
                        principal_id='operator-2', at=NOW+1)['removed']
    assert parent.preview.get('ceiling_north') is None
    events = other.audit_events()
    assert [e['event'] for e in events] == ['preview.approved', 'preview.revoked']
    assert events[0]['record']['bundle']['digest'] == measured()['digest']


def test_two_connections_race_only_one_can_approve_and_stale_revoke_fails(tmp_path):
    path = tmp_path/'cas.sqlite3'
    a, b = store(path), store(path)
    def attempt(s):
        try:
            return approve(s)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, (a, b)))
    rows = [r for r in results if r]
    assert len(rows) == 1
    first = rows[0]
    second = approve(b, expected_revision=first['calibration_revision'])
    with pytest.raises(ValueError, match='changed'):
        a.revoke('ceiling_north', expected_revision=first['calibration_revision'],
                  principal_id='operator-1', at=NOW+2)
    assert a.get('ceiling_north') == second


def test_database_failure_does_not_create_memory_success(tmp_path, monkeypatch):
    s = store(tmp_path/'broken.sqlite3')
    original = s._connect
    def fail():
        raise sqlite3.OperationalError('simulated disk failure')
    monkeypatch.setattr(s, '_connect', fail)
    with pytest.raises(sqlite3.OperationalError):
        approve(s)
    monkeypatch.setattr(s, '_connect', original)
    assert s.get('ceiling_north') is None


def test_synthetic_or_excess_error_or_missing_limits_cannot_be_approved(tmp_path):
    s = store(tmp_path/'strict.sqlite3')
    for bundle, limits in [(json.loads(VECTOR.read_text()), LIMITS),
                            (measured(), {'p95_m': .0001, 'max_m': .001}),
                            (measured(), {}), (measured(), {'p95_m': True, 'max_m': .02})]:
        with pytest.raises(ValueError):
            s.approve(bundle, expected_revision=None, approved_by='operator-1',
                       approved_at=NOW, limits=limits)
    assert s.get('ceiling_north') is None


def test_corrupt_persisted_candidate_is_not_returned_as_approved(tmp_path):
    s = store(tmp_path/'corrupt.sqlite3')
    approve(s)
    with sqlite3.connect(s.path) as db:
        db.execute("UPDATE preview_calibrations SET payload_json='{}'")
    assert store(s.path).get('ceiling_north') is None


def test_memory_only_reports_its_lifetime():
    s = store(None)
    row = approve(s)
    assert row['persistent'] is False
    assert store(None).get('ceiling_north') is None


def test_concurrent_replace_and_revoke_have_one_cas_winner(tmp_path):
    from threading import Barrier
    a = store(tmp_path/'replace-revoke.db')
    b = store(a.path)
    initial = approve(a)
    barrier = Barrier(2)
    def compete(replace):
        barrier.wait(timeout=3.)
        try:
            if replace:
                return approve(a, expected_revision=initial['calibration_revision'])
            return b.revoke('ceiling_north', expected_revision=initial['calibration_revision'],
                            principal_id='operator-2', at=NOW+1)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (True, False)))
    winner, = [value for value in results if value is not None]
    assert a.get('ceiling_north') == (None if winner.get('removed') else winner)
    assert len(a.audit_events()) == 2
