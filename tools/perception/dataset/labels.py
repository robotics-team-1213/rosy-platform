"""D-379 automatic labels for one camera frame. Pure numpy/cv2, no I/O.

Sources, most trusted first:
  lidar       a scan return is a vertical surface (wall or obstacle) standing on
              the floor. Its floor contact projects to a row per image column; up
              to WALL_HEIGHT_M above it is wall, below the nearest contact is floor.
              The LiDAR never sees paint, so bright pixels there are lane paint.
  trajectory  where the robot actually drove next is drivable floor.
  rule        lane_keep.floor_white_mask (or keep v2): only compared, never used
              as a label. Where it marks paint on a LiDAR wall the LiDAR wins and
              the disagreement is counted.

Class ids follow the shared D-356/D-373 dataset contract (CLASSES below).
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from geometry import WALL_HEIGHT_M, Camera, to_frame

LABEL_VERSION = "d379-auto/1"

FLOOR, LANE, WALL, DRIVABLE, STOP_LINE, CROSSWALK, UNKNOWN = range(7)
# role is the closed D-356 list; wall stays its own class (role ignore until
# the contract gets a wall role), unknown is the loss ignore_index.
CLASSES = [
    {"index": FLOOR, "name": "floor", "role": "background", "color": [90, 90, 90]},
    {"index": LANE, "name": "lane_line", "role": "lane_marking", "color": [255, 255, 255]},
    {"index": WALL, "name": "wall", "role": "ignore", "color": [220, 60, 60]},
    {"index": DRIVABLE, "name": "drivable", "role": "drivable", "color": [60, 200, 60]},
    {"index": STOP_LINE, "name": "stop_line", "role": "stop_line", "color": [250, 200, 0]},
    {"index": CROSSWALK, "name": "crosswalk", "role": "ignore", "color": [0, 160, 255]},
    {"index": UNKNOWN, "name": "unknown", "role": "ignore", "color": [0, 0, 0]},
]
IGNORE_INDEX = UNKNOWN

# Rows either side of a wall's floor contact left unknown: NOMINAL pitch is
# good to about 1 deg (horizon robust sd 2.6 px, D-364 section 3), ~5 px/deg.
CONTACT_MARGIN_PX = 4
# Plus the row error of a LiDAR range error this size (RPLIDAR C1, dark walls).
RANGE_SIGMA_M = 0.03
MAX_MARGIN_PX = 30
# Consecutive scan returns further apart than this (+ per metre) are separate surfaces.
SEGMENT_GAP_M = 0.04
SEGMENT_GAP_PER_M = 0.03
MIN_RANGE_M = 0.08  # closer returns are the robot's own body
GAP_FILL_PX = 16    # widest column gap between two walls that still counts as floor
# Paint = brighter than the LiDAR-proven floor of the same row by this much.
PAINT_MIN_CONTRAST = 35.0
PAINT_HEADROOM = 0.30
PAINT_MAX_SATURATION = 60
MIN_ROW_FLOOR_PX = 20
# Trajectory band: robot footprint and how much of the future path to use.
FOOTPRINT_HALF_WIDTH_M = 0.05
TRAJ_MAX_DISTANCE_M = 0.8
TRAJ_MAX_TURN_RAD = math.radians(35.0)  # past a corner the path hides behind walls
TRAJ_MIN_TRAVEL_M = 0.15                # otherwise the band is below the image
TRAJ_STEP_M = 0.01
# A band pixel on a LiDAR wall is a contradiction; this many make the frame a conflict.
CONFLICT_PX = 150

CONF = {"wall_near": 0.9, "wall_far": 0.7, "floor": 0.8, "paint": 0.7, "paint_rule_agrees": 0.85,
        "drivable": 0.9, "drivable_lidar": 0.95}


def _clip(p):
    return np.clip(np.round(p), -10000, 10000).astype(np.int32)


def _fill_quads(shape, quads):
    mask = np.zeros(shape, np.uint8)
    for q in quads:
        cv2.fillConvexPoly(mask, _clip(q).reshape(-1, 1, 2), 1)
    return mask.astype(bool)


def scan_segments(xy, gap_m=SEGMENT_GAP_M, gap_per_m=SEGMENT_GAP_PER_M):
    """Split ordered scan points into runs of neighbouring returns (list of index arrays)."""
    if len(xy) == 0:
        return []
    d = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    r = np.hypot(xy[:, 0], xy[:, 1])
    limit = gap_m + gap_per_m * np.maximum(r[:-1], r[1:])
    cuts = np.nonzero(d > limit)[0] + 1
    return np.split(np.arange(len(xy)), cuts)


def _fill_column_gaps(contact, dist, max_gap_px):
    """Columns between two walls (a gap in the returns) get the nearer neighbour's
    contact row: floor below it is still proven free. They get no wall pixels."""
    w = contact.size
    have = ~np.isnan(contact)
    if have.all() or not have.any():
        return contact, dist
    idx = np.arange(w)
    left = np.maximum.accumulate(np.where(have, idx, -1))
    right = np.minimum.accumulate(np.where(have, idx, w)[::-1])[::-1]
    gap = ~have & (left >= 0) & (right < w) & (right - left - 1 <= max_gap_px)
    out, d = contact.copy(), dist.copy()
    li, ri = left[gap], right[gap]
    out[gap] = np.maximum(contact[li], contact[ri])
    d[gap] = np.minimum(dist[li], dist[ri])
    return out, d


def wall_label(cam: Camera, xy, wall_height_m=WALL_HEIGHT_M, margin_px=CONTACT_MARGIN_PX,
               max_gap_px=GAP_FILL_PX):
    """LiDAR wall label for one frame.

    xy: (N,2) base-frame returns at the frame time, in scan order.
    Returns (wall bool HxW, floor bool HxW, contact row per column (float, nan =
    no return), wall distance per column (nan = none)).
    """
    h, w = cam.height, cam.width
    quads, col_best = [], np.full(w, np.nan)
    contact = np.full(w, np.nan)
    for seg in scan_segments(np.asarray(xy, dtype=np.float64)):
        p = xy[seg]
        if len(p) == 1:  # lone return: a 1 cm wide sliver
            p = np.array([p[0] - [0, 0.005], p[0] + [0, 0.005]])
        bottom = np.column_stack([p, np.zeros(len(p))])
        top = np.column_stack([p, np.full(len(p), wall_height_m)])
        ub, vb, db = cam.project(bottom)
        ut, vt, dt = cam.project(top)
        for i in range(len(p) - 1):
            if min(db[i], db[i + 1], dt[i], dt[i + 1]) <= 0.02:
                continue
            quads.append(np.array([[ub[i], vb[i]], [ub[i + 1], vb[i + 1]],
                                   [ut[i + 1], vt[i + 1]], [ut[i], vt[i]]]))
            # contact row per column along this edge (linear in u is exact for a
            # straight floor segment only in projective terms; 1 px here)
            u0, u1 = sorted((ub[i], ub[i + 1]))
            c0, c1 = max(0, int(math.ceil(u0))), min(w - 1, int(math.floor(u1)))
            if c1 < c0:
                continue
            cols = np.arange(c0, c1 + 1)
            span = ub[i + 1] - ub[i]
            f = np.zeros_like(cols, dtype=float) if abs(span) < 1e-9 else (cols - ub[i]) / span
            rows = vb[i] + f * (vb[i + 1] - vb[i])
            dist = np.hypot(*(p[i] + f[:, None] * (p[i + 1] - p[i])).T)
            better = np.isnan(contact[cols]) | (rows > contact[cols])
            contact[cols[better]] = rows[better]
            col_best[cols[better]] = dist[better]
    wall = _fill_quads((h, w), quads)
    contact, col_best = _fill_column_gaps(contact, col_best, max_gap_px)
    rows = np.arange(h)[:, None]
    have = ~np.isnan(contact)
    c = np.where(have, contact, -1e9)[None, :]
    # A range error moves a near contact row a lot: d(row)/d(r) ~ fx * h / r^2.
    r = np.maximum(np.nan_to_num(col_best, nan=10.0), 0.05)
    m = np.minimum(margin_px + cam.fx * cam.height_m * RANGE_SIGMA_M / r ** 2, MAX_MARGIN_PX)[None, :]
    wall &= rows < c - m
    floor = have[None, :] & (rows > c + m) & (rows > cam.horizon_row + margin_px)
    floor &= ~wall
    return wall, floor, contact, col_best


def paint_mask(bgr, region, min_contrast=PAINT_MIN_CONTRAST, headroom=PAINT_HEADROOM,
               max_sat=PAINT_MAX_SATURATION):
    """Bright, unsaturated pixels inside `region`, against that row's own floor."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    v, s = hsv[..., 2].astype(np.float32), hsv[..., 1]
    out = np.zeros(region.shape, bool)
    if not region.any():
        return out
    overall = float(np.median(v[region]))
    for r in np.nonzero(region.any(axis=1))[0]:
        vals = v[r][region[r]]
        ref = float(np.median(vals)) if vals.size >= MIN_ROW_FLOOR_PX else overall
        ref = min(ref, overall + 25.0)  # a row that is mostly tape keeps a carpet reference
        thr = ref + max(min_contrast, headroom * (255.0 - ref))
        out[r] = region[r] & (v[r] >= thr) & (s[r] <= max_sat)
    k = np.ones((2, 2), np.uint8)
    return cv2.morphologyEx(out.astype(np.uint8), cv2.MORPH_OPEN, k).astype(bool)


