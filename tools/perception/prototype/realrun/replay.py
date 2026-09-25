"""Replay real teleop video through the CURRENT camera lane perception.

Measurement only: imports repo modules read-only (src/core/control).
Usage: python replay.py <part 1..7> [max_frames]
Outputs go to ./out under the current working directory.
Env: ROSY_CAMERA_PROFILE overrides the camera profile JSON.
"""
import json
import math
import os
import sys
import time

import cv2
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
sys.path.insert(0, REPO + "/src/core/control")

from control.sensing.perception.camera_ground import simulation_ground_plane  # noqa: E402
from control.sensing.perception.lane import detect_lane_error, detect_lane_centre, LANE_LINE_WIDTH_M  # noqa: E402
from control.sensing.perception.lane_boundaries import LaneBoundaryTracker  # noqa: E402
from control.sensing.perception.lane_bev import BEV_CELL_M  # noqa: E402
from control.sensing.perception.lane_debug import render_debug, PANEL_W, PANEL_H  # noqa: E402
from control.sensing.perception.road import detect_road_observation  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEO = REPO + "/data/teleop/learning/teleop_20260919_151213_part%02d.mp4"
PROFILE = os.environ.get("ROSY_CAMERA_PROFILE", os.path.join(
    REPO, "docs", "validation", "perception-real-video", "2026-09-24", "camera_profile_draft.json"))
FPS = 8.0

prof = json.load(open(PROFILE))
W, H = int(prof["width"]), int(prof["height"])
HFOV = 2.0 * math.atan((W / 2.0) / prof["fx"])
PITCH = float(prof["pitch_rad"])
CAM_H = float(prof["height_m"])
X_OFF = float(prof["x_offset_m"])
HORIZON = float(prof["horizon_row_px"])
ROLL_SLOPE = math.tan(float(prof["roll_rad"]))  # rows per column, +right lower

# Mirror line_observer_node._ground(): Gazebo-declared projection path, fed the
# REAL measured geometry (the only camera-ground constructor the node has).
GROUND = simulation_ground_plane(
    source="GAZEBO", simulation_enabled=True, use_sim_time=True,
    width_px=W, height_px=H, height_m=CAM_H, pitch_rad=PITCH,
    hfov_rad=HFOV, max_range_m=0.6)
assert GROUND is not None

# Device defaults (config/line_follow.yaml) for line / lane.
YAML = dict(bright_threshold=180, roi_top_fraction=0.40, washed_fraction=0.40,
            min_pixels=80, roi_bottom_fraction=1.0, lane_half_width_m=0.0925)
# centre mode kwargs: the only launch that runs the BEV ladder is the Gazebo
# lane launch (map_v2_fleet_lane.launch.py): roi 0.25/0.75, washed 0.75.
CENTRE_KW = dict(bright_threshold=180, lane_half_width_m=0.0925,
                 roi_top_fraction=0.25, roi_bottom_fraction=0.75,
                 washed_fraction=0.75)


def wall_mask(gray, thr=180):
    """Bright pixels belonging to a vertical surface: per column, a bright run
    that reaches up to the horizon band and continues down (gap <= 3 px); its
    lowest row is the wall base. Floor paint never reaches the horizon."""
    bright = gray > thr
    mask = np.zeros_like(bright)
    base = np.full(gray.shape[1], -1, np.int32)
    top_band = slice(56, 84)
    for c in range(gray.shape[1]):
        col = bright[:, c]
        hz = np.flatnonzero(col[top_band])
        if hz.size == 0:
            continue
        r = 56 + int(hz.max())
        gap = 0
        last = r
        while r + 1 < gray.shape[0]:
            r += 1
            if col[r]:
                last = r
                gap = 0
            else:
                gap += 1
                if gap > 3:
                    break
        base[c] = last
        mask[:last + 1, c] = col[:last + 1]
    return mask, base


