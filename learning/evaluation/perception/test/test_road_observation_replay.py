"""Truth-free artifact replay; synthetic snapshots do not prove physical calibration."""
import hashlib
import importlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
for holder in ('learning/registry/perception', 'learning/evaluation/perception'):
    sys.path.insert(0, str(ROOT / holder))

import store
from test_road_fitness import _replay_model, _snapshots


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def bundle(tmp_path, monkeypatch, *, real_runtime=False, **changes):
    replay = importlib.import_module('road_observation_replay')
    model_folder = tmp_path / 'model'
    model_folder.mkdir()
    model = _replay_model(model_folder, real_runtime=real_runtime)
    monkeypatch.setattr(replay.LaneSegModel, 'open', lambda *args: model)
    folder = tmp_path / 'inputs'
    folder.mkdir()
    raw = cv2.imencode('.png', np.zeros((12, 12, 3), np.uint8))[1].tobytes()
    (folder / 'frame.png').write_bytes(raw)
    image, anchor = _snapshots()
    def snapshot(value):
        doc = asdict(value)
        doc['received_at'] = value.received_at.isoformat()
        return doc
    doc = {'schema': 'rosy.perception.road-observation-input/1',
           'model_manifest_sha256': sha((model_folder / 'model_manifest.json').read_bytes()),
           'image': 'frame.png', 'image_sha256': sha(raw),
           'image_snapshot': snapshot(image), 'anchor_snapshot': snapshot(anchor),
           'seed_pixels': [[10, 2]], 'now_ns': 1050}
    doc.update(changes)
    (folder / 'manifest.json').write_text(json.dumps(doc))
    fixed = folder.parent / store.content_sha(folder)
    folder.rename(fixed)
    return replay, model, fixed, doc


@pytest.mark.parametrize('real_runtime', [False, True])
def test_artifact_roundtrip_binds_model_image_and_snapshot_without_truth(tmp_path, monkeypatch, real_runtime):
    replay, model, inputs, doc = bundle(tmp_path, monkeypatch, real_runtime=real_runtime)
    out = tmp_path / 'observation.json'
    args = SimpleNamespace(model=str(model.manifest.folder), inputs=str(inputs), max_age_ns=100, out=str(out))
    assert replay.execute(args) == 0
    decoded = replay.read_artifact(out, sha(out.read_bytes()))
    assert decoded['bindings']['inputs_sha256'] == inputs.name
    assert decoded['bindings']['model_manifest_sha256'] == doc['model_manifest_sha256']
    assert decoded['bindings']['image_sha256'] == doc['image_sha256']
    observed = decoded['observation']
    assert observed['model_revision'] == model.model_revision
    assert observed['fitness_verdict'] == 'HOLD'
    assert observed['image_snapshot_id'] == doc['image_snapshot']['snapshot_id']
    assert np.all(np.asarray(observed['labels'])[:2] == 255)
    assert observed['preprocessing']['seed_pixels'] == [[5, 1]]
    assert observed['region_reason'] == 'ok'
    assert decoded['inputs'] == json.loads(json.dumps(doc))
    with pytest.raises(ValueError, match='hash'):
        replay.read_artifact(out, '0' * 64)
    before = out.read_bytes()
    assert replay.execute(args) == 2
    assert out.read_bytes() == before


@pytest.mark.parametrize('changes', [
    {'model_manifest_sha256': '0' * 64}, {'image_sha256': '0' * 64},
    {'image': '../outside.png'}, {'image': '\\frame.png'}, {'image': 'C:frame.png'},
    {'road_truth': [[1]]}, {'destination': 'left'},
    {'seed_pixels': [[True, 2]]}, {'now_ns': True}])
def test_input_mismatch_or_privileged_field_never_writes_output(tmp_path, monkeypatch, changes):
    replay, model, inputs, _ = bundle(tmp_path, monkeypatch, **changes)
    out = tmp_path / 'observation.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=inputs,
                                          max_age_ns=100, out=out)) == 2
    assert not out.exists()


@pytest.mark.parametrize('which', ['image_snapshot', 'anchor_snapshot'])
def test_invalid_snapshot_preserves_abstention_in_artifact(tmp_path, monkeypatch, which):
    replay, model, inputs, doc = bundle(tmp_path, monkeypatch)
    doc[which]['validity'] = 'INVALID'
    (inputs / 'manifest.json').write_text(json.dumps(doc))
    changed = inputs.parent / store.content_sha(inputs)
    inputs.rename(changed)
    out = tmp_path / 'out.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=changed,
                                          max_age_ns=100, out=out)) == 0
    observed = replay.read_artifact(out, sha(out.read_bytes()))['observation']
    assert observed['current_region'] is None
    assert (observed['labels'] is None) == (which == 'image_snapshot')
    assert (observed['road_surface'] is None) == (which == 'image_snapshot')


@pytest.mark.parametrize('target', ['model', 'inputs'])
def test_files_changed_during_inference_do_not_publish(tmp_path, monkeypatch, target):
    replay, model, inputs, _ = bundle(tmp_path, monkeypatch)
    original = model._session.run
    def run(image):
        path = model.manifest.folder / 'model.onnx' if target == 'model' else inputs / 'frame.png'
        path.write_bytes(b'changed')
        return original(image)
    model._session.run = run
    out = tmp_path / 'out.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=inputs,
                                          max_age_ns=100, out=out)) == 2
    assert not out.exists()


