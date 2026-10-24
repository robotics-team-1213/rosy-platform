"""Remote deployment must preserve role, explicit authority and one-shot start."""
import importlib.util
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a'*40
RUN = SHA+'-'+'b'*12


def module():
    spec = importlib.util.spec_from_file_location('remote_omx_native_under_test',
        ROOT/'tools/remote/remote_omx_native.py')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def receipt():
    anchor = '/var/lib/rosy-native-sim/1000'
    return {'schema': 'rosy.omx-native-deployment/1', 'role': 'ai', 'host': 'ai@ai.test',
        'revision': SHA, 'run_id': RUN, 'account': 'ai', 'uid': 1000,
        'state_root': anchor, 'release': anchor+'/releases/'+SHA,
        'state': anchor+'/state/'+RUN[-12:], 'deployment_status': 'READY',
        'unit': 'rosy-native-sim-'+RUN, 'task_execution': 'NOT_RUN'}


class Remote:
    def __init__(self, *, lost=False, bad_probe=False):
        self.calls, self.lost, self.bad_probe = [], lost, bad_probe

    def json(self, args, **kwargs):
        self.calls.append(args)
        if args[-1] == 'probe':
            return {'schema': 'rosy.native-sim-control/1', 'version': 1,
                'role': 'site' if self.bad_probe else 'ai', 'account': 'ai', 'uid': 1000,
                'state_root': '/var/lib/rosy-native-sim/1000'}
        if 'reserve' in args:
            return {'runtime': 'NOT_RUN'}
        if 'start' in args:
            if self.lost:
                raise TimeoutError('SSH reply lost after start request')
            return {'returncode': 0, 'unit': 'rosy-native-sim-'+RUN}
        raise AssertionError(args)


def test_only_approved_sim_role_is_selected():
    m = module()
    lab = {'sim_hosts': ['ai@ai.test=ai', 'model@model.test=model', 'site@site.test=site'],
           'site_host': 'site@site.test'}
    assert m.choose_target(lab, 'ai') == 'ai@ai.test'
    with pytest.raises(ValueError):
        m.choose_target(lab, 'site')
    with pytest.raises(ValueError):
        m.choose_target({'sim_hosts': ['site@site.test=ai'], 'site_host': 'site@site.test'}, 'ai')


@pytest.mark.parametrize('change', [
    {'uid': 0}, {'role': 'site'}, {'account': 'root'}, {'run_id': '../escape'},
    {'state': '/etc'}, {'release': '/tmp/unbound'}, {'unit': 'ssh.service'},
    {'deployment_status': 'NEEDS_PROVISIONING'},
])
def test_invalid_activation_binding_never_reaches_remote(tmp_path, change):
    m, remote = module(), Remote()
    value = receipt() | change
    with pytest.raises((ValueError, PermissionError)):
        m.start_prepared(value, tmp_path, remote, approve_sim=True, approve_startup=True)
    assert remote.calls == []


@pytest.mark.parametrize('sim,startup', [(False, False), (False, True), (True, False)])
def test_separate_execution_approvals_are_required(tmp_path, sim, startup):
    m, remote = module(), Remote()
    with pytest.raises(PermissionError):
        m.start_prepared(receipt(), tmp_path, remote, approve_sim=sim, approve_startup=startup)
    assert remote.calls == []


@pytest.mark.parametrize('experiment',['pick-place-policy','pick-place-policy-contact'])
def test_policy_study_requires_its_own_explicit_start_approval(tmp_path,experiment):
    m,remote=module(),Remote()
    value=receipt()|dict(experiment=experiment)
    with pytest.raises(PermissionError):
        m.start_prepared(value,tmp_path,remote,approve_sim=True,approve_startup=True)
    assert not remote.calls


@pytest.mark.parametrize('experiment',['pick-place-policy-calibration','pick-place-policy-contact'])
def test_policy_approval_reaches_reservation_and_is_recorded_before_start(tmp_path,experiment):
    m,remote=module(),Remote()
    value=receipt()|dict(experiment=experiment)
    result=m.start_prepared(value,tmp_path,remote,approve_sim=True,approve_startup=True,
                            approve_study=True)
    reserve=next(call for call in remote.calls if 'reserve' in call)
    assert '--approve-policy-study' in reserve
    assert json.loads((tmp_path/'start-request.json').read_text())['policy_study_approved'] is True
    assert result['task_success']=='UNKNOWN'


