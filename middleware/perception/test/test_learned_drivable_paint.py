"""D-597: keep-mode paint from the learned drivable way - target, branch rule, boundary paint,
the paint worker's drivable kind, the cropped-input manifest, and the keeper end to end."""
import json

import numpy as np
import pytest

from control.sensing.perception.lane_keep import LaneKeeper, clean_learned_mask
from control.sensing.perception.lane_keep_lines import PAINT_HALF_WIDTH_M
from control.sensing.perception.learned.drivable_paint import (
    boundary_paint, drivable_target, lateral_px_per_m, right_branch, right_exit_way)
from control.sensing.perception.learned.lane_mask import preprocess, uncrop_logits
from control.sensing.perception.learned.manifest import ClassSpec, ManifestError, load_manifest
from control.sensing.perception.learned.paint_worker import LearnedPaintWorker
from test_lane_keep import GROUND, HALF, X_OFFSET, X, Y, _render

# The crop128 delivery's class list (lane-seg-20261010-71edcb6d): drivable is the last channel.
CLASSES = (ClassSpec(0, "background", "background"), ClassSpec(1, "lane_left", "lane_marking"),
           ClassSpec(2, "lane_right", "lane_marking"), ClassSpec(3, "crosswalk", "ignore"),
           ClassSpec(4, "speed_bump", "ignore"), ClassSpec(5, "drivable", "drivable"))
LANE_ONLY = CLASSES[:3]


def _logits(labels, n=len(CLASSES)):
    out = np.full((1, n) + labels.shape, -5.0, np.float32)
    for k in range(n):
        out[0, k][labels == k] = 5.0
    return out


def _road(h=240, w=320, left=120, right=200):
    labels = np.zeros((h, w), np.int64)
    labels[120:, left:right] = 5
    labels[120:, left - 6:left] = 1
    labels[120:, right:right + 6] = 2
    return labels


def test_a_straight_road_is_the_way():
    way, info = drivable_target(_logits(_road()), CLASSES)
    assert info == dict(reason="ok", branches=1, near_fraction=pytest.approx(80 / 320, abs=1e-3))
    assert way[200, 120:200].all() and not way[200, :120].any() and not way[200, 200:].any()


def test_a_fork_follows_the_right_branch():
    labels = np.zeros((240, 320), np.int64)
    labels[160:, 130:191] = 5                                # the robot's own road
    labels[60:160, 100:151] = 5                              # left branch
    labels[60:160, 170:231] = 5                              # right branch
    labels[60:160, 151:170] = 1                              # gore paint between them
    way, info = drivable_target(_logits(labels), CLASSES)
    assert info["reason"] == "ok" and info["branches"] == 2
    assert way[100, 170:231].all() and not way[100, 100:151].any()   # D-384: keep right


def test_right_branch_starts_on_the_road_under_the_robot():
    region = np.zeros((20, 40), bool)
    region[10:, 15:25] = True                                # own road at the centre
    region[15:, 0:5] = True                                  # another strip, bottom left, not joined
    way, branches = right_branch(region)
    assert branches == 1 and way[12, 15:25].all() and not way[:, 0:5].any()


def test_a_t_junction_opening_sideways_is_two_exits_and_the_right_one_is_kept():
    # Replay 2026-10-10 (docs/validation/drivable-branch-replay-2026-10-10.md): at a T the crossbar
    # opens to both frame sides and no row splits, so the row scan sees one branch and goes straight.
    region = np.zeros((240, 320), bool)
    region[150:, 120:200] = True                             # the robot's own road
    region[125:150, :] = True                                # the crossing road, both ways out of view
    way, exits = right_exit_way(region, 112)
    assert exits == 2 and way[135, 300:].all() and not way[135, :20].any() and way[220, 120:200].all()
    assert right_branch(region)[1] == 1                      # what drivable_target uses today


def test_a_ring_entry_takes_the_right_branch_behind_a_model_hole():
    # Replay 2026-10-10, 8kcn at a ring entry: the ring road to the right showed only beyond a patch
    # the model left unlabelled, joined to the road ahead near the top of the view.
    region = np.zeros((240, 320), bool)
    region[160:, 100:220] = True                             # own road
    region[125:160, 0:200] = True                            # ring road going left in front of the island
    region[112:125, 180:] = True                             # far rows joining to the right
    region[112:150, 260:] = True                             # ring road going right, behind the hole
    way, exits = right_exit_way(region, 112)
    assert exits == 2 and way[140, 280:].all() and not way[140, :40].any()


def test_a_ragged_far_edge_and_an_open_floor_are_one_exit():
    region = np.zeros((240, 320), bool)
    region[112:, 60:260] = True
    region[112:116, 150:175] = False                         # a notch in the far edge
    assert right_exit_way(region, 112) == (None, 1)
    region = np.zeros((240, 320), bool)
    region[112:, 40:] = True                                 # the 9dfk ring exit of D-592: one open floor
    assert right_exit_way(region, 112) == (None, 1)


