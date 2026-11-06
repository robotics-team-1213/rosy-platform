"""Pixel flood fill follows the photo's own colour boundary."""
import json

import numpy as np
import pytest

from test_review_app import open_store
from test_review_cycle import CLASSES
from review_app import Conflict
import review_masks


def bound_store(tmp_path):
    store = open_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    return store


def test_flood_fills_connected_similar_region_only(tmp_path):
    store = bound_store(tmp_path)
    review = review_masks.get(store, 0)
    assert review['width'] == 32 and review['height'] == 24
    flooded = review_masks.update(store, 0, {'version': 0, 'action': 'flood',
                                             'label': 2, 'seed': [0, 0], 'tolerance': 100},
                                  Conflict)
    assert flooded['version'] == 1 and flooded['status'] == 'pending'
    assert np.all(review_masks.pixels(store, flooded) == 2)


def test_flood_rejects_bad_seed_tolerance_and_label(tmp_path):
    pytest.importorskip('cv2'), pytest.importorskip('numpy')
    store = bound_store(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        review_masks.update(store, 0, {'version': 0, 'action': 'flood',
                                       'label': 2, 'seed': [32, 0], 'tolerance': 16},
                            Conflict)
    with pytest.raises(ValueError, match='tolerance'):
        review_masks.update(store, 0, {'version': 0, 'action': 'flood',
                                       'label': 2, 'seed': [0, 0], 'tolerance': 101},
                            Conflict)
    with pytest.raises(ValueError, match='known mask index'):
        review_masks.update(store, 0, {'version': 0, 'action': 'flood',
                                       'label': 9, 'seed': [0, 0], 'tolerance': 16},
                            Conflict)
    with pytest.raises(Conflict):
        review_masks.update(store, 0, {'version': 9, 'action': 'flood',
                                       'label': 2, 'seed': [0, 0], 'tolerance': 16},
                            Conflict)
    assert review_masks.get(store, 0)['version'] == 0


def test_flood_is_undoable_and_approvable(tmp_path):
    pytest.importorskip('cv2'), pytest.importorskip('numpy')
    store = bound_store(tmp_path)
    flooded = review_masks.update(store, 0, {'version': 0, 'action': 'flood',
                                             'label': 0, 'seed': [5, 5], 'tolerance': 100},
                                  Conflict)
    undone = review_masks.update(store, 0, {'version': flooded['version'], 'action': 'undo'},
                                 Conflict)
    assert undone['status'] == 'pending'
    assert np.all(review_masks.pixels(store, undone) == 255)
    painted = review_masks.update(
        store, 0, {'version': undone['version'], 'action': 'flood',
                   'label': 3, 'seed': [1, 1], 'tolerance': 100}, Conflict)
    approved = review_masks.update(store, 0, {'version': painted['version'], 'action': 'approve',
                                              'complete_frame_review': True,
                                              'background_reviewed': True}, Conflict)
    assert approved['status'] == 'approved'
    assert np.all(review_masks.pixels(store, approved) == 3)


def test_flood_preserves_high_contrast_photo_boundary(tmp_path):
    from types import SimpleNamespace
    import cv2

    photo = np.array([[[0, 0, 0], [255, 255, 32], [255, 255, 32]]], dtype=np.uint8)
    image = tmp_path / 'high-contrast.png'
    assert cv2.imwrite(str(image), photo)
    store = SimpleNamespace(image=lambda index: image)
    region = review_masks.flood_region(store, 0, {'width': 3, 'height': 1}, [0, 0], 16)
    assert region.tolist() == [[True, False, False]]


def test_flood_lab_distance_and_four_connectivity():
    pytest.importorskip('cv2')
    grey = np.full((4, 6, 3), 120, dtype=np.uint8)
    grey[:, 3:] = 200
    left = review_masks.flood_region_photo(grey, [0, 0], 10)
    assert left[:, :3].all() and not left[:, 3:].any()
    diagonal = np.array([[[10, 10, 10], [200, 200, 200]],
                         [[200, 200, 200], [10, 10, 10]]], dtype=np.uint8)
    region = review_masks.flood_region_photo(diagonal, [0, 0], 0)
    assert region.tolist() == [[True, False], [False, False]]


def test_flood_one_pixel_barrier_blocks_region():
    pytest.importorskip('cv2')
    photo = np.full((5, 5, 3), 100, dtype=np.uint8)
    photo[2, :] = (0, 0, 255)
    region = review_masks.flood_region_photo(photo, [0, 0], 10)
    assert region[:2].all() and not region[2:].any()


def test_multiple_lane_samples_cover_shading_without_spilling_to_floor():
    pytest.importorskip('cv2')
    photo = np.full((8, 12, 3), 70, dtype=np.uint8)
    photo[2:6, :6] = (205, 205, 205)
    photo[2:6, 6:] = (235, 235, 235)
    selected, tolerance = review_masks.sampled_region_photo(photo, [[2, 3], [9, 3]], 'auto')
    assert 8 <= tolerance <= 40
    assert selected[2:6].all()
    assert not selected[:2].any() and not selected[6:].any()


def test_sample_preview_does_not_save_and_apply_is_undoable(tmp_path):
    store = bound_store(tmp_path)
    body = {'version': 0, 'label': 2, 'seeds': [[0, 0], [10, 10]], 'tolerance': 'auto'}
    png, count, tolerance = review_masks.preview(store, 0, body, Conflict)
    assert png.startswith(b'\x89PNG') and count > 0 and 8 <= tolerance <= 40
    assert review_masks.get(store, 0)['version'] == 0
    saved = review_masks.update(store, 0, dict(body, action='sample', tolerance=tolerance), Conflict)
    assert saved['version'] == 1 and saved['status'] == 'pending'
    undone = review_masks.update(store, 0, {'version': 1, 'action': 'undo'}, Conflict)
    assert np.all(review_masks.pixels(store, undone) == 255)


def test_sample_rejects_unbounded_points_and_stale_version(tmp_path):
    store = bound_store(tmp_path)
    body = {'version': 0, 'label': 2, 'seeds': [[0, 0]] * 33, 'tolerance': 16}
    with pytest.raises(ValueError, match='1..32'):
        review_masks.preview(store, 0, body, Conflict)
    with pytest.raises(Conflict):
        review_masks.preview(store, 0, dict(body, version=1), Conflict)
    with pytest.raises(ValueError, match='1..32'):
        review_masks.update(store, 0, dict(body, action='sample'), Conflict)
    assert review_masks.get(store, 0)['version'] == 0


@pytest.mark.parametrize('action', ['sample', 'polygon'])
def test_protected_selection_preserves_distinct_labels_and_explicit_replacement(tmp_path, action):
    store = bound_store(tmp_path)
    marked = review_masks.update(store, 0, {'version': 0, 'action': 'paint',
                                          'label': 2, 'radius': 0, 'points': [[2, 2]]}, Conflict)
    before = review_masks.pixels(store, marked).copy()
    body = {'version': marked['version'], 'label': 3, 'preserve_existing': True,
            'seeds': [[0, 0]], 'tolerance': 100,
            'points': [[0, 0], [31, 0], [31, 23], [0, 23]]}
    if action == 'sample':
        import cv2
        png, count, _ = review_masks.preview(store, 0, body, Conflict)
        preview = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        assert count == before.size - 1
        assert preview[2, 2] == 255
    saved = review_masks.update(store, 0, dict(body, action=action), Conflict)
    after = review_masks.pixels(store, saved)
    assert after[2, 2] == 2 and np.all(after[before == 255] == 3)
    assert saved['status'] == 'pending'
    restored = review_masks.update(store, 0, {'version': saved['version'], 'action': 'undo'}, Conflict)
    assert np.array_equal(review_masks.pixels(store, restored), before)
    replaced = review_masks.update(store, 0, dict(body, action=action, version=restored['version'],
                                                preserve_existing=False), Conflict)
    assert np.all(review_masks.pixels(store, replaced) == 3)
    with pytest.raises(ValueError, match='boolean'):
        review_masks.update(store, 0, dict(body, action=action, version=replaced['version'],
                                         preserve_existing='true'), Conflict)


@pytest.mark.parametrize('seeds,corrected', [
    ([[2, 2]], [(2, 2), (3, 2)]),
    ([[0, 0]], []),
    ([[2, 2], [6, 6], [8, 8]], [(2, 2), (3, 2), (6, 6), (8, 8)]),
])
def test_protected_sample_corrects_only_explicitly_seeded_mask_components(tmp_path, seeds, corrected):
    import cv2

    store = bound_store(tmp_path)
    marked = review_masks.get(store, 0)
    for label, point in [(2, [2, 2]), (2, [3, 2]), (2, [4, 3]), (2, [6, 6]), (1, [8, 8])]:
        marked = review_masks.update(store, 0, {'version': marked['version'], 'action': 'paint',
                                             'label': label, 'radius': 0, 'points': [point]}, Conflict)
    before = review_masks.pixels(store, marked).copy()
    selected = before == 255
    for x, y in corrected:
        selected[y, x] = True
    expected = before.copy()
    expected[selected] = 3
    body = {'version': marked['version'], 'label': 3, 'seeds': seeds,
            'tolerance': 100, 'preserve_existing': True}
    png, count, _ = review_masks.preview(store, 0, body, Conflict)
    preview = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert count == int(selected.sum())
    assert np.array_equal(preview, np.where(selected, 3, 255))
    assert review_masks.get(store, 0)['version'] == marked['version']
    assert np.array_equal(review_masks.pixels(store, marked), before)
    saved = review_masks.update(store, 0, dict(body, action='sample'), Conflict)
    assert np.array_equal(review_masks.pixels(store, saved), expected)
    assert saved['status'] == 'pending'


def test_protected_sample_still_respects_photo_boundary_within_seeded_component(tmp_path):
    from test_review_app import bright_store

    store = bright_store(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    marked = review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 2}, Conflict)
    body = {'version': marked['version'], 'label': 3, 'seeds': [[0, 0]],
            'tolerance': 0, 'preserve_existing': True}
    _, count, _ = review_masks.preview(store, 0, body, Conflict)
    assert 0 < count < marked['width'] * marked['height']
    saved = review_masks.update(store, 0, dict(body, action='sample'), Conflict)
    image = review_masks.pixels(store, saved)
    assert image[0, 0] == 3 and image[0, -1] == 2


