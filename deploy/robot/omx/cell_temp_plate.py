#!/usr/bin/env python3
"""Temp plate pose and slots from one top-camera frame (read-only: never moves an arm, never writes the cell config).

The plate (CAD rosy-modeling/parts/omx-temp-slot/plate/temp_slot_plate.scad v12) is not fixed to the table, so its
pockets are measured each time it is set down. This fits the plate's CAD outline to the plate-coloured region the top
camera sees and prints, as JSON, what cell_slot_prior reads from the site config: sites.<site>.slots and slots_fit
({residual_mm, residual_deg}). A person copies them into the config; the tool writes nothing.

    python cell_temp_plate.py --config cell-arm-b-policy.json --site temp_plate_b --image top.jpg [--names a,b,c]

Exit 0 with {"slots", "slots_fit", ...}; exit 2 with {"refuse": why, ...} when the frame does not fix the plate:
no plate region, the fit at its search bound, the plate looking another size than CAD through the camera model (the
model is off at plate height and arm-frame slots would carry that error), too little outline visible (the arm-side edge
and one long side are needed), or a residual over cell_slot_prior's 3 mm / 1 deg. The F1-F4 marks (Ø4 mm) are not used:
in the 2026-11-27 frames F1/F2 are under the stacks or past the frame, and two marks fix a pose with no residual.

Plate frame (mm): origin at the middle pocket's centre, +y along it away from the arm, the arm axis at (0, -ARM_R).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

# CAD v12 values (temp_slot_plate.scad): pocket pk_w x pk_l, arm_r, flare = pk_l/2 tan(yaw_tol 3), catch 5, rim 3, gap_min 0.6
ARM_R = 200.0
POCKET_MM = (30.8, 96.0)
FLOOR_MM, TOP_MM = 8.0, 13.6  # deck_t (pocket floor) and ear_h = deck_t + seat_h 0.6 + catch 5 (the flat top beside the pockets)
_FLARE = POCKET_MM[1] / 2 * math.tan(math.radians(3))
FAN_DEG = 2 * math.degrees(math.asin((POCKET_MM[0] + 2 * _FLARE + 0.6) / 2 / (ARM_R - POCKET_MM[1] / 2)))  # 13.77
_OUTER = (POCKET_MM[0] + 2 * _FLARE + 2 * 5 + 2 * 3, POCKET_MM[1] + 2 * 5 + 2 * 3)  # one lane's outline (ow, ol)
CORNER_MM = 6.0  # corner_r: outline points this close to a hull corner are left out (rounded in the print)
STRIP_Y, STRIP_X = -61.5, 30.0  # the arm-side flat strip through F3/F4 (check_fiducials: flat), |x| <= 30

SCALE_TOL = 0.03  # the plate must look its CAD size through the camera model within 3 %
SEARCH_MM, SEARCH_DEG, SCALES = 30.0, 10.0, (0.85, 1.30)
CAP_PX, INLIER_PX, MARGIN_PX = 8.0, 3.0, 4


def lane(i: int, p) -> tuple[float, float]:
    """Plate-frame point of lane i (0..2, lane 1 the middle) given in that lane's own frame (its pocket centre at 0)."""
    t = math.radians(-(i - 1) * FAN_DEG)
    x, y = p[0], p[1] + ARM_R
    return x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t) - ARM_R


def _frame(pose):
    cx, cy, yaw = pose
    ey = np.array([math.cos(math.radians(yaw)), math.sin(math.radians(yaw))])
    return np.array([cx, cy]), np.array([ey[1], -ey[0]]), ey


def to_arm(pose, pts_mm, scale: float = 1.0) -> np.ndarray:
    """Arm-frame points (m) of plate-frame points (mm); pose = (x m, y m, yaw deg of the plate's +y)."""
    c, ex, ey = _frame(pose)
    p = np.asarray(pts_mm, float).reshape(-1, 2) * scale / 1000
    return c + p[:, :1] * ex + p[:, 1:] * ey


def slots_at(pose, names) -> list:
    """sites.<site>.slots for a plate pose, lanes in CAD order (lane 0 at plate x < 0)."""
    out = []
    for i, name in enumerate(names):
        xy = to_arm(pose, [lane(i, (0, 0))])[0]
        yaw = pose[2] - (i - 1) * FAN_DEG
        out.append({"name": name, "xy": [round(float(xy[0]), 4), round(float(xy[1]), 4)],
                    "yaw_deg": round((yaw + 180) % 360 - 180, 1), "pocket_mm": list(POCKET_MM)})
    return out


