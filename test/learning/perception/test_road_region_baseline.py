"""D-659: evaluate observed region candidates separately from the chosen drive way."""
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
for folder in ("middleware/perception", "contracts/foundation"):
    sys.path.insert(0, str(ROOT / folder))

from control.sensing.perception.learned.drivable_paint import drivable_target  # noqa: E402
from control.sensing.perception.learned.lane_mask import lane_bounded_drivable  # noqa: E402
from control.sensing.perception.learned.manifest import ClassSpec  # noqa: E402

CLASSES = (ClassSpec(0, "background", "background"),
           ClassSpec(1, "lane_left", "lane_marking"),
           ClassSpec(2, "lane_right", "lane_marking"),
           ClassSpec(3, "crosswalk", "ignore"),
           ClassSpec(4, "speed_bump", "ignore"),
           ClassSpec(5, "drivable", "drivable"))


def candidate(labels, *, ignore_top=0):
    return lane_bounded_drivable(labels, 5, [1, 2], through_idxs=[3, 4],
                                 max_row_growth=math.inf, ignore_top=ignore_top)


def test_connected_fork_is_observed_before_a_drive_branch_is_chosen():
    labels = np.zeros((240, 320), np.int64)
    labels[160:, 130:191] = 5
    labels[60:160, 100:151] = 5
    labels[60:160, 170:231] = 5
    labels[60:160, 151:170] = 1
    observed = candidate(labels)
    assert observed[100, 100:151].all()
    assert observed[100, 170:231].all()
    logits = np.eye(len(CLASSES), dtype=np.float32)[labels].transpose(2, 0, 1)[None]
    chosen, info = drivable_target(logits, CLASSES)
    assert info["reason"] == "ok" and info["branches"] == 2
    assert chosen[100, 170:231].all() and not chosen[100, 100:151].any()
    assert np.all(~(chosen & (labels == 5)) | observed)


def test_another_disconnected_road_is_not_the_robot_region():
    labels = np.zeros((240, 320), np.int64)
    labels[120:, 130:191] = 5
    labels[120:, 10:80] = 5
    observed = candidate(labels)
    assert observed[180, 130:191].all()
    assert not observed[:, 10:80].any()
    assert (labels == 5).sum() > observed.sum()


def test_visible_region_does_not_fill_occlusions_or_unobserved_crop():
    labels = np.zeros((240, 320), np.int64)
    labels[80:, 120:201] = 5
    labels[160:180, 145:175] = 0
    labels[190:195, 120:201] = 3
    observed = candidate(labels, ignore_top=128)
    assert not observed[:128].any()
    assert not observed[160:180, 145:175].any()
    assert not observed[190:195].any()
    assert observed[150, 120:201].all() and observed[200, 120:201].all()
    logits = np.eye(len(CLASSES), dtype=np.float32)[labels].transpose(2, 0, 1)[None]
    chosen, info = drivable_target(logits, CLASSES, ignore_top=128)
    assert info["reason"] == "ok"
    assert chosen[160:180, 145:175].all()
    assert not chosen[:128].any()


def test_missing_centre_seed_is_a_heuristic_not_verified_region_membership():
    labels = np.zeros((240, 320), np.int64)
    labels[120:, 110:145] = 5
    labels[120:, 180:260] = 5
    observed = candidate(labels)
    assert observed[180, 180:260].all()
    assert not observed[:, 110:145].any()
    assert not (labels[:, labels.shape[1] // 2] == 5).any()
