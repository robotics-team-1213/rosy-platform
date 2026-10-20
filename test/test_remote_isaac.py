"""Remote experiment receipts are saved before start and never become commands."""
import hashlib
import importlib.util
import json
from pathlib import Path
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


class Remote:
    def __init__(self, receipt):
        self.receipt, self.calls, self.fail = receipt, [], True

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


@pytest.mark.parametrize('name', ['../escape.json', 'CON.json', 'a\\b.json', 'x:drive.json'])
def test_fetch_rejects_portable_path_escape(tmp_path, name):
    mod = module()
    row = {'run_id': 'd' * 32, 'status': 'SUCCEEDED', 'snapshot': 'FINAL',
           'artifacts': {'files': [{'id': 'import-report', 'name': name, 'bytes': 2,
                    'sha256': hashlib.sha256(b'{}').hexdigest(), 'media_type': 'application/json'}]}}
    class Files:
        def call(self, sha, payload):
            return dict(row, data_base64='e30=')
    with pytest.raises(ValueError):
        mod.fetch_snapshot({'source_sha': SHA, 'run_id': row['run_id']}, Files(), tmp_path / 'fetch')
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
            return {'run_id': 'd' * 32, 'status': 'SUCCEEDED', 'snapshot': 'FINAL',
                    'artifacts': {'files': [metadata]}}
    remote = Files()
    receipt = {'source_sha': SHA, 'run_id': 'd' * 32}
    first = mod.fetch_snapshot(receipt, remote, tmp_path / 'fetch')
    second = mod.fetch_snapshot(receipt, remote, tmp_path / 'fetch')
    assert first != second
    assert (first / 'import-report.json').read_bytes() == b'{}'
    remote.bad = True
    with pytest.raises(ValueError):
        mod.fetch_snapshot(receipt, remote, tmp_path / 'fetch')