def test_changed_root_host_role_blocks_reservation(tmp_path):
    m, remote = module(), Remote(bad_probe=True)
    with pytest.raises(PermissionError):
        m.start_prepared(receipt(), tmp_path, remote, approve_sim=True, approve_startup=True)
    assert len(remote.calls) == 1
    assert not (tmp_path/'start-request.json').exists()


def test_service_ack_is_not_task_success_and_cannot_be_sent_twice(tmp_path):
    m, remote = module(), Remote()
    result = m.start_prepared(receipt(), tmp_path, remote, approve_sim=True, approve_startup=True)
    assert result['service_start'] == 'ACKNOWLEDGED'
    assert result['task_success'] == 'UNKNOWN'
    assert json.loads((tmp_path/'start-request.json').read_text())['run_id'] == RUN
    with pytest.raises((FileExistsError, PermissionError)):
        m.start_prepared(receipt(), tmp_path, remote, approve_sim=True, approve_startup=True)
    assert len([args for args in remote.calls if 'start' in args]) == 1


def test_lost_start_reply_requires_reconciliation_without_retry(tmp_path):
    m, remote = module(), Remote(lost=True)
    result = m.start_prepared(receipt(), tmp_path, remote, approve_sim=True, approve_startup=True)
    assert result['service_start'] == 'UNKNOWN'
    assert result['retry'] == 'RECONCILE_ONLY'
    assert (tmp_path/'start-request.json').exists()
    with pytest.raises((FileExistsError, PermissionError)):
        m.start_prepared(receipt(), tmp_path, remote, approve_sim=True, approve_startup=True)
    assert len([args for args in remote.calls if 'start' in args]) == 1


def test_root_bootstrap_executes_only_verified_private_copies(tmp_path, monkeypatch):
    m = module()
    payloads = {'install-native-sim-control.py': b'# pinned installer\n',
                'rosy-native-sim-control': b'#!/usr/bin/python3 -I\n'}
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in payloads.items()}
    program = m.bootstrap_program(payloads, hashes, 'ai', 'ai')
    original = tempfile.TemporaryDirectory
    monkeypatch.setattr(tempfile, 'TemporaryDirectory',
                        lambda **kwargs: original(dir=tmp_path, prefix='root-private-'))
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    calls = []
    def install(args, **kwargs):
        folder = Path(args[2]).parent
        assert folder.stat().st_mode & 0o777 == 0o700
        assert {name: (folder/name).read_bytes() for name in payloads} == payloads
        assert args[:2] == ['/usr/bin/python3', '-I']
        assert args[3:] == ['--role', 'ai', '--account', 'ai', '--approve-native-sim']
        calls.append(args)
    monkeypatch.setattr(subprocess, 'run', install)
    exec(compile(program, '<root-bootstrap>', 'exec'), {})
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_root_bootstrap_rejects_changed_payload_before_privileged_writes(tmp_path, monkeypatch):
    m = module()
    payloads = {'install-native-sim-control.py': b'# pinned installer\n',
                'rosy-native-sim-control': b'#!/usr/bin/python3 -I\n'}
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in payloads.items()}
    program = m.bootstrap_program(payloads, hashes, 'ai', 'ai')
    program = program.replace(base64.b64encode(payloads['rosy-native-sim-control']).decode(),
                              base64.b64encode(b'changed helper').decode())
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setattr(tempfile, 'TemporaryDirectory',
                        lambda **kwargs: pytest.fail('wrote root bootstrap before digest check'))
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: pytest.fail('ran changed payload'))
    with pytest.raises(ValueError, match='digest'):
        exec(compile(program, '<root-bootstrap>', 'exec'), {})


