"""A retained capture window is evidence coverage, never proof of zero commands."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from fleet.server.observation_store import ObservationStore
from test_observation_store import sample


@pytest.fixture
def exporter():
    path = Path(__file__).resolve().parents[3] / 'learning/curation/pinky/fleet_observations.py'
    spec = importlib.util.spec_from_file_location('window_exporter', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def populate(path, times=(10, 11, 12), *, max_rows=100_000):
    store = ObservationStore(path, max_rows=max_rows)
    for stamp in times:
        store.append_snapshot([sample(), dict(sample(), robot_id='rosy_02', online=False,
                                             state=None, _state_mono=None)],
                              received_at=stamp, monotonic_now=stamp)
    return store


def check(exporter, path, **kwargs):
    return exporter.capture_window(path, robot_id='rosy_01', start=10.5, end=11.5,
                                   max_gap_s=1, **kwargs)


def test_complete_window_is_bounded_private_and_read_only(exporter, tmp_path):
    store = populate(tmp_path / 'fleet.db')
    before = store.path.read_bytes()
    result = check(exporter, store.path)
    assert result['capture_complete'] is True and result['state'] == 'UNREVIEWED'
    assert result['field_accepted'] is False and result['normal_commands'] is None
    assert result['model_calls'] is None and result['recurrence'] is None
    assert len(result['rows']) == 6 and all(len(r['sha256']) == 64 for r in result['rows'])
    assert 'voltage' not in json.dumps(result) and store.path.read_bytes() == before


@pytest.mark.parametrize('mode', ['partial_roster', 'gap', 'restart', 'legacy', 'subject',
                                  'clock', 'monotonic', 'left', 'right', 'limit'])
def test_incomplete_window_holds(exporter, tmp_path, mode):
    path = tmp_path / 'fleet.db'
    store = populate(path)
    with sqlite3.connect(path) as db:
        if mode == 'partial_roster':
            db.execute("DELETE FROM fleet_observations WHERE observation_id=4")
        elif mode == 'gap':
            db.execute("DELETE FROM fleet_observations WHERE received_at=11")
        elif mode in ('left', 'right'):
            db.execute('DELETE FROM fleet_observations WHERE received_at=?', (10 if mode == 'left' else 12,))
        elif mode in ('restart', 'legacy', 'subject', 'monotonic'):
            for oid, payload in db.execute('SELECT observation_id,payload_json FROM fleet_observations WHERE received_at=11').fetchall():
                body = json.loads(payload)
                if mode == 'legacy': del body['capture']
                elif mode == 'restart': body['capture']['run_id'] = 'f' * 32
                elif mode == 'monotonic': body['capture']['monotonic_at'] = 9
                else: body['capture']['robot_ids'] = ['rosy_02']
                db.execute('UPDATE fleet_observations SET payload_json=? WHERE observation_id=?',
                           (json.dumps(body, ensure_ascii=False, separators=(',', ':')), oid))
        elif mode == 'clock':
            db.execute('UPDATE fleet_observations SET received_at=9 WHERE received_at=11')
    result = check(exporter, path, **({'max_rows': 5} if mode == 'limit' else {}))
    assert result['state'] == 'HOLD' and result['capture_complete'] is False
    assert result['reasons'] and result['normal_commands'] is None


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), True, '1', 0, -1])
def test_window_rejects_invalid_gap(exporter, tmp_path, bad):
    with pytest.raises(ValueError):
        exporter.capture_window(tmp_path / 'missing.db', robot_id='rosy_01',
                                start=10, end=11, max_gap_s=bad)


def test_window_checks_payload_identity_and_credentials(exporter, tmp_path):
    store = populate(tmp_path / 'fleet.db')
    with sqlite3.connect(store.path) as db:
        body = json.loads(db.execute('SELECT payload_json FROM fleet_observations WHERE observation_id=3').fetchone()[0])
        body['state'] = {'api_key': 'private'}
        db.execute('UPDATE fleet_observations SET payload_json=? WHERE observation_id=3',
                   (json.dumps(body, ensure_ascii=False, separators=(',', ':')),))
    with pytest.raises(ValueError, match='validation'):
        check(exporter, store.path)


def test_window_cli_preserves_export_cli_and_never_overwrites(exporter, tmp_path):
    store = populate(tmp_path / 'fleet.db')
    output = tmp_path / 'window.json'
    command = [sys.executable, '-I', '-S', exporter.__file__, str(store.path), str(output),
               '--window', '--robot-id', 'rosy_01', '--start', '10.5', '--end', '11.5', '--max-gap-s', '1']
    completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_bytes()) == json.loads(completed.stdout)
    assert json.loads(completed.stdout)['capture_complete'] is True
    original = output.read_bytes()
    assert subprocess.run(command, capture_output=True, timeout=10).returncode != 0
    assert output.read_bytes() == original