@pytest.mark.parametrize('entry', ['preview', 'sample', 'polygon'])
@pytest.mark.parametrize('preserve', [1, 'true', None, [], {}])
def test_protected_selection_requires_typed_boolean_without_saving(tmp_path, entry, preserve):
    store = bound_store(tmp_path)
    body = {'version': 0, 'label': 3, 'preserve_existing': preserve, 'seeds': [[0, 0]],
            'tolerance': 100, 'points': [[0, 0], [31, 0], [31, 23], [0, 23]]}
    with pytest.raises(ValueError, match='preserve_existing must be boolean'):
        if entry == 'preview':
            review_masks.preview(store, 0, body, Conflict)
        else:
            review_masks.update(store, 0, dict(body, action=entry), Conflict)
    assert review_masks.get(store, 0)['version'] == 0


def indexed_selection(store, image, *, frame=0, withdrawn=0, origin=None):
    path, digest = review_masks.freeze(store, review_masks.encode(image))
    with store.connect() as db:
        db.execute('INSERT INTO pixel_drafts(frame,sha256,path,catalog_sha256,withdrawn,origin) VALUES (?,?,?,?,?,?)',
                   (frame, digest, path, '0' * 64, withdrawn,
                    json.dumps(origin) if isinstance(origin, dict) else origin))
    return path, digest


