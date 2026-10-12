"""The privileged client installer binds only the separately reviewed conversation proof."""
import copy
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


@pytest.mark.parametrize('field,value', [
    ('source_commit','b'*40), ('semantic_evidence_sha256','b'*64),
    ('primary_admitted',False), ('primary_admitted',1), ('valid_until',float('inf')),
    ('valid_until',0), ('valid_until',True), ('ssh_port',2222), ('ssh_port',True),
    ('host','-oProxyCommand=bad'), ('key_file','/tmp/key'), ('hourly_followup',True),
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
