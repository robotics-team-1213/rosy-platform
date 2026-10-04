import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/training/pinky'), str(ROOT / 'learning/registry/policy/test')]
from test_comparison_job import native_job
from artifact_export import export
import artifact_export
from registry import Registry
from dataset_store import DatasetStore
from test_registry import promotion, TEST_KEY


def reseal_file_index(root, path):
    index = json.loads((root / 'files.json').read_text())
    index[path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
    (root / 'files.json').write_text(json.dumps(index))


def test_actual_model_export_keeps_unknowns_and_bound_rejection(tmp_path):
    _, job = native_job(tmp_path)
    doc = export(job, tmp_path / 'artifact', model='tiny_cnn')
    assert doc['profile'] == 'pinky_base_velocity_v1'
    assert doc['cameras'][0]['calibration_sha256'] is None and doc['camera_profile_revision'] is None
    assert doc['action']['semantics'] == 'base_velocity_candidate'
    store = DatasetStore(tmp_path / 'registry/datasets')
    config = json.loads((job / 'config.json').read_text())
    for root in config['train_roots'] + [config['eval_root']]:
        store.register(root)
    registry = Registry(tmp_path / 'registry', trusted={
        'test-verifier': {'key': TEST_KEY, 'kinds': {'offline_eval', 'sim_eval', 'owner_contract', 'independent_task_outcome'}}})
    registry.register(tmp_path / 'artifact')
    result = registry.assess_pinky(doc['revision'])
    assert result['verdict'] == 'reject'
    assert registry.assess_pinky(doc['revision']) == result
    assert len(registry.history()) == 2
    evidence, claim, receipts = promotion(tmp_path, doc)
    with pytest.raises(ValueError, match='bound Pinky offline evaluation rejected'):
        registry.promote(claim, evidence, receipts)
    assert Registry(tmp_path / 'registry').show(doc['revision'])['stage'] == 'unregistered'


def test_hash_consistent_changed_eval_truth_is_rejected(tmp_path):
    _, job = native_job(tmp_path)
    path = job / 'evaluation-predictions.npz'
    with np.load(path, allow_pickle=False) as arrays:
        copied = {key: arrays[key].copy() for key in arrays.files}
    copied['truth'][:, 0] += .01
    np.savez(path, **copied); reseal_file_index(job, path)
    with pytest.raises(ValueError, match='evaluation truth'):
        export(job, tmp_path / 'artifact', model='tiny_cnn')
    assert not (tmp_path / 'artifact').exists()


def test_unknown_model_does_not_make_output(tmp_path):
    with pytest.raises(ValueError, match='model'):
        export(tmp_path / 'missing', tmp_path / 'artifact', model='constant')
    assert not (tmp_path / 'artifact').exists()


def test_hash_consistent_changed_weights_cannot_use_old_prediction_report(tmp_path):
    torch = pytest.importorskip('torch')
    _, job = native_job(tmp_path)
    path = job / 'tiny_cnn.pt'
    state = torch.load(path, weights_only=True)
    state['8.bias'] += 1.
    torch.save(state, path); reseal_file_index(job, path)
    with pytest.raises(ValueError, match='model prediction'):
        export(job, tmp_path / 'artifact', model='tiny_cnn')
    assert not (tmp_path / 'artifact').exists()


def test_cached_pass_cannot_bypass_fresh_raw_failure(tmp_path, monkeypatch):
    _, job = native_job(tmp_path)
    def rejected(_):
        raise ValueError('fresh raw derivation rejected')
    monkeypatch.setattr(artifact_export, 'verify', rejected, raising=False)
    with pytest.raises(ValueError, match='fresh raw derivation'):
        export(job, tmp_path / 'artifact', model='tiny_cnn')
    assert not (tmp_path / 'artifact').exists()
