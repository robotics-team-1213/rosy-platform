"""Operator admission is separate from Discord; no host changes or inference."""
import json
import time

import pytest


def proof():
    from deploy.ai_pc.operator_acceptance import CASES
    from rosy.decision.conversation.operator import OperatorProfile
    from rosy.decision.conversation.codec import digest
    files = {'source.py':'b'*64}
    receipt = dict(schema='rosy.operator-evaluation/1', evaluation_owner='model_pc', verdict='PASS',
        source_commit='a'*40, profile=OperatorProfile().model_dump(), source_manifest_sha256=digest(files),
        evaluated_at=time.time()-1, suite_sha256=digest(CASES),
        cases=[dict(name=n, passed=True) for n, _, _ in CASES])
    return dict(source_commit='a'*40, files=files), receipt


def test_multilingual_receipt_cannot_reuse_old_korean_only_cases():
    from deploy.ai_pc.operator_acceptance import CASES, validate_receipt
    from rosy.decision.conversation.operator import OperatorProfile
    assert any('en-' in name for name, _, _ in CASES)
    assert any('negated' in name for name, _, _ in CASES)
    cfg, receipt = proof()
    validate_receipt(receipt, cfg, OperatorProfile())
    for field in ['evaluated_at', 'suite_sha256']:
        changed = {k:v for k,v in receipt.items() if k != field}
        with pytest.raises(ValueError): validate_receipt(changed, cfg, OperatorProfile())


def test_operator_install_preparation_binds_existing_snapshot_and_expiry():
    from deploy.site.install_operator_broker import prepare
    from rosy.decision.conversation.codec import digest
    import hashlib
    cfg, receipt = proof()
    raw = json.dumps(receipt).encode()
    result = prepare(cfg, raw, hashlib.sha256(raw).hexdigest())
    assert result['source_commit'] == cfg['source_commit']
    assert cfg['files'].items() <= result['files'].items()
    assert result['valid_until'] == receipt['evaluated_at']+7*86400
    for changes in [dict(source_commit='c'*40), dict(verdict='FAIL'), dict(evaluated_at=1.),
                    dict(evaluated_at=time.time()+600), dict(evaluation_owner='ai_pc')]:
        wrong = json.dumps(receipt | changes).encode()
        with pytest.raises(ValueError): prepare(cfg, wrong, hashlib.sha256(wrong).hexdigest())
    with pytest.raises(ValueError): prepare(cfg, raw, '0'*64)
