import copy
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'), str(ROOT / 'test')]
from registry import Registry
from rosy.contracts.learning import seal
from test_learning_artifact_contracts import policy
from test_dataset_store import dataset
from dataset_store import DatasetStore

TEST_KEY = b'test-key' * 4


def source(tmp_path, report=None):
    root = tmp_path / 'source'
    root.mkdir()
    payload = b'weights'
    file = root / 'weights.bin'
    file.write_bytes(payload)
    ref = {'path': file.name, 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
    doc = policy()
    dataset_root = tmp_path / 'dataset-source'
    manifest = dataset(dataset_root)
    DatasetStore(tmp_path / 'registry' / 'datasets').register(dataset_root)
    doc['dataset_revisions'] = [manifest['revision']]
    doc.update(files=[ref], normalization=ref, evaluations=[ref])
    if report is not None:
        blob = json.dumps(report).encode()
        (root / 'offline-report.json').write_bytes(blob)
        doc['evaluations'] = [{'path': 'offline-report.json', 'sha256': hashlib.sha256(blob).hexdigest(), 'bytes': len(blob)}]
    doc = seal(doc)
    (root / 'policy-artifact.json').write_text(json.dumps(doc))
    return root, doc


def rejected_report():
    return {'algorithm': 'lerobot-act', 'verdict': 'reject', 'reasons': ['does_not_beat_constant_target_baseline'],
            'mae_rad': .03, 'constant_baseline_mae_rad': .006, 'limit_violations': 0,
            'target_clusters_0_001_rad': 5, 'eval_frames': 12,
            'reloaded_prediction_verified': True, 'independent_task_success': 'unverified'}


def promotion(tmp_path, doc):
    root = tmp_path / 'evidence'
    root.mkdir()
    checks = []
    for kind in ['offline_eval', 'sim_eval', 'owner_contract', 'independent_task_outcome']:
        blob = json.dumps({'policy_revision': doc['revision'], 'kind': kind, 'verdict': 'pass'}).encode()
        (root / (kind + '.json')).write_bytes(blob)
        checks.append({'kind': kind, 'verdict': 'pass', 'report': {
            'path': kind + '.json', 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}})
    prom = seal({'schema': 'rosy.promotion-record/1', 'policy_revision': doc['revision'],
                 'from_stage': 'unregistered', 'to_stage': 'L0', 'checks': checks, 'authority': None})
    receipts = []
    for check in checks:
        payload = {'promotion_revision': prom['revision'], 'policy_revision': doc['revision'],
                   'kind': check['kind'], 'report_sha256': check['report']['sha256'], 'verdict': 'pass'}
        signature = hmac.new(TEST_KEY, json.dumps(payload, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
        receipts.append({'principal': 'test-verifier', 'payload': payload, 'signature': signature})
    return root, prom, receipts


def test_register_snapshot_survives_source_change_and_restart(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry')
    assert registry.register(root)['stage'] == 'unregistered'
    (root / 'weights.bin').write_bytes(b'changed')
    again = Registry(tmp_path / 'registry')
    assert again.show(doc['revision'])['stage'] == 'unregistered'
    assert len(again.history()) == 1
    with pytest.raises(ValueError, match='hash'):
        again.register(root)


def test_registration_is_idempotent(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry')
    registry.register(root); registry.register(root)
    assert len(registry.history()) == 1


def test_act_failed_report_cannot_claim_pass_and_is_durably_recorded(tmp_path):
    root, doc = source(tmp_path, rejected_report())
    registry = Registry(tmp_path / 'registry'); registry.register(root)
    result = registry.assess_act(doc['revision'])
    assert result['verdict'] == 'reject'
    assert result['reasons'] == ['does_not_beat_constant_target_baseline']
    assert Registry(tmp_path / 'registry').show(doc['revision'])['stage'] == 'unregistered'
    assert registry.history()[-1]['operation'] == 'assessment'
    assert registry.assess_act(doc['revision']) == result
    assert len(registry.history()) == 2


def test_snapshot_and_history_tamper_are_detected(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry'); registry.register(root)
    with sqlite3.connect(registry.root / 'registry.sqlite3') as db:
        db.execute("UPDATE events SET body='{}' WHERE sequence=1")
    with pytest.raises(ValueError, match='chain'):
        registry.history()


def test_promotion_needs_scoped_trusted_receipts_and_stage_cas(tmp_path):
    root, doc = source(tmp_path)
    evidence, prom, receipts = promotion(tmp_path, doc)
    registry = Registry(tmp_path / 'registry'); registry.register(root)
    with pytest.raises(ValueError, match='trust'):
        registry.promote(prom, evidence, receipts)
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(registry.root, trusted=trusted)
    altered = copy.deepcopy(receipts); altered[0]['payload']['report_sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='receipt'):
        registry.promote(prom, evidence, altered)
    assert registry.promote(prom, evidence, receipts)['stage'] == 'L0'
    with pytest.raises(ValueError, match='stage'):
        registry.promote(prom, evidence, receipts)
    assert len(registry.history()) == 2


def test_unsigned_pass_report_does_not_override_actual_act_rejection(tmp_path):
    root, doc = source(tmp_path, rejected_report())
    evidence, prom, receipts = promotion(tmp_path, doc)
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(tmp_path / 'registry', trusted=trusted); registry.register(root)
    with pytest.raises(ValueError, match='ACT'):
        registry.promote(prom, evidence, receipts)
    assert len(registry.history()) == 1


def test_snapshot_tamper_blocks_future_mutations(tmp_path):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry'); registry.register(root)
    (registry.root / 'artifacts' / doc['revision'] / 'weights.bin').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash'):
        registry.history()
    with pytest.raises(ValueError, match='hash'):
        registry.register(root)


def test_claimed_act_pass_is_recomputed_not_trusted(tmp_path):
    report = rejected_report(); report['verdict'] = 'offline_only'
    root, doc = source(tmp_path, report)
    registry = Registry(tmp_path / 'registry'); registry.register(root)
    with pytest.raises(ValueError, match='recomputed'):
        registry.assess_act(doc['revision'])
    assert len(registry.history()) == 1


def test_actual_failed_report_is_not_accepted_even_with_valid_receipt(tmp_path):
    root, doc = source(tmp_path)
    evidence, prom, receipts = promotion(tmp_path, doc)
    failed = json.dumps({'policy_revision': doc['revision'], 'kind': 'sim_eval', 'verdict': 'reject'}).encode()
    (evidence / 'sim_eval.json').write_bytes(failed)
    check = next(c for c in prom['checks'] if c['kind'] == 'sim_eval')
    check['report'].update(sha256=hashlib.sha256(failed).hexdigest(), bytes=len(failed))
    prom = seal(prom)
    for r in receipts:
        r['payload']['promotion_revision'] = prom['revision']
        if r['payload']['kind'] == 'sim_eval': r['payload']['report_sha256'] = check['report']['sha256']
        r['signature'] = hmac.new(TEST_KEY, json.dumps(r['payload'], sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(tmp_path / 'registry', trusted=trusted); registry.register(root)
    with pytest.raises(ValueError, match='actual report'):
        registry.promote(prom, evidence, receipts)
    assert len(registry.history()) == 1


def test_transaction_failure_leaves_no_registered_policy_and_snapshot_can_recover(tmp_path, monkeypatch):
    root, doc = source(tmp_path)
    registry = Registry(tmp_path / 'registry')
    def fail(*args): raise RuntimeError('simulated interruption before DB commit')
    with monkeypatch.context() as patch:
        patch.setattr(registry, '_append', fail)
        with pytest.raises(RuntimeError): registry.register(root)
    assert registry.history() == []
    assert registry.register(root)['stage'] == 'unregistered'
    assert len(registry.history()) == 1


def test_promotion_evidence_tamper_is_detected_after_restart(tmp_path):
    root, doc = source(tmp_path)
    evidence, prom, receipts = promotion(tmp_path, doc)
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(tmp_path / 'registry', trusted=trusted); registry.register(root)
    registry.promote(prom, evidence, receipts)
    (registry.root / 'evidence' / prom['revision'] / 'sim_eval.json').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash'):
        Registry(registry.root).show(doc['revision'])


def test_two_competing_promotions_commit_only_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    root, doc = source(tmp_path)
    evidence, prom, receipts = promotion(tmp_path, doc)
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(tmp_path / 'registry', trusted=trusted); registry.register(root)
    barrier = threading.Barrier(2)
    def attempt():
        other = Registry(registry.root, trusted=trusted)
        barrier.wait()
        try: return other.promote(prom, evidence, receipts)['stage']
        except ValueError as exc: return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(results) == ['L0', 'promotion current stage differs']
    assert len(registry.history()) == 2


def test_verifier_cannot_sign_checks_outside_its_installed_scope(tmp_path):
    root, doc = source(tmp_path)
    evidence, prom, receipts = promotion(tmp_path, doc)
    registry = Registry(tmp_path / 'registry', trusted={
        'test-verifier': {'key': TEST_KEY, 'kinds': {'offline_eval'}}})
    registry.register(root)
    with pytest.raises(ValueError, match='trust'):
        registry.promote(prom, evidence, receipts)
    assert len(registry.history()) == 1


@pytest.mark.parametrize('bad', ['signature', 'principal'])
def test_forged_signature_or_unknown_principal_cannot_promote(tmp_path, bad):
    root, doc = source(tmp_path)
    evidence, prom, receipts = promotion(tmp_path, doc)
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(tmp_path / 'registry', trusted=trusted); registry.register(root)
    receipts[0][bad] = 'f' * 64
    with pytest.raises(ValueError, match='receipt|trust'):
        registry.promote(prom, evidence, receipts)
    assert len(registry.history()) == 1


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, True])
def test_invalid_metric_does_not_create_assessment(tmp_path, value):
    report = rejected_report(); report['mae_rad'] = value
    root, doc = source(tmp_path, report)
    registry = Registry(tmp_path / 'registry'); registry.register(root)
    with pytest.raises(ValueError, match='metric'):
        registry.assess_act(doc['revision'])
    assert len(registry.history()) == 1


def test_renamed_act_report_cannot_bypass_rejection(tmp_path):
    root, doc = source(tmp_path, rejected_report())
    (root / 'offline-report.json').rename(root / 'renamed.json')
    doc['evaluations'][0]['path'] = 'renamed.json'
    doc = seal(doc); (root / 'policy-artifact.json').write_text(json.dumps(doc))
    evidence, prom, receipts = promotion(tmp_path, doc)
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(tmp_path / 'registry', trusted=trusted); registry.register(root)
    with pytest.raises(ValueError, match='ACT'):
        registry.promote(prom, evidence, receipts)


def test_missing_registered_dataset_blocks_promotion(tmp_path):
    root, doc = source(tmp_path)
    evidence, prom, receipts = promotion(tmp_path, doc)
    trusted = {'test-verifier': {'key': TEST_KEY, 'kinds': {c['kind'] for c in prom['checks']}}}
    registry = Registry(tmp_path / 'registry', trusted=trusted); registry.register(root)
    with sqlite3.connect(registry.root / 'datasets' / 'datasets.sqlite3') as db:
        db.execute('DELETE FROM datasets')
    with pytest.raises(ValueError, match='dataset'):
        registry.promote(prom, evidence, receipts)
