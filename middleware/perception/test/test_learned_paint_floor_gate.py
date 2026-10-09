"""D-588 floor gate on the learned paint mask: lane pixels on a wall are dropped, floor tape stays."""

import numpy as np
import pytest

from control.sensing.perception.lane_keep_lines import clean_learned_mask
from control.sensing.perception.learned.lane_mask import (
    FOOT_GAP_FRACTION, WALL_CODE, NoWallClass, floor_paint, lane_marking_mask)
from control.sensing.perception.learned.manifest import ClassSpec, ManifestError
from control.sensing.perception.learned.runner import LaneSegModel

FLOOR, LANE, WALL, DRIVABLE = 0, 1, 2, 3
CLASSES = (ClassSpec(0, "floor", "background"), ClassSpec(1, "lane_line", "lane_marking"),
           ClassSpec(2, "wall", "wall"), ClassSpec(3, "drivable", "drivable"))
H, W = 240, 320
WALL_FOOT = 100   # rows 0..99 are wall, the floor starts at row 100
HORIZON = 60.0    # gap tolerance below the foot: floor(0.25 * (99 - 60)) = 9 rows


def _scene() -> np.ndarray:
    labels = np.full((H, W), FLOOR, np.int64)
    labels[:WALL_FOOT] = WALL
    return labels


def _logits(labels: np.ndarray, n_classes: int = len(CLASSES)) -> np.ndarray:
    out = np.full((1, n_classes, *labels.shape), -5.0, np.float32)
    for c in range(n_classes):
        out[0, c][labels == c] = 5.0
    return out


def _gated(labels):
    return floor_paint(lane_marking_mask(_logits(labels), CLASSES, floor_gate=True), HORIZON).astype(bool)


def test_gated_mask_carries_wall_codes_and_ungated_stays_binary():
    labels = _scene()
    labels[150:240, 40:60] = LANE
    gated = lane_marking_mask(_logits(labels), CLASSES, floor_gate=True)
    assert set(np.unique(gated)) == {0, 1, WALL_CODE} and (gated[:WALL_FOOT] == WALL_CODE).all()
    assert set(np.unique(lane_marking_mask(_logits(labels), CLASSES))) == {0, 1}


def test_lane_pixels_painted_on_the_wall_are_dropped():
    labels = _scene()
    labels[60:90, 250:300] = LANE                # blob on the wall face (28e8454d, SIM 2026-10-09)
    assert lane_marking_mask(_logits(labels), CLASSES)[60:90, 250:300].all()   # gate off: as before
    assert not _gated(labels).any()


def test_wall_paint_reaching_down_to_the_floor_is_dropped():
    labels = _scene()
    labels[70:110, 280:320] = LANE               # the blob runs past the wall foot onto the floor
    labels[85:88, 290:300] = WALL                # wall specks inside the blob do not stop the walk
    assert not _gated(labels).any()


def test_band_along_the_wall_foot_is_dropped():
    labels = _scene()
    labels[WALL_FOOT:WALL_FOOT + 3, :] = LANE    # floor-wall seam painted as lane
    assert not _gated(labels).any()


def test_floor_lines_are_kept():
    labels = _scene()
    labels[150:240, 40:60] = LANE                # left line
    labels[150:240, 260:280] = LANE              # right line
    labels[200:210, 60:260] = DRIVABLE
    expected = labels == LANE
    assert np.array_equal(_gated(labels), expected)


def test_band_along_the_wall_foot_behind_a_short_floor_gap_is_dropped():
    labels = _scene()
    labels[WALL_FOOT + 4:WALL_FOOT + 10, :] = LANE      # 4 floor rows, then paint hugging the foot
    labels[150:240, 40:60] = LANE                        # a real line well away from the wall
    assert np.array_equal(_gated(labels), (labels == LANE) & (np.arange(H)[:, None] >= 150))


def test_corner_tape_near_the_wall_is_kept_when_floor_shows_between():
    gap = int(FOOT_GAP_FRACTION * (WALL_FOOT - 1 - HORIZON)) + 2
    labels = _scene()
    labels[WALL_FOOT + gap:WALL_FOOT + gap + 6, 0:320] = LANE   # transverse corner tape on the floor
    labels[WALL_FOOT + gap + 6:240, 300:310] = LANE              # and the line running into it
    assert np.array_equal(_gated(labels), labels == LANE)


def test_stray_wall_speck_on_the_floor_does_not_cut_a_line():
    labels = _scene()
    labels[150:240, 150:170] = LANE
    labels[200:205, 150:170] = WALL              # misread speck inside the tape, not connected to the wall
    labels[230:235, 150:170] = WALL              # one below the tape
    gated = _gated(labels)
    assert gated[150:200, 150:170].all() and gated[205:230, 150:170].all()


