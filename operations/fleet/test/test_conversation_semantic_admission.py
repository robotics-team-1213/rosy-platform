"""A protected manifest hash does not establish successful semantic evaluation."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from deploy.ai_pc import deliberation_conversation_broker as broker
from rosy.decision.conversation.codec import Profile, source_policy


def host_configuration(monkeypatch, raw, *, include_source=True, omit=None, mutation=None):
    import pwd
    profile = Profile(revision='d728-test')
    cfg = {'source_commit': 'a'*40, 'profile': profile.model_dump(),
           'policy': source_policy('a'*40, profile), 'valid_until': 9999999999.,
           'semantic_evidence_sha256': hashlib.sha256(raw).hexdigest(),
           'files': {'proof.json': hashlib.sha256(raw).hexdigest()}}
    from deploy.ai_pc.conversation_acceptance import source_files
    contents = {name: (broker.ROOT/name).read_bytes() for name in source_files(broker.ROOT)}
    if mutation: contents[mutation] = b'changed source'
    if include_source:
        cfg['files'].update({name: hashlib.sha256(data).hexdigest() for name, data in contents.items()})
    if omit: cfg['files'].pop(omit)
    monkeypatch.setattr(pwd, 'getpwnam', lambda _: SimpleNamespace(pw_uid=997))
    monkeypatch.setattr(broker.os, 'getuid', lambda: 997)
    monkeypatch.setattr(broker, 'protected', lambda p: json.dumps(cfg).encode()
                        if p == broker.CONFIG else raw if p.name == 'proof.json'
                        else contents[p.relative_to(broker.ROOT).as_posix()])
    return cfg, profile


@pytest.mark.parametrize('raw', [b'proof', b'{}', b'{"verdict":"PASS"}',
                                b'{"verdict":"PASS","cases":[]}'])
def test_manifest_hash_alone_never_admits_conversation(monkeypatch, raw):
    host_configuration(monkeypatch, raw)
    with pytest.raises(ValueError):
        broker.configuration()


def proof():
    import time
    from deploy.ai_pc.conversation_acceptance import CASES, EXPECTED, question, source_files, source_digest
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
            plan = EXPECTED[case[0]]
            for step in plan.get('steps', [plan]):
                parameters = {k: v for k, v in step.items() if k not in {'do', 'robot', 'waypoint'}}
                answer['steps'].append({'verb': step['do'], 'robot_id': step.get('robot'),
                    'place_id': step.get('waypoint'), 'parameters_json': json.dumps(parameters)})
        cases.append({'case': case[0], 'input': value.model_dump(),
                      'input_hash': value.digest, 'answer': answer})
    return {'schema': 'rosy.conversation-evaluation/1', 'verdict': 'PASS',
            'evaluation_owner': 'model_pc', 'source_commit': 'a'*40,
            'profile': profile.model_dump(), 'policy': source_policy('a'*40, profile),
            'suite_sha256': digest({'cases': CASES, 'expected': EXPECTED}),
            'source_manifest_sha256': source_digest({name: hashlib.sha256((broker.ROOT/name).read_bytes()).hexdigest()
                for name in source_files(broker.ROOT)}), 'evaluated_at': at, 'cases': cases}


def test_complete_protected_semantic_proof_is_admitted(monkeypatch):
    cfg, profile = host_configuration(monkeypatch, json.dumps(proof()).encode())
    assert broker.configuration() == (cfg, profile)


def test_semantic_proof_without_inference_source_closure_is_refused(monkeypatch):
    host_configuration(monkeypatch, json.dumps(proof()).encode(), include_source=False)
    with pytest.raises(ValueError):
        broker.configuration()


def test_semantic_suite_covers_every_exposed_control_verb():
    from typing import get_args
    from deploy.ai_pc import conversation_acceptance as acceptance
    from core_common.intent import interpret
    from rosy.decision.conversation.codec import SemanticStep
    plans = getattr(acceptance, 'EXPECTED', {'navigate': {'do': 'navigate',
                         'robot': 'rosy_40', 'waypoint': 'A'}})
    covered = {call.verb for plan in plans.values() for call in interpret(plan)}
    assert set(get_args(SemanticStep.model_fields['verb'].annotation)) <= covered


def test_prompt_examples_are_valid_typed_proposals():
    import re
    from deploy.ai_pc.deliberation_conversation import instruction
    from deploy.ai_pc.conversation_acceptance import CASES, question
    from rosy.decision.conversation.codec import semantic_answer
    text = instruction()
    for match in re.finditer(r'\{"kind":', text):
        value, _ = json.JSONDecoder().raw_decode(text[match.start():])
        semantic_answer(value, question(CASES[0], 1.))


def test_frozen_prior_turn_cases_include_accepted_and_unaccepted_context():
    from deploy.ai_pc.conversation_acceptance import CASES, question
    cases={case[0]:question(case,1000.) for case in CASES}
    for name in ('accepted_followup','unaccepted_followup','prior_chat','prior_status',
                 'prior_unknown','prior_withdrawn','prior_foreign','prior_map_changed'):
        assert len(cases[name].history)==1
        assert (cases[name].accepted_execution_context is not None)==(name=='accepted_followup')
    assert cases['prior_chat'].history[0].response


@pytest.mark.parametrize('change',['context','history','intent','order'])
def test_prior_turn_proof_cannot_omit_or_rewrite_frozen_context(monkeypatch,change):
    value=proof()
    row=next(r for r in value['cases'] if r['case']=='accepted_followup')
    if change=='context':row['input']['accepted_execution_context']=None
    elif change=='history':row['input']['history']=[]
    elif change=='intent':row['answer']['steps'][0]['robot_id']='rosy_41'
    else:value['cases'].reverse()
    host_configuration(monkeypatch,json.dumps(value).encode())
    with pytest.raises(ValueError):broker.configuration()


@pytest.mark.parametrize('path', ['deploy/ai_pc/deliberation_conversation.py',
    'deploy/ai_pc/deliberation_conversation_broker.py', 'deploy/ai_pc/conversation_acceptance.py',
    'operations/decision/src/rosy/decision/conversation/codec.py',
    'operations/decision/src/rosy/decision/__init__.py', 'deploy/site/requirements-fleet.txt'])
@pytest.mark.parametrize('change', ['omitted', 'changed'])
def test_semantic_proof_binds_inference_dependency_source(monkeypatch, path, change):
    host_configuration(monkeypatch, json.dumps(proof()).encode(),
                       **({'omit': path} if change == 'omitted' else {'mutation': path}))
    with pytest.raises(ValueError):
        broker.configuration()


@pytest.mark.parametrize('change', ['failed', 'partial', 'duplicate', 'kind', 'input',
                                   'input_type', 'hash', 'profile', 'profile_type', 'policy',
                                   'owner', 'stale', 'fact', 'command'])
def test_semantic_proof_tampering_is_rejected(monkeypatch, change):
    value = proof()
    if change == 'failed': value['verdict'] = 'FAIL'
    elif change == 'partial': value['cases'].pop()
    elif change == 'duplicate': value['cases'][1] = value['cases'][0]
    elif change == 'kind': value['cases'][1]['answer']['kind'] = 'CHAT'
    elif change == 'input': value['cases'][0]['input']['principal_id'] = 'other'
    elif change == 'input_type': value['cases'][0]['input']['schema_version'] = True
    elif change == 'hash': value['cases'][0]['input_hash'] = 'b'*64
    elif change == 'profile': value['profile']['revision'] = 'd728-other'
    elif change == 'profile_type': value['profile']['max_calls'] = True
    elif change == 'policy': value['policy']['authority'] = 'control'
    elif change == 'owner': value['evaluation_owner'] = 'ai_pc'
    elif change == 'stale': value['evaluated_at'] -= 8*86400
    elif change == 'fact': value['cases'][0]['answer']['response'] = '현재 로봇은 이동 완료 상태입니다.'
    elif change == 'command': value['cases'][2]['answer']['steps'][0]['verb'] = 'home'
    host_configuration(monkeypatch, json.dumps(value).encode())
    with pytest.raises(ValueError):
        broker.configuration()
