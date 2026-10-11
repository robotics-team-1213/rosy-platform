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


def bundle(tmp_path, monkeypatch, **changes):
    replay = importlib.import_module('road_observation_replay')
    model_folder = tmp_path / 'model'
    model_folder.mkdir()
    model = _replay_model(model_folder)
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


def test_artifact_roundtrip_binds_model_image_and_snapshot_without_truth(tmp_path, monkeypatch):
    replay, model, inputs, doc = bundle(tmp_path, monkeypatch)
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
    {'image': '../outside.png'}, {'road_truth': [[1]]}, {'destination': 'left'},
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
