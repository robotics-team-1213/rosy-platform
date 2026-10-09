"""D-570: learned paint mask moved by odometry between frames (ground-plane homography), the
odometry history it reads, the worker's serve/fallback gate and the idle cadence."""
import math

import numpy as np
import pytest

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
def test_gate_reports_each_fallback_reason(motion, age, reason):
    worker, frame = _worker_with_mask()
    for k in range(1, 5):                                    # frames 1..4 at 8 Hz; reuse_n 1 below
        worker.mask_for(frame, 4, 10.0 + k * 0.125, motion=motion, max_age_s=0.9, reuse_n=1)
    assert worker.mask_for(frame, 4, 10.0 + age, motion=motion, max_age_s=0.9, reuse_n=1) is None
    assert worker.reuse["paint_fallback_reason"] == reason and not worker.reuse["paint_compensated"]
    empty = LearnedPaintWorker(_Slot(), clock=lambda: 0.0, start=False)
    assert empty.mask_for(frame, 4, 0.0, motion=motion, max_age_s=0.9) is None
    assert empty.reuse["paint_fallback_reason"] == 'no_mask'


def test_a_compensated_mask_is_served_with_its_motion_and_revision():
    worker, frame = _worker_with_mask()
    got = worker.mask_for(frame, 4, 10.625, motion=lambda m, a, b: (m * 0 + 7, 0.05, -0.2), max_age_s=0.9)
    assert got is not None and got.max() == 7
    assert worker.reuse == dict(paint_mask_age_s=0.625, paint_compensated=True, paint_motion_dxy_m=0.05,
                                paint_motion_dyaw_rad=-0.2, paint_fallback_reason=None)
    assert worker.used_model_revision == "m1"


def test_without_compensation_the_old_unwarped_reuse_still_serves():
    worker, frame = _worker_with_mask()
    got = worker.mask_for(frame, 4, 10.125, motion=lambda m, a, b: 'no_odom', max_age_s=0.9, reuse_n=4)
    assert got is not None and worker.reuse["paint_fallback_reason"] == 'no_odom'


def test_idle_cadence_never_queues_behind_a_running_inference_and_keeps_the_cap():
    worker = LearnedPaintWorker(_Slot(), clock=lambda: 0.0, start=False)
    frame = np.zeros((240, 320, 3), np.uint8)
    worker.mask_for(frame, 2, 0.0, when_idle=True)
    assert worker._pending is not None
    pending, worker._pending, worker._busy = worker._pending, None, True    # inference running
    worker.mask_for(frame, 2, 0.125, when_idle=True)
    worker.mask_for(frame, 2, 0.25, when_idle=True)
    assert worker._pending is None                           # nothing waits behind it
    worker._pending = pending
    worker.step()                                            # done; worker idle again
    worker.mask_for(frame, 2, 0.375, when_idle=True)
    assert worker._pending is not None and worker._pending[2] == 3
    worker.step()
    worker.mask_for(frame, 2, 0.5, when_idle=True)
    assert worker._pending is None                           # idle, but only 1 frame since the last: cap


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