def pixel_to_ground(pts):
    """(n,2) image (col,row) -> (n,2) base_link (x fwd, y left) on the floor, NaN
    where the ray misses the floor or is beyond 0.6 m."""
    col, row = pts[:, 0].astype(np.float64), pts[:, 1].astype(np.float64)
    ang = PITCH + np.arctan((row - GROUND.principal_y) / GROUND.focal_px)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = np.where(ang > 0, CAM_H / np.tan(ang), np.nan)
        den = (GROUND.focal_px * math.sin(PITCH) + (row - GROUND.principal_y) * math.cos(PITCH))
        lat = CAM_H * (col - GROUND.principal_x) / den
    d[(d > 0.6) | (d <= 0)] = np.nan
    return np.stack([d + X_OFF, -lat], axis=1)


class BevVO:
    """Stand-in odometry (the video has none): KLT floor features in the
    image, projected to the ground plane, rigid 2-D RANSAC fit per frame."""

    def __init__(self, view=None):
        self.prev = None
        self.pose = (0.0, 0.0, 0.0)
        self.ok = 0
        self.fail = 0
        self.last_step = (0.0, 0.0)
        self.last_inliers = 0

    def step(self, gray, wall):
        floor = np.zeros_like(gray)
        floor[112:, :] = 255          # rows within ~0.6 m of the camera
        floor[wall] = 0
        prev, self.prev = self.prev, (gray, floor)
        self.last_step = (0.0, 0.0)
        if prev is None:
            return self.pose
        p0 = cv2.goodFeaturesToTrack(prev[0], 300, 0.01, 5, mask=prev[1], blockSize=5)
        if p0 is None or len(p0) < 12:
            self.fail += 1
            return self.pose
        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev[0], gray, p0, None, winSize=(21, 21), maxLevel=3)
        good = st.ravel() == 1
        p0, p1 = p0.reshape(-1, 2)[good], p1.reshape(-1, 2)[good]
        g0, g1 = pixel_to_ground(p0), pixel_to_ground(p1)
        ok = np.isfinite(g0).all(1) & np.isfinite(g1).all(1) & (p1[:, 1] >= 112)
        if ok.sum() < 12:
            self.fail += 1
            return self.pose
        T, inl = cv2.estimateAffinePartial2D(g1[ok], g0[ok], method=cv2.RANSAC,
                                            ransacReprojThreshold=0.004, maxIters=500)
        if T is None or inl.sum() < 10:
            self.fail += 1
            return self.pose
        scale = math.hypot(T[0, 0], T[1, 0])
        dth = math.atan2(T[1, 0], T[0, 0])
        dx, dy = float(T[0, 2]), float(T[1, 2])
        if abs(scale - 1) > 0.1 or math.hypot(dx, dy) > 0.06 or abs(dth) > math.radians(30):
            self.fail += 1
            return self.pose
        self.ok += 1
        self.last_inliers = int(inl.sum())
        x, y, th = self.pose
        c, s = math.cos(th), math.sin(th)
        self.pose = (x + c * dx - s * dy, y + s * dx + c * dy, th + dth)
        self.last_step = (math.hypot(dx, dy), dth)
        return self.pose


def horizon_pts(scale_y, scale_x=1.0):
    y0 = HORIZON - ROLL_SLOPE * (W / 2.0)
    y1 = HORIZON + ROLL_SLOPE * (W / 2.0)
    return ((0, int(round(y0 * scale_y))), (int(round(W * scale_x)) - 1, int(round(y1 * scale_y))))


def row_for_range(d):
    ang = math.atan2(CAM_H, d) - PITCH
    return GROUND.principal_y + GROUND.focal_px * math.tan(ang)


