"""A protected manifest hash does not establish successful semantic evaluation."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from deploy.ai_pc import deliberation_conversation_broker as broker
from rosy.decision.conversation.codec import Profile, source_policy


def host_configuration(monkeypatch, raw):
    import pwd
    profile = Profile(revision='d728-test')
    cfg = {'source_commit': 'a'*40, 'profile': profile.model_dump(),
           'policy': source_policy('a'*40, profile), 'valid_until': 9999999999.,
           'semantic_evidence_sha256': hashlib.sha256(raw).hexdigest(),
           'files': {'proof.json': hashlib.sha256(raw).hexdigest()}}
    monkeypatch.setattr(pwd, 'getpwnam', lambda _: SimpleNamespace(pw_uid=997))
    monkeypatch.setattr(broker.os, 'getuid', lambda: 997)
    monkeypatch.setattr(broker, 'protected', lambda p: json.dumps(cfg).encode()
                        if p == broker.CONFIG else raw)
    return cfg, profile


@pytest.mark.parametrize('raw', [b'proof', b'{}', b'{"verdict":"PASS"}',
                                b'{"verdict":"PASS","cases":[]}'])
def test_manifest_hash_alone_never_admits_conversation(monkeypatch, raw):
    host_configuration(monkeypatch, raw)
    with pytest.raises(ValueError):
        broker.configuration()


def proof():
    import time
    from deploy.ai_pc.conversation_acceptance import CASES, question
    from rosy.decision.conversation.codec import digest
    profile = Profile(revision='d728-test')
    at = time.time()
    cases = []
    for case in CASES:
        value = question(case, at)
        kind = case[2][0]
        answer = {'kind': kind, 'response': '안녕하세요.', 'steps': [],
                  'evidence_refs': [], 'review_required': False, 'reason': None}
        if kind in ('CLARIFY', 'REFUSE'):
            answer['reason'] = 'UNSUPPORTED'
        if kind == 'CONTROL':
            answer['steps'] = [{'verb': 'navigate', 'robot_id': 'rosy_40',
                                'place_id': 'A', 'parameters_json': '{}'}]
        cases.append({'case': case[0], 'input': value.model_dump(),
                      'input_hash': value.digest, 'answer': answer})
    return {'schema': 'rosy.conversation-evaluation/1', 'verdict': 'PASS',
            'evaluation_owner': 'model_pc', 'source_commit': 'a'*40,
            'profile': profile.model_dump(), 'policy': source_policy('a'*40, profile),
            'suite_sha256': digest(CASES), 'evaluated_at': at, 'cases': cases}


def test_complete_protected_semantic_proof_is_admitted(monkeypatch):
    cfg, profile = host_configuration(monkeypatch, json.dumps(proof()).encode())
    assert broker.configuration() == (cfg, profile)


@pytest.mark.parametrize('change', ['failed', 'partial', 'duplicate', 'kind', 'input',
                                   'hash', 'profile', 'policy', 'owner', 'stale', 'fact'])
def test_semantic_proof_tampering_is_rejected(monkeypatch, change):
    value = proof()
    if change == 'failed': value['verdict'] = 'FAIL'
    elif change == 'partial': value['cases'].pop()
    elif change == 'duplicate': value['cases'][1] = value['cases'][0]
    elif change == 'kind': value['cases'][1]['answer']['kind'] = 'CHAT'
    elif change == 'input': value['cases'][0]['input']['principal_id'] = 'other'
    elif change == 'hash': value['cases'][0]['input_hash'] = 'b'*64
    elif change == 'profile': value['profile']['revision'] = 'd728-other'
    elif change == 'policy': value['policy']['authority'] = 'control'
    elif change == 'owner': value['evaluation_owner'] = 'ai_pc'
    elif change == 'stale': value['evaluated_at'] -= 8*86400
    elif change == 'fact': value['cases'][0]['answer']['response'] = '현재 로봇은 이동 완료 상태입니다.'
    host_configuration(monkeypatch, json.dumps(value).encode())
    with pytest.raises(ValueError):
        broker.configuration()
