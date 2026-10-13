"""Human mask return requires both image and mask byte-bound full-frame approval."""
import hashlib
import json

import cv2
import numpy as np
import pytest

import build
import edge_review
import edge_review_return as receiver


def inputs(tmp_path, approved=True):
    root = tmp_path / 'source'
    root.mkdir()
    raw = cv2.imencode('.png', np.zeros((8, 8, 3), np.uint8))[1].tobytes()
    (root / 'frame.png').write_bytes(raw)
    video = 'teleop_robot_20260930T120000Z.mp4'
    (root / video).write_bytes(b'video')
    candidate = {'image': 'frame.png', 'image_sha256': edge_review.digest(raw),
                 'decoded_bgr_sha256': edge_review.digest(bytes(8 * 8 * 3)),
                 'source_video': video, 'frame_index': 7, 'candidate_tags': []}
    (root / 'manifest.json').write_text(json.dumps({'schema': 'rosy.edge-candidate-review/1',
        'sources': [{'video': video, 'sha256': edge_review.digest(b'video')}], 'images': [candidate]}))
    train = tmp_path / 'train.json'
    train.write_text(json.dumps({'frames': [{'session': '20260930T120000Z_robot', 'split': 'train'}]}))
    fixed = tmp_path / 'fixed' / 'temporary'
    fixed.mkdir(parents=True)
    (fixed / 'manifest.json').write_text(json.dumps({'purpose': 'eval', 'frames': [
        {'session': '20261001T120000Z_robot', 'split': 'eval'}]}))
    name = build.content_sha(fixed)
    fixed = fixed.rename(fixed.parent / name)
    pack = tmp_path / 'pack'
    edge_review.prepare(root, root, [train], [fixed / 'manifest.json'], pack)
    export = tmp_path / 'cvat'
    (export / 'SegmentationClass').mkdir(parents=True)
    labelmap = 'background:0,0,0::\nlane_line:230,25,75::\n'
    (export / 'labelmap.txt').write_text(labelmap)
    mask = cv2.imencode('.png', np.zeros((8, 8, 3), np.uint8))[1].tobytes()
    mask_name = 'SegmentationClass/20260930T120000Z_robot__00000007.png'
    (export / mask_name).write_bytes(mask)
    human = tmp_path / 'human.jsonl'
    row = {'index': 0, 'image_sha256': edge_review.digest(raw), 'mask': mask_name,
           'mask_sha256': hashlib.sha256(mask).hexdigest(), 'review_status': 'approved' if approved else 'pending_human',
           'complete_frame_review': approved, 'background_reviewed': approved}
    human.write_text(json.dumps(row) + '\n')
    classes = tmp_path / 'classes.yaml'
    classes.write_text('classes:\n  - {index: 0, name: floor, role: background, color: [0, 0, 0]}\n'
                       '  - {index: 1, name: lane_line, role: lane_marking, color: [230, 25, 75]}\n')
    return pack, human, export, classes, fixed


def test_pending_reviews_create_no_frames_or_masks(tmp_path):
    pack, human, export, classes, fixed = inputs(tmp_path, False)
    out = tmp_path / 'return'
    result = receiver.receive(pack, human, export, classes, [fixed], out)
    assert result['exported_frames'] == 0 and result['queued_frames'] == 1
    assert not list(out.rglob('frames.jsonl')) and not list(out.rglob('SegmentationClass/*.png'))
    assert result['training_dataset_qualified'] is False


def test_pending_does_not_require_a_fabricated_cvat_export(tmp_path):
    pack, human, export, classes, fixed = inputs(tmp_path, False)
    (export / 'labelmap.txt').unlink()
    assert receiver.receive(pack, human, export, classes, [fixed], tmp_path / 'return')['exported_frames'] == 0


def test_changed_approved_mask_is_rejected_by_builder(tmp_path):
    pack, human, export, classes, fixed = inputs(tmp_path)
    out = tmp_path / 'return'
    receiver.receive(pack, human, export, classes, [fixed], out)
    mask = next((out / 'cvat/SegmentationClass').glob('*.png'))
    changed = np.zeros((8, 8, 3), np.uint8)
    changed[:] = [75, 25, 230]
    cv2.imwrite(str(mask), changed)
    with pytest.raises(build.BuildError, match='mask hash'):
        build.build_dataset(out / 'cvat', list((out / 'frames').iterdir()),
                            build.load_classes(classes), tmp_path / 'dataset', exclude_eval=[fixed])


