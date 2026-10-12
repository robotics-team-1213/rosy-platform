"""Administrator installer boundary checks; all host mutations are simulated."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'deploy/site/install_conversation_broker.py'


def module():
    assert SCRIPT.exists(), 'protected conversation installer is missing'
    spec = importlib.util.spec_from_file_location('conversation_install', SCRIPT)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_installer_rejects_unprivileged_before_reading_inputs(tmp_path):
    m = module()
    if os.geteuid() == 0:
        pytest.skip('unprivileged test account required')
    with pytest.raises(ValueError, match='ADMIN_INSTALL_REQUIRED'):
        m.require_admin()
    assert list(tmp_path.iterdir()) == []


def test_dispatcher_allows_only_two_exact_zero_argument_commands(tmp_path):
    m = module()
    script = tmp_path/'ingress'
    script.write_bytes(m.dispatcher())
    subprocess.run(['/bin/sh', '-n', str(script)], check=True)
    for command in ('', 'id', 'rosy-conversation-v1 extra', 'rosy-conversation-v1; id', 'rosy-status-v1\n'):
        p = subprocess.run(['/bin/sh', str(script)], env={'SSH_ORIGINAL_COMMAND': command}, capture_output=True)
        assert p.returncode == 64
    for command in ('rosy-status-v1', 'rosy-conversation-v1'):
        p = subprocess.run(['/bin/sh', str(script), 'unexpected'], env={'SSH_ORIGINAL_COMMAND': command}, capture_output=True)
        assert p.returncode == 64


def test_root_path_rejects_untrusted_owner_and_symlink(tmp_path):
    m = module()
    target = tmp_path/'file'
    target.write_bytes(b'private')
    link = tmp_path/'link'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='PROTECTED'):
        m.protected(link)
    if os.geteuid() != 0:
        with pytest.raises(ValueError, match='PROTECTED'):
            m.protected(target)


def test_replacement_is_idempotent_and_refuses_foreign_files(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m, 'protected', lambda p: p.read_bytes())
    monkeypatch.setattr(m, 'trusted_directory', lambda p: None)
    monkeypatch.setattr(m.os, 'chown', lambda *a: None)
    target = tmp_path/'managed'
    m.replace_managed(target, b'old', 0o600, os.getgid(), ())
    m.replace_managed(target, b'new', 0o600, os.getgid(), (b'old',))
    backup = target.with_name('managed.before-'+hashlib.sha256(b'old').hexdigest())
    assert backup.read_bytes() == b'old'
    m.replace_managed(target, b'new', 0o600, os.getgid(), ())
    assert len(list(tmp_path.iterdir())) == 2
    with pytest.raises(ValueError, match='FOREIGN'):
        m.replace_managed(target, b'foreign', 0o600, 0, ())
    assert target.read_bytes() == b'new'


def test_receipt_binds_independent_proof_and_source():
    m = module()
    proof = {'source_commit':'a'*40, 'source_manifest_sha256':'b'*64, 'suite_sha256':'c'*64,
             'evaluated_at':123, 'profile':{'revision':'d728-semantic-v2'}}
    receipt = {**{k:proof[k] for k in ('source_commit','source_manifest_sha256','suite_sha256','evaluated_at')},
        'schema':'rosy.conversation-evaluation-receipt/1', 'verdict':'PASS', 'evaluation_owner':'model_pc',
        'candidate_diagnostics_used':False, 'device_commands_performed':False,
        'protected_admission_performed':False, 'proof_sha256':'d'*64, 'profile_revision':'d728-semantic-v2'}
    m.validate_receipt(receipt, proof, 'd'*64)
    for key,value in [('source_commit','f'*40), ('proof_sha256','e'*64), ('evaluation_owner','ai_pc'),
                      ('candidate_diagnostics_used',True), ('suite_sha256','e'*64)]:
        with pytest.raises(ValueError, match='RECEIPT'):
            m.validate_receipt({**receipt,key:value}, proof, 'd'*64)

@pytest.fixture
def bundle(tmp_path, monkeypatch):
    import base64
    m = module()
    monkeypatch.setattr(m, 'REVIEWED', tmp_path)
    monkeypatch.setattr(m, 'trusted_directory', lambda p: None)
    monkeypatch.setattr(m, 'protected', lambda p: p.read_bytes())
    source = tmp_path/'source'
    names = ['deploy/site/deliberation_install.py', 'deploy/site/requirements-fleet.txt',
        'deploy/ai_pc/conversation_acceptance.py', 'deploy/ai_pc/deliberation_conversation_broker.py',
        'deploy/ai_pc/deliberation_conversation.py', 'operations/decision/src/rosy/decision/conversation/codec.py']
    files = {}
    for name in names:
        path = source/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'# source\n')
        files[name] = m.sha(path.read_bytes())
    manifest = {'source_commit':'a'*40,'files':files}
    proof = {'source_commit':'a'*40, 'source_manifest_sha256':m.sha(json.dumps(files,sort_keys=True,separators=(',',':')).encode()),
             'suite_sha256':'c'*64, 'evaluated_at':123, 'profile':{'revision':'d728-semantic-v2'}}
    proof_raw = json.dumps(proof).encode()
    receipt = {**{k:proof[k] for k in ('source_commit','source_manifest_sha256','suite_sha256','evaluated_at')},
        'schema':'rosy.conversation-evaluation-receipt/1', 'verdict':'PASS', 'evaluation_owner':'model_pc',
        'candidate_diagnostics_used':False, 'device_commands_performed':False,
        'protected_admission_performed':False, 'proof_sha256':m.sha(proof_raw), 'profile_revision':'d728-semantic-v2'}
    wire = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20'+b'x'*32
    values = {'source-manifest.json':json.dumps(manifest).encode(), 'semantic-evaluation-proof.json':proof_raw,
              'semantic-evaluation-receipt.json':json.dumps(receipt).encode(),
              'ingress.pub':b'ssh-ed25519 '+base64.b64encode(wire)+b' fixture\n'}
    for name,raw in values.items():
        (tmp_path/name).write_bytes(raw)
    pins = dict(zip(('manifest','proof','receipt','public_key'),map(m.sha,values.values())))
    return m, tmp_path, pins


def test_reviewed_source_hashes_and_independent_receipt_match(bundle):
    m,root,pins = bundle
    manifest,proof,contents,*_ = m.inputs(root,pins)
    assert manifest['source_commit'] == proof['source_commit']
    assert set(contents) == set(manifest['files'])


@pytest.mark.parametrize('name', ['source-manifest.json','semantic-evaluation-proof.json',
    'semantic-evaluation-receipt.json','ingress.pub','source/deploy/ai_pc/deliberation_conversation.py'])
def test_each_tampered_review_input_is_rejected(bundle,name):
    m,root,pins = bundle
    (root/name).write_bytes(b'changed')
    with pytest.raises(ValueError,match='SHA_MISMATCH'):
        m.inputs(root,pins)


def test_missing_proof_fails_before_any_installation(bundle):
    m,root,pins = bundle
    (root/'semantic-evaluation-proof.json').unlink()
    with pytest.raises(FileNotFoundError):
        m.inputs(root,pins)
    assert not (root/'venv').exists()


def test_incomplete_source_manifest_is_rejected_even_with_new_manifest_pin(bundle):
    m,root,pins = bundle
    path = root/'source-manifest.json'
    value = json.loads(path.read_bytes())
    value['files'].pop('deploy/ai_pc/deliberation_conversation_broker.py')
    path.write_text(json.dumps(value))
    pins['manifest'] = m.sha(path.read_bytes())
    with pytest.raises(ValueError,match='CLOSURE'):
        m.inputs(root,pins)


def test_changed_source_cannot_borrow_prior_evaluation(bundle):
    m,root,pins = bundle
    path = root/'source-manifest.json'
    value = json.loads(path.read_bytes())
    source = root/'source/deploy/ai_pc/deliberation_conversation.py'
    source.write_bytes(b'# changed source\n')
    value['files']['deploy/ai_pc/deliberation_conversation.py'] = m.sha(source.read_bytes())
    path.write_text(json.dumps(value))
    pins['manifest'] = m.sha(path.read_bytes())
    with pytest.raises(ValueError,match='EVALUATED_SOURCE'):
        m.inputs(root,pins)


@pytest.mark.parametrize('name', ['../outside.py','/etc/shadow','deploy//bad.py','deploy/./bad.py'])
def test_source_manifest_cannot_escape_snapshot(bundle,name):
    m,root,pins = bundle
    path = root/'source-manifest.json'
    value = json.loads(path.read_bytes())
    value['files'][name] = 'a'*64
    path.write_text(json.dumps(value))
    pins['manifest'] = m.sha(path.read_bytes())
    with pytest.raises(ValueError,match='SOURCE_PATH'):
        m.inputs(root,pins)


def test_ingress_account_refuses_unregistered_existing_account(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import grp
    import pwd
    m = module()
    account = SimpleNamespace(pw_name='rosy-model-ingress',pw_uid=996,pw_gid=983,pw_dir='/var/empty',pw_shell='/bin/sh')
    monkeypatch.setattr(pwd,'getpwnam',lambda _:account)
    monkeypatch.setattr(grp,'getgrgid',lambda _:SimpleNamespace(gr_name=account.pw_name,gr_mem=[]))
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    with pytest.raises(FileNotFoundError):
        m.account_registration(None,tmp_path)


def test_ingress_account_rejects_supplementary_group(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import grp
    import pwd
    m = module()
    account = SimpleNamespace(pw_name='rosy-model-ingress',pw_uid=996,pw_gid=983,pw_dir='/var/empty',pw_shell='/bin/sh')
    monkeypatch.setattr(pwd,'getpwnam',lambda _:account)
    monkeypatch.setattr(pwd,'getpwall',lambda:[account])
    monkeypatch.setattr(grp,'getgrgid',lambda _:SimpleNamespace(gr_name=account.pw_name,gr_mem=[]))
    monkeypatch.setattr(m.os,'getgrouplist',lambda *a:[983,27])
    monkeypatch.setattr(m,'protected',lambda p:p.read_bytes())
    path = tmp_path/'ingress.json'
    path.write_text(json.dumps({'uid':996,'gid':983}))
    path.chmod(0o600)
    with pytest.raises(ValueError,match='DEDICATED_INGRESS'):
        m.account_registration(None,tmp_path)
