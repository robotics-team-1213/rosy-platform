"""Pixel flood fill follows the photo's own colour boundary."""
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
