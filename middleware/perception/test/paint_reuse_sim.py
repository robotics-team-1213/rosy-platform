"""D-570 cadence simulation: the real LearnedPaintWorker against a fake model with a fixed
latency, 8 Hz frames and analytic odometry (straight or a constant-rate arc), counting the
keep frames that got a learned mask. 'old' is the node's pre-D-570 rule (turning forces
cadence 1, unwarped reuse), 'new' the ego-motion warped reuse. Frames carry rendered tape so
a warped mask can be compared with the mask the same frame would get fresh (IoU).

    python middleware/perception/test/paint_reuse_sim.py      # prints the table
"""
import math
import pathlib
import sys

import numpy as np

_HERE = pathlib.Path(__file__).resolve()
for _p in (_HERE.parents[1], _HERE.parents[3] / "contracts" / "foundation"):
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

import yaml  # noqa: E402

from control.sensing.perception.camera_ground import nominal_ground_plane  # noqa: E402
from control.sensing.perception.lane_keep_lines import HORIZON_MARGIN_PX, drop_small_components  # noqa: E402
from control.sensing.perception.learned.paint_motion import OdomHistory, mask_homography, warp_mask  # noqa: E402
from control.sensing.perception.learned.paint_worker import LearnedPaintWorker  # noqa: E402

PROFILE = yaml.safe_load((_HERE.parents[3] / "middleware" / "apps" / "device" / "pinky" / "profile"
                          / "config" / "camera_nominal.yaml").read_text(encoding="utf-8"))
GROUND = nominal_ground_plane(source="NOMINAL", allowed=True, width_px=320, height_px=240, profile=PROFILE)
X_OFFSET = float(PROFILE["x_offset_m"])
CUT = int(math.ceil(GROUND.horizon_row)) + HORIZON_MARGIN_PX
HALF, TAPE_HALF = 0.0925, 0.0125
PERIOD, V = 0.125, 0.08          # 8 Hz camera, rosy_default line_follow cruise_speed


def _floor_xy():
    rows, cols = np.mgrid[0:240, 0:320].astype(float)
    angle = GROUND.pitch_rad + np.arctan((rows - GROUND.principal_y) / GROUND.focal_px)
    with np.errstate(divide="ignore", invalid="ignore"):
        forward = np.where((angle > 0) & (rows >= CUT), GROUND.height_m / np.tan(angle), np.nan)
        den = GROUND.focal_px * np.sin(GROUND.pitch_rad) + (rows - GROUND.principal_y) * np.cos(GROUND.pitch_rad)
        right = GROUND.height_m * (cols - GROUND.principal_x) / den
    return forward + X_OFFSET, np.where(np.isfinite(forward), -right, np.nan)


FX, FY = _floor_xy()


def pose_at(t, wz):
    if abs(wz) < 1e-9:
        return (V * t, 0.0, 0.0)
    r = V / wz
    return (r * math.sin(wz * t), r * (1 - math.cos(wz * t)), wz * t)


def render(pose, wz):
    """Tape mask at `pose`: the lane's two lines, straight (y = +-HALF) or arcs around the turn
    centre, dashed (5 cm tape, 5 cm gap) so motion along the lane changes the picture."""
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    ox, oy = x + FX * c - FY * s, y + FX * s + FY * c
    if abs(wz) < 1e-9:
        d, along = np.abs(oy), ox
    else:
        r = V / wz
        d = np.abs(np.hypot(ox, oy - r) - abs(r))
        along = np.arctan2(ox, np.sign(r) * (r - oy)) * abs(r)
    with np.errstate(invalid="ignore"):
        return ((np.abs(d - HALF) <= TAPE_HALF) & (np.mod(along, 0.10) < 0.05)).astype(np.uint8)


class _Model:
    model_revision = "sim"

    def infer_mask(self, frame):
        return frame, 0.0         # the frame *is* its true tape mask


class _Slot:
    def poll(self):
        return _Model()


def simulate(latency_s, every_n, *, new, wz=0.0, frames=200, odom_lag_s=0.02,
             max_age_s=0.9, max_dxy_m=0.10, max_dyaw_rad=0.40, reuse_max_wz=0.15):
    """(learned share of frames after warm-up, mean IoU of served vs fresh mask, inferences per
    second, mean IoU the same aged masks would have had unwarped)."""
    now = [0.0]
    worker = LearnedPaintWorker(_Slot(), stale_s=0.6, clock=lambda: now[0], start=False)
    history = OdomHistory()
    odom_t = [0.0]
    inflight = None               # (done_at, pending snapshot)
    used = ious = 0.0
    raw = []
    current = [None]

    def iou(a, b):
        union = ((a > 0) | (b > 0)).sum()
        return ((a > 0) & (b > 0)).sum() / union if union else 1.0
    runs = 0
    turning = abs(wz) > reuse_max_wz

    def motion(mask, src, dst):
        raw.append(iou(mask, current[0]))
        a, b = history.pose_at(src), history.pose_at(dst)
        if a is None or b is None:
            return 'no_odom'
        got = mask_homography(GROUND, X_OFFSET, a, b, mask.shape, CUT, max_dxy_m=max_dxy_m, max_dyaw_rad=max_dyaw_rad)
        return got if isinstance(got, str) else (drop_small_components(warp_mask(mask, got[0], CUT)), got[1], got[2])

    warm = 8
    for k in range(frames):
        t = now[0] = k * PERIOD
        while odom_t[0] <= t - odom_lag_s:
            history.add(odom_t[0], *pose_at(odom_t[0], wz))
            odom_t[0] += 0.02
        if inflight is not None and inflight[0] <= t:
            newer, worker._pending = worker._pending, inflight[1]
            worker.step()
            worker._pending, inflight = newer, None
        truth = current[0] = render(pose_at(t, wz), wz)
        every = every_n if new or not turning else 1
        mask = worker.mask_for(truth, every, t, motion=motion if new else None, max_age_s=max_age_s,
                               reuse_n=1 if turning else every_n)
        if inflight is None and worker._pending is not None:
            inflight, worker._pending = (t + latency_s, worker._pending), None
            runs += 1
        if k >= warm and mask is not None:
            used += 1
            ious += iou(mask, truth)
    n = frames - warm
    return (used / n, (ious / used if used else float("nan")), runs / (frames * PERIOD),
            float(np.mean(raw)) if raw else float("nan"))


def table():
    rows = []
    for latency in (0.2, 0.3, 0.4):
        for label, wz in (("straight", 0.0), ("turn 0.32 rad/s", V / 0.25), ("turn 0.60 rad/s", 0.6)):
            for every_n in (2, 4):
                old = simulate(latency, every_n, new=False, wz=wz)
                new = simulate(latency, every_n, new=True, wz=wz)
                rows.append((latency, label, every_n, old, new))
    return rows


if __name__ == "__main__":
    print("| latency ms | motion | every_n | old used % | new used % (IoU warped / unwarped) "
          "| inferences/s old/new |")
    print("|---|---|---|---|---|---|")
    for latency, label, every_n, old, new in table():
        print(f"| {latency * 1000:.0f} | {label} | {every_n} | {old[0] * 100:.0f} | {new[0] * 100:.0f} ({new[1]:.2f} / {new[3]:.2f}) "
              f"| {old[2]:.1f}/{new[2]:.1f} |")