@pytest.mark.parametrize('preserve', [True, False])
def test_indexed_sample_selection_preview_and_apply_share_protected_region(tmp_path, preserve):
    import cv2

    store = bound_store(tmp_path)
    marked = review_masks.get(store, 0)
    for label, point in [(2, [2, 2]), (2, [3, 2]), (2, [6, 6]), (1, [8, 8])]:
        marked = review_masks.update(store, 0, {'version': marked['version'], 'action': 'paint',
                                             'label': label, 'radius': 0, 'points': [point]}, Conflict)
    before = review_masks.pixels(store, marked).copy()
    candidate = np.full(before.shape, 255, np.uint8)
    candidate[1:10, 1:10] = 3
    candidate[12, 12] = 1
    _, digest = indexed_selection(store, candidate)
    selected = candidate == 3
    if preserve:
        editable = before == 255
        editable[2, 2:4] = True
        selected &= editable
    expected = before.copy()
    expected[selected] = 3
    body = {'version': marked['version'], 'label': 3, 'seeds': [[2, 2]],
            'selection_sha256': digest, 'preserve_existing': preserve}
    png, count, tolerance = review_masks.preview(store, 0, body, Conflict)
    preview = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert tolerance == 0 and count == int(selected.sum())
    assert np.array_equal(preview, np.where(selected, 3, 255))
    assert review_masks.get(store, 0)['version'] == marked['version']
    saved = review_masks.update(store, 0, dict(body, action='sample'), Conflict)
    assert np.array_equal(review_masks.pixels(store, saved), expected)
    assert saved['status'] == 'pending'


