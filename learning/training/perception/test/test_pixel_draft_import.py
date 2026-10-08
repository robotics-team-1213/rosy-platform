"""An indexed draft enters review as pending pixels, never as approval."""
import hashlib
import json

import cv2
import numpy as np
import pytest

from test_review_app import open_store
from test_review_cycle import catalog
import review_ingest
import review_masks


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
