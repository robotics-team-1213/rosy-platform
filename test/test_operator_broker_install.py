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


def test_source_inventory_hash_is_not_limited_like_an_inference_packet():
    from deploy.ai_pc.operator_acceptance import evaluate, validate_receipt, CASES
    from deploy.ai_pc.conversation_acceptance import source_digest
    from rosy.decision.conversation.operator import OperatorProfile
    files = {f'contracts/source_module_{n:04d}.py':'b'*64 for n in range(400)}
    assert len(json.dumps(files)) > 16384
    def execute(question, *_):
        name, _, kinds = next(case for case in CASES if case[1] == question.question)
        reference = 'robot:r2' if name in {'scope-status','en-scope-status'} else 'robot:r1'
        return dict(kind=kinds[0], response='Classified', evidence_refs=[reference] if kinds[0] == 'STATUS' else [])
    receipt = evaluate(execute, source_commit='a'*40, files=files)
    assert receipt['source_manifest_sha256'] == source_digest(files) and receipt['verdict'] == 'PASS'
    validate_receipt(receipt, dict(source_commit='a'*40, files=files), OperatorProfile())


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


def test_signed_site_stacks_select_optional_operator_config_from_fleet_only():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for name in ['compose.yaml', 'compose.pairing.yaml']:
        text = (root/'deploy/site'/name).read_text()
        fleet = text.split('  fleet:\n', 1)[1].split('  vision:\n', 1)[0]
        assert '--assistant-config-optional\n      - /run/rosy-deliberation/operator.json' in fleet
        assert text.count('/run/rosy-deliberation/operator.json') == 1


@pytest.mark.parametrize('check', [True, False])
def test_operator_installer_check_writes_nothing_and_failed_readback_rolls_back(tmp_path, monkeypatch, check):
    import hashlib
    import os
    from types import SimpleNamespace
    from deploy.site import install_operator_broker as m
    from deploy.ai_pc import conversation_acceptance
    from rosy.decision.conversation.codec import digest
    base = m.base
    monkeypatch.setattr(base, 'REVIEWED', tmp_path)
    monkeypatch.setattr(base, 'VERSIONS', tmp_path/'versions')
    target = base.VERSIONS/('a'*40); target.mkdir(parents=True)
    (target/'source.py').write_bytes(b'reviewed source')
    installed, receipt = proof()
    installed['files'] = {'source.py':hashlib.sha256(b'reviewed source').hexdigest()}
    receipt['source_manifest_sha256'] = digest(installed['files'])
    config = tmp_path/'conversation.json'; config.write_text(json.dumps(installed))
    evidence = tmp_path/'proof.json'; evidence.write_text(json.dumps(receipt))
    broker = tmp_path/'broker'; broker.write_bytes(base.broker_wrapper(target))
    monkeypatch.setattr(base, 'CONFIG', config); monkeypatch.setattr(base, 'BROKER', broker)
    monkeypatch.setattr(m, 'CONFIG', tmp_path/'operator.json')
    monkeypatch.setattr(base, 'require_admin', lambda:None)
    monkeypatch.setattr(base, 'trusted_directory', lambda _:None)
    monkeypatch.setattr(base, 'protected', lambda p:p.read_bytes())
    monkeypatch.setattr(conversation_acceptance, 'source_files', lambda _:['source.py'])
    monkeypatch.setattr(m.pwd, 'getpwnam', lambda _:SimpleNamespace(pw_name='test', pw_gid=os.getgid()))
    writes = []
    def replace(path, data, mode, gid, allowed):
        writes.append(path); path.write_bytes(data)
    monkeypatch.setattr(base, 'replace_managed', replace)
    calls = []
    def run(*args, **_):
        code = args[args.index('-c')+1]; calls.append(code)
        assert '/api/chat' not in code
        if 'operator_broker' in code: raise ValueError('READBACK_FAILED')
    monkeypatch.setattr(base, 'run', run)
    args = [str(evidence), '--proof-sha256', base.sha(evidence.read_bytes()),
            '--conversation-config-sha256', base.sha(config.read_bytes())]
    if check:
        assert m.main(args+['--check']) == 0
        assert not writes and len(calls) == 1
    else:
        with pytest.raises(ValueError, match='READBACK_FAILED'): m.main(args)
        assert not m.CONFIG.exists()
    assert json.loads(config.read_text()) == installed and broker.read_bytes() == base.broker_wrapper(target)
