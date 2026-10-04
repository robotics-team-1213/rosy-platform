"""Unlabelled historical candidates stay outside training and fixed evaluation."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('edge_review', Path(__file__).resolve().parents[1]
                                             / 'dataset' / 'edge_review.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def inputs(tmp_path):
    cv2, np = pytest.importorskip('cv2'), pytest.importorskip('numpy')
    root = tmp_path / 'input'
    root.mkdir()
    pixels = np.zeros((24, 32, 3), dtype=np.uint8)
    data = cv2.imencode('.png', pixels)[1].tobytes()
    (root / 'frame.png').write_bytes(data)
    video = 'teleop_robot_20260930T120000Z.mp4'
    (root / video).write_bytes(b'original-video')
    row = {'image': 'frame.png', 'image_sha256': hashlib.sha256(data).hexdigest(),
           'decoded_bgr_sha256': hashlib.sha256(pixels.tobytes()).hexdigest(),
           'source_video': video, 'frame_index': 7, 'video_time_s': 0.875,
           'candidate_tags': ['dark_candidate'], 'label_status': 'unlabelled'}
    manifest = {'schema': 'rosy.edge-candidate-review/1', 'images': [row],
                'sources': [{'video': video, 'sha256': hashlib.sha256(b'original-video').hexdigest(),
                             'sidecars': []}]}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    train, evaluation = tmp_path / 'train.json', tmp_path / 'eval.json'
    train.write_text(json.dumps({'frames': [{'session': '20260930T120000Z_robot', 'split': 'val'}]}))
    evaluation.write_text(json.dumps({'frames': [{'session': '20261001T120000Z_robot', 'split': 'eval'}]}))
    return root, train, evaluation


def test_overlap_and_deferred_scope_do_not_become_labels(tmp_path):
    root, train, evaluation = inputs(tmp_path)
    out = tmp_path / 'review'
    result = module.prepare(root, root, [train], [evaluation], out)
    assert result['images_verified'] == 1
    assert result['training_dataset_qualified'] is False
    row = json.loads((out / 'queue.jsonl').read_text())
    assert row['dataset_memberships'][0]['split'] == 'val'
    assert row['eligible_new_holdout'] is False
    assert row['review_status'] == 'pending_human'
    assert row['lowlight_improvement_deferred'] is True
    assert (out / 'images/frame.png').read_bytes() == (root / 'frame.png').read_bytes()
    assert not list(out.rglob('*mask*'))


@pytest.mark.parametrize('change', ['file', 'pixels', 'path', 'video', 'source', 'duplicate', 'zip_collision'])
def test_invalid_inputs_leave_no_complete_output(tmp_path, change):
    root, train, evaluation = inputs(tmp_path)
    path = root / 'manifest.json'
    manifest = json.loads(path.read_text())
    if change == 'file':
        (root / 'frame.png').write_bytes(b'changed')
    elif change == 'pixels':
        manifest['images'][0]['decoded_bgr_sha256'] = '0' * 64
    elif change == 'path':
        manifest['images'][0]['image'] = '../outside.png'
    elif change == 'video':
        (root / manifest['sources'][0]['video']).write_bytes(b'changed')
    elif change == 'source':
        manifest['images'][0]['source_video'] = 'unknown.mp4'
    elif change == 'zip_collision':
        (root / 'other.png').write_bytes((root / 'frame.png').read_bytes())
        manifest['images'].append(dict(manifest['images'][0], image='other.png'))
    else:
        manifest['images'].append(manifest['images'][0])
    path.write_text(json.dumps(manifest))
    out = tmp_path / 'review'
    with pytest.raises(ValueError):
        module.prepare(root, root, [train], [evaluation], out)
    assert not out.exists()


def test_eval_overlap_is_quarantined_even_with_different_video_hash(tmp_path):
    root, train, evaluation = inputs(tmp_path)
    evaluation.write_text(train.read_text())
    out = tmp_path / 'review'
    module.prepare(root, root, [train], [evaluation], out)
    row = json.loads((out / 'queue.jsonl').read_text())
    assert row['fixed_eval_overlap'] is True
    assert row['disposition'] == 'quarantine_eval_overlap'
