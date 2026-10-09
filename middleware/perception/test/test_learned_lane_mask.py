"""D-356 learned lane evidence: logits to the LaneObservation sign convention."""

import numpy as np
import pytest

from control.sensing.perception.learned.lane_mask import (
    MIN_COMPONENT_PX,
    LaneMaskEvidence,
    NonFiniteLogits,
    VisibleHysteresis,
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
    with pytest.raises(NonFiniteLogits):
        lane_evidence(bad, CLASSES)
    assert issubclass(NonFiniteLogits, ValueError)


def test_pixel_centre_reference():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 159:161] = 1  # columns 159,160 -> centroid 159.5 == (w-1)/2
    assert abs(lane_evidence(_logits(mask), CLASSES).error) < 1e-6


WALL = CLASSES + (ClassSpec(2, "wall", "wall"),)


def test_wall_fraction_is_the_near_field_band_share():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 150:170] = 1
    mask[:, 240:320] = 2          # a wall on the right quarter, whole height
    mask[:144, 0:80] = 2          # far-field wall only: outside the near band
    ev = lane_evidence(_logits(mask, 3), WALL)
    assert ev.wall_fraction == pytest.approx(0.25, abs=1e-6)
    assert ev.visible and abs(ev.error) < 0.02   # wall pixels never pull the lane centre


def test_wall_is_not_a_lane_target_even_without_lane_pixels():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 280:320] = 2
    ev = lane_evidence(_logits(mask, 3), WALL)
    assert not ev.visible and ev.error is None
    assert ev.wall_fraction == pytest.approx(0.125, abs=1e-6)


def test_no_wall_class_means_zero_wall_fraction():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 150:170] = 1
    assert lane_evidence(_logits(mask), CLASSES).wall_fraction == 0.0


def _reference_evidence(logits, classes):
    """The pre-2026-10-01 implementation: full-frame softmax, labels from it."""
    from control.sensing.perception.learned import lane_mask as lm

    probs = lm._softmax(logits[0].astype(np.float32))
    labels = probs.argmax(axis=0)
    fractions = {c.name: float((labels == c.index).sum()) / labels.size for c in classes}
    h, w = labels.shape
    band = slice(int(h * (1 - lm.NEAR_FIELD_FRACTION)), h)
    band_labels, band_conf = labels[band], probs.max(axis=0)[band]

    def _target(role):
        idx = [c.index for c in classes if c.role == role]
        return np.isin(band_labels, idx) if idx else np.zeros_like(band_labels, bool)

    wall = _target("wall")
    target = _target("drivable") & ~wall
    if target.mean() < lm.DRIVABLE_MIN_FRACTION:
        target = _target("lane_marking") & ~wall
    if not target.any():
        return LaneMaskEvidence(False, None, 0.0, fractions, float(wall.mean()))
    _, xs = np.nonzero(target)
    error = float(np.clip((xs.mean() - (w - 1) / 2.0) / (w / 2.0), -1.0, 1.0))
    confidence = float(np.clip(target.any(axis=1).mean() * band_conf[target].mean(), 0.0, 1.0))
    return LaneMaskEvidence(True, error, confidence, fractions, float(wall.mean()))


@pytest.mark.parametrize("seed", range(8))
def test_band_only_softmax_matches_the_full_frame_reference(seed):
    """D-373 CPU budget: softmax on the near-field band only, argmax on logits for
    the fractions; error and confidence stay bit-identical on random logits. The area
    filter (2026-10-02) is off here: random logits are all speckle, and this pins the
    softmax shortcut, not the filter."""
    classes = (ClassSpec(0, "floor", "background"), ClassSpec(1, "line", "lane_marking"),
               ClassSpec(2, "wall", "wall"), ClassSpec(3, "drivable", "drivable"))
    rng = np.random.default_rng(seed)
    logits = rng.normal(0.0, 3.0, (1, 4, 240, 320)).astype(np.float32)
    if seed % 2:
        logits[0, 3] -= 6.0  # drivable rare: the lane_marking fallback path
    got, want = lane_evidence(logits, classes, min_component_px=0), _reference_evidence(logits, classes)
    assert got == want


# --- 2026-10-02 post-processing audit: component area filter and visible hysteresis ------------

