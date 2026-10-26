"""Collection transfer transports verified bytes without overwriting raw sessions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1]/'tools/remote/omx_collection_transfer.py'
    spec = importlib.util.spec_from_file_location('omx_collection_transfer', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def raw(root):
    root.mkdir()
    (root/'samples.jsonl').write_bytes(b'{}\n')
    manifest = dict(schema='rosy.omx-collection-session.v1', state='CLOSED', mode='hardware',
                    source_mode='scripted_teacher', files={'samples.jsonl': hashlib.sha256(b'{}\n').hexdigest()})
    (root/'manifest.json').write_text(json.dumps(manifest))
    return manifest


def test_verified_manifest_bytes_and_exact_file_coverage(module, tmp_path):
    root = tmp_path/'raw'
    raw(root)
    result = module.verify_tree(root)
    assert result['manifest_sha256'] == hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()
    assert result['file_count'] == 1
    (root/'extra').write_text('unlisted')
    with pytest.raises(ValueError):
        module.verify_tree(root)


@pytest.mark.parametrize('fault', ['hash', 'open', 'rehearsal', 'path', 'symlink'])
def test_corrupt_or_unclosed_source_refused(module, tmp_path, fault):
    root = tmp_path/'raw'
    manifest = raw(root)
    if fault == 'hash': (root/'samples.jsonl').write_bytes(b'changed')
    if fault == 'open': manifest['state'] = 'RUNNING'
    if fault == 'rehearsal': manifest.update(mode='rehearsal', source_mode='simulation')
    if fault == 'path': manifest['files'] = {'../escape': 'a'*64}
    if fault == 'symlink':
        (root/'samples.jsonl').unlink()
        outside = tmp_path/'outside'
        outside.write_bytes(b'{}\n')
        (root/'samples.jsonl').symlink_to(outside)
    (root/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        module.verify_tree(root)


def test_transfer_reserves_then_copies_and_rechecks_source_before_receipt(module, monkeypatch):
    monkeypatch.setattr(module.lab_hosts, 'load', lambda: dict(site_host='site@host', test_hosts=['model@host']))
    calls = []
    verified = dict(manifest_sha256='a'*64, file_count=2)
    def remote(host, action, *args):
        calls.append((host, action))
        return dict(verified) if action in ('source', 'destination') else {}
    monkeypatch.setattr(module, '_remote', remote)
    monkeypatch.setattr(module, '_copy', lambda *args: calls.append(('copy', args)))
    result = module.transfer('session-1', 'received-1')
    assert [call[1] for call in calls if call[0] != 'copy'] == [
        'source', 'reserve', 'destination', 'source', 'finish', 'release']
    assert calls[2][0] == 'copy'
    assert result['manifest_sha256'] == 'a'*64 and result['verified'] is True
    assert result['receipt_path'] == 'rosy-test/omx-il-data/transfer-receipts/received-1.json'


def test_transfer_reads_the_independent_native_host(module, monkeypatch):
    monkeypatch.setattr(module.lab_hosts, 'load', lambda: dict(
        site_host='site@host', omx_hosts=['arm@host'], test_hosts=['model@host']))
    calls = []
    verified = dict(manifest_sha256='a'*64, file_count=2)
    monkeypatch.setattr(module, '_remote', lambda host, action, *args: calls.append((host, action)) or verified)
    monkeypatch.setattr(module, '_copy', lambda *args: calls.append(('copy', args)))
    module.transfer('session')
    assert calls[0] == ('arm@host', 'source')
    assert calls[2][1][0] == 'arm@host'
    assert not any(call[0] == 'site@host' for call in calls)


@pytest.mark.parametrize('hosts', [[], ['arm@host', 'arm2@host']])
def test_transfer_refuses_missing_or_ambiguous_native_source(module, monkeypatch, hosts):
    monkeypatch.setattr(module.lab_hosts, 'load', lambda: dict(
        site_host='site@host', omx_hosts=hosts, test_hosts=['model@host']))
    monkeypatch.setattr(module, '_remote', lambda *args: pytest.fail('transport invoked'))
    with pytest.raises(ValueError, match='exactly one'):
        module.transfer('session')


@pytest.mark.parametrize('name', ['../outside', '-option', 'space name', 'x;y', 'x/y'])
def test_unsafe_session_names_never_reach_transport(module, name, monkeypatch):
    monkeypatch.setattr(module, '_remote', lambda *args: pytest.fail('transport invoked'))
    with pytest.raises(ValueError):
        module.transfer(name)


def test_source_mutation_never_emits_success_receipt(module, monkeypatch):
    monkeypatch.setattr(module.lab_hosts, 'load', lambda: dict(site_host='site@host', test_hosts=['model@host']))
    calls = []
    def remote(host, action, *args):
        calls.append(action)
        return dict(manifest_sha256=('b' if calls.count('source') > 1 else 'a')*64, file_count=1)
    monkeypatch.setattr(module, '_remote', remote)
    monkeypatch.setattr(module, '_copy', lambda *args: None)
    with pytest.raises(ValueError, match='changed'):
        module.transfer('session')
    assert 'finish' not in calls and calls[-1] == 'release'


def test_receiver_reserves_exclusively_and_writes_receipt_outside_raw_tree(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module.Path, 'home', lambda: tmp_path)
    source = tmp_path/'rosy-test/omx-collections/session'
    source.parent.mkdir(parents=True)
    raw(source)
    original = module.verify_tree(source)
    token = 'a'*32
    module._receiver('reserve', 'session', 'received', token)
    with pytest.raises(FileExistsError):
        module._receiver('reserve', 'session', 'received', 'b'*32)
    destination = tmp_path/'rosy-test/omx-il-data/collections/received'
    shutil.copytree(source, destination)
    result = module._receiver('finish', 'session', 'received', token, original['manifest_sha256'])
    assert result['verified']
    assert module.verify_tree(destination) == original
    assert (destination.parent.parent/'transfer-receipts/received.json').is_file()
    module._receiver('release', 'session', 'received', token)
    with pytest.raises(ValueError, match='exists'):
        module._receiver('reserve', 'session', 'received', token)


def test_copy_uses_direct_new_destination_and_pinned_noninteractive_transport(module, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr(module.subprocess, 'run', run)
    module._copy('site@host', 'model@host', 'session', 'received')
    argv, kwargs = calls[0]
    assert argv[:4] == ['scp', '-3', '-q', '-r']
    assert 'BatchMode=yes' in argv and 'StrictHostKeyChecking=yes' in argv
    assert argv[-2:] == ['site@host:rosy-test/omx-collections/session',
                         'model@host:rosy-test/omx-il-data/collections/received']
    assert kwargs['timeout'] == 1800 and 'shell' not in kwargs
