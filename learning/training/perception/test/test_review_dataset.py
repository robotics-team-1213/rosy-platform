"""Read-only candidate diagnostics; this API never grants dataset qualification."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))
import review_dataset as target
from test_review_authority import current, digest, seal_bundle


def delivery(value, stamp=100):
    return {'schema': 'rosy.pinky-review-current-delivery/1', 'workspace_id': value['workspace_id'],
            'available': True, 'checked_at_unix': stamp, 'authority': copy.deepcopy(value)}


def test_pending_bundle_is_read_only_and_never_qualified(tmp_path):
    value = current(); root = tmp_path / 'bundle'; seal_bundle(root, value)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    calls = []
    def fetch():
        calls.append(True); return delivery(value)
    report = target.inspect_candidates(root, fetch_current=fetch, workspace_id='fixture', now=lambda: 100)
    assert len(calls) == 2
    assert report['training_dataset_qualified'] is False
    assert report['approved_masks'] == 0
    assert 'mask_not_approved' in report['frames'][0]['blockers']
    assert 'source_group_unknown' in report['frames'][0]['blockers']
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('stamp', [True, float('nan'), float('inf'), 9, 106])
def test_invalid_freshness_denied_before_bundle_read(stamp):
    with pytest.raises(ValueError):
        target.inspect_candidates('unused', fetch_current=lambda: delivery(current(), stamp),
                                  workspace_id='fixture', now=lambda: 100)


@pytest.mark.parametrize('field,bad', [('available', 1), ('schema', 'other'), ('workspace_id', 'wrong')])
def test_delivery_types_and_workspace(field, bad):
    envelope = delivery(current()); envelope[field] = bad
    with pytest.raises(ValueError):
        target.inspect_candidates('unused', fetch_current=lambda: envelope, workspace_id='fixture', now=lambda: 100)


def test_changed_authority_between_fetches_refuses_report(tmp_path):
    value = current(); root = tmp_path / 'bundle'; seal_bundle(root, value)
    other = copy.deepcopy(value); other['generation'] = 2; other = digest(other)
    snapshots = iter([delivery(value), delivery(other)])
    with pytest.raises(ValueError, match='changed'):
        target.inspect_candidates(root, fetch_current=lambda: next(snapshots), workspace_id='fixture', now=lambda: 100)


def test_capture_group_connects_sessions_and_exact_duplicate_images():
    rows = [dict(frame=0, source_session='part01', capture_group='shared', image_sha256='a', source_video_sha256='v', video_frame=1),
            dict(frame=1, source_session='part04', capture_group='shared', image_sha256='b', source_video_sha256='v', video_frame=2),
            dict(frame=2, source_session='other', capture_group='elsewhere', image_sha256='b', source_video_sha256=None, video_frame=None)]
    assert target.source_components(rows, {}) == [[0, 1, 2]]


def test_alternate_representation_hashes_connect_components():
    rows = [dict(frame=i, source_session=str(i), capture_group=str(i), image_sha256=str(i),
                 source_video_sha256=None, video_frame=None) for i in range(2)]
    assert target.source_components(rows, {0: ['same'], 1: ['same']}) == [[0, 1]]


@pytest.mark.parametrize('shape,dtype,value', [((2, 3, 3), 'uint8', 0), ((2, 3), 'uint16', 0),
                                              ((2, 3), 'uint8', 255), ((2, 3), 'uint8', 7)])
def test_bad_indexed_mask_blocks(shape, dtype, value):
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode('.png', np.full(shape, value, dtype=dtype)); assert ok
    assert target.mask_blockers(encoded.tobytes(), width=3, height=2, indices={0, 5})


def test_crosswalk_ignore_role_index_is_still_valid_class_pixel():
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode('.png', np.full((2, 3), 5, dtype='uint8')); assert ok
    assert target.mask_blockers(encoded.tobytes(), width=3, height=2, indices={0, 5}) == []

@pytest.mark.parametrize('age', [True, float('nan'), float('inf'), 0, 91])
def test_freshness_bound_is_strict(age):
    with pytest.raises(ValueError):
        target.inspect_candidates('unused', fetch_current=lambda: delivery(current()),
                                  workspace_id='fixture', authority_max_age_s=age, now=lambda: 100)


def test_older_previous_revision_refuses_current():
    with pytest.raises(ValueError, match='older'):
        target.inspect_candidates('unused', fetch_current=lambda: delivery(current()), workspace_id='fixture',
                                  previous_authority={'workspace_id': 'fixture', 'generation': 2,
                                                      'decision_sha256': 'a' * 64}, now=lambda: 100)


def test_eval_full_content_union_and_missing_source_group_remains_unknown(tmp_path):
    from dataset.build import content_sha
    folders = []
    for i in range(2):
        stage = tmp_path / ('eval' + str(i)) / 'staging'; stage.mkdir(parents=True)
        (stage / 'image.png').write_bytes(b'image' + bytes([i]))
        (stage / 'manifest.json').write_text(json.dumps({'purpose': 'eval', 'frames': [
            {'session': 'held' + str(i), 'image': 'image.png'}]}))
        final = stage.with_name(content_sha(stage)); stage.rename(final); folders.append(final)
    refs, sessions, groups, videos, hashes, complete = target._eval_inventory(folders)
    assert len(refs) == 2 and sessions == {'held0', 'held1'}
    assert len(hashes) == 2 and not groups and not videos and complete is False
    (folders[0] / 'image.png').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='content hash'):
        target._eval_inventory(folders)


@pytest.mark.parametrize('index', [True, 0.0, '0', 255])
def test_class_indices_cannot_be_coerced(index):
    pytest.importorskip('yaml')
    raw = json.dumps({'classes': [{'index': index, 'name': 'floor', 'role': 'background'}]}).encode()
    with pytest.raises(ValueError, match='strict class'):
        target._classes(raw, {})


def test_duplicate_class_indices_denied():
    raw = json.dumps({'classes': [{'index': 0, 'name': 'floor', 'role': 'background'},
                                 {'index': 0, 'name': 'lane', 'role': 'lane_marking'}]}).encode()
    with pytest.raises(ValueError, match='unique contiguous'):
        target._classes(raw, {})


def test_raw_yaml_hash_and_normalized_signature_are_distinct():
    from dataset.build import load_classes
    raw = b'classes:\n - {index: 0, name: floor, role: background}\n - {index: 1, name: crosswalk, role: ignore}\n'
    classes = load_classes('captured', require_color=False, source_bytes=raw)
    current = {'pixel_classes_sha256': hashlib.sha256(raw).hexdigest(),
               'classes_signature': hashlib.sha256(json.dumps(classes, sort_keys=True).encode()).hexdigest()}
    assert target._classes(raw, current) == {0, 1}
    current['classes_signature'] = current['pixel_classes_sha256']
    with pytest.raises(ValueError, match='signature'):
        target._classes(raw, current)

@pytest.mark.parametrize('suffix', ['.jpg', '.bmp'])
def test_grayscale_non_png_is_never_indexed_approval(suffix):
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode(suffix, np.zeros((2, 3), dtype='uint8')); assert ok
    assert target.mask_blockers(encoded.tobytes(), width=3, height=2, indices={0}) == ['mask_not_8bit_grayscale_png']


def test_primary_image_dimensions_are_decoded_from_captured_bytes():
    np = pytest.importorskip('numpy'); cv2 = pytest.importorskip('cv2')
    ok, encoded = cv2.imencode('.jpg', np.zeros((2, 3, 3), dtype='uint8')); assert ok
    assert target.image_blockers(encoded.tobytes(), width=3, height=2) == []
    assert target.image_blockers(encoded.tobytes(), width=4, height=2) == ['image_dimensions_differ']


def test_empty_hashed_eval_inventory_cannot_establish_source_disjointness(tmp_path):
    from dataset.build import content_sha
    stage = tmp_path / 'eval' / 'stage'; stage.mkdir(parents=True)
    (stage / 'manifest.json').write_text(json.dumps({'purpose': 'eval', 'frames': [], 'labels': [{'session': 'held'}]}))
    final = stage.with_name(content_sha(stage)); stage.rename(final)
    inventory = target._eval_inventory([final])
    assert inventory[1] == {'held'} and inventory[-1] is False
