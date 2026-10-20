"""The privileged client installer binds only the separately reviewed conversation proof."""
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'deploy/site/install-status-client.py'


@pytest.fixture
def installer():
    spec = importlib.util.spec_from_file_location('site_client', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def admission():
    from fleet.server.channel.conversation.runtime import ConversationConfig
    from rosy.decision.conversation.codec import Profile, source_policy
    profile = Profile(revision='d728-semantic-v2')
    proof = {'schema':'rosy.conversation-evaluation/1', 'verdict':'PASS',
             'evaluation_owner':'model_pc', 'source_commit':'a'*40,
             'profile':profile.model_dump(), 'policy':source_policy('a'*40, profile),
             'evaluated_at':time.time()-10}
    raw = json.dumps(proof).encode()
    config = dict(host='model.example', ssh_port=22, key_file='/run/rosy-deliberation/broker.key',
        known_hosts_file='/run/rosy-deliberation/known_hosts', source_commit='a'*40,
        profile=profile.model_dump(), policy=proof['policy'], valid_until=time.time()+60,
        primary_admitted=True, semantic_evidence_sha256=hashlib.sha256(raw).hexdigest())
    ConversationConfig.model_validate(config)
    return config, raw


def test_conversation_config_accepts_separate_proof(installer, admission):
    cfg, proof = admission
    installer.validate_conversation(cfg, proof)
    assert cfg['ssh_port'] == 22


def test_d831_client_binds_preprocessing_policy_and_refuses_policy_downgrade(installer, admission):
    from rosy.decision.conversation.codec import Profile, source_policy
    from rosy.decision.conversation.preprocessing import DISCORD_REVISION
    cfg, raw = admission
    proof = json.loads(raw)
    profile = Profile(revision=DISCORD_REVISION)
    cfg['profile'] = proof['profile'] = profile.model_dump()
    cfg['policy'] = proof['policy'] = source_policy(cfg['source_commit'], profile)
    raw = json.dumps(proof).encode()
    cfg['semantic_evidence_sha256'] = hashlib.sha256(raw).hexdigest()
    installer.validate_conversation(cfg, raw)
    cfg['policy'] = dict(cfg['policy'])
    cfg['policy'].pop('preprocessing_version')
    with pytest.raises(ValueError):
        installer.validate_conversation(cfg, raw)


@pytest.mark.parametrize('field,value', [
    ('source_commit','b'*40), ('semantic_evidence_sha256','b'*64),
    ('primary_admitted',False), ('primary_admitted',1), ('valid_until',float('inf')),
    ('valid_until',0), ('valid_until',True), ('ssh_port',2222), ('ssh_port',True),
    ('host','-oProxyCommand=bad'), ('host',123), ('key_file','/tmp/key'), ('hourly_followup',True),
    ('policy',{}), ('profile',{}),
])
def test_conversation_config_refuses_drift(installer, admission, field, value):
    cfg, proof = admission
    cfg[field] = value
    with pytest.raises((ValueError, SystemExit)):
        installer.validate_conversation(cfg, proof)


@pytest.mark.parametrize('field,value', [('verdict','HOLD'), ('evaluation_owner','ai_pc'),
    ('evaluated_at',0), ('evaluated_at',float('inf')), ('evaluated_at',time.time()+3600)])
def test_even_pinned_proof_requires_current_independent_admission(installer, admission, field, value):
    cfg, raw = admission
    proof = json.loads(raw); proof[field] = value
    raw = json.dumps(proof).encode()
    cfg['semantic_evidence_sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises((ValueError, SystemExit)):
        installer.validate_conversation(cfg, raw)


def test_reviewed_reader_refuses_symlink_before_read(installer, tmp_path):
    target = tmp_path/'config'; target.write_bytes(b'{}')
    link = tmp_path/'link'; link.symlink_to(target)
    with pytest.raises((ValueError, SystemExit)):
        installer.reviewed_bytes(link, hashlib.sha256(b'{}').hexdigest(), tmp_path)


def test_conversation_cli_reaches_root_boundary_without_mutation(tmp_path):
    import os
    import subprocess
    import sys
    if os.geteuid() == 0:pytest.skip('requires unprivileged test account')
    result = subprocess.run([sys.executable, str(SCRIPT), 'config', 'pins', 'public',
        '--conversation', '--config-sha256','a'*64, '--known-hosts-sha256','b'*64,
        '--conversation-proof','proof', '--proof-sha256','c'*64, '--public-key-sha256','d'*64],
        capture_output=True, text=True, timeout=5,
        env={**os.environ,'PYTHONPATH':str(SCRIPT.parents[2])})
    assert result.returncode != 0 and 'root installation required' in result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('name', ['status.json','conversation.json'])
def test_install_destination_modes_and_status_preservation(installer, admission, tmp_path, monkeypatch, name):
    import os
    from types import SimpleNamespace
    cfg, _ = admission
    key = tmp_path/'private'; key.write_bytes(b'test-private-key'); key.chmod(0o600)
    real_path = Path
    mapped = {'/etc/rosy':tmp_path, '/home/robttt/.rosy/status-incoming/broker.key':key}
    monkeypatch.setattr(installer,'Path',lambda path:mapped.get(str(path),real_path(path)))
    monkeypatch.setattr(installer.pwd,'getpwnam',lambda _:SimpleNamespace(pw_uid=os.getuid()))
    monkeypatch.setattr(installer,'trusted_directory',lambda _:None)
    monkeypatch.setattr(installer.os,'chown',lambda *args:None)
    def public_key(args, **kwargs):
        assert args[:3] == ['/usr/bin/ssh-keygen','-y','-f']
        return 'ssh-ed25519 public'
    monkeypatch.setattr(installer.subprocess,'check_output',public_key)
    calls=[]
    monkeypatch.setattr(installer,'install_file',lambda path,data,mode,gid=0:calls.append((path.name,data,mode,gid)))
    installer.install_client(cfg,b'config',b'model.example ssh-ed25519 host\n',b'ssh-ed25519 public',name)
    assert calls == [('broker.key',b'test-private-key',0o640,10001),
        ('known_hosts',b'model.example ssh-ed25519 host\n',0o640 if name=='conversation.json' else 0o644,
         10001 if name=='conversation.json' else 0), (name,b'config',0o640,10001)]


@pytest.mark.parametrize('pins', [b'model.example ssh-ed25519 first\nother ssh-ed25519 second',
    b'[model.example]:2222 ssh-ed25519 host', b'foreign.example ssh-ed25519 host'])
def test_pin_scope_refused_before_private_key_access(installer, admission, monkeypatch, pins):
    cfg, _ = admission
    monkeypatch.setattr(installer.os,'open',lambda *a:pytest.fail('private key accessed'))
    with pytest.raises(SystemExit,match='one fixed host pin'):
        installer.install_client(cfg,b'config',pins,b'public','conversation.json')