def test_crosswalk_paint_on_the_road_does_not_cut_the_way():
    labels = _road()
    labels[170:180, 120:200] = 3                             # a crosswalk band across the road
    way, info = drivable_target(_logits(labels), CLASSES)
    assert info["reason"] == "ok" and way[150, 120:200].all() and way[175, 120:200].all()


def test_no_drivable_class_or_too_little_of_it_is_no_target():
    labels = _road()
    assert drivable_target(_logits(np.where(labels == 5, 0, labels), 3), LANE_ONLY)[1]["reason"] == "no_drivable_class"
    labels[:, :] = 0
    labels[230:, 150:153] = 5                                # a speck near the robot
    way, info = drivable_target(_logits(labels), CLASSES)
    assert way is None and info["reason"] == "low_coverage"


def test_rows_above_a_crop_are_never_drivable():
    way, _ = drivable_target(_logits(_road()), CLASSES, ignore_top=150)
    assert not way[:150].any() and way[200, 120:200].all()


def test_boundary_paint_sits_just_outside_the_way_and_not_at_the_frame_border():
    way = np.zeros((4, 40), bool)
    way[1, 10:20] = True
    way[2, 0:20] = True                                      # touches the left border
    paint = boundary_paint(way, np.full(4, 100.0), 0.0125)   # 2.5 cm at 100 px/m: 2-3 px strips
    strip = int(round(2 * 0.0125 * 100.0))
    assert paint[1, 10 - strip:10].all() and paint[1, 20:20 + strip].all() and paint[1].sum() == 2 * strip
    assert paint[2, 20:20 + strip].all() and paint[2].sum() == strip
    assert not paint[0].any() and not paint[3].any()
    with pytest.raises(ValueError):
        boundary_paint(way, np.ones(3), 0.0125)


def test_lateral_scale_matches_the_ground_plane():
    rows = np.array([200.0])
    scale = lateral_px_per_m(rows, focal_px=GROUND.focal_px, principal_y=GROUND.principal_y,
                             pitch_rad=GROUND.pitch_rad, height_m=GROUND.height_m)
    one_cm = GROUND.lateral(GROUND.principal_x + scale[0] * 0.01, 200.0)
    assert one_cm == pytest.approx(0.01, rel=1e-6)
    above = lateral_px_per_m(np.array([0.0]), focal_px=GROUND.focal_px, principal_y=GROUND.principal_y,
                             pitch_rad=GROUND.pitch_rad, height_m=GROUND.height_m)
    assert GROUND.horizon_row > 0 and above[0] == 0.0


def _way_paint(y0):
    """The keeper's paint for a lane centred at y0 whose drivable way ends at the tapes' inner edges."""
    way = np.isfinite(X) & (np.abs(Y - y0) < HALF - PAINT_HALF_WIDTH_M) & (X < 0.6)
    scale = lateral_px_per_m(np.arange(way.shape[0]), focal_px=GROUND.focal_px, principal_y=GROUND.principal_y,
                             pitch_rad=GROUND.pitch_rad, height_m=GROUND.height_m)
    return clean_learned_mask(boundary_paint(way, scale, PAINT_HALF_WIDTH_M), GROUND.horizon_row)


@pytest.mark.parametrize("y0", [0.0, 0.03, -0.03])
def test_the_keeper_steers_on_the_way_like_on_the_tape(y0):
    image = _render([(y0 + HALF, 0.0), (y0 - HALF, 0.0)])
    by_tape = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0).update(image, GROUND, lane_half_width_m=HALF)
    keeper = LaneKeeper(camera_x_offset_m=X_OFFSET, smoothing=0.0)
    by_way = keeper.update(image, GROUND, lane_half_width_m=HALF, paint_mask=_way_paint(y0))
    assert keeper.last["strategy"] == "both"
    assert by_way.error == pytest.approx(by_tape.error, abs=0.05)
    if y0:
        assert np.sign(by_way.error) == -np.sign(y0)          # lane to the left -> steer left (error < 0)


class _Slot:
    def __init__(self, model):
        self.model, self.last_error = model, None

    def poll(self):
        return self.model


class _DrivableModel:
    model_revision = "m-drv"

    def __init__(self, kind):
        self.kind, self.calls = kind, 0

    def infer_drivable(self, frame):
        self.calls += 1
        mask = np.zeros(frame.shape[:2], np.uint8)
        mask[120:, 100:200] = 1
        return mask, self.kind, dict(reason="ok" if self.kind == "drivable" else "low_coverage"), 1.0

    def infer_mask(self, frame):
        raise AssertionError("the drivable target must not take the lane_marking path")