def test_fetch_keeps_separate_hash_bound_snapshots_without_stale_files(tmp_path):
    m = module()
    class Snapshots:
        def __init__(self):
            self.replies = []
            for name, content in [('budget.resv', b'early snapshot'), ('exit.json', b'{"exit_code":0}')]:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                    entry = tarfile.TarInfo(name)
                    entry.size = len(content)
                    archive.addfile(entry, io.BytesIO(content))
                self.replies.append(stream.getvalue())
        def script(self, program, **kwargs):
            return self.replies.pop(0)
    remote = Snapshots()
    first = m.fetch(receipt(), tmp_path, remote)
    second = m.fetch(receipt(), tmp_path, remote)
    assert first['evidence'] != second['evidence']
    assert (Path(first['evidence'])/'budget.resv').read_bytes() == b'early snapshot'
    assert not (Path(second['evidence'])/'budget.resv').exists()
    assert (Path(second['evidence'])/'exit.json').exists()
    for result in [first, second]:
        archive = Path(result['archive'])
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == result['archive_sha256']
        assert json.loads((archive.parent/'receipt.json').read_text()) == result


@pytest.mark.parametrize('action', ['status', 'fetch'])
def test_read_only_cli_succeeds_while_reporting_missing_provisioning(tmp_path, monkeypatch, action):
    m = module()
    value = receipt() | {'deployment_status': 'NEEDS_PROVISIONING'}
    path = tmp_path/'deployment.json'
    path.write_text(json.dumps(value))
    runner = SimpleNamespace(_LAB={'sim_hosts': ['ai@ai.test=ai']})
    monkeypatch.setitem(sys.modules, 'remote_pytest', runner)
    monkeypatch.setattr(m, 'SSH', lambda *args: object())
    monkeypatch.setattr(m, 'helper_probe', lambda *_: None)
    monkeypatch.setattr(m, 'fetch', lambda *_: {'deployment_status': 'NEEDS_PROVISIONING', 'evidence': 'captured'})
    monkeypatch.setattr(sys, 'argv', ['remote_omx_native.py', action, '--receipt', str(path)])
    assert m.main() == 0


def test_fetch_maps_linux_log_names_to_portable_files_without_losing_archive(tmp_path):
    m = module()
    stream = io.BytesIO()
    names = ['home/.gz/sim/log/2026-10-17T19:06:43.250759905/server.log',
             'g2/result.json', 'logs/CON.txt', 'logs/Foo', 'logs/foo', 'logs/trailing.']
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name in names:
            entry = tarfile.TarInfo(name)
            content = name.encode()
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
    raw = stream.getvalue()
    remote = SimpleNamespace(script=lambda *_args, **_kwargs: raw)
    result = m.fetch(receipt(), tmp_path, remote)
    mapping = json.loads(Path(result['extraction_map']).read_text())
    assert set(mapping) == set(names)
    assert mapping['g2/result.json'] == 'g2/result.json'
    assert len({name.casefold() for name in mapping.values()}) == len(names)
    for original, portable in mapping.items():
        assert not any(character in portable for character in ':<>"\\|?*')
        assert all(not part.endswith(('.', ' ')) and part.lower().split('.')[0] != 'con'
                   for part in portable.split('/'))
        assert (Path(result['evidence']) / portable).read_bytes() == original.encode()
    assert Path(result['archive']).read_bytes() == raw
    assert result['archive_sha256'] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('name,kind', [('../outside', 'file'), ('/absolute', 'file'), ('inside', 'symlink')])
def test_fetch_rejects_non_regular_or_escaping_members_but_retains_raw_archive(tmp_path, name, kind):
    m = module()
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        entry = tarfile.TarInfo(name)
        if kind == 'symlink':
            entry.type, entry.linkname = tarfile.SYMTYPE, 'target'
        archive.addfile(entry)
    raw = stream.getvalue()
    with pytest.raises((ValueError, tarfile.FilterError)):
        m.fetch(receipt(), tmp_path, SimpleNamespace(script=lambda *_args, **_kwargs: raw))
    captures = list((tmp_path / 'fetches').glob('*/archive.tar.gz'))
    assert len(captures) == 1 and captures[0].read_bytes() == raw
