"""D-570: learned paint mask moved by odometry between frames (ground-plane homography), the
odometry history it reads, the worker's serve/fallback gate and the idle cadence."""
import math

import numpy as np
import pytest

from control.sensing.perception.evidence_mode import EvidenceModes
from control.sensing.perception.learned.paint_motion import (
    ODOM_HISTORY_MAX_LEAD_S, OdomHistory, _ground_to_pixel, mask_homography, warp_mask,
)
from control.sensing.perception.learned.paint_worker import LearnedPaintWorker
from paint_reuse_sim import CUT, GROUND, X_OFFSET, simulate

BOUNDS = dict(max_dxy_m=0.10, max_dyaw_rad=0.40)


def _row_of(x_base):
    """Image row of floor points x_base metres ahead of base_link (GroundPlane inverse)."""
    angle = math.atan2(GROUND.height_m, x_base - X_OFFSET) - GROUND.pitch_rad
    return GROUND.principal_y + GROUND.focal_px * math.tan(angle)


def test_ground_homography_matches_ground_plane():
    g = _ground_to_pixel(GROUND, X_OFFSET)
    for row, col in ((200, 40), (150, 160), (120, 300)):
        x = GROUND.distance(row) + X_OFFSET
        y = -GROUND.lateral(col, row)
        u, v, w = g @ (x, y, 1.0)
        assert (u / w, v / w) == pytest.approx((col, row), abs=1e-6)


def test_forward_motion_moves_a_transverse_line_down_by_the_expected_rows():
    mask = np.zeros((240, 320), np.uint8)
    r0 = int(round(_row_of(0.30)))
    mask[r0, :] = 1
    h, dxy, dyaw = mask_homography(GROUND, X_OFFSET, (0, 0, 0), (0.05, 0, 0), mask.shape, CUT, **BOUNDS)
    assert dxy == pytest.approx(0.05) and dyaw == 0
    rows = np.nonzero(warp_mask(mask, h, CUT)[:, 160])[0]
    assert rows.size and abs(rows.mean() - _row_of(0.25) - (r0 - _row_of(0.30))) <= 1.0
    assert rows.mean() > r0 + 10                             # nearer floor is lower in the picture


def test_pure_yaw_shifts_columns_and_unseen_floor_stays_empty():
    full = np.zeros((240, 320), np.uint8)
    full[CUT:] = 1
    h, _, dyaw = mask_homography(GROUND, X_OFFSET, (0, 0, 0), (0, 0, 0.2), full.shape, CUT, **BOUNDS)
    out = warp_mask(full, h, CUT)
    assert dyaw == pytest.approx(0.2)
    assert out[:CUT].sum() == 0                              # nothing above the horizon cut
    assert out[CUT + 20:, :20].sum() == 0                    # turned left: the new left edge was never seen
    assert out[CUT + 20:, -20:].all()                        # the right side still sees old floor
    dot = np.zeros((240, 320), np.uint8)
    dot[228:233, 158:163] = 1                                # near-field centre column
    cols = np.nonzero(warp_mask(dot, h, CUT).any(axis=0))[0]
    assert cols.size and cols.mean() > 160 + 20              # a left turn moves floor to the right


def test_motion_beyond_the_bounds_or_behind_the_old_lens_is_refused():
    shape = (240, 320)
    assert mask_homography(GROUND, X_OFFSET, (0, 0, 0), (0.11, 0, 0), shape, CUT, **BOUNDS) == 'motion_bound'
    assert mask_homography(GROUND, X_OFFSET, (0, 0, 0), (0, 0, -0.41), shape, CUT, **BOUNDS) == 'motion_bound'
    # backing up past the nearest visible floor: the new view's floor was behind the old lens
    assert mask_homography(GROUND, X_OFFSET, (0, 0, 0), (-0.3, 0, 0), shape, CUT,
                           max_dxy_m=1.0, max_dyaw_rad=1.0) == 'motion_bound'


