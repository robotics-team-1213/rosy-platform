"""D-682 frozen object replay; synthetic reviews/backends do not establish accuracy."""
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[4]
for holder in ('learning/curation/perception', 'learning/registry/perception',
               'learning/evaluation/perception', 'middleware/perception', 'contracts/foundation',
               'middleware/perception/test', 'test/learning/perception', 'tools/perception'):
    sys.path.insert(0, str(ROOT / holder))

import object_fitness_replay as replay
import review_evidence as evidence
import review_eval_bootstrap as bootstrap
import store
from test_object_eval_publication import fixture
from test_learned_detector import model_dir, FakeSession
from control.sensing.perception.learned.detector import ObjectDetModel
from control.sensing.perception.learned.manifest import load_manifest
from core_common.observation import ObservationSnapshot, SnapshotValidity


def seal(folder):
    target = folder.parent / store.content_sha(folder)
    folder.rename(target)
    return target


def bundle(tmp_path, monkeypatch):
    registry, review, _ = fixture(tmp_path, monkeypatch)
    published = bootstrap.publish(registry.root, review.state, 'objects', tmp_path / 'scratch', target='objects')
    truth = Path(published['path'])
    frame = store.read_fixed_manifest(truth)['frames'][0]
    model_folder = model_dir(tmp_path)
    raw = json.loads((model_folder / 'model_manifest.json').read_bytes())
    train = registry.datasets_dir / 'train' / 'stage'
    train.mkdir(parents=True)
    image_raw = cv2.imencode('.png', np.ones((24, 32, 3), np.uint8))[1].tobytes()
    (train / 'image.png').write_bytes(image_raw)
    (train / 'manifest.json').write_bytes(evidence.encoded(dict(schema='rosy.perception.dataset/1',
        purpose='train', classes=raw['output']['classes'], frames=[dict(session='train-session',
        capture_group='train-group', image='image.png', image_sha256=evidence.sha(image_raw))])))
    train = seal(train)
    raw['dataset'] = dict(repo='store:train', revision=train.name)
    (model_folder / 'model_manifest.json').write_bytes(evidence.encoded(raw))
    model = ObjectDetModel(load_manifest(model_folder), FakeSession(boxes=[(50, 58, 100, 100, 5, .9)]))
    opened = []
    def open_fixed(folder, *, conf, iou):
        opened.append(folder)
        model._conf, model._iou = conf, iou
        return model
    monkeypatch.setattr(replay.ObjectDetModel, 'open', open_fixed)
    image = ObservationSnapshot('image-1', 'camera', 1000, datetime.now(timezone.utc),
                                'front', 'cal-1', ('capture',), SnapshotValidity.VALID)
    snapshot = asdict(image)
    snapshot.update(received_at=image.received_at.isoformat(), validity=image.validity.value)
    inputs = tmp_path / 'inputs' / 'stage'
    inputs.mkdir(parents=True)
    doc = dict(schema='rosy.perception.object-inputs/1', model_revision=raw['model_revision'],
        model_manifest_sha256=evidence.sha((model_folder / 'model_manifest.json').read_bytes()),
        eval_sha256=truth.name, preprocessing_sha256=evidence.sha(evidence.encoded(raw['input'])),
        training_refs=[f'train@{train.name}'], match_iou=.5, small_area_fraction=.2,
        detector_confidence=.25, detector_nms_iou=.5,
        frames=[dict(identity=frame['identity'], image_sha256=frame['image_sha256'], domain='real',
                     conditions=['occlusion'], now_ns=1050, image_snapshot=snapshot)])
    (inputs / 'manifest.json').write_bytes(evidence.encoded(doc))
    return model_folder, registry, truth, seal(inputs), model, opened


def run(bundle):
    model, registry, truth, inputs, _, _ = bundle
    return replay.run(model, store_root=registry.root, eval_dir=truth, inputs=inputs, max_age_ns=100)


def modify_inputs(bundle, mutator):
    path = bundle[3]
    stage = path.parent / 'changed'
    path.rename(stage)
    doc = json.loads((stage / 'manifest.json').read_bytes())
    mutator(doc)
    (stage / 'manifest.json').write_bytes(evidence.encoded(doc))
    return (*bundle[:3], seal(stage), *bundle[4:])


def test_sealed_object_truth_runs_existing_detector_and_remains_hold(tmp_path, monkeypatch):
    data = bundle(tmp_path, monkeypatch)
    report = run(data)
    assert report['fitness_verdict'] == 'HOLD'
    assert report['frames'][0]['classes']['person']['recall'] == 1
    assert report['frames'][0]['classes']['person']['occluded_recall'] == 1
    assert report['summary']['domains']['simulation']['frames'] == 0
    assert report['bindings']['declared_training_disjoint'] is True
    assert len(data[5]) == 1


@pytest.mark.parametrize('key,value', [('model_revision', 'wrong'), ('eval_sha256', 'a' * 64),
    ('model_manifest_sha256', 'b' * 64), ('preprocessing_sha256', 'c' * 64),
    ('detector_confidence', True), ('detector_nms_iou', 0), ('match_iou', 0),
    ('small_area_fraction', 2), ('training_refs', [])])