@pytest.mark.parametrize("kind", ["drivable", "lane_marking"])
def test_worker_cleans_each_kind_with_its_own_function(kind):
    worker = LearnedPaintWorker(_Slot(_DrivableModel(kind)), stale_s=5.0, clock=lambda: 0.0, start=False,
                                target="drivable")
    frame = np.zeros((240, 320, 3), np.uint8)
    worker.mask_for(frame, 1, 10.0)
    worker.step()
    got = worker.mask_for(frame, 1, 10.125, clean=lambda m: m * 0 + 7, clean_drivable=lambda m: m * 0 + 9)
    assert worker.used_paint_kind == kind and worker.used_model_revision == "m-drv"
    assert int(got.max()) == (9 if kind == "drivable" else 7)
    assert worker.used_drivable["reason"] == ("ok" if kind == "drivable" else "low_coverage")
    worker.reset()
    assert worker.used_paint_kind is None and worker.used_drivable is None


def test_worker_refuses_a_drivable_mask_without_its_cleaner_and_an_unknown_target():
    worker = LearnedPaintWorker(_Slot(_DrivableModel("drivable")), stale_s=5.0, clock=lambda: 0.0, start=False,
                                target="drivable")
    frame = np.zeros((240, 320, 3), np.uint8)
    worker.mask_for(frame, 1, 10.0)
    worker.step()
    with pytest.raises(ValueError):
        worker.mask_for(frame, 1, 10.125, clean=lambda m: m)
    with pytest.raises(ValueError):
        LearnedPaintWorker(None, start=False, target="road")


def _crop_manifest(tmp_path, crop):
    from test_learned_runner import _model_dir
    folder = _model_dir(tmp_path)
    doc = json.loads((folder / "model_manifest.json").read_text(encoding="utf-8"))
    doc["input"]["shape"] = [1, 3, 128, 320]
    if crop is not None:
        doc["input"]["crop"] = crop
    (folder / "model_manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    return folder


def test_a_cropped_input_model_is_fed_its_rows_and_uncropped_to_background(tmp_path):
    manifest = load_manifest(_crop_manifest(tmp_path, {"from_frame": [240, 320], "rows": [112, 240]}))
    assert manifest.input.crop == (240, 320, 112, 240)
    frame = np.zeros((480, 640, 3), np.uint8)
    frame[224:] = 255                                       # the bottom 128 rows of the 240-row frame
    x = preprocess(frame, manifest.input)
    assert x.shape == (1, 3, 128, 320) and x.min() == pytest.approx(1.0)
    logits = np.zeros((1, 2, 128, 320), np.float32)
    logits[0, 1] = 5.0                                       # lane everywhere the model sees
    full = uncrop_logits(logits, manifest.input, manifest.classes).argmax(axis=1)[0]
    assert full.shape == (240, 320) and (full[:112] == 0).all() and (full[112:] == 1).all()


def test_an_uncropped_manifest_is_unchanged(tmp_path):
    from test_learned_runner import _model_dir
    manifest = load_manifest(_model_dir(tmp_path))
    logits = np.zeros((1, 2, 240, 320), np.float32)
    assert manifest.input.crop is None and uncrop_logits(logits, manifest.input, manifest.classes) is logits


@pytest.mark.parametrize("crop", [
    {"from_frame": [240, 320], "rows": [100, 240]},          # 140 rows for a 128-row input
    {"from_frame": [240, 640], "rows": [112, 240]},          # width differs from the input
    {"from_frame": [200, 320], "rows": [112, 240]},          # rows outside the frame
    {"from_frame": [240, 320]},                              # rows missing
    {"from_frame": [240, 320], "rows": [112, 240], "pad": 0},
])
def test_a_bad_crop_is_refused(tmp_path, crop):
    with pytest.raises(ManifestError, match="input.crop"):
        load_manifest(_crop_manifest(tmp_path, crop))


def test_runner_falls_back_to_lane_marking_without_a_drivable_class(tmp_path):
    from control.sensing.perception.learned.runner import LaneSegModel
    from test_learned_runner import _factory, _model_dir
    model = LaneSegModel.open(_model_dir(tmp_path), session_factory=_factory())
    mask, kind, info, latency_ms = model.infer_drivable(np.zeros((480, 640, 3), np.uint8))
    assert kind == "lane_marking" and info["reason"] == "no_drivable_class"
    assert mask.shape == (480, 640) and mask.any() and latency_ms >= 0


def test_a_ragged_edge_finger_is_not_a_branch():
    region = np.zeros((40, 60), bool)
    region[20:, 20:40] = True                                # own road
    region[5:20, 20:36] = True                               # the road going on
    region[5:20, 38:40] = True                               # a 2 px finger on the right edge
    way, branches = right_branch(region)
    assert branches == 1 and way[10, 20:36].all() and not way[10, 38:40].any()


def test_an_enclosed_hole_is_not_a_fork():
    labels = _road()
    labels[150:170, 150:170] = 0                             # a box on the road, background around it
    way, info = drivable_target(_logits(labels), CLASSES)
    assert info["branches"] == 1 and way[160, 120:200].all()  # filled: the edges stay the road's