def test_odom_history_interpolates_wraps_and_refuses_gaps():
    hist = OdomHistory()
    hist.add(1.0, 0.0, 0.0, math.pi - 0.1)
    hist.add(1.1, 0.01, 0.0, -math.pi + 0.1)                 # across +-pi
    x, _, yaw = hist.pose_at(1.05)
    assert x == pytest.approx(0.005) and abs(abs(yaw) - math.pi) < 1e-9
    assert hist.pose_at(0.99) is None                        # before the history
    assert hist.pose_at(1.1 + ODOM_HISTORY_MAX_LEAD_S / 2)[0] == pytest.approx(0.015)   # carried on
    assert hist.pose_at(1.1 + ODOM_HISTORY_MAX_LEAD_S + 0.01) is None
    hist.add(1.5, 0.05, 0.0, 0.0)                            # 0.4 s gap: no pose inside it
    assert hist.pose_at(1.3) is None
    hist.add(1.2, 0.0, 0.0, 0.0)                             # clock went back: history dropped
    assert hist.pose_at(1.05) is None


class _Model:
    model_revision = "m1"

    def infer_mask(self, frame):
        return np.ones(frame.shape[:2], np.uint8), 300.0


class _Slot:
    def poll(self):
        return _Model()


def _worker_with_mask(src_stamp=10.0):
    worker = LearnedPaintWorker(_Slot(), stale_s=0.6, clock=lambda: src_stamp, start=False)
    frame = np.zeros((240, 320, 3), np.uint8)
    worker.mask_for(frame, 4, src_stamp)
    worker.step()
    return worker, frame


@pytest.mark.parametrize("motion, age, reason", [
    (lambda m, a, b: 'no_odom', 0.5, 'no_odom'),
    (lambda m, a, b: 'motion_bound', 0.5, 'motion_bound'),
    (lambda m, a, b: (m * 0 + 7, 0.04, 0.1), 1.0, 'too_old'),
])
def test_gate_reports_each_skipped_warp(motion, age, reason):
    worker, frame = _worker_with_mask()
    for k in range(1, 5):                                    # frames 1..4 at 8 Hz; reuse_n 1 below
        worker.mask_for(frame, 4, 10.0 + k * 0.125, motion=motion, max_age_s=0.9, reuse_n=1)
    assert worker.mask_for(frame, 4, 10.0 + age, motion=motion, max_age_s=0.9, reuse_n=1) is None
    assert worker.reuse["paint_warp_skipped"] == reason and worker.reuse["paint_reuse"] == 'none'
    empty = LearnedPaintWorker(_Slot(), clock=lambda: 0.0, start=False)
    assert empty.mask_for(frame, 4, 0.0, motion=motion, max_age_s=0.9) is None
    assert empty.reuse["paint_reuse"] == 'none' and empty.reuse["paint_warp_skipped"] == 'no_mask'


def test_a_stamp_before_the_mask_is_clock_back_not_too_old():
    worker, frame = _worker_with_mask()
    assert worker.mask_for(frame, 4, 9.9, motion=lambda m, a, b: (m, 0.0, 0.0), max_age_s=0.9) is None
    assert worker.reuse["paint_warp_skipped"] == 'clock_back'


def test_the_worker_clock_also_caps_a_warped_mask():
    now = [10.0]
    worker = LearnedPaintWorker(_Slot(), stale_s=0.6, clock=lambda: now[0], start=False)
    frame = np.zeros((240, 320, 3), np.uint8)
    worker.mask_for(frame, 4, 10.0)
    worker.step()
    now[0] = 11.1                                            # stamps say 0.5 s, the clock says 1.1 s
    assert worker.mask_for(frame, 4, 10.5, motion=lambda m, a, b: (m, 0.0, 0.0), max_age_s=0.9) is None
    assert worker.reuse["paint_warp_skipped"] == 'too_old'
    now[0] = 10.9                                            # within max(stale_s, max_age_s) + margin
    assert worker.mask_for(frame, 4, 10.625, motion=lambda m, a, b: (m, 0.0, 0.0), max_age_s=0.9) is not None


def test_a_warped_mask_is_served_with_its_motion_and_revision():
    worker, frame = _worker_with_mask()
    got = worker.mask_for(frame, 4, 10.625, motion=lambda m, a, b: (m * 0 + 7, 0.05, -0.2), max_age_s=0.9)
    assert got is not None and got.max() == 7
    assert worker.reuse == dict(paint_reuse='warped', paint_warp_skipped=None, paint_mask_age_s=0.625,
                                paint_motion_dxy_m=0.05, paint_motion_dyaw_rad=-0.2)
    assert worker.used_model_revision == "m1"