def _speckle(shape, seed=0, density=0.002):
    """The audit's false-positive model: 2-3 px blobs below the top quarter (carpet glare)."""
    rng = np.random.default_rng(seed)
    h, w = shape
    out = np.zeros(shape, np.int64)
    n = int(density * h * w / 4)
    for y, x, s in zip(rng.integers(h // 4, h - 3, n), rng.integers(0, w - 3, n), rng.integers(2, 4, n)):
        out[y:y + s, x:x + s] = 1
    return out


def test_speckle_alone_is_not_a_visible_lane():
    """Audit: speckle took `visible` from 0.896 to 1.000 (10 % false 'lane visible')."""
    ev = lane_evidence(_logits(_speckle((240, 320))), CLASSES)
    assert not ev.visible and ev.error is None


def test_speckle_does_not_move_a_real_lane():
    mask = np.zeros((240, 320), np.int64)
    mask[:, 260:280] = 1
    clean = lane_evidence(_logits(mask), CLASSES)
    noisy = lane_evidence(_logits(np.maximum(mask, _speckle(mask.shape))), CLASSES)
    assert noisy.visible and noisy.error == pytest.approx(clean.error, abs=1e-6)


def test_the_area_floor_is_configurable():
    blob = np.zeros((240, 320), np.int64)
    blob[200:205, 100:105] = 1                                      # 25 px
    assert not lane_evidence(_logits(blob), CLASSES).visible
    assert lane_evidence(_logits(blob), CLASSES, min_component_px=20).visible
    assert MIN_COMPONENT_PX == 40


def test_real_lane_label_stays_visible_and_speckle_does_not_shift_it():
    """133221Z/000120 D-379 auto label (lane_line = 1) through the shadow evidence path."""
    import cv2
    import perception_data
    lab = cv2.imread(str(perception_data.label_file(perception_data.SESSION_133221Z, 'masks', 120)),
                     cv2.IMREAD_UNCHANGED)
    lane = (lab == 1).astype(np.int64)
    clean = lane_evidence(_logits(lane), CLASSES)
    noisy = lane_evidence(_logits(np.maximum(lane, _speckle(lane.shape))), CLASSES)
    assert clean.visible and noisy.visible
    assert noisy.error == pytest.approx(clean.error, abs=.02)


def _ev(visible, confidence):
    return LaneMaskEvidence(visible, .1 if visible else None, confidence, {})


def test_visible_hysteresis_enters_at_035_and_exits_below_025():
    gate = VisibleHysteresis()
    assert (gate.enter, gate.exit) == (.35, .25)
    seq = [(True, .30), (True, .35), (True, .25), (True, .24), (True, .30), (True, .40), (False, .9)]
    out = [gate.update(_ev(*v)) for v in seq]
    assert [o.visible for o in out] == [False, True, True, False, False, True, False]
    assert out[0].error is None and out[1].error == .1
    assert out[1].confidence == .35          # confidence is passed through untouched


def test_visible_hysteresis_rejects_inverted_thresholds():
    with pytest.raises(ValueError):
        VisibleHysteresis(enter=.2, exit=.3)


V13 = (ClassSpec(0, "background", "background"), ClassSpec(1, "lane_left", "lane_marking"),
       ClassSpec(2, "lane_right", "lane_marking"), ClassSpec(3, "crosswalk", "ignore"),
       ClassSpec(4, "speed_bump", "ignore"), ClassSpec(5, "drivable", "drivable"))


def test_inner_half_of_a_touching_boundary_line_is_drivable():
    """D-554 item 10: drivable 110-209 (centred); lane_left 100-109 touches it, lane_right does
    not (gap 210-211), so only lane_left 105-109 joins the target: mean x 157 -> -2.5/160."""
    mask = np.zeros((240, 320), np.int64)
    mask[:, 100:110], mask[:, 110:210], mask[:, 212:222] = 1, 5, 2
    ev = lane_evidence(_logits(mask, 6), V13)
    assert ev.error == pytest.approx(-2.5 / 160)
    mask[:, 210:212] = 5  # now lane_right touches too: 212-216 joins, mean x 160.5
    assert lane_evidence(_logits(mask, 6), V13).error == pytest.approx(1.0 / 160)