@pytest.mark.parametrize('entry', ['preview', 'sample'])
@pytest.mark.parametrize('failure', ['missing', 'wrong_frame', 'withdrawn', 'tampered',
                                    'malformed', 'invalid_digest', 'wrong_size'])
def test_indexed_sample_selection_rejects_unavailable_or_corrupted_candidate(tmp_path, entry, failure):
    store = bound_store(tmp_path)
    candidate = np.full((2, 2) if failure == 'wrong_size' else (24, 32), 3, np.uint8)
    path, digest = indexed_selection(store, candidate, frame=1 if failure == 'wrong_frame' else 0,
                                     withdrawn=int(failure == 'withdrawn'))
    if failure == 'missing':
        digest = 'f' * 64
    elif failure == 'tampered':
        (store.state / path).write_bytes(b'corrupted candidate')
    elif failure == 'malformed':
        digest = 123
    elif failure == 'invalid_digest':
        digest = '../candidate.png'
    body = {'version': 0, 'label': 3, 'seeds': [[0, 0]], 'selection_sha256': digest,
            'preserve_existing': True}
    with pytest.raises(ValueError):
        if entry == 'preview':
            review_masks.preview(store, 0, body, Conflict)
        else:
            review_masks.update(store, 0, dict(body, action='sample'), Conflict)
    assert review_masks.get(store, 0)['version'] == 0


@pytest.mark.parametrize('entry', ['preview', 'sample'])
def test_indexed_sample_selection_cannot_erase_the_outside_sentinel(tmp_path, entry):
    store = bound_store(tmp_path)
    marked = review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 2}, Conflict)
    candidate = np.full((24, 32), 255, np.uint8)
    candidate[1:10, 1:10] = 3
    _, digest = indexed_selection(store, candidate)
    body = {'version': marked['version'], 'label': 255, 'seeds': [[2, 2]],
            'selection_sha256': digest, 'preserve_existing': False}
    with pytest.raises(ValueError):
        if entry == 'preview':
            review_masks.preview(store, 0, body, Conflict)
        else:
            review_masks.update(store, 0, dict(body, action='sample'), Conflict)
    assert review_masks.get(store, 0)['version'] == marked['version']
    assert np.all(review_masks.pixels(store, marked) == 2)


@pytest.mark.parametrize('entry', ['preview', 'sample'])
@pytest.mark.parametrize('provenance', ['human_points', 'learned', 'missing', 'malformed',
                                       'other_label', 'other_points', 'other_checkpoint'])
def test_evaluation_indexed_selection_requires_matching_recorded_human_points(tmp_path, entry, provenance):
    store = bound_store(tmp_path)
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES ('workspace_kind','evaluation')")
    origin = {'action': 'sam_points', 'sam_prompt': {'label': 3, 'points': [[2, 2]]},
              'job_id': 'a' * 32, 'requested_by': 'human-reviewer', 'model': 'sam3',
              'model_digest': 'b' * 64, 'sam_checkpoint_sha256': 'b' * 64}
    if provenance == 'learned':
        origin['action'] = 'pixel_draft'
    elif provenance == 'missing':
        origin = None
    elif provenance == 'malformed':
        origin = 'legacy-sam-candidate'
    elif provenance == 'other_label':
        origin['sam_prompt']['label'] = 2
    elif provenance == 'other_points':
        origin['sam_prompt']['points'] = [[4, 4]]
    elif provenance == 'other_checkpoint':
        origin['model_digest'] = 'c' * 64
    candidate = np.full((24, 32), 255, np.uint8)
    candidate[1:4, 1:4] = 3
    _, digest = indexed_selection(store, candidate, origin=origin)
    body = {'version': 0, 'label': 3, 'seeds': [[2, 2]], 'selection_sha256': digest,
            'preserve_existing': True}

    def select():
        if entry == 'preview':
            return review_masks.preview(store, 0, body, Conflict)
        return review_masks.update(store, 0, dict(body, action='sample'), Conflict)

    if provenance != 'human_points':
        with pytest.raises(ValueError, match='evaluation.*human'):
            select()
        assert review_masks.get(store, 0)['version'] == 0
    elif entry == 'preview':
        _, count, tolerance = select()
        assert count == 9 and tolerance == 0
        assert review_masks.get(store, 0)['version'] == 0
    else:
        saved = select()
        assert saved['status'] == 'pending'
        assert np.array_equal(review_masks.pixels(store, saved), candidate)