def trajectory_band(cam: Camera, pose0, future, half_width=FOOTPRINT_HALF_WIDTH_M,
                    max_distance=TRAJ_MAX_DISTANCE_M, max_turn=TRAJ_MAX_TURN_RAD,
                    min_travel=TRAJ_MIN_TRAVEL_M, step=TRAJ_STEP_M):
    """Floor the robot drove over next, as a mask on the frame taken at pose0.

    future: (x, y, yaw) arrays of odom poses after the frame, in time order.
    Returns (mask or None when the robot did not move enough, travel metres used).
    """
    fx, fy, fa = (np.asarray(a, dtype=np.float64) for a in future)
    if fx.size < 2:
        return None, 0.0
    seg = np.hypot(np.diff(fx), np.diff(fy))
    travel = np.concatenate([[0.0], np.cumsum(seg)])
    turn = np.abs(fa - pose0[2])
    keep = (travel <= max_distance) & (np.maximum.accumulate(turn) <= max_turn)
    n = int(np.argmin(keep)) if not keep.all() else keep.size
    used = float(travel[n - 1]) if n else 0.0
    if used < min_travel:
        return None, used
    # resample by distance so a stop does not pile up samples
    at = np.arange(0.0, used + 1e-9, step)
    px, py = np.interp(at, travel[:n], fx[:n]), np.interp(at, travel[:n], fy[:n])
    pa = np.interp(at, travel[:n], fa[:n])
    nx, ny = -np.sin(pa), np.cos(pa)
    left = np.column_stack([px + half_width * nx, py + half_width * ny])
    right = np.column_stack([px - half_width * nx, py - half_width * ny])
    lb = to_frame((0.0, 0.0, 0.0), pose0, left)
    rb = to_frame((0.0, 0.0, 0.0), pose0, right)
    ul, vl, dl = cam.project(np.column_stack([lb, np.zeros(len(lb))]))
    ur, vr, dr = cam.project(np.column_stack([rb, np.zeros(len(rb))]))
    quads = [np.array([[ul[i], vl[i]], [ul[i + 1], vl[i + 1]], [ur[i + 1], vr[i + 1]], [ur[i], vr[i]]])
             for i in range(len(at) - 1)
             if min(dl[i], dl[i + 1], dr[i], dr[i + 1]) > 0.02]
    mask = _fill_quads((cam.height, cam.width), quads)
    mask[: int(math.ceil(cam.horizon_row)) + 1] = False
    return mask, used