def test_readback_refuses_mask_shape_even_with_matching_file_hash(tmp_path, monkeypatch):
    replay, model, inputs, _ = bundle(tmp_path, monkeypatch)
    out = tmp_path / 'out.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=inputs,
                                          max_age_ns=100, out=out)) == 0
    doc = json.loads(out.read_bytes())
    doc['observation']['road_surface'] = [[True]]
    out.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='mask'):
        replay.read_artifact(out, sha(out.read_bytes()))


def test_input_directory_symlink_does_not_bypass_fixed_input_gate(tmp_path, monkeypatch):
    replay, model, inputs, _ = bundle(tmp_path, monkeypatch)
    alias = tmp_path / 'alias'
    alias.symlink_to(inputs, target_is_directory=True)
    out = tmp_path / 'out.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=alias,
                                          max_age_ns=100, out=out)) == 2
    assert not out.exists()


def test_oversized_prediction_is_rejected_before_session_open(tmp_path, monkeypatch):
    replay, model, inputs, doc = bundle(tmp_path, monkeypatch)
    manifest_path = model.manifest.folder / 'model_manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    manifest['input'].pop('crop')
    manifest['input']['shape'] = [1, 3, 1001, 1001]
    manifest_path.write_text(json.dumps(manifest))
    doc['model_manifest_sha256'] = sha(manifest_path.read_bytes())
    (inputs / 'manifest.json').write_text(json.dumps(doc))
    changed = inputs.parent / store.content_sha(inputs)
    inputs.rename(changed)
    def never_open(*args):
        pytest.fail('oversized input reached session initialization')
    monkeypatch.setattr(replay.LaneSegModel, 'open', never_open)
    with pytest.raises(ValueError, match='oversized'):
        replay.run(model.manifest.folder, inputs=changed, max_age_ns=100)


@pytest.mark.parametrize('target', ['hash', 'snapshot', 'abstention'])
def test_readback_rejects_inconsistent_lineage_with_matching_hash(tmp_path, monkeypatch, target):
    replay, model, inputs, _ = bundle(tmp_path, monkeypatch)
    out = tmp_path / 'out.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=inputs,
                                          max_age_ns=100, out=out)) == 0
    doc = json.loads(out.read_bytes())
    if target == 'hash':
        doc['bindings']['image_sha256'] = '0' * 64
    elif target == 'snapshot':
        doc['observation']['image_snapshot_id'] = 'other'
    else:
        doc['observation']['input_errors'] = ['anchor_invalid']
    out.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        replay.read_artifact(out, sha(out.read_bytes()))


@pytest.mark.parametrize('target', ['image_invalid', 'anchor_invalid', 'calibration', 'clock',
    'errors', 'region', 'reason', 'mapped_seeds', 'rows', 'crop_labels', 'latency', 'max_age',
    'digest', 'model_revision', 'camera_profile', 'valid_abstention'])
def test_readback_recomputes_validity_and_region_even_when_hash_matches(tmp_path, monkeypatch, target):
    replay, model, inputs, _ = bundle(tmp_path, monkeypatch)
    out = tmp_path / 'out.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=inputs,
                                          max_age_ns=100, out=out)) == 0
    doc = json.loads(out.read_bytes())
    observed = doc['observation']
    if target in ('image_invalid', 'anchor_invalid'):
        doc['inputs'][target.split('_')[0] + '_snapshot']['validity'] = 'INVALID'
    elif target == 'calibration':
        doc['inputs']['anchor_snapshot']['calibration_revision'] = 'other'
    elif target == 'clock':
        doc['inputs']['now_ns'] = 1200
    elif target == 'errors':
        observed.update(input_errors=['invented_error'], current_region=None, region_reason='invalid_inputs')
    elif target == 'region':
        observed['current_region'] = np.zeros_like(observed['current_region'], dtype=bool).tolist()
    elif target == 'reason':
        observed['region_reason'] = 'no_anchor'
    elif target == 'mapped_seeds':
        observed['preprocessing']['seed_pixels'] = [[0, 0]]
    elif target == 'rows':
        observed['preprocessing']['predicted_rows'] = [0, 6]
    elif target == 'crop_labels':
        observed['labels'][0][0] = 0
    elif target == 'latency':
        observed['infer_latency_ms'] = -1
    elif target == 'max_age':
        doc['bindings']['max_age_ns'] = True
    elif target == 'digest':
        doc['bindings']['inputs_sha256'] = 'unverified'
    elif target == 'model_revision':
        observed['model_revision'] = '../other'
    elif target == 'camera_profile':
        observed['camera_profile_revision'] = ''
    else:
        observed.update(labels=None, road_surface=None, current_region=None,
                        region_reason='invalid_inputs', infer_latency_ms=None)
    out.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        replay.read_artifact(out, sha(out.read_bytes()))


def test_backend_failure_is_diagnostic_exit_two_without_artifact(tmp_path, monkeypatch):
    replay, model, inputs, _ = bundle(tmp_path, monkeypatch)
    def fail(image):
        raise RuntimeError('backend execution failed')
    model._session.run = fail
    out = tmp_path / 'out.json'
    assert replay.execute(SimpleNamespace(model=model.manifest.folder, inputs=inputs,
                                          max_age_ns=100, out=out)) == 2
    assert not out.exists()
