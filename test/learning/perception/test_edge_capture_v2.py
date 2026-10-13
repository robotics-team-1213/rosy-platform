"""edge_capture.merge_v2: LiDAR base + lane-model components >= 40 px, 255 elsewhere."""
import numpy as np

import edge_capture
from labels import FLOOR, IGNORE_INDEX, LANE, WALL


def test_no_base_is_all_unlabelled_plus_big_lane_components():
    model = np.zeros((20, 20), np.uint8)
    model[2:12, 2:6] = LANE          # 40 px: kept
    model[15:17, 15:18] = LANE       # 6 px: speckle
    d = edge_capture.merge_v2(None, model)
    assert (d[2:12, 2:6] == LANE).all()
    assert (d[15:17, 15:18] == IGNORE_INDEX).all()
    assert set(np.unique(d)) == {LANE, IGNORE_INDEX}


def test_lane_never_paints_over_wall_and_base_is_not_modified():
    base = np.full((20, 20), FLOOR, np.uint8)
    base[:, 10:] = WALL
    model = np.zeros_like(base)
    model[0:10, 5:15] = LANE         # 50 lane-model pixels on floor, 50 on wall
    d = edge_capture.merge_v2(base, model)
    assert (d[0:10, 5:10] == LANE).all() and (d[:, 10:] == WALL).all()
    assert (base[0:10, 5:10] == FLOOR).all()


def test_component_size_is_counted_after_the_wall_cut():
    base = np.full((20, 20), WALL, np.uint8)
    base[0:5, 0:5] = FLOOR           # only 25 lane pixels can land on floor
    model = np.full_like(base, LANE)
    d = edge_capture.merge_v2(base, model)
    assert (d[0:5, 0:5] == FLOOR).all()