def combine(bgr, *, wall=None, floor=None, band=None, rules=None, wall_dist=None):
    """Merge the sources into (class mask uint8, confidence uint8, record dict).

    rules: {name: bool mask} of rule paint, compared only.
    """
    h, w = bgr.shape[:2]
    cls = np.full((h, w), UNKNOWN, np.uint8)
    conf = np.zeros((h, w), np.float32)
    rec = {"sources": [], "disagreement": {}}
    rules = rules or {}
    agree = np.zeros((h, w), bool)
    if rules:
        agree = np.logical_or.reduce([m.astype(bool) for m in rules.values()])
    if wall is not None:
        rec["sources"].append("lidar")
        paint = paint_mask(bgr, floor)
        cls[floor] = FLOOR
        conf[floor] = CONF["floor"]
        cls[paint] = LANE
        conf[paint] = np.where(agree[paint], CONF["paint_rule_agrees"], CONF["paint"])
        cls[wall] = WALL
        if wall_dist is not None:
            far = np.clip((np.nan_to_num(wall_dist, nan=2.0) - 1.0) / 0.5, 0.0, 1.0)
            col_conf = CONF["wall_near"] + far * (CONF["wall_far"] - CONF["wall_near"])
            conf[wall] = np.broadcast_to(col_conf[None, :], (h, w))[wall]
        else:
            conf[wall] = CONF["wall_near"]
    if band is not None:
        rec["sources"].append("trajectory")
        on_wall = band & (cls == WALL)
        rec["disagreement"]["trajectory_on_lidar_wall_px"] = int(on_wall.sum())
        region = band & ~on_wall
        band_paint = paint_mask(bgr, region) if wall is None else (region & (cls == LANE))
        drivable = region & ~band_paint
        conf[drivable] = np.where(cls[drivable] == FLOOR, CONF["drivable_lidar"], CONF["drivable"])
        cls[drivable] = DRIVABLE
        newly = band_paint & (cls != LANE)
        cls[newly] = LANE
        conf[newly] = np.where(agree[newly], CONF["paint_rule_agrees"], CONF["paint"])
        cls[on_wall] = UNKNOWN
        conf[on_wall] = 0.0
    rec["conflict"] = rec["disagreement"].get("trajectory_on_lidar_wall_px", 0) >= CONFLICT_PX
    rec["rules"] = {name: rule_stats(m.astype(bool), cls) for name, m in rules.items()}
    rec["pixels"] = {c["name"]: int((cls == c["index"]).sum()) for c in CLASSES}
    return cls, (np.clip(conf, 0, 1) * 255).astype(np.uint8), rec


