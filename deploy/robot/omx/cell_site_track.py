#!/usr/bin/env python3
"""A site that moves (the Pinky robot's tray) followed in the top view, so its surface polygon, ROI and place point
are where the robot is now (2026-10-30).

The Pinky tray's polygon and place point were set at 20:30; by 23:04 the robot had moved ~45 px and the configured
place area sat on its body. Here features of the robot (lidar, labels, tray edges) in a reference frame are matched
to the current frame, a rotation + translation is fitted with RANSAC, and the reference polygon and place pixel are
moved with it. Too few matches: refused ("site not found"), never the stale numbers.

  sites.<site>.track = {"reference": "<frame.jpg>", "surface_px": [[x, y], ...], "place_px": [x, y]}
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

import cell_params as prm


def motion(ref, cur, polygon_px, params=None) -> dict:
    """{"ok", "M" (2x3 image affine, rotation + translation), "inliers", "turn_deg", "why"} for the region around
    polygon_px (grown by track.around_px), contrast-equalised so a darker or brighter frame still matches."""
    import cv2

    def grey(img):
        g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.createCLAHE(2.0, (8, 8)).apply(g)

    around = prm.get(params, "track.around_px")
    x, y, w, h = cv2.boundingRect(np.asarray(polygon_px, np.int32))
    mask = np.zeros(ref.shape[:2], np.uint8)
    mask[max(0, y - around):y + h + around, max(0, x - around):x + w + around] = 255
    search = np.zeros(cur.shape[:2], np.uint8)
    reach = around + prm.get(params, "track.reach_px")
    search[max(0, y - reach):y + h + reach, max(0, x - reach):x + w + reach] = 255
    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(grey(ref), mask)
    k2, d2 = orb.detectAndCompute(grey(cur), search)
    if d1 is None or d2 is None:
        return {"ok": False, "why": "site not found: no features"}
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
    if len(matches) < 4:
        return {"ok": False, "why": f"site not found: {len(matches)} matches"}
    M, inliers = cv2.estimateAffinePartial2D(np.float32([k1[m.queryIdx].pt for m in matches]),
                                             np.float32([k2[m.trainIdx].pt for m in matches]), method=cv2.RANSAC,
                                             ransacReprojThreshold=3.0)
    n = int(inliers.sum()) if inliers is not None else 0
    if M is None or n < prm.get(params, "track.min_inliers"):
        return {"ok": False, "why": f"site not found: {n} matching features"}
    scale = math.hypot(M[0, 0], M[1, 0])
    if abs(scale - 1) > 0.05:  # the robot moves on the floor: its size in the view does not change
        return {"ok": False, "why": f"site not found: fitted scale {scale:.2f}"}
    return {"ok": True, "M": M, "inliers": n, "turn_deg": math.degrees(math.atan2(M[1, 0], M[0, 0]))}


def moved_px(M, points) -> list:
    return [[round(float(v), 1) for v in M @ np.array([p[0], p[1], 1.0])] for p in points]


def raw_at(pixel_fn, pixel, guess=(0.0, 0.2), iterations: int = 6):
    """The arm point (m) that shows at `pixel`: pixel_fn inverted by Newton steps with a numerical Jacobian."""
    q, h = np.array(guess, float), 1e-3
    for _ in range(iterations):
        p = np.array(pixel_fn(tuple(q)))
        J = np.column_stack([(np.array(pixel_fn((q[0] + h, q[1]))) - p) / h, (np.array(pixel_fn((q[0], q[1] + h))) - p) / h])
        q = q + np.linalg.solve(J, np.asarray(pixel, float) - p)
    return float(q[0]), float(q[1])


def follow(config: dict, site: str, cur, pixel_fn, work_dir=None) -> tuple[dict, dict]:
    """(config with the site moved, report). A site without `track` is returned unchanged."""
    import cv2

    s = config["sites"][site]
    track = s.get("track")
    if not track:
        return config, {"site": site, "tracked": False}
    ref_path = Path(track["reference"]).expanduser()
    ref = cv2.imread(str(ref_path if ref_path.is_absolute() or work_dir is None else Path(work_dir) / ref_path))
    if ref is None:
        return config, {"site": site, "tracked": False, "why": f"no reference frame {track['reference']}"}
    m = motion(ref, cur, track["surface_px"], config.get("params"))
    if not m["ok"]:
        return config, {"site": site, "tracked": False, "why": m["why"]}
    polygon = moved_px(m["M"], track["surface_px"])
    (px, py), = moved_px(m["M"], [track["place_px"]])
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    pad = prm.get(config.get("params"), "track.roi_pad_px")
    place = raw_at(pixel_fn, (px, py), guess=s["place"])
    a, b = pixel_fn(place), pixel_fn((place[0] + 0.01, place[1]))
    c = pixel_fn((place[0], place[1] + 0.01))
    mirrored = np.linalg.det(np.array([[b[0] - a[0], c[0] - a[0]], [b[1] - a[1], c[1] - a[1]]])) < 0
    turn = -m["turn_deg"] if mirrored else m["turn_deg"]  # the arm frame turns the other way when the view is mirrored
    moved = dict(s, surface_px=polygon, place=[round(place[0], 4), round(place[1], 4)], start=[round(place[0], 4), round(place[1], 4)],
                 auto_roi=[round(min(xs)) - pad, round(min(ys)) - pad, round(max(xs)) + pad, round(max(ys)) + pad],
                 yaw_deg=round(track.get("yaw_deg", s["yaw_deg"]) + turn, 1))
    return dict(config, sites=dict(config["sites"], **{site: moved})), {
        "site": site, "tracked": True, "inliers": m["inliers"], "turn_deg": round(m["turn_deg"], 1),
        "shift_px": [round(float(m["M"][0, 2]), 1), round(float(m["M"][1, 2]), 1)], "place": moved["place"],
        "surface_px": polygon}
