"""D-356 learned lane evidence: logits to the LaneObservation sign convention."""

import numpy as np
import pytest

from control.sensing.perception.learned.lane_mask import (
    LaneMaskEvidence,
    lane_evidence,
    preprocess,
)
from control.sensing.perception.learned.manifest import ClassSpec, InputSpec

CLASSES = (ClassSpec(0, "floor", "background"), ClassSpec(1, "line", "lane_marking"))
SPEC = InputSpec((1, 3, 240, 320), "rgb", 1 / 255, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5))


def _logits(mask: np.ndarray, n_classes: int = 2) -> np.ndarray:
    out = np.full((1, n_classes, *mask.shape), -5.0, np.float32)
    for c in range(n_classes):
        out[0, c][mask == c] = 5.0
    return out


def test_preprocess_shape_color_and_normalisation():
    bgr = np.zeros((240, 320, 3), np.uint8)
    bgr[..., 2] = 255  # red in BGR
    x = preprocess(bgr, SPEC)
    assert x.shape == (1, 3, 240, 320) and x.dtype == np.float32
    assert x[0, 0].max() == pytest.approx(1.0)   # R channel first for rgb
    assert x[0, 2].min() == pytest.approx(-1.0)  # B channel empty


def test_preprocess_resizes_other_frame_sizes():
    x = preprocess(np.zeros((480, 640, 3), np.uint8), SPEC)
    assert x.shape == (1, 3, 240, 320)


def test_centred_lane_gives_zero_error():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 150:170] = 1
    ev = lane_evidence(_logits(mask), CLASSES)
    assert ev.visible and abs(ev.error) < 0.02 and ev.confidence > 0.9


def test_lane_right_of_centre_is_positive():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 260:280] = 1
    ev = lane_evidence(_logits(mask), CLASSES)
    assert ev.error > 0.5


def test_no_lane_pixels_is_not_visible():
    ev = lane_evidence(_logits(np.zeros((240, 320), np.int64)), CLASSES)
    assert ev == LaneMaskEvidence(False, None, 0.0, ev.class_fractions)
    assert ev.class_fractions["floor"] == pytest.approx(1.0)


def test_only_far_field_lane_is_not_visible():
    mask = np.zeros((240, 320), np.int64)
    mask[:100, 150:170] = 1  # top rows only
    assert not lane_evidence(_logits(mask), CLASSES).visible


def test_drivable_role_preferred_when_present():
    classes = CLASSES + (ClassSpec(2, "road", "drivable"),)
    mask = np.zeros((240, 320), np.int64)
    mask[:, 0:20] = 1          # a boundary line far left
    mask[:, 200:300] = 2       # drivable area right of centre
    ev = lane_evidence(_logits(mask, 3), classes)
    assert ev.error > 0.3


def test_non_finite_logits_raise():
    bad = _logits(np.zeros((240, 320), np.int64))
    bad[0, 0, 0, 0] = np.nan
    with pytest.raises(ValueError):
        lane_evidence(bad, CLASSES)


def test_pixel_centre_reference():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 159:161] = 1  # columns 159,160 -> centroid 159.5 == (w-1)/2
    assert abs(lane_evidence(_logits(mask), CLASSES).error) < 1e-6
