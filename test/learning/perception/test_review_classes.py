"""Explicit class revisions preserve label bytes and scope invalidation to one lane."""
import copy
import json
import sqlite3

import pytest

import class_sets
import review_classes
import review_masks
import review_versions
from review_store import Conflict
from test_review_app import open_store
from test_review_cycle import CLASSES


def request(store, lane, rows, count):
    current = review_classes.snapshot(store, lane)
    return dict(kind=lane, classes=rows, expected_sha=current['expected_sha'], expected_impact=count, confirm=True)


def test_object_addition_preserves_boxes_and_quarantines_drafts(tmp_path):
    store = open_store(tmp_path)
    with store.connect() as db:
        db.execute("UPDATE frames SET status='approved',review=json_set(review,'$.review_status','approved','$.complete_frame_review',json('true')) WHERE id=0")
        db.execute('INSERT INTO object_drafts VALUES (?,?,?,?,?)', (0, 'a'*64, '[]', 'model', 'b'*64))
    before = store.get(0)
    excluded = store.get(1)
    rows = copy.deepcopy(class_sets.object_set(store)['classes'])
    rows.append(dict(index=len(rows), name='new_object', display='새 물체', color=[13, 27, 49]))
    body = request(store, 'object', rows, 1)
    review_classes.revise(store, body, 'admin', Conflict)
    after = store.get(0)
    assert after['review']['boxes'] == before['review']['boxes']
    assert after['version'] == before['version'] + 1 and after['status'] == 'pending'
    assert store.get(1) == dict(excluded, version=excluded['version'] + 1)
    assert not store.object_drafts(0)
    assert 'new_object' in store.object_classes()
    assert review_versions.version(store, 'object', 0, before['version'])['status'] == 'approved'
    with pytest.raises(Conflict):
        review_classes.revise(store, body, 'admin', Conflict)
    with store.connect() as db:
        assert json.loads(db.execute('SELECT old_binding FROM class_revisions').fetchone()[0])['sha256'] != class_sets.object_set(store)['sha256']
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE class_revisions SET actor='other'")


def test_pixel_display_preserves_approval_then_color_change_requires_review_without_mask_rewrite(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, dict(version=0, action='fill_unknown', label=0), Conflict)
    prior = review_masks.get(store, 0)
    with store.connect() as db:
        db.execute("UPDATE masks SET status='approved',complete=1,background=1 WHERE frame=0")
        db.execute("INSERT INTO masks(frame,version,status) VALUES (1,4,'excluded')")
    excluded = review_masks.get(store, 1)
    before = review_masks.get(store, 0)
    rows = copy.deepcopy(review_masks.served_classes(store)['classes'])
    rows[0]['display'] = '바닥 표시'
    review_classes.revise(store, request(store, 'pixel', rows, 0), 'admin', Conflict)
    assert review_masks.get(store, 0)['version'] == before['version']
    assert review_masks.get(store, 0)['status'] == 'approved'
    assert review_masks.classes(store)['sha256'] == before['classes']['sha256']
    rows[0]['color'] = [91, 92, 93]
    objects = store.list_frames()
    review_classes.revise(store, request(store, 'pixel', rows, 1), 'admin', Conflict)
    after = review_masks.get(store, 0)
    assert after['status'] == 'pending' and after['version'] == before['version'] + 1
    assert (after['path'], after['sha256']) == (before['path'], before['sha256'])
    assert store.list_frames() == objects
    historical = review_versions.version(store, 'pixel', 0, before['version'])
    assert historical['available'] and historical['classes']['classes'][0]['color'] == [90, 90, 90]
    assert review_masks.get(store, 1)['status'] == excluded['status']
    assert review_masks.get(store, 1)['version'] == excluded['version'] + 1
    assert (store.state / 'pixel' / (after['classes']['sha256'] + '.yaml')).is_file()
    assert prior['sha256'] == after['sha256']


@pytest.mark.parametrize('mutation', [lambda rows: rows[0].update(name='renamed'),
    lambda rows: rows[0].update(index=255), lambda rows: rows[0].update(extra='bad'),
    lambda rows: rows[0].update(color=[True, 2, 3]), lambda rows: rows[0].update(role='wall')])
def test_pixel_revision_rejects_identity_changes_and_invalid_input(tmp_path, mutation):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    rows = copy.deepcopy(review_masks.served_classes(store)['classes'])
    mutation(rows)
    with pytest.raises(ValueError):
        review_classes.revise(store, request(store, 'pixel', rows, 0), 'admin', Conflict)


def test_revision_stale_impact_rejected_without_binding_change(tmp_path):
    store = open_store(tmp_path)
    before = review_classes.snapshot(store, 'object')
    rows = copy.deepcopy(before['binding']['classes'])
    rows.append(dict(index=len(rows), name='new_object', display='새 물체', color=[13, 27, 49]))
    with pytest.raises(Conflict):
        review_classes.revise(store, request(store, 'object', rows, 999), 'admin', Conflict)
    assert review_classes.snapshot(store, 'object') == before


def test_class_revision_http_requires_manager_csrf_and_matching_project(tmp_path):
    from test_learning_collaboration import running, request as http
    with running(tmp_path) as (url, _, store):
        assert http(url, '/api/classes?kind=object', 'editor')[0] == 403
        code, current = http(url, '/api/classes?kind=object', 'reviewer')
        assert code == 200 and current['workspace_id'] == 'alpha'
        rows = copy.deepcopy(current['binding']['classes'])
        rows[0]['display'] = '새 표시 이름'
        body = request(store, 'object', rows, 0)
        assert http(url, '/api/classes/revisions', 'reviewer', body)[0] == 403
        assert http(url, '/api/classes/revisions', 'editor', body, current['token'])[0] == 403
        assert http(url, '/api/classes/revisions', 'reviewer', dict(body, project_id='other'), current['token'])[0] == 400
        assert http(url, '/api/classes/revisions', 'reviewer', body, current['token'])[0] == 200
        assert class_sets.object_set(store)['sha256'] == current['binding']['sha256']


@pytest.mark.parametrize('lane', ['object', 'pixel'])
def test_pending_old_editor_cannot_approve_after_class_revision(tmp_path, lane):
    from test_learning_collaboration import running, request as http
    with running(tmp_path) as (url, _, store):
        review_masks.bind_classes(store, CLASSES)
        with store.connect() as db:
            db.execute("UPDATE frames SET status='pending' WHERE id=0")
        old_version = store.get(0)['version'] if lane == 'object' else review_masks.get(store, 0)['version']
        current = review_classes.snapshot(store, lane)
        rows = copy.deepcopy(current['binding']['classes'])
        if lane == 'object':
            rows.append(dict(index=len(rows), name='new_object', display='새 물체', color=[13, 27, 49]))
        else:
            rows[0]['color'] = [91, 92, 93]
        review_classes.revise(store, request(store, lane, rows, 0), 'admin', Conflict)
        assert (store.get(0) if lane == 'object' else review_masks.get(store, 0))['version'] == old_version + 1
        _, workspace = http(url, '/api/workspace', 'reviewer')
        path = '/api/frames/0' if lane == 'object' else '/api/masks/0'
        body = dict(version=old_version, action='approve', complete_frame_review=True, background_reviewed=True)
        assert http(url, path, 'reviewer', body, workspace['token'])[0] == 409
