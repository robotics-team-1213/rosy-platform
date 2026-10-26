"""Remote experiment receipts are saved before start and never become commands."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


def module():
    path = ROOT / 'tools/remote/remote_isaac.py'
    assert path.is_file(), 'Remote Isaac CLI is missing'
    spec = importlib.util.spec_from_file_location('remote_isaac', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def request():
    return {'request_id': uuid.uuid4().hex, 'scenario_id': 'omx-f-import', 'config': {'seed': 0},
            'source_sha': SHA, 'expected_input_sha256': 'b' * 64}


def test_explicit_model_target_is_selected_without_test_host_fallback():
    lab = {'sim_hosts': ['fake@ai=ai', 'fake@model=model'], 'site_host': 'fake@site',
           'test_hosts': ['fake@test']}
    assert module().choose_target(lab, 'model') == 'fake@model'


@pytest.mark.parametrize('lab', [
    {'sim_hosts': []},
    {'sim_hosts': ['fake@one=model', 'fake@two=model']},
    {'sim_hosts': ['fake@site=model'], 'site_host': 'fake@site'},
    {'sim_hosts': ['fake@bad;command=model']},
])
def test_model_target_refuses_missing_ambiguous_site_or_shell_target(lab):
    with pytest.raises(ValueError):
        module().choose_target(lab, 'model')


class Remote:
    def __init__(self, receipt):
        self.receipt, self.calls, self.fail = receipt, [], True

    def hold(self, run_id, active):
        pass

    def call(self, sha, payload):
        self.calls.append(payload)
        assert self.receipt.exists(), 'receipt must precede network start'
        if payload['action'] == 'start' and self.fail:
            self.fail = False
            raise ConnectionError('response lost')
        value = json.loads(self.receipt.read_text())
        return {'run_id': value['run_id'], 'input_sha256': value['input_sha256'],
                'status': 'RUNNING', 'snapshot': 'OBSERVATION_NOT_ATOMIC'}


def test_receipt_survives_response_loss_and_retry_uses_same_run(tmp_path):
    mod = module()
    path = tmp_path / 'receipt.json'
    remote, value = Remote(path), request()
    with pytest.raises(ConnectionError):
        mod.start(value, path, remote)
    saved = json.loads(path.read_text())
    row = mod.start(value, path, remote)
    assert row['run_id'] == saved['run_id']
    assert all(call['request']['request_id'] == value['request_id'] for call in remote.calls)
    assert mod.observe(path, remote)['run_id'] == saved['run_id']


def test_receipt_conflicts_and_unapproved_host_fail_before_network(tmp_path):
    mod = module()
    path = tmp_path / 'receipt.json'
    remote, value = Remote(path), request()
    with pytest.raises(ConnectionError):
        mod.start(value, path, remote)
    for change in [{'source_sha': 'HEAD'}, {'request_id': uuid.uuid4().hex}, {'cmd': 'shell'}]:
        with pytest.raises(ValueError):
            mod.start(dict(value, **change), path, remote)
    assert len(remote.calls) == 1
    with pytest.raises(ValueError):
        mod.choose_target({'sim_hosts': ['fake@host=ai']}, 'model')


def test_receipt_cannot_follow_changed_model_host(tmp_path):
    mod = module()
    path = tmp_path / 'receipt.json'
    remote = Remote(path)
    remote.target_id = 'c' * 64
    with pytest.raises(ConnectionError):
        mod.start(request(), path, remote)
    remote.target_id = 'd' * 64
    with pytest.raises(ValueError):
        mod.observe(path, remote)
    assert len(remote.calls) == 1


def test_receipt_is_complete_before_publication(tmp_path, monkeypatch):
    mod = module()
    path = tmp_path / 'receipt.json'
    original = mod.json.dump
    def interrupted(value, stream, **kw):
        stream.write('{')
        raise OSError('writer stopped')
    monkeypatch.setattr(mod.json, 'dump', interrupted)
    with pytest.raises(OSError):
        mod._save(path, {'must': 'be complete'})
    assert not path.exists()
    monkeypatch.setattr(mod.json, 'dump', original)
    mod._save(path, {'must': 'be complete'})
    assert json.loads(path.read_text()) == {'must': 'be complete'}


@pytest.mark.parametrize('name', ['../escape.json', 'CON.json', 'a\\b.json', 'x:drive.json'])
def test_fetch_rejects_portable_path_escape(tmp_path, name):
    mod = module()
    row = {'run_id': 'd' * 32, 'input_sha256': 'b' * 64, 'status': 'SUCCEEDED', 'snapshot': 'FINAL',
           'artifacts': {'files': [{'id': 'import-report', 'name': name, 'bytes': 2,
                    'sha256': hashlib.sha256(b'{}').hexdigest(), 'media_type': 'application/json'}]}}
    class Files:
        def call(self, sha, payload):
            return dict(row, data_base64='e30=')
    with pytest.raises(ValueError):
        mod.fetch_snapshot({'source_sha': SHA, 'run_id': row['run_id'], 'input_sha256': 'b' * 64}, Files(), tmp_path / 'fetch')
    assert not (tmp_path / 'escape.json').exists()


def test_fetch_verifies_hash_and_keeps_new_snapshot_each_time(tmp_path):
    mod = module()
    metadata = {'id': 'import-report', 'name': 'import-report.json', 'bytes': 2,
                'sha256': hashlib.sha256(b'{}').hexdigest(), 'media_type': 'application/json'}
    class Files:
        bad = False
        def call(self, sha, payload):
            if payload['action'] == 'artifact':
                return dict(metadata, data_base64='e30=' if not self.bad else 'e10=')
            return {'run_id': 'd' * 32, 'input_sha256': 'b' * 64, 'status': 'SUCCEEDED', 'snapshot': 'FINAL',
                    'artifacts': {'files': [metadata]}}
    remote = Files()
    receipt = {'source_sha': SHA, 'run_id': 'd' * 32, 'input_sha256': 'b' * 64}
    first = mod.fetch_snapshot(receipt, remote, tmp_path / 'fetch')
    second = mod.fetch_snapshot(receipt, remote, tmp_path / 'fetch')
    assert first != second
    assert (first / 'import-report.json').read_bytes() == b'{}'
    remote.bad = True
    with pytest.raises(ValueError):
        mod.fetch_snapshot(receipt, remote, tmp_path / 'fetch')


def test_fetch_fingerprint_conflict_makes_no_snapshot_or_artifact_request(tmp_path):
    mod = module()
    calls = []
    class Files:
        def call(self, sha, payload):
            calls.append(payload['action'])
            return {'run_id': 'd' * 32, 'input_sha256': 'c' * 64, 'snapshot': 'FINAL'}
    with pytest.raises(ValueError):
        mod.fetch_snapshot({'source_sha': SHA, 'run_id': 'd' * 32, 'input_sha256': 'b' * 64},
                           Files(), tmp_path / 'fetch')
    assert calls == ['status']
    assert not (tmp_path / 'fetch').exists()


def test_fetch_syncs_artifact_before_completion_marker(tmp_path, monkeypatch):
    mod = module()
    import os
    synced = []
    real_sync = os.fsync
    def sync(fd):
        synced.append(Path(os.readlink('/proc/self/fd/' + str(fd))).name)
        real_sync(fd)
    monkeypatch.setattr(os, 'fsync', sync)
    save = mod._save
    def publish(path, value):
        if path.name == 'snapshot.json':
            assert 'import-report.json' in synced, 'artifact data must precede durable completion'
        save(path, value)
    monkeypatch.setattr(mod, '_save', publish)
    metadata = {'id': 'import-report', 'name': 'import-report.json', 'bytes': 2,
                'sha256': hashlib.sha256(b'{}').hexdigest(), 'media_type': 'application/json'}
    class Files:
        def call(self, sha, payload):
            if payload['action'] == 'artifact':
                return dict(metadata, data_base64='e30=')
            return {'run_id': 'd' * 32, 'input_sha256': 'b' * 64, 'snapshot': 'FINAL',
                    'artifacts': {'files': [metadata]}}
    mod.fetch_snapshot({'source_sha': SHA, 'run_id': 'd' * 32, 'input_sha256': 'b' * 64},
                       Files(), tmp_path / 'fetch')


def test_transport_preserves_unknown_run_with_diagnostic_error():
    mod = module()
    from types import SimpleNamespace
    row = {'run_id': 'd' * 32, 'status': 'UNKNOWN', 'error': 'owned cleanup unconfirmed'}
    remote = mod.SSH.__new__(mod.SSH)
    remote.host = 'unused-test-host'
    remote.runner = SimpleNamespace(remote=lambda *a, **k: SimpleNamespace(returncode=0,
                                    stdout=json.dumps(row).encode()))
    assert remote._invoke('fixed script', {}) == row


def isaac_host(tmp_path, monkeypatch, statuses):
    """The real HOLD script against HOME=tmp_path; the supervisor reports `statuses` in order."""
    mod = module()
    monkeypatch.setenv('HOME', str(tmp_path))
    remote = mod.SSH.__new__(mod.SSH)
    remote.target_id = None
    remote._invoke = lambda script, value: json.loads(subprocess.run(
        [sys.executable, '-c', script], input=json.dumps(value).encode(),
        capture_output=True, check=True).stdout)

    def call(sha, payload):
        value = json.loads((tmp_path / 'receipt.json').read_text())
        return {'run_id': value['run_id'], 'input_sha256': value['input_sha256'],
                'status': statuses.pop(0), 'revision': 0}
    remote.call = call
    return mod, remote


def test_supervisor_run_holds_gpu_reservation_until_terminal(tmp_path, monkeypatch):
    statuses = ['RUNNING', 'RUNNING', 'SUCCEEDED']
    mod, remote = isaac_host(tmp_path, monkeypatch, statuses)
    receipt = tmp_path / 'receipt.json'
    row = mod.start(request(), receipt, remote)
    resv = tmp_path / 'rosy-jobs' / ('isaac-' + row['run_id'] + '.resv')
    expiry, kind, cores, gb = resv.read_text().split()
    assert (kind, cores, gb) == ('gpu', '6', '8')
    assert time.time() < int(expiry) <= time.time() + 7200
    resv.write_text('%d gpu 6 8\n' % (time.time() + 10))
    mod.observe(receipt, remote)
    assert int(resv.read_text().split()[0]) > time.time() + 7000, 'active poll renews the hold'
    mod.observe(receipt, remote)
    assert not resv.exists() and not statuses


def test_stopping_supervisor_run_releases_reservation(tmp_path, monkeypatch):
    statuses = ['RUNNING', 'RUNNING', 'STOP_REQUESTED']
    mod, remote = isaac_host(tmp_path, monkeypatch, statuses)
    receipt = tmp_path / 'receipt.json'
    row = mod.start(request(), receipt, remote)
    resv = tmp_path / 'rosy-jobs' / ('isaac-' + row['run_id'] + '.resv')
    assert resv.exists()
    mod.observe(receipt, remote, stop=True)
    assert not resv.exists() and not statuses
