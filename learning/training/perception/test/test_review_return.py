"""Human return processing binds originals and separates actual image sizes."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('review_return', Path(__file__).resolve().parents[1]
                                              / 'dataset' / 'review_return.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture_inputs(tmp_path, approved=True):
    cv2, np = pytest.importorskip('cv2'), pytest.importorskip('numpy')
    images = tmp_path / 'images'
    images.mkdir()
    rows, reviews = [], []
    for index, (width, height) in enumerate(((32, 24), (64, 48))):
        data = cv2.imencode('.jpg', np.zeros((height, width, 3), dtype=np.uint8))[1].tobytes()
        (images / f'{index}.jpg').write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        rows.append({'index': index, 'image': f'{index}.jpg', 'image_sha256': digest,
                     'width': width, 'height': height, 'boxes': []})
        reviews.append({'index': index, 'image_sha256': digest,
                        'review_status': 'approved' if approved else 'pending_human',
                        'complete_frame_review': approved,
                        'boxes': [{'label': 'traffic_light', 'bbox_xyxy': [1, 2, 12, 14], 'signal_state': 'unknown'}]})
    source, human = tmp_path / 'source.jsonl', tmp_path / 'human.jsonl'
    source.write_bytes(module._jsonl(rows))
    human.write_bytes(module._jsonl(reviews))
    return source, human, images


def test_mixed_sizes_export_global_indices_and_exact_inputs(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    out = tmp_path / 'return'
    result = module.receive_review(source, human, images, out)
    assert result['exported_frames'] == 2 and result['queued_frames'] == 0
    assert result['classes'] == list(module.exporter.OBJECT_CLASSES)
    assert (out / 'groups/32x24/000000.txt').exists()
    assert (out / 'groups/64x48/000001.txt').exists()
    assert (out / 'inputs/human.jsonl').read_bytes() == human.read_bytes()
    assert 'signal_state' in (out / 'inputs/human.jsonl').read_text()
    assert result['training_dataset_qualified'] is False
    for index in (0, 1):
        assert (out / f'inputs/images/{index:06d}.jpg').read_bytes() == (images / f'{index}.jpg').read_bytes()
    for item in result['files']:
        data = (out / item['path']).read_bytes()
        assert item['sha256'] == hashlib.sha256(data).hexdigest()
        assert item['bytes'] == len(data)
    assert (out / 'COMPLETE').read_text().strip() == hashlib.sha256((out / 'manifest.json').read_bytes()).hexdigest()


def test_pending_reviews_create_no_labels(tmp_path):
    source, human, images = fixture_inputs(tmp_path, approved=False)
    out = tmp_path / 'return'
    result = module.receive_review(source, human, images, out)
    assert result['exported_frames'] == 0 and result['queued_frames'] == 2
    assert not list(out.glob('groups/*/*.txt'))


def test_source_path_traversal_rejected_before_output(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    rows = module._parse(source.read_bytes())
    rows[1]['image'] = '../images/1.jpg'
    source.write_bytes(module._jsonl(rows.values()))
    out = tmp_path / 'return'
    with pytest.raises(ValueError, match='relative contained image path'):
        module.receive_review(source, human, images, out)
    assert not out.exists()


@pytest.mark.parametrize('problem', ['human_hash', 'source_hash', 'dimensions', 'extra_index', 'approval_bool', 'source_box'])
def test_late_invalid_reference_writes_nothing(tmp_path, problem):
    source, human, images = fixture_inputs(tmp_path)
    rows = module._parse(source.read_bytes())
    reviews = module._parse(human.read_bytes())
    if problem == 'human_hash':
        reviews[1]['image_sha256'] = 'b' * 64
    elif problem == 'source_hash':
        rows[1]['image_sha256'] = 'a' * 64
    elif problem == 'dimensions':
        rows[1]['width'] = 32
    elif problem == 'extra_index':
        reviews[1]['index'] = 7
    elif problem == 'source_box':
        rows[1]['objects'] = [{'label': 'robot', 'bbox_xyxy': [1, 2, 99, 14]}]
    else:
        reviews[1]['complete_frame_review'] = 1
    source.write_bytes(module._jsonl(rows.values()))
    human.write_bytes(module._jsonl(reviews.values()))
    out = tmp_path / 'return'
    with pytest.raises(ValueError):
        module.receive_review(source, human, images, out)
    assert not out.exists()


def test_originals_changing_after_capture_cannot_change_export(tmp_path, monkeypatch):
    source, human, images = fixture_inputs(tmp_path)
    original_human = human.read_bytes()
    original_image = (images / '0.jpg').read_bytes()
    delegate = module.exporter.main

    def mutate_originals(argv, **kw):
        source.write_bytes(b'invalid new source')
        human.write_bytes(b'invalid new review')
        (images / '0.jpg').write_bytes(b'changed original')
        return delegate(argv, **kw)

    monkeypatch.setattr(module.exporter, 'main', mutate_originals)
    out = tmp_path / 'return'
    result = module.receive_review(source, human, images, out)
    assert result['exported_frames'] == 2
    assert (out / 'inputs/human.jsonl').read_bytes() == original_human
    assert (out / 'groups/32x24/images/000000.jpg').read_bytes() == original_image


def test_second_group_failure_has_no_outer_complete_receipt(tmp_path, monkeypatch):
    source, human, images = fixture_inputs(tmp_path)
    delegate, calls = module.exporter.main, []

    def fail_second(argv, **kw):
        calls.append(argv)
        if len(calls) == 2:
            raise ValueError('group failed')
        return delegate(argv, **kw)

    monkeypatch.setattr(module.exporter, 'main', fail_second)
    out = tmp_path / 'return'
    with pytest.raises(ValueError, match='group failed'):
        module.receive_review(source, human, images, out)
    assert not (out / 'manifest.json').exists()
    assert not (out / 'COMPLETE').exists()


def test_custom_class_list_is_accepted_and_recorded(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    classes = ('car', 'traffic_light')
    out = tmp_path / 'return'
    result = module.receive_review(source, human, images, out, classes=classes)
    assert result['classes'] == list(classes)
    group = json.loads((out / 'groups/32x24/manifest.json').read_text(encoding='utf-8'))
    assert group['classes'] == list(classes)
    assert (out / 'groups/32x24/000000.txt').read_text().startswith('1 ')
    with pytest.raises(ValueError, match='object class'):
        module.receive_review(source, human, images, tmp_path / 'other', classes=('car',))
