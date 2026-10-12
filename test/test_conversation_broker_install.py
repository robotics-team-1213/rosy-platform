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
    m.replace_managed(target, b'old', 0o600, 0, ())
    m.replace_managed(target, b'new', 0o600, 0, (b'old',))
    backup = target.with_name('managed.before-'+hashlib.sha256(b'old').hexdigest())
    assert backup.read_bytes() == b'old'
    m.replace_managed(target, b'new', 0o600, 0, ())
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
