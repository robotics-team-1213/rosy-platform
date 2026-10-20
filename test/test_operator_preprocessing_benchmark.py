"""Opt-in fixed-model before/after measurements; no install, messages or devices."""
import hashlib
import json
import os
from pathlib import Path
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('ROSY_RUN_OPERATOR_MODEL_TESTS') != '1',
                               reason='opt-in Model PC fixed-model benchmark')


def test_real_fixed_model_preprocessing_baseline_or_candidate(tmp_path, monkeypatch):
    from core_common.protocol.assistant import AssistantFact
    from deploy.ai_pc import operator_broker as broker
    from deploy.ai_pc.operator_acceptance import CASES
    from rosy.decision.conversation.operator import OperatorInput, OperatorProfile, OperatorScope, checked_operator_answer
    from deploy.ai_pc.deliberation_ollama import loaded
    assert os.environ.get('ROSY_OPERATOR_EVALUATION_OWNER') == 'model_pc'
    source = os.environ['ROSY_OPERATOR_SOURCE_COMMIT']
    assert len(source) == 40
    profile = OperatorProfile()
    exchange = broker.exchange
    current = exchange('/api/ps', None, 5)
    assert all(m.get('name') == profile.model_id for m in current['models'])
    exchange('/api/chat', {'model':profile.model_id, 'messages':[], 'stream':False,
             'keep_alive':'10m', 'options':{'num_ctx':8192}}, 90)
    loaded(exchange('/api/ps', None, 5))
    measured = []

    def capture(path, body, remaining):
        value = exchange(path, body, remaining)
        if path == '/api/chat':
            measured.append((value['prompt_eval_count'], value['eval_count']))
        return value

    monkeypatch.setattr(broker, 'exchange', capture)
    results = []
    for name, text, kinds in CASES[:19]:
        q = OperatorInput(scope=OperatorScope(principal_id='synthetic-evaluator', conversation_id='bench-'+name),
            request_id=name, question=text, locale='en-US' if name.startswith('en-') else 'ko-KR',
            observed_at=time.time(), facts=[AssistantFact(ref='robot:r1', text='r1: 온라인, 모드 IDLE',
                                                        observed_at=time.time())])
        started = time.monotonic()
        answer = checked_operator_answer(broker.execute(q, profile, 30), q)
        elapsed = (time.monotonic()-started)*1000
        inputs, outputs = measured[-1]
        results.append(dict(name=name, input_hash=q.digest, kind=answer.kind,
            passed=answer.kind in kinds, input_tokens=inputs, output_tokens=outputs, elapsed_ms=elapsed))
    assert len(measured) == 19
    receipt = dict(source_commit=source, profile=profile.model_dump(), results=results)
    output = tmp_path/'preprocessing-benchmark.json'
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PREPROCESSING_BENCHMARK '+json.dumps(dict(path=str(output), source_commit=source,
        sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
        input_tokens=sum(r['input_tokens'] for r in results),
        passed=sum(r['passed'] for r in results), cases=len(results))))
    assert all(r['passed'] for r in results), json.dumps(results)


def test_real_discord_preprocessing_profile_has_independent_semantic_proof(tmp_path, monkeypatch):
    from deploy.ai_pc import conversation_acceptance as acceptance
    from deploy.ai_pc import deliberation_conversation as broker
    from deploy.ai_pc.deliberation_ollama import loaded
    from rosy.decision.conversation.codec import Profile, digest, semantic_answer, source_policy
    from rosy.decision.conversation.preprocessing import DISCORD_REVISION
    from core_common.intent import interpret
    assert os.environ.get('ROSY_OPERATOR_EVALUATION_OWNER') == 'model_pc'
    source = os.environ['ROSY_OPERATOR_SOURCE_COMMIT']
    profile = Profile(revision=DISCORD_REVISION)
    exchange = broker.exchange
    current = exchange('/api/ps', None, 5)
    assert all(m.get('name') == profile.model_id for m in current['models'])
    exchange('/api/chat', {'model':profile.model_id, 'messages':[], 'stream':False,
        'keep_alive':'10m', 'options':{'num_ctx':8192}}, 90)
    loaded(exchange('/api/ps', None, 5))
    captured = []
    def capture(path, body, remaining):
        value = exchange(path, body, remaining)
        if path == '/api/chat':
            captured.append(value)
        return value
    monkeypatch.setattr(broker, 'exchange', capture)
    at, rows, failures, measurements = time.time(), [], [], []
    cases, expected = acceptance.cases_for(profile), acceptance.expected_for(profile)
    for case in cases:
        q = acceptance.question(case, at)
        captured_before = len(captured)
        started = time.monotonic()
        try:
            output = broker.execute(q, profile, 30)
            assert len(captured) == captured_before+1
            raw = json.loads(captured[-1]['message']['content'])
            answer = semantic_answer(raw, q, preprocessing=True)
            passed = answer.kind in case[2]
            if answer.kind == 'CONTROL':
                passed = passed and interpret(answer.intent) == interpret(expected[case[0]])
            if case[0] == 'scope-status':
                passed = passed and answer.evidence_refs == ['robot:rosy_41']
            assert output['kind'] == answer.kind
            if not passed:
                failures.append(dict(case=case[0], kind=answer.kind))
            measurements.append(dict(case=case[0], elapsed_ms=(time.monotonic()-started)*1000,
                                     usage=output['usage']))
        except Exception as exc:
            failures.append(dict(case=case[0], error=type(exc).__name__))
            raw = json.loads(captured[-1]['message']['content']) if len(captured) > captured_before else {}
        rows.append(dict(case=case[0], input=q.model_dump(), input_hash=q.digest, answer=raw))
    root = Path(__file__).resolve().parents[1]
    files = {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in acceptance.source_files(root)}
    proof = dict(schema='rosy.conversation-evaluation/1', verdict='PASS' if not failures else 'FAIL',
        evaluation_owner='model_pc', source_commit=source, profile=profile.model_dump(),
        policy=source_policy(source, profile), suite_sha256=digest(dict(cases=cases, expected=expected)),
        source_manifest_sha256=acceptance.source_digest(files), evaluated_at=at, cases=rows)
    output = tmp_path/'discord-preprocessing-proof.json'
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print('DISCORD_PREPROCESSING_PROOF '+json.dumps(dict(path=str(output), source_commit=source,
        sha256=hashlib.sha256(output.read_bytes()).hexdigest(), cases=len(cases), failures=failures,
        input_tokens=sum(row['usage']['input_tokens'] for row in measurements))))
    assert not failures, json.dumps(failures)
    acceptance.validate(proof, dict(source_commit=source, policy=proof['policy'], files=files,
        semantic_evidence_sha256=hashlib.sha256(output.read_bytes()).hexdigest()), profile)