def test_fixed_bindings_and_parameters_refuse_before_model(tmp_path, monkeypatch, key, value):
    data = bundle(tmp_path, monkeypatch)
    changed = modify_inputs(data, lambda doc: doc.update({key: value}))
    with pytest.raises(ValueError):
        run(changed)
    assert data[5] == []


def test_observed_image_identity_mismatch_is_refused(tmp_path, monkeypatch):
    data = bundle(tmp_path, monkeypatch)
    changed = modify_inputs(data, lambda doc: doc['frames'][0].update(image_sha256='f' * 64))
    with pytest.raises(ValueError, match='image'):
        run(changed)
    assert data[5] == []


def test_eval_reservation_drift_is_refused_before_model(tmp_path, monkeypatch):
    data = bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(store.Store, 'eval_reservations', lambda self: {})
    with pytest.raises(ValueError, match='reservation'):
        run(data)
    assert data[5] == []


def test_artifact_change_during_inference_never_returns_report(tmp_path, monkeypatch):
    data = bundle(tmp_path, monkeypatch)
    original = data[4].infer
    def mutate(bgr):
        result = original(bgr)
        (data[3] / 'unexpected.txt').write_text('changed')
        return result
    monkeypatch.setattr(data[4], 'infer', mutate)
    with pytest.raises(ValueError):
        run(data)


def test_cli_works_without_robot_config_and_refuses_output_overwrite(tmp_path, monkeypatch):
    import rosy_ml
    data = bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(rosy_ml, 'load_config', lambda *a, **k: pytest.fail('robot config read'))
    output = tmp_path / 'report.json'
    args = ['object-fitness', str(data[0]), '--store', str(data[1].root), '--eval', str(data[2]),
            '--inputs', str(data[3]), '--max-age-ns', '100', '--out', str(output)]
    assert rosy_ml.main(args) == 0
    assert json.loads(output.read_bytes())['fitness_verdict'] == 'HOLD'
    before = output.read_bytes()
    assert rosy_ml.main(args) == 2
    assert output.read_bytes() == before


def change_training(data, mutator):
    model_folder, registry, truth, inputs, model, opened = data
    observations = json.loads((inputs / 'manifest.json').read_bytes())
    name, digest = store.parse_dataset_ref(observations['training_refs'][0])
    old = registry.dataset_path(name, digest)
    stage = old.parent / 'changed'
    old.rename(stage)
    doc = json.loads((stage / 'manifest.json').read_bytes())
    mutator(stage, doc)
    (stage / 'manifest.json').write_bytes(evidence.encoded(doc))
    train = seal(stage)
    raw = json.loads((model_folder / 'model_manifest.json').read_bytes())
    raw['dataset']['revision'] = train.name
    (model_folder / 'model_manifest.json').write_bytes(evidence.encoded(raw))
    model.manifest = load_manifest(model_folder)
    return modify_inputs(data, lambda d: d.update(training_refs=[f'{name}@{train.name}'],
        model_manifest_sha256=evidence.sha((model_folder / 'model_manifest.json').read_bytes())))


@pytest.mark.parametrize('overlap', ['session', 'capture_group', 'image'])
def test_training_overlap_is_refused_with_content_consistent_refs(tmp_path, monkeypatch, overlap):
    data = bundle(tmp_path, monkeypatch)
    frame = store.read_fixed_manifest(data[2])['frames'][0]
    def alter(stage, doc):
        if overlap == 'image':
            raw = (data[2] / frame['image']).read_bytes()
            (stage / 'image.png').write_bytes(raw)
            doc['frames'][0]['image_sha256'] = evidence.sha(raw)
        else:
            doc['frames'][0][overlap] = frame[overlap]
    changed = change_training(data, alter)
    with pytest.raises(ValueError, match='overlap'):
        run(changed)
    assert data[5] == []


def test_training_class_order_must_match_candidate(tmp_path, monkeypatch):
    data = bundle(tmp_path, monkeypatch)
    def alter(stage, doc):
        doc['classes'][0]['name'], doc['classes'][1]['name'] = doc['classes'][1]['name'], doc['classes'][0]['name']
    changed = change_training(data, alter)
    with pytest.raises(ValueError, match='class'):
        run(changed)
    assert data[5] == []


def test_reservation_change_during_inference_refuses_report(tmp_path, monkeypatch):
    data = bundle(tmp_path, monkeypatch)
    original = data[4].infer
    def mutate(bgr):
        result = original(bgr)
        monkeypatch.setattr(store.Store, 'eval_reservations', lambda self: {})
        return result
    monkeypatch.setattr(data[4], 'infer', mutate)
    with pytest.raises(ValueError, match='reservation'):
        run(data)


def test_cli_backend_failure_is_exit_two_without_report(tmp_path, monkeypatch):
    import rosy_ml
    data = bundle(tmp_path, monkeypatch)
    def fail(bgr):
        raise RuntimeError('backend execution failed')
    monkeypatch.setattr(data[4], 'infer', fail)
    output = tmp_path / 'report.json'
    args = ['object-fitness', str(data[0]), '--store', str(data[1].root), '--eval', str(data[2]),
            '--inputs', str(data[3]), '--max-age-ns', '100', '--out', str(output)]
    assert rosy_ml.main(args) == 2
    assert not output.exists()
