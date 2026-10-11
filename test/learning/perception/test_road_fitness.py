"""D-665 source tests; synthetic arrays are not independent real/sim acceptance."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
for directory in ("middleware/perception", "contracts/foundation", "operations/world/src",
                  "learning/evaluation/perception"):
    sys.path.insert(0, str(ROOT / directory))

from control.sensing.perception.learned.road_region import observed_road_region  # noqa: E402
from rosy.world.api import ObservationSnapshot, SnapshotValidity  # noqa: E402
from rosy.world.state.projections.road_region import road_region_input_errors  # noqa: E402
from road_fitness import evaluate_frame  # noqa: E402

CLASSES = [{"index": 0, "name": "floor", "role": "background"},
           {"index": 1, "name": "lane", "role": "lane_marking"},
           {"index": 2, "name": "road", "role": "drivable", "semantic": "road_surface/1"},
           {"index": 3, "name": "stop", "role": "stop_line"},
           {"index": 4, "name": "crosswalk", "role": "ignore"},
           {"index": 5, "name": "other_ignore", "role": "ignore"}]


def _labels(connected=False):
    labels = np.zeros((12, 12), np.int64)
    labels[:, :5] = labels[:, 7:] = 2
    labels[:, 5:7] = 1
    if connected:
        labels[9:, :] = 2
    return labels


def _snapshots():
    image = ObservationSnapshot("image", "camera", 1000, datetime(2026, 10, 11, tzinfo=timezone.utc),
                                "camera", "cal-v1", ("frame-sha",), SnapshotValidity.VALID, "tf-v1")
    anchor = replace(image, snapshot_id="anchor", source="pose_projection", evidence_refs=("image", "pose"))
    return image, anchor


def test_fork_keeps_both_branches_without_selecting_a_drive_way():
    mask, reason = observed_road_region(_labels(True), CLASSES, ((10, 5),))
    assert reason == "ok" and mask[2, 2] and mask[2, 9]
    assert not mask[2, 5]


def test_region_excludes_other_road_and_does_not_fill_occlusions():
    labels = _labels()
    labels[6, 2] = 255
    mask, reason = observed_road_region(labels, CLASSES, ((10, 2),))
    assert reason == "ok" and mask[2, 2] and not mask[:, 7:].any()
    assert not mask[6, 2]


@pytest.mark.parametrize("paint", [3, 4, 5])
def test_only_declared_road_paint_connects_regions(paint):
    labels = _labels()
    labels[6, :5] = paint
    mask, reason = observed_road_region(labels, CLASSES, ((10, 2),))
    assert reason == "ok" and not mask[6].any()
    assert bool(mask[2, 2]) is (paint != 5)


@pytest.mark.parametrize("seeds,reason", [
    ((), "no_anchor"), (((20, 2),), "anchor_out_of_frame"),
    (((10, 5),), "anchor_not_on_observed_road"),
    (((10, 2), (10, 9)), "ambiguous_region"),
])
def test_membership_without_one_verified_component_abstains(seeds, reason):
    mask, actual = observed_road_region(_labels(), CLASSES, seeds)
    assert mask is None and actual == reason


@pytest.mark.parametrize("semantic", [None, "current_road_region/1", "trajectory_band/1"])
def test_region_logic_does_not_reinterpret_legacy_road_labels(semantic):
    classes = [dict(c) for c in CLASSES]
    classes[2]["semantic"] = semantic
    with pytest.raises(ValueError, match="road_surface"):
        observed_road_region(_labels(), classes, ((10, 2),))


@pytest.mark.parametrize("change,reason", [
    ({"captured_at_ns": 800}, "anchor_stale"),
    ({"captured_at_ns": 1100}, "anchor_future"),
    ({"validity": SnapshotValidity.UNKNOWN}, "anchor_invalid"),
    ({"frame_id": "map"}, "frame_mismatch"),
    ({"calibration_revision": "other"}, "calibration_mismatch"),
    ({"transform_revision": None}, "transform_unverified"),
    ({"transform_revision": "other"}, "transform_mismatch"),
    ({"evidence_refs": ("other-image",)}, "image_reference_missing"),
])
def test_world_checks_projection_inputs_before_region_logic(change, reason):
    image, anchor = _snapshots()
    assert road_region_input_errors(image, anchor, now_ns=1050, max_age_ns=100) == ()
    errors = road_region_input_errors(image, replace(anchor, **change), now_ns=1050, max_age_ns=100)
    assert reason in errors


def test_paired_evaluation_keeps_truth_denominators_when_region_abstains():
    image, anchor = _snapshots()
    labels = _labels()
    road_truth = (labels == 2).astype(np.uint8)
    region_truth = np.zeros_like(road_truth)
    region_truth[:, :5] = 1
    region_truth[0] = 255
    report = evaluate_frame(labels, CLASSES, image, anchor, (), road_truth, region_truth,
                            domain="real", conditions=("occlusion",), now_ns=1050, max_age_ns=100)
    assert report["domain"] == "real" and report["conditions"] == ["occlusion"]
    assert report["road_surface"]["iou"] == 1
    assert report["current_region"]["valid_truth_pixels"] == 132
    assert report["current_region"]["unknown_truth_pixels"] == 12
    assert report["current_region"]["scored_pixels"] == 0
    assert report["current_region"]["iou"] is None and report["region_reason"] == "no_anchor"
    assert report["fitness_verdict"] == "HOLD"


def test_wrong_region_is_measured_separately_from_correct_whole_road():
    image, anchor = _snapshots()
    labels = _labels()
    road_truth = (labels == 2).astype(np.uint8)
    region_truth = np.zeros_like(road_truth)
    region_truth[:, 7:] = 1
    report = evaluate_frame(labels, CLASSES, image, anchor, ((10, 2),), road_truth, region_truth,
                            domain="simulation", conditions=(), now_ns=1050, max_age_ns=100)
    assert report["road_surface"]["iou"] == 1
    assert report["current_region"]["iou"] == 0
    assert report["current_region"]["other_region_included_pixels"] == 60
    assert report["current_region"]["self_region_missed_pixels"] == 60
    assert report["fitness_verdict"] == "HOLD"
