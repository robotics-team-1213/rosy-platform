"""An indexed draft enters review as pending pixels, never as approval."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from test_review_app import open_store
from test_review_cycle import catalog
import review_ingest
import review_masks


V13_CLASSES = (Path(__file__).resolve().parents[1] / 'classes' /
               'lane_lr6_drivable.yaml').read_bytes()


def test_model_object_draft_for_existing_frame_waits_for_explicit_review(tmp_path):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    before = store.get(2)
    rows[0]['objects'] = [{'bbox_xyxy': [2, 3, 12, 14], 'label': 'cone'}]
    rows[0]['annotation_source'] = 'qwen3-vl:8b-instruct'
    (folder / 'verified-inputs.jsonl').write_text(json.dumps(rows[0]) + '\n')

    result = review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    assert result['object_draft_candidates_queued'] == 1
    assert store.get(2) == before
    draft = store.object_drafts(2)[0]
    assert draft['boxes'] == rows[0]['objects']
    assert draft['origin'] == 'qwen3-vl:8b-instruct'
    assert review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})['object_draft_candidates_queued'] == 0

    with pytest.raises(ValueError, match='다른 탭'):
        store.update(2, {'version': before['version'] - 1, 'action': 'apply_object_draft',
                         'draft_sha256': draft['sha256']})
    applied = store.update(2, {'version': before['version'], 'action': 'apply_object_draft',
                               'draft_sha256': draft['sha256']})
    assert applied['review']['boxes'] == rows[0]['objects']
    assert applied['status'] == 'pending'
    assert applied['review']['review_origin'] == 'model_draft_pending_human'
    assert applied['review']['draft_origin'] == 'qwen3-vl:8b-instruct'


def test_object_draft_rejects_alternate_image_of_same_video_frame(tmp_path):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    rows[1]['objects'] = [{'bbox_xyxy': [2, 3, 12, 14], 'label': 'cone'}]
    (folder / 'verified-inputs.jsonl').write_text(json.dumps(rows[1]) + '\n')
    with pytest.raises(ValueError, match='exact reviewed image'):
        review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    assert store.object_drafts(2) == []


@pytest.mark.parametrize('outside_column,side', [(2, 'left'), (29, 'right')])
def test_v13_draft_and_approval_reject_drivable_outside_visible_lane(tmp_path, outside_column, side):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    classes.write_bytes(V13_CLASSES)
    pixels = np.zeros((24, 32), np.uint8)
    pixels[:, 8] = 1
    pixels[:, 24] = 2
    pixels[:, 9:24] = 5
    draft = folder / 'draft.png'

    def write_draft(image):
        draft.write_bytes(review_masks.encode(image))
        rows[0]['mask'] = {'indexed_png': draft.name,
                           'sha256': hashlib.sha256(draft.read_bytes()).hexdigest(),
                           'classes_sha256': hashlib.sha256(V13_CLASSES).hexdigest()}
        (folder / 'verified-inputs.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))

    bad = pixels.copy()
    bad[:, outside_column] = 5
    binding = {'classes': [{'name': 'lane_left', 'index': 1},
                           {'name': 'lane_right', 'index': 2},
                           {'name': 'drivable', 'index': 5}]}
    assert review_masks.lane_boundary_violations(bad, binding)[side] == 24
    write_draft(bad)
    with pytest.raises(ValueError, match='drivable outside visible lane boundary'):
        review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    with pytest.raises(KeyError):
        store.get(2)

    write_draft(pixels)
    assert review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})['added'] == 1
    review = review_masks.get(store, 2)
    assert review_masks.lane_boundary_violations(review_masks.pixels(store, review), review['classes']) == {'left': 0, 'right': 0}
    candidate_path, candidate_sha = review_masks.freeze(store, review_masks.encode(bad))
    with store.connect() as db:
        db.execute('INSERT INTO pixel_drafts(frame,sha256,path,catalog_sha256) VALUES (?,?,?,?)',
                   (2, candidate_sha, candidate_path, '0' * 64))
    with pytest.raises(ValueError, match='drivable outside visible lane boundary'):
        review_masks.update(store, 2, {'version': review['version'], 'action': 'apply_draft',
                                       'draft_sha256': candidate_sha}, ValueError)
    assert review_masks.get(store, 2)['version'] == review['version']
    edited = review_masks.update(store, 2, {'version': review['version'], 'action': 'paint',
                                           'label': 5, 'radius': 0,
                                           'points': [[outside_column, 12]]}, ValueError)
    with pytest.raises(ValueError, match='drivable outside visible lane boundary'):
        review_masks.update(store, 2, {'version': edited['version'], 'action': 'approve',
                                       'complete_frame_review': True,
                                       'background_reviewed': True}, ValueError)
    assert review_masks.get(store, 2)['status'] == 'pending'
    corrected = review_masks.update(store, 2, {'version': edited['version'], 'action': 'paint',
                                              'label': 0, 'radius': 0,
                                              'points': [[outside_column, 12]]}, ValueError)
    approved = review_masks.update(store, 2, {'version': corrected['version'], 'action': 'approve',
                                              'complete_frame_review': True,
                                              'background_reviewed': True}, ValueError)
    assert approved['status'] == 'approved'


def test_verified_object_draft_is_pending_and_bad_box_rejects_import(tmp_path):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    rows[0]['objects'] = [{'bbox_xyxy': [2, 3, 12, 14], 'label': 'cone',
                           'source': 'vision_model_candidate'}]
    catalog_file = folder / 'verified-inputs.jsonl'
    catalog_file.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    result = review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    assert result['added'] == 1
    assert store.get(2)['source']['objects'] == rows[0]['objects']
    assert store.get(2)['review']['boxes'] == []
    assert store.get(2)['status'] == 'pending'
    rows[0]['objects'][0]['bbox_xyxy'] = [2, 3, 99, 14]
    catalog_file.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError, match='outside'):
        review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})


def test_indexed_draft_import_keeps_255_and_pending_status(tmp_path):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    pixels = np.full((24, 32), 255, np.uint8)
    pixels[:, :8] = 1
    pixels[:, 8:16] = 0
    draft = folder / 'draft.png'
    draft.write_bytes(cv2.imencode('.png', pixels)[1].tobytes())
    rows[0]['mask'] = {'indexed_png': draft.name,
                       'sha256': hashlib.sha256(draft.read_bytes()).hexdigest(),
                       'classes_sha256': hashlib.sha256(classes.read_bytes()).hexdigest()}
    (folder / 'verified-inputs.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    result = review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    review = review_masks.get(store, 2)
    assert result['added'] == 1 and review['status'] == 'pending'
    assert np.array_equal(review_masks.pixels(store, review), pixels)
    assert review['approval'] is None
    assert store.get(2)['review']['review_status'] == 'pending_human'
    # A regenerated draft cannot overwrite a person's current pixel revision.
    current = review_masks.update(store, 2, {'version': 1, 'action': 'fill', 'label': 0}, ValueError)
    approved = review_masks.update(store, 2, {'version': current['version'], 'action': 'approve',
                                                'complete_frame_review': True,
                                                'background_reviewed': True}, ValueError)
    draft.write_bytes(cv2.imencode('.png', np.full((24, 32), 1, np.uint8))[1].tobytes())
    rows[0]['mask']['sha256'] = hashlib.sha256(draft.read_bytes()).hexdigest()
    rows[0]['annotation_source'] = 'v12_pixel_mask_candidate'
    (folder / 'verified-inputs.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    assert review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})['added'] == 0
    assert review_masks.get(store, 2)['version'] == approved['version']
    assert np.all(review_masks.pixels(store, review_masks.get(store, 2)) == 0)
    candidate = review_masks.get(store, 2)['draft_candidates'][0]['sha256']
    assert review_masks.get(store, 2)['draft_candidates'][0]['origin'] == 'v12_pixel_mask_candidate'
    before_preview = review_masks.get(store, 2)
    preview = cv2.imdecode(np.frombuffer(review_masks.draft_preview(store, 2, candidate), np.uint8),
                           cv2.IMREAD_COLOR)
    assert preview.shape == (24, 32, 3)
    assert review_masks.get(store, 2) == before_preview
    with pytest.raises(ValueError):
        review_masks.update(store, 2, {'version': approved['version'] - 1,
                                        'action': 'apply_draft', 'draft_sha256': candidate}, ValueError)
    applied = review_masks.update(store, 2, {'version': approved['version'],
                                              'action': 'apply_draft', 'draft_sha256': candidate}, ValueError)
    assert applied['status'] == 'pending' and applied['approval'] is None
    assert np.all(review_masks.pixels(store, applied) == 1)
    assert applied['draft_candidates'] == []
    undone = review_masks.update(store, 2, {'version': applied['version'], 'action': 'undo'}, ValueError)
    assert undone['status'] == 'pending' and np.all(review_masks.pixels(store, undone) == 0)
    with store.connect() as db:
        db.execute('UPDATE pixel_drafts SET withdrawn=1 WHERE frame=? AND sha256=?', (2, candidate))
    assert all(row['sha256'] != candidate for row in review_masks.get(store, 2)['draft_candidates'])
    with pytest.raises(ValueError, match='selected draft is unavailable'):
        review_masks.update(store, 2, {'version': undone['version'],
                                        'action': 'apply_draft', 'draft_sha256': candidate}, ValueError)
    with pytest.raises(ValueError, match='selected draft is unavailable'):
        review_masks.draft_preview(store, 2, candidate)
    assert review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})['added'] == 0
    with store.connect() as db:
        assert db.execute('SELECT withdrawn FROM pixel_drafts WHERE frame=? AND sha256=?',
                          (2, candidate)).fetchone()[0] == 1


@pytest.mark.parametrize('kind', ['rgb', '16bit', 'unknown', 'escape', 'hash', 'jpeg', 'classes'])
def test_bad_indexed_draft_rejects_whole_import(tmp_path, kind):
    store = open_store(tmp_path)
    folder, classes, rows = catalog(tmp_path)
    before = store.list_frames()
    if kind == 'rgb':
        pixels = np.zeros((24, 32, 3), np.uint8)
    elif kind == '16bit':
        pixels = np.zeros((24, 32), np.uint16)
    else:
        pixels = np.full((24, 32), 8 if kind == 'unknown' else 255, np.uint8)
    draft = folder / 'draft.png'
    draft.write_bytes(cv2.imencode('.jpg' if kind == 'jpeg' else '.png', pixels)[1].tobytes())
    rows[0]['mask'] = {'indexed_png': '../draft.png' if kind == 'escape' else draft.name,
                       'sha256': '0' * 64 if kind == 'hash' else hashlib.sha256(draft.read_bytes()).hexdigest(),
                       'classes_sha256': '0' * 64 if kind == 'classes'
                       else hashlib.sha256(classes.read_bytes()).hexdigest()}
    (folder / 'verified-inputs.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError):
        review_ingest.import_frames(store, {'path': str(folder), 'classes': str(classes)})
    assert store.list_frames() == before