def pose_of(slots) -> tuple | None:
    """Plate pose from three slots: the middle pocket (by bearing from the arm) is the origin, +y pointing away from the arm."""
    if not slots or len(slots) != 3:
        return None
    bearing = [math.atan2(s["xy"][1], s["xy"][0]) for s in slots]
    ref = math.atan2(sum(map(math.sin, bearing)), sum(map(math.cos, bearing)))  # no wrap at +-180 deg
    mid = sorted(zip(bearing, range(3)), key=lambda b: (b[0] - ref + math.pi) % (2 * math.pi))[1]
    mid = slots[mid[1]]
    c = np.asarray(mid["xy"], float)
    yaw = float(mid["yaw_deg"])
    if math.cos(math.radians(yaw)) * c[0] + math.sin(math.radians(yaw)) * c[1] < 0:
        yaw += 180
    return float(c[0]), float(c[1]), (yaw + 180) % 360 - 180


def deck_points(slots) -> list:
    """Arm-frame points (m) on the plate's arm-side flat top (TOP_MM over the table), or [] without three slots."""
    pose = pose_of(slots)
    if pose is None:
        return []
    return [tuple(p) for p in to_arm(pose, [(x, STRIP_Y) for x in np.arange(-STRIP_X, STRIP_X + 0.1, 5.0)])]


def hull_mm() -> np.ndarray:
    """The plate outline's corners in the plate frame (the convex hull of the three lanes' outlines)."""
    return cv2.convexHull(np.float32([lane(i, (sx * _OUTER[0] / 2, sy * _OUTER[1] / 2))
                                      for i in range(3) for sx in (-1, 1) for sy in (-1, 1)])).reshape(-1, 2).astype(float)


def outline_mm(step: float = 2.0):
    """(points, edge) along the plate outline in the plate frame; edge 'arm', 'far', 'left' or 'right' (plate x) per point;
    corners left out."""
    hull = hull_mm()
    pts, kind = [], []
    y_min, y_max = hull[:, 1].min(), hull[:, 1].max()
    for k in range(len(hull)):
        a, b = hull[k], hull[(k + 1) % len(hull)]
        n = np.linalg.norm(b - a)
        name = "arm" if max(a[1], b[1]) < y_min + 0.5 else "far" if min(a[1], b[1]) > y_max - 15 else "left" if a[0] + b[0] < 0 else "right"
        for t in np.arange(CORNER_MM, n - CORNER_MM + 1e-6, step):
            pts.append(a + (b - a) * t / n)
            kind.append(name)
    return np.array(pts), np.array(kind)