@pytest.mark.parametrize('change', ['missing_meta', 'conflicting_approval'])
def test_builder_requires_complete_consistent_human_binding(tmp_path, change):
    pack, human, export, classes, fixed = inputs(tmp_path)
    out = tmp_path / 'return'
    receiver.receive(pack, human, export, classes, [fixed], out)
    directory = next((out / 'frames').iterdir())
    if change == 'missing_meta':
        (directory / 'session.json').unlink()
    else:
        row = json.loads((directory / 'frames.jsonl').read_text())
        row['human_review']['mask_sha256'] = '0' * 64
        (directory / 'frames.jsonl').write_text(json.dumps(row) + '\n')
    with pytest.raises(build.BuildError, match='human'):
        build.build_dataset(out / 'cvat', [directory], build.load_classes(classes), tmp_path / 'dataset')


def test_two_reviewed_sessions_build_png_dataset_end_to_end(tmp_path):
    pack, human, export, classes, fixed = inputs(tmp_path)
    root = tmp_path / 'source'
    manifest = json.loads((root / 'manifest.json').read_text())
    (root / 'second.png').write_bytes((root / 'frame.png').read_bytes())
    video = 'teleop_robot_20260930T130000Z.mp4'
    (root / video).write_bytes(b'video')
    manifest['sources'].append({'video': video, 'sha256': edge_review.digest(b'video')})
    manifest['images'].append(dict(manifest['images'][0], image='second.png', source_video=video))
    (root / 'manifest.json').write_text(json.dumps(manifest))
    pack = tmp_path / 'two-session-pack'
    edge_review.prepare(root, root, [tmp_path / 'train.json'], [fixed / 'manifest.json'], pack)
    review = json.loads(human.read_text())
    second_mask = 'SegmentationClass/20260930T130000Z_robot__00000007.png'
    (export / second_mask).write_bytes((export / review['mask']).read_bytes())
    human.write_text(json.dumps(review) + '\n' + json.dumps(dict(review, index=1, mask=second_mask)) + '\n')
    out = tmp_path / 'return'
    returned = receiver.receive(pack, human, export, classes, [fixed], out)
    dataset = tmp_path / 'dataset'
    built = build.build_dataset(out / 'cvat', [out / name for name in returned['frame_dirs']],
                                build.load_classes(classes), dataset, exclude_eval=[fixed])
    assert len(built['frames']) == 2
    assert {frame['split'] for frame in built['frames']} == {'train', 'val'}
    for frame in built['frames']:
        assert frame['image'].endswith('.png')
        assert (dataset / frame['image']).read_bytes() == (root / 'frame.png').read_bytes()
    assert built['disjoint_from'][0]['content_sha'] == fixed.name


def test_approved_masks_bind_original_png_for_existing_builder(tmp_path):
    pack, human, export, classes, fixed = inputs(tmp_path)
    out = tmp_path / 'return'
    result = receiver.receive(pack, human, export, classes, [fixed], out)
    frame_dir = out / 'frames/20260930T120000Z_robot'
    row = json.loads((frame_dir / 'frames.jsonl').read_text())
    assert row['index'] == 7 and row['image_sha256'] == edge_review.digest((pack / 'images/frame.png').read_bytes())
    assert (frame_dir / row['image']).read_bytes() == (pack / 'images/frame.png').read_bytes()
    assert build._resolve('20260930T120000Z_robot__00000007', build._read_frames([frame_dir]), 'mask')
    assert result['exported_frames'] == 1
    assert result['training_dataset_qualified'] is False  # No dataset/split invented.


@pytest.mark.parametrize('change', ['image', 'mask', 'background', 'shape', 'queue', 'eval', 'duplicate'])
def test_bad_approval_is_rejected_before_output(tmp_path, change):
    pack, human, export, classes, fixed = inputs(tmp_path)
    row = json.loads(human.read_text())
    if change == 'image': row['image_sha256'] = '0' * 64
    elif change == 'mask': row['mask_sha256'] = '0' * 64
    elif change == 'background': row['background_reviewed'] = False
    elif change == 'shape':
        raw = cv2.imencode('.png', np.zeros((4, 4, 3), np.uint8))[1].tobytes()
        (export / row['mask']).write_bytes(raw)
        row['mask_sha256'] = edge_review.digest(raw)
    elif change == 'queue': (pack / 'queue.jsonl').write_text('{}\n')
    elif change == 'eval': (fixed / 'manifest.json').write_text('{}')
    human.write_text(json.dumps(row) + '\n' + (json.dumps(row) + '\n' if change == 'duplicate' else ''))
    out = tmp_path / 'return'
    with pytest.raises(ValueError): receiver.receive(pack, human, export, classes, [fixed], out)
    assert not out.exists()
