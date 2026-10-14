"""Historical versions remain attributable, bounded and read-only."""
import json

import cv2
import numpy as np
import pytest

from review_app import Conflict
import review_masks
import review_versions
from test_review_app import open_store
from test_review_cycle import CLASSES


def test_history_pages_all_events_without_duplicates(tmp_path):
    store = open_store(tmp_path)
    for number in range(1, 26):
        store.update(0, {'version': number, 'action': 'reopen'}, actor='reviewer-a')
    first = review_versions.page(store, 'object', 0)
    second = review_versions.page(store, 'object', 0, before=first['next_before'])
    assert [row['version'] for row in first['events'] + second['events']] == list(range(26, 0, -1))
    assert second['next_before'] is None
    assert first['events'][0]['actor'] == 'reviewer-a'
    assert 'actor' not in second['events'][-1]
    before = store.get(0)
    old = review_versions.version(store, 'object', 0, 1)
    with store.connect() as db:
        expected = json.loads(db.execute('SELECT review FROM events WHERE frame=0 AND version=1').fetchone()[0])
    assert old['boxes'] == expected['boxes']
    assert old['available'] and old['status'] == 'approved'
    assert store.get(0) == before


def test_pixel_versions_preserve_mask_and_actor_across_edits(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict, actor='alice')
    first = review_masks.get(store, 0)
    review_masks.update(store, 0, {'version': 1, 'action': 'fill', 'label': 2}, Conflict, actor='bob')
    before = review_masks.get(store, 0)
    old = review_versions.version(store, 'pixel', 0, 1)
    assert old['available'] and old['actor'] == 'alice' and not old['current']
    assert old['mask_sha256'] == first['sha256']
    current = review_versions.version(store, 'pixel', 0, 2)
    assert current['actor'] == 'bob' and current['current']
    decoded = cv2.imdecode(np.frombuffer(review_versions.image(store, 0, 1), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == (24, 32, 3)
    assert review_masks.get(store, 0) == before
    assert not review_versions.version(store, 'pixel', 0, 0)['available']
    assert not review_versions.version(store, 'pixel', 0, 99)['available']
    with pytest.raises(ValueError, match='unavailable'):
        review_versions.image(store, 0, 99)


@pytest.mark.parametrize('field,value', [('path','../../outside.png'), ('sha256','0'*64)])
def test_historical_mask_rejects_path_escape_and_tampering(tmp_path, field, value):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    for number in range(2):
        review_masks.update(store, 0, {'version': number, 'action': 'fill', 'label': number}, Conflict)
    with store.connect() as db:
        row = db.execute('SELECT review FROM pixel_events WHERE frame=0 AND version=2').fetchone()
        detail = json.loads(row[0]); detail[field] = value
        db.execute('UPDATE pixel_events SET review=? WHERE frame=0 AND version=2', (json.dumps(detail),))
    with pytest.raises(ValueError):
        review_versions.version(store, 'pixel', 0, 1)


@pytest.mark.parametrize('lane,index,before,limit', [('bad',0,None,20),('pixel',-1,None,20),
    ('pixel',0,0,20),('pixel',0,None,101),('object',True,None,20)])
def test_history_rejects_invalid_bounds(tmp_path, lane, index, before, limit):
    with pytest.raises(ValueError):
        review_versions.page(open_store(tmp_path), lane, index, before, limit)


def test_object_snapshot_rejects_source_identity_change(tmp_path):
    store = open_store(tmp_path)
    with store.connect() as db:
        row = db.execute('SELECT review FROM events WHERE frame=0').fetchone()
        detail = json.loads(row[0]); detail['image_sha256'] = '0'*64
        db.execute('UPDATE events SET review=? WHERE frame=0', (json.dumps(detail),))
    with pytest.raises(ValueError, match='source image'):
        review_versions.version(store, 'object', 0, 1)


def test_missing_retained_pixel_file_is_explicitly_unavailable(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, Conflict)
    snapshot = review_masks.get(store, 0)
    (store.state / snapshot['path']).unlink()
    assert not review_versions.version(store, 'pixel', 0, 1)['available']