def plate_mask(img, roi) -> np.ndarray:
    """Plate-coloured (white / pale blue, low saturation) pixels of the components whose centre lies in the site's ROI."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 1] < 60) & (hsv[..., 2] > 150)).astype(np.uint8) * 255
    m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m)
    x0, y0, x1, y1 = roi
    keep = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 150 and x0 - 10 <= cent[i][0] <= x1 + 10 and y0 - 10 <= cent[i][1] <= y1 + 10]
    m = np.isin(lab, keep).astype(np.uint8) * 255
    cols = np.flatnonzero(m[-MARGIN_PX - 1])
    if len(cols):  # the frame cuts the plate: close it along the cut so pockets and stacks inside become one filled plate
        m[-MARGIN_PX - 1, cols.min():cols.max() + 1] = 255
    filled = np.zeros_like(m)
    cv2.drawContours(filled, cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], -1, 255, cv2.FILLED)
    return filled


def fit(img, pixel_fn, z_top: float, init, roi) -> dict:
    """{"pose", "scale", "slots_fit", ...} or {"refuse": why, ...}. pixel_fn(xy_m, z_m) is the site's top-camera model."""
    h, w = img.shape[:2]
    grid = [(init[0] + dx, init[1] + dy) for dx in (-0.15, 0, 0.15) for dy in (-0.15, 0, 0.15)]
    px = [pixel_fn(p, z_top) for p in grid]
    if any(p is None for p in px):
        return {"refuse": "camera model: no top-camera pixel for the plate's place (site map missing)"}
    hm, _ = cv2.findHomography(np.float32(grid) * 1000, np.float32(px))  # arm mm -> pixel at the plate's top

    def proj(arm_m):
        return cv2.perspectiveTransform(np.float32(arm_m * 1000).reshape(-1, 1, 2), hm).reshape(-1, 2)

    mask = plate_mask(img, roi)
    if not mask.any():
        return {"refuse": "no plate-coloured region in the site's auto_roi"}
    edge = np.zeros_like(mask)
    cv2.drawContours(edge, cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], -1, 255, 1)
    cut = MARGIN_PX + 3  # the frame cut (and the line plate_mask closes it with) is no plate edge
    edge[:cut], edge[-cut:], edge[:, :cut], edge[:, -cut:] = 0, 0, 0, 0
    if not edge.any():
        return {"refuse": "no plate edge seen inside the frame"}
    dist = cv2.distanceTransform(255 - edge, cv2.DIST_L2, 3)
    pts, kind = outline_mm()

    def dists(pose, s):
        q = proj(to_arm(pose, pts, s))
        vis = (q[:, 0] >= MARGIN_PX) & (q[:, 0] < w - MARGIN_PX) & (q[:, 1] >= MARGIN_PX) & (q[:, 1] < h - MARGIN_PX)
        d = np.full(len(q), CAP_PX)
        qi = q[vis].astype(int)
        d[vis] = np.minimum(dist[qi[:, 1], qi[:, 0]], CAP_PX)
        return d, vis, q

    edge_px = np.argwhere(edge > 0)[:, ::-1].astype(np.float32)
    corners = hull_mm()

    def cost(pose, s):
        # two-sided truncated chamfer: visible outline -> seen edge, and seen edge -> outline, each a mean, so neither
        # pulling outline points into the frame nor leaving seen edge unexplained (an occluding stack) pays off
        d, vis, _ = dists(pose, s)
        if not vis.any():
            return CAP_PX
        poly = proj(to_arm(pose, corners, s))
        a, b = poly, np.roll(poly, -1, axis=0)
        ab = b - a
        t = np.clip(((edge_px[:, None] - a[None]) * ab[None]).sum(2) / (ab * ab).sum(1)[None], 0, 1)
        back = np.min(np.linalg.norm(edge_px[:, None] - (a[None] + t[..., None] * ab[None]), axis=2), axis=1)
        return 0.5 * float(d[vis].mean()) + 0.5 * float(np.minimum(back, CAP_PX).mean())

    best = (math.inf, tuple(init), 1.0)
    for s in np.arange(SCALES[0], SCALES[1] + 1e-6, 0.05):
        for dyaw in np.arange(-SEARCH_DEG, SEARCH_DEG + 1e-6, 2.0):
            for dx in np.arange(-SEARCH_MM, SEARCH_MM + 1e-6, 5.0):
                for dy in np.arange(-SEARCH_MM, SEARCH_MM + 1e-6, 5.0):
                    pose = (init[0] + dx / 1000, init[1] + dy / 1000, init[2] + dyaw)
                    c = cost(pose, s)
                    if c < best[0]:
                        best = (c, pose, s)

    def refine(pose, s, free_scale):
        c = cost(pose, s)
        for step in (2.0, 1.0, 0.5, 0.25, 0.1):
            moved = True
            while moved:
                moved = False
                cands = [(pose[0] + a * step / 1000, pose[1] + b * step / 1000, pose[2] + g * step / 2, s + k * step / 100)
                         for a, b, g, k in ((1, 0, 0, 0), (-1, 0, 0, 0), (0, 1, 0, 0), (0, -1, 0, 0), (0, 0, 1, 0), (0, 0, -1, 0))
                         + (((0, 0, 0, 1), (0, 0, 0, -1)) if free_scale else ())]
                for cand in cands:
                    cc = cost(cand[:3], cand[3])
                    if cc < c:
                        c, pose, s, moved = cc, cand[:3], cand[3], True
        return pose, s

    pose, s = refine(best[1], best[2], True)
    out = {"scale": round(s, 3), "init": [round(init[0], 4), round(init[1], 4), round(init[2], 1)]}
    off = (pose[0] - init[0]) * 1000, (pose[1] - init[1]) * 1000, pose[2] - init[2]
    if (max(abs(off[0]), abs(off[1])) >= SEARCH_MM - 0.5 or abs(off[2]) >= SEARCH_DEG - 0.25
            or not SCALES[0] + 0.005 < s < SCALES[1] - 0.005):
        return {**out, "refuse": f"fit hit its search bound (+-{SEARCH_MM:.0f} mm / +-{SEARCH_DEG:.0f} deg from the expected "
                                 f"pose, scale {SCALES[0]}-{SCALES[1]}): the plate is not found near its expected place"}

    def matched(pose, s):
        d, vis, q = dists(pose, s)
        ok = vis & (d <= INLIER_PX)
        return {k: int((ok & (kind == k)).sum()) for k in ("arm", "left", "right", "far")}, int((vis & (kind == "arm")).sum()), d, vis, ok, q

    seen, arm_vis, *_ = matched(pose, s)
    out["matched"] = seen
    if arm_vis == 0 or seen["arm"] < 0.5 * arm_vis or min(seen["left"], seen["right"]) < 10:
        # one long side leaves the plate's size (so the camera model check) and its place along the arm edge open
        return {**out, "refuse": f"too little outline matched (arm-side edge {seen['arm']}/{arm_vis}, long sides "
                                 f"{seen['left']} / {seen['right']}): the arm-side edge and both long sides must be seen"}
    if abs(s - 1) > SCALE_TOL:
        return {**out, "refuse": f"plate looks {s:.2f}x its CAD size through the camera model (allowed +-{SCALE_TOL:.0%}): "
                                 "the top-camera model is off at plate height, so arm-frame slots would carry that error"}
    pose, _ = refine(pose, 1.0, False)
    seen, arm_vis, d, vis, ok, q = matched(pose, 1.0)
    out.update(pose=[round(pose[0], 4), round(pose[1], 4), round(pose[2], 2)], matched=seen, visible=int(vis.sum()), points=len(pts))
    arm_q = q[ok & (kind == "arm")]
    near = edge_px[np.min(np.linalg.norm(edge_px[:, None] - arm_q[None], axis=2), axis=1) <= INLIER_PX]
    back = cv2.perspectiveTransform(near.reshape(-1, 1, 2), np.linalg.inv(hm)).reshape(-1, 2)
    vx, vy = cv2.fitLine(back, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()[:2]
    model_deg = pose[2] - 90  # the arm-side edge runs along the plate's x axis
    near = vis & (d < CAP_PX)  # past CAP_PX the outline is taken as hidden (a stack over it); 3-8 px off still counts
    out["slots_fit"] = {"residual_mm": round(float(np.sqrt(np.mean(d[near] ** 2))) * _mm_per_px(hm, pose), 2),
                        "residual_deg": round(abs((math.degrees(math.atan2(vy, vx)) - model_deg + 90) % 180 - 90), 2)}
    return out


def _mm_per_px(hm, pose) -> float:
    c = np.float32([[pose[0] * 1000, pose[1] * 1000], [pose[0] * 1000 + 10, pose[1] * 1000]])
    q = cv2.perspectiveTransform(c.reshape(-1, 1, 2), hm).reshape(-1, 2)
    return 10.0 / float(np.linalg.norm(q[1] - q[0]))


def measure(img, pixel_fn, site_cfg: dict, names=None) -> dict:
    """The fit plus the slots it gives; the expected pose comes from the site's slots, else its start and a radial axis."""
    import cell_slot_prior

    init = pose_of(site_cfg.get("slots"))
    if init is None:
        x, y = site_cfg.get("start") or site_cfg.get("place")
        r = math.hypot(x, y)
        init = (x / r * ARM_R / 1000, y / r * ARM_R / 1000, math.degrees(math.atan2(y, x)))
    names = names or [s["name"] for s in sorted(site_cfg.get("slots") or [], key=lambda s: _lane_index(init, s))] or ["R1", "R2", "R3"]
    out = fit(img, pixel_fn, float(site_cfg["surface_z"]) + (TOP_MM - FLOOR_MM) / 1000, init, site_cfg["auto_roi"])
    if "refuse" not in out:
        fit_ = out["slots_fit"]
        if fit_["residual_mm"] > cell_slot_prior.FIT_MM or fit_["residual_deg"] > cell_slot_prior.FIT_DEG:
            out["refuse"] = (f"residual {fit_['residual_mm']} mm / {fit_['residual_deg']} deg over the prior's "
                             f"{cell_slot_prior.FIT_MM} mm / {cell_slot_prior.FIT_DEG} deg")
        else:
            out["slots"] = slots_at(tuple(out["pose"]), names)
    return out


def _lane_index(pose, slot) -> float:
    c, ex, _ = _frame(pose)
    return float((np.asarray(slot["xy"], float) - c) @ ex)  # plate x: lane 0 first


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, type=Path, help="cell-arm-<a|b>-policy.json (read only)")
    ap.add_argument("--site", required=True)
    ap.add_argument("--image", required=True, type=Path, help="top-camera frame (cell_job_client.py frame top --out f)")
    ap.add_argument("--names", help="slot names in lane order (plate x < 0 first); default: the site's slots, else R1,R2,R3")
    args = ap.parse_args(argv)
    import cell_calibration as cal
    import cell_pivot
    import cell_slot_prior
    from cell_auto_setup import load_config

    config = load_config(args.config)
    raw = json.loads(args.config.read_text(encoding="utf-8"))
    calibration = cell_pivot.with_site_maps(config, cal.load(Path(raw["calibration_path"])))
    img = cv2.imread(str(args.image))
    if img is None:
        print(json.dumps({"site": args.site, "refuse": f"cannot read {args.image}"}))
        return 2
    out = measure(img, lambda p, z: cell_slot_prior.pixel_at(config, calibration, args.site, p, z), config["sites"][args.site],
                  args.names.split(",") if args.names else None)
    print(json.dumps({"site": args.site, "image": str(args.image), **out}, ensure_ascii=False))
    return 2 if "refuse" in out else 0


if __name__ == "__main__":
    sys.exit(main())
