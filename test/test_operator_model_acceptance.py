"""Opt-in real fixed-model evaluation on Model PC; no deployment or device writes."""
import hashlib
import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('ROSY_RUN_OPERATOR_MODEL_TESTS') != '1',
                               reason='opt-in real Model PC inference')


def test_real_operator_model_accepts_korean_and_english(tmp_path):
    from deploy.ai_pc.operator_acceptance import evaluate, validate_receipt, source_files
    from deploy.ai_pc.operator_broker import execute
    from deploy.ai_pc.deliberation_ollama import exchange, loaded
    from rosy.decision.conversation.operator import OperatorProfile
    assert os.environ.get('ROSY_OPERATOR_EVALUATION_OWNER') == 'model_pc'
    source = os.environ['ROSY_OPERATOR_SOURCE_COMMIT']
    assert len(source) == 40
    profile = OperatorProfile()
    current = exchange('/api/ps', None, 5)
    assert all(m.get('name') == profile.model_id for m in current['models']), 'Model PC must be idle or use the fixed model'
    # Explicit opt-in may load the existing fixed local model; never download or change its digest.
    exchange('/api/chat', {'model':profile.model_id, 'messages':[], 'stream':False,
                         'keep_alive':'10m', 'options':{'num_ctx':8192}}, 90)
    loaded(exchange('/api/ps', None, 5))
    root = Path(__file__).resolve().parents[1]
    files = {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in source_files(root)}
    receipt = evaluate(execute, source_commit=source, files=files)
    output = tmp_path/'operator-model-evaluation.json'
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    print('OPERATOR_MODEL_RESULT '+json.dumps({'source_commit':source, 'cases':receipt['cases'],
        'verdict':receipt['verdict'], 'receipt_path':str(output),
        'receipt_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
    assert receipt['verdict'] == 'PASS', json.dumps(receipt['cases'])
    validate_receipt(receipt, dict(source_commit=source, files=files), profile)