def test_columns_without_a_wall_are_untouched():
    labels = np.full((H, W), FLOOR, np.int64)
    labels[0:240, 100:120] = LANE                # a line reaching the top row, no wall in view
    assert np.array_equal(_gated(labels), labels == LANE)


def test_gate_needs_a_wall_class():
    classes = (ClassSpec(0, "floor", "background"), ClassSpec(1, "lane_line", "lane_marking"))
    logits = np.zeros((1, 2, H, W), np.float32)
    lane_marking_mask(logits, classes)           # gate off: fine
    with pytest.raises(NoWallClass):
        lane_marking_mask(logits, classes, floor_gate=True)


def test_clean_learned_mask_applies_the_gate_to_codes_at_frame_size():
    labels = _scene()
    labels[150:240, 40:60] = LANE
    labels[60:90, 250:300] = LANE
    codes = lane_marking_mask(_logits(labels), CLASSES, size=(640, 480), floor_gate=True)
    assert codes.shape == (480, 640) and codes.dtype == np.uint8
    paint = clean_learned_mask(codes, 2 * HORIZON)
    assert set(np.unique(paint)) == {0, 1}
    assert paint[300:480, 80:120].all() and not paint[:300].any()


def test_clean_learned_mask_leaves_binary_masks_as_before():
    mask = np.zeros((H, W), np.uint8)
    mask[150:240, 40:60] = 1
    mask[70:90, 250:300] = 1                     # no wall codes: no gate, only the D-408 cleaning
    paint = clean_learned_mask(mask, HORIZON)
    assert paint[150:240, 40:60].all() and paint[75:90, 250:300].all()


# --- LaneSegModel: the paint path reads the gate; no wall class fails closed at open -----------------------

class _Session:
    def __init__(self, labels, n_classes=len(CLASSES)):
        self.labels, self.n = labels, n_classes

    def run(self, x):
        return _logits(self.labels, self.n)


def _model_dir(tmp_path, classes):
    import hashlib
    import json
    d = tmp_path / "m"
    d.mkdir()
    (d / "model.onnx").write_bytes(b"fake")
    (d / "model_manifest.json").write_text(json.dumps({
        "schema": "rosy.perception.model/1", "model_revision": "lane-seg-20261010-00000001", "task": "lane_seg",
        "files": [{"name": "model.onnx", "sha256": hashlib.sha256(b"fake").hexdigest(), "precision": "fp32"}],
        "input": {"shape": [1, 3, H, W], "color": "rgb", "scale": 1 / 255,
                  "mean": [0, 0, 0], "std": [1, 1, 1], "layout": "nchw"},
        "output": {"layout": "nchw_logits", "classes": [
            {"index": c.index, "name": c.name, "role": c.role} for c in classes]},
        "dataset": {"repo": "org/d", "revision": "a" * 40},
        "camera_profile_revision": "cam-1"}), encoding="utf-8")
    return d


def test_model_infer_mask_applies_the_gate_when_opened_with_it(tmp_path):
    labels = _scene()
    labels[150:240, 40:60] = LANE
    labels[60:90, 250:300] = LANE
    folder = _model_dir(tmp_path, CLASSES)
    frame = np.zeros((H, W, 3), np.uint8)
    gated = LaneSegModel.open(folder, session_factory=lambda p, t: _Session(labels), floor_gate=True)
    plain = LaneSegModel.open(folder, session_factory=lambda p, t: _Session(labels))
    codes = gated.infer_mask(frame)[0]
    assert np.array_equal(floor_paint(codes, HORIZON).astype(bool), (labels == LANE) & (np.arange(H)[:, None] >= 150))
    assert plain.infer_mask(frame)[0][60:90, 250:300].all() and plain.infer_mask(frame)[0].max() == 1
    assert np.array_equal(gated.infer_with_mask(frame)[1], gated.infer_mask(frame)[0])


def test_model_without_wall_class_is_refused_with_the_gate(tmp_path):
    classes = (ClassSpec(0, "floor", "background"), ClassSpec(1, "lane_line", "lane_marking"))
    folder = _model_dir(tmp_path, classes)
    labels = np.zeros((H, W), np.int64)
    factory = lambda p, t: _Session(labels, 2)  # noqa: E731
    with pytest.raises(ManifestError, match="wall"):
        LaneSegModel.open(folder, session_factory=factory, floor_gate=True)
    assert LaneSegModel.open(folder, session_factory=factory).floor_gate is False