def info_panel(rec):
    p = np.full((PANEL_H, PANEL_W, 3), 24, np.uint8)
    L = []
    ln = rec["line"]
    L.append("line(dev) " + ("NONE" if ln is None else f"e{ln['error']:+.2f} c{ln['confidence']:.2f}"))
    la = rec["lane"]
    L.append("lane(dev) " + ("NONE" if la is None else f"e{la['error']:+.2f} c{la['confidence']:.2f}"))
    fz = rec["centre_frozen"]
    L.append(f"centre@noodom {fz['tier']}")
    rd = rec["road"]
    sl = rd["stop_line"]
    cw = rd["crosswalk"]
    L.append("stop " + ("-" if sl is None else f"r{sl['row']:.0f} " + ("?" if sl['dist'] is None else f"{sl['dist']:.2f}m"))
             + "  xwalk " + ("-" if cw is None else f"r{cw['row']:.0f}"))
    L.append(f"wall-paint {rec['wall_paint_frac']:.2f}  lit {rec['bev_lit_frac']:.2f}")
    flags = []
    if rec["boundary_on_wall"]:
        flags.append("BOUNDARY=WALL")
    if rec["boundary_wide"]:
        flags.append("WIDE")
    if rec["boundary_far"]:
        flags.append("FAR")
    L.append(" ".join(flags) or "-")
    L.append(f"{rec['part']}#{rec['frame']}  vo {rec['vo_step_m']*100:.1f}cm {math.degrees(rec['vo_dth']):+.0f}d")
    for k, t in enumerate(L):
        cv2.putText(p, t, (6, 20 + 22 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (240, 240, 240) if k != 5 or t == "-" else (80, 80, 255), 1, cv2.LINE_AA)
    return p


def comp_stats(labels, label, view, wall_bev):
    cells = labels == label
    n = int(cells.sum())
    xs, ys = view.x[cells], view.y[cells]
    length = math.hypot(np.ptp(xs), np.ptp(ys)) + BEV_CELL_M
    width = n * BEV_CELL_M ** 2 / length
    near = int(np.argmin(np.hypot(xs, ys)))
    return dict(cells=n, length=length, width=width,
                near_x=float(xs[near]), near_y=float(ys[near]),
                wall_frac=float(wall_bev[cells].mean()) if n else 0.0)


def main():
    part = int(sys.argv[1])
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 9
    out_dir = os.path.join(os.getcwd(), "out")
    os.makedirs(out_dir, exist_ok=True)
    cap = cv2.VideoCapture(VIDEO % part)
    tracker = LaneBoundaryTracker(camera_x_offset_m=X_OFF)
    frozen = LaneBoundaryTracker(camera_x_offset_m=X_OFF)
    from control.sensing.perception.lane_bev import BirdsEye
    vo = BevVO(BirdsEye(GROUND, W, H, X_OFF))
    writer = cv2.VideoWriter(os.path.join(out_dir, f"overlay_p{part:02d}_mp4v.mp4"),
                             cv2.VideoWriter_fourcc(*"mp4v"), FPS, (2 * PANEL_W, 2 * PANEL_H))
    jl = open(os.path.join(out_dir, f"frames_p{part:02d}.jsonl"), "w")
    raw_dir = os.path.join(out_dir, "raw", f"p{part:02d}")
    os.makedirs(raw_dir, exist_ok=True)
    far_row = row_for_range(0.40)   # BEV_MAX_RANGE_M from the camera
    i = 0
    t0 = time.time()
    while i < limit:
        ok, frame = cap.read()
        if not ok:
            break
        now = i / FPS
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        wmask, wbase = wall_mask(gray)
        pose = vo.step(gray, wmask)
        obs = tracker.update(now, pose, frame, GROUND, **CENTRE_KW)
        last = tracker.last
        obs_f = frozen.update(now, (0.0, 0.0, 0.0), frame, GROUND, **CENTRE_KW)
        view = tracker._view
        wall_bev = wmask[view._pixel_row, view._pixel_col] & view.observable
        paint = last.get("paint")
        lit = int(paint.sum()) if paint is not None else 0
        observable = int(view.observable.sum())
        wall_paint_frac = float((wall_bev & (paint > 0)).sum() / lit) if lit else 0.0
        chosen = {}
        on_wall = wide = far = False
        labels = None
        if "left_label" in last:
            # recompute labels the tracker used
            _, labels = cv2.connectedComponents(paint, connectivity=4)
            for side in ("left", "right"):
                lab = last.get(side + "_label")
                if lab is None:
                    continue
                st = comp_stats(labels, lab, view, wall_bev)
                chosen[side] = st
                on_wall |= st["wall_frac"] > 0.5
                wide |= st["width"] > 0.06
                far |= abs(st["near_y"]) > 1.6 * 0.0925 or st["near_x"] > 0.40
        line = detect_lane_error(frame, bright_threshold=180, roi_top_fraction=0.40,
                                 washed_fraction=0.40, min_pixels=80)
        band = gray[96:] > 180
        line_lit = int(band.sum())
        line_wall_frac = float((wmask[96:] & band).sum() / line_lit) if line_lit else 0.0
        lane = detect_lane_centre(frame, GROUND, bright_threshold=180, lane_half_width_m=0.0925,
                                  roi_top_fraction=0.40, roi_bottom_fraction=1.0,
                                  washed_fraction=0.40)
        road = detect_road_observation(frame, ground=GROUND)

        def mk(m):
            return None if m is None else dict(row=m.image_row, dist=m.distance_m,
                                               conf=m.confidence)
        wall_cols = wbase >= 0
        rec = dict(
            part=part, frame=i, t=now,
            tier=tracker.tier,
            error=None if obs is None else obs.error,
            confidence=None if obs is None else obs.confidence,
            visible=obs is not None,
            source=last.get("source"), junction=last.get("junction"),
            centre_frozen=dict(tier=frozen.tier,
                               error=None if obs_f is None else obs_f.error,
                               confidence=None if obs_f is None else obs_f.confidence,
                               junction=frozen.last.get("junction")),
            line=None if line is None else dict(error=line.error, confidence=line.confidence),
            line_wall_frac=line_wall_frac, line_lit=line_lit,
            lane=None if lane is None else dict(error=lane.error, confidence=lane.confidence),
            road=dict(stop_line=mk(road.stop_line), crosswalk=mk(road.crosswalk),
                      signal=None if road.signal is None else road.signal.colour),
            bev_lit_frac=lit / observable if observable else 0.0,
            washed=bool(observable and lit > CENTRE_KW["washed_fraction"] * observable),
            washed_dev=bool(observable and lit > 0.40 * observable),
            wall_paint_frac=wall_paint_frac,
            wall_cols=int(wall_cols.sum()),
            wall_base_max=int(wbase.max()) if wall_cols.any() else -1,
            wall_in_bev=bool(wall_cols.any() and wbase.max() >= far_row),
            chosen=chosen, boundary_on_wall=bool(on_wall), boundary_wide=bool(wide),
            boundary_far=bool(far),
            vo_step_m=vo.last_step[0], vo_dth=vo.last_step[1], vo_inliers=vo.last_inliers,
            mean_gray=float(gray.mean()),
            sharp=float(cv2.Laplacian(gray[120:], cv2.CV_64F).var()),
        )
        jl.write(json.dumps(rec) + "\n")
        # overlay
        img = render_debug(frame, tracker, obs, mode="centre", bright_threshold=180)
        sy = PANEL_H / H
        a, b = horizon_pts(sy)
        cv2.line(img, a, b, (0, 255, 255), 1, cv2.LINE_AA)
        r = int(round(far_row * sy))
        cv2.line(img, (0, r), (PANEL_W - 1, r), (255, 160, 0), 1)
        cv2.putText(img, "BEV 0.40m", (PANEL_W - 70, r - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.33,
                    (255, 160, 0), 1, cv2.LINE_AA)
        pts = [(c, int(round(wbase[c] * sy))) for c in range(W) if wbase[c] >= 0]
        for c, rr in pts:
            img[min(rr, PANEL_H - 1), c] = (255, 0, 255)
        img[PANEL_H:, PANEL_W:] = info_panel(rec)
        writer.write(img)
        cv2.imwrite(os.path.join(raw_dir, f"{i:04d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        i += 1
    writer.release()
    jl.close()
    print(f"part {part}: {i} frames in {time.time() - t0:.1f}s; vo ok {vo.ok} fail {vo.fail}")


if __name__ == "__main__":
    main()