def test_a_skipped_warp_still_serves_the_old_unwarped_reuse_and_says_so():
    worker, frame = _worker_with_mask()
    got = worker.mask_for(frame, 4, 10.125, motion=lambda m, a, b: 'motion_bound', max_age_s=0.9, reuse_n=4)
    assert got is not None
    assert worker.reuse["paint_reuse"] == 'unwarped' and worker.reuse["paint_warp_skipped"] == 'motion_bound'
    off, frame = _worker_with_mask()
    assert off.mask_for(frame, 4, 10.125) is not None
    assert off.reuse["paint_reuse"] == 'unwarped' and off.reuse["paint_warp_skipped"] == 'off'


def test_same_relative_motion_gives_the_same_homography_anywhere_in_odom():
    h0, *_ = mask_homography(GROUND, X_OFFSET, (0, 0, 0), (0.04, 0.01, 0.1), (240, 320), CUT, **BOUNDS)
    src = (1.0, 2.0, math.pi / 2)
    c, s = math.cos(src[2]), math.sin(src[2])                # the same body-frame step from src
    dst = (src[0] + 0.04 * c - 0.01 * s, src[1] + 0.04 * s + 0.01 * c, src[2] + 0.1)
    h1, *_ = mask_homography(GROUND, X_OFFSET, src, dst, (240, 320), CUT, **BOUNDS)
    assert np.allclose(h0 / h0[2, 2], h1 / h1[2, 2], atol=1e-9)


def _paint_for():
    """line_observer_node._paint_for compiled alone (no rclpy on the host)."""
    import ast
    from pathlib import Path
    from control.sensing.perception.lane_bev import pose_if_fresh
    src = (Path(__file__).resolve().parents[1] / "control" / "line_observer_node.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_paint_for")
    namespace = dict(pose_if_fresh=pose_if_fresh, clean_learned_mask=lambda m, h: m,
                     denoise_white_mask=lambda f, h: "denoise")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "line_observer_node.py", "exec"), namespace)
    return namespace["_paint_for"]


class _Param:
    def __init__(self, value):
        self.value = value


class _Recorder:
    reuse = None
    used_model_revision = None

    def __init__(self):
        self.calls = []

    def mask_for(self, frame, every_n, stamp, **kw):
        self.calls.append((every_n, kw.get("motion"), kw.get("reuse_n")))
        return None


class _Node:
    def __init__(self, wz, compensate):
        self.params = dict(paint_source='learned', learned_paint_every_n=4, learned_paint_reuse_max_wz=0.15,
                           learned_paint_motion_compensation=compensate, learned_paint_max_age_s=0.9)
        self._odom_twist = None if wz is None else (0.08, wz)
        self._odom_stamp = 10.0
        self._paint_worker = _Recorder()
        self._paint_motion = lambda ground: "warp"
        self._evidence_modes = EvidenceModes()

    def get_parameter(self, name):
        return _Param(self.params[name])


@pytest.mark.parametrize("wz, every_n", [(0.0, 4), (0.5, 1), (None, 1)])
def test_default_off_passes_exactly_the_pre_d570_cadence(wz, every_n):
    node = _Node(wz, compensate=False)
    ground = type("G", (), {"horizon_row": 80.0})()
    assert _paint_for()(node, np.zeros((240, 320, 3), np.uint8), ground, 10.0) == ("denoise", "denoise_fallback")
    assert node._paint_worker.calls == [(every_n, None, every_n)]   # turning / no odom: every frame, as before


def test_compensation_keeps_the_cadence_while_turning():
    node = _Node(0.5, compensate=True)
    ground = type("G", (), {"horizon_row": 80.0})()
    _paint_for()(node, np.zeros((240, 320, 3), np.uint8), ground, 10.0)
    assert node._paint_worker.calls == [(4, "warp", 1)]


def test_simulated_cadence_old_vs_new():
    """Pi 5 ~300 ms inference at 8 Hz: the old rule served 50 % straight / 0 % turning at
    every_n 4 (measured live: 48 %); the warped reuse serves every frame after warm-up."""
    old_straight = simulate(0.3, 4, new=False, frames=80)
    old_turn = simulate(0.3, 4, new=False, wz=0.32, frames=80)
    new_straight = simulate(0.3, 4, new=True, frames=80)
    new_turn = simulate(0.3, 4, new=True, wz=0.32, frames=80)
    assert old_straight[0] == pytest.approx(0.5, abs=0.05) and old_turn[0] == 0
    assert new_straight[0] == 1 and new_turn[0] == 1
    assert new_straight[1] > 0.8 > new_straight[3] and new_turn[1] > 0.8 > new_turn[3]   # warp aligns
    assert new_turn[2] <= old_turn[2]                        # and costs no more inference
