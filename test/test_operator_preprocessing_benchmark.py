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