def rule_stats(rule, cls):
    """Rule paint against the auto label: where did the rule put paint?"""
    return {"paint_px": int(rule.sum()),
            "on_wall": int((rule & (cls == WALL)).sum()),
            "on_floor": int((rule & ((cls == FLOOR) | (cls == DRIVABLE))).sum()),
            "on_lane": int((rule & (cls == LANE)).sum()),
            "on_unknown": int((rule & (cls == UNKNOWN)).sum()),
            "lane_px": int((cls == LANE).sum()),
            "wall_px": int((cls == WALL).sum())}


def edge_image(bgr):
    """Vertical brightness gradient (row r+1 minus row r, smoothed) for fit_pitch."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=5) / 64.0


def fit_pitch(cam: Camera, samples, wall_height_m=WALL_HEIGHT_M, lo_deg=2.0, hi_deg=18.0,
              step_deg=0.1):
    """Camera pitch that puts LiDAR walls on the image's wall edges.

    samples: [(xy base-frame returns ahead of the robot, edge_image)]. The score is
    the mean edge response at the projected wall base (bright wall above dark
    carpet: negative gradient) and wall top (dark room above bright wall:
    positive). The NOMINAL pitch came from a 2026-09-19 camera mount; a remounted
    camera moves it by degrees, which is tens of rows at the wall base.
    Returns (pitch_rad, {pitch_deg: score}).
    """
    import dataclasses
    curve = {}
    for deg in np.arange(lo_deg, hi_deg + 1e-9, step_deg):
        c = dataclasses.replace(cam, pitch_rad=math.radians(deg))
        total, n = 0.0, 0
        for xy, gy in samples:
            if len(xy) == 0:
                continue
            ub, vb, db = c.project(np.column_stack([xy, np.zeros(len(xy))]))
            _, vt, dt = c.project(np.column_stack([xy, np.full(len(xy), wall_height_m)]))
            ok = ((db > 0.05) & (dt > 0.05) & (ub >= 0) & (ub < c.width)
                  & (vb >= 0) & (vb < c.height) & (vt >= 0) & (vt < c.height))
            cols = ub[ok].astype(int)
            total += float(gy[vt[ok].astype(int), cols].sum() - gy[vb[ok].astype(int), cols].sum())
            n += int(ok.sum())
        curve[round(float(deg), 2)] = total / n if n else float("-inf")
    best = max(curve, key=curve.get)
    return math.radians(best), curve


OVERLAY_BGR = {FLOOR: (200, 120, 40), LANE: (255, 0, 255), WALL: (40, 40, 230),
               DRIVABLE: (60, 220, 60), STOP_LINE: (0, 200, 250), CROSSWALK: (255, 160, 0)}


def overlay(bgr, cls, alpha=0.45):
    """Label colours over the frame (BGR), for eyeballing (not the dataset colours)."""
    lut = np.zeros((256, 3), np.uint8)
    for k, v in OVERLAY_BGR.items():
        lut[k] = v
    colour = lut[cls]
    out = bgr.copy()
    m = cls != UNKNOWN
    out[m] = (bgr[m] * (1 - alpha) + colour[m] * alpha).astype(np.uint8)
    return out