@pytest.mark.parametrize('entry', ['preview', 'sample'])
@pytest.mark.parametrize('failure', ['failed', 'other_frame', 'other_digest', 'other_points',
                                    'other_checkpoint', 'missing_requester'])
def test_evaluation_selection_origin_cannot_override_durable_job_provenance(tmp_path, entry, failure):
    store = bound_store(tmp_path)
    origin = {'action': 'sam_points', 'sam_prompt': {'label': 3, 'points': [[2, 2]]},
              'job_id': 'a' * 32, 'requested_by': 'human-reviewer', 'model': 'sam3',
              'model_digest': 'b' * 64, 'sam_checkpoint_sha256': 'b' * 64}
    candidate = np.full((24, 32), 3, np.uint8)
    _, digest = indexed_selection(store, candidate, origin=origin)
    job = {'id': 'a' * 32, 'frame': 0, 'action': 'sam_points', 'state': 'succeeded',
           'label': 3, 'points': [[2, 2]], 'actor': 'human-reviewer', 'model': 'sam3',
           'model_digest': 'b' * 64, 'sam_checkpoint_sha256': 'b' * 64,
           'image_sha256': store.get(0)['source']['image_sha256'],
           'classes_sha256': review_masks.classes(store)['sha256'],
           'result': {'selection_sha256': digest, 'candidate_sha256': digest, 'selected_pixels': 768}}
    if failure == 'failed':
        job['state'] = 'failed'
    elif failure == 'other_frame':
        job['frame'] = 1
    elif failure == 'other_digest':
        job['result']['selection_sha256'] = 'f' * 64
    elif failure == 'other_points':
        job['points'] = [[4, 4]]
    elif failure == 'other_checkpoint':
        job['model_digest'] = 'c' * 64
    elif failure == 'missing_requester':
        job['actor'] = ''
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES ('workspace_kind','evaluation')")
        db.execute('CREATE TABLE review_ai_jobs(id TEXT PRIMARY KEY, frame INTEGER NOT NULL, document TEXT NOT NULL)')
        db.execute('INSERT INTO review_ai_jobs VALUES (?,?,?)', (job['id'], job['frame'], json.dumps(job)))
    body = {'version': 0, 'label': 3, 'seeds': [[2, 2]], 'selection_sha256': digest,
            'preserve_existing': True}
    with pytest.raises(ValueError, match='evaluation.*human'):
        if entry == 'preview':
            review_masks.preview(store, 0, body, Conflict)
        else:
            review_masks.update(store, 0, dict(body, action='sample'), Conflict)
    assert review_masks.get(store, 0)['version'] == 0


def test_flood_refused_on_excluded_frame_and_demotes_approval(tmp_path):
    pytest.importorskip('cv2'), pytest.importorskip('numpy')
    store = bound_store(tmp_path)
    with pytest.raises(ValueError, match='재검수'):
        review_masks.update(store, 1, {'version': 0, 'action': 'flood',
                                       'label': 2, 'seed': [0, 0], 'tolerance': 16},
                            Conflict)
    filled = review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0},
                                 Conflict)
    approved = review_masks.update(store, 0, {'version': filled['version'], 'action': 'approve',
                                              'complete_frame_review': True,
                                              'background_reviewed': True}, Conflict)
    assert approved['status'] == 'approved'
    demoted = review_masks.update(store, 0, {'version': approved['version'], 'action': 'flood',
                                             'label': 2, 'seed': [0, 0], 'tolerance': 100},
                                  Conflict)
    assert demoted['status'] == 'pending'
    assert np.all(review_masks.pixels(store, demoted) == 2)


def test_flood_rejects_photo_dimension_mismatch(tmp_path):
    from types import SimpleNamespace
    cv2 = pytest.importorskip('cv2')
    image = tmp_path / 'wide.png'
    assert cv2.imwrite(str(image), np.zeros((4, 8, 3), dtype=np.uint8))
    store = SimpleNamespace(image=lambda index: image)
    with pytest.raises(ValueError, match='dimensions differ'):
        review_masks.flood_region(store, 0, {'width': 8, 'height': 8}, [0, 0], 16)
