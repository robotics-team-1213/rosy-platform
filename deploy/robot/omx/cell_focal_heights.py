#!/usr/bin/env python3
"""Focal length of a fixed camera from the printed board lying flat at two known heights. No arm, no tilting by hand.

Why (2026-11-13): every top-camera (D435 colour) survey so far fixed f at the nominal 615 px, and the hand-held ChArUco
set was one pose, which only fixes f/Z (1166 px/m), so nothing had measured f. Two parallel planes a known height
apart do: for a guessed f, solvePnP gives each plane's distance from the camera along its normal; only the true f makes
the two distances differ by the lift. The lift comes from CAD (containers are 30 mm per layer), so the answer does not
depend on tilt, on where in the image the board lies, or on a person holding still.
A check, not the calibration: it assumes the principal point at the image centre and no distortion, and in simulation
lands within about 2 % (a principal point 13 px off moves f about 1.7 %, board placement about 1 %). It tells a right
focal length from a degenerate fit (2229 or 1229 px against 615); a multi-tilt ChArUco fit stays the source of K/dist.

  cell_focal_heights.py LOW_DIR HIGH_DIR --lift-mm 90 [--out focal.json]
  LOW_DIR / HIGH_DIR: frames (.jpg/.png) of the board resting flat on the lower and the raised surface.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_checkerboard as cb


def detections(images: list, board=None) -> list:
    board = board or cb.charuco_board(*cb.PRINTED)
    found = [cb.find_charuco(img, board, min_corners=12) for img in images]
    return [f for f in found if f is not None]


def plane_distance(found: list, size: tuple, f_px: float) -> tuple:
    """(median distance to the board plane in metres, its normal per view) with K = f at the image centre."""
    K = np.array([[f_px, 0, size[0] / 2], [0, f_px, size[1] / 2], [0, 0, 1.0]])
    dists, normals = [], []
    for obj, pix in found:
        pose = cb.board_pose(np.asarray(pix, np.float64), np.asarray(obj, np.float64), K, np.zeros(5))
        if pose is None:
            continue
        R, t = pose
        dists.append(abs(float(R[:, 2] @ t)))
        normals.append(R[:, 2] * np.sign(R[2, 2]))
    return (float(np.median(dists)) if dists else math.nan), normals


def focal_from_heights(low: list, high: list, size: tuple, lift_m: float) -> dict:
    """low/high: detections of the board flat on the lower and on the raised surface (same camera, same size)."""
    if not 0.01 <= lift_m <= 0.3:
        raise ValueError("lift must be 10-300 mm")
    reasons = []
    if len(low) < 2 or len(high) < 2:
        return {"accepted": False, "reasons": ["need_two_views_per_height"], "views": [len(low), len(high)]}

    if not _gap(low, high, size, lift_m, F_RANGE[0]) < 0 < _gap(low, high, size, lift_m, F_RANGE[1]):
        return {"accepted": False, "reasons": ["lift_not_explained_by_any_focal_length"], "views": [len(low), len(high)]}
    f_px = _solve(low, high, size, lift_m)
    d_low, n_low = plane_distance(low, size, f_px)
    d_high, n_high = plane_distance(high, size, f_px)
    each = [plane_distance([v], size, f_px)[0] for v in low + high]
    if len(n_low) != len(low) or len(n_high) != len(high) or not all(map(math.isfinite, each)):
        return {"accepted": False, "reasons": ["board_pose_failed"], "views": [len(low), len(high)]}
    normals = np.asarray(n_low + n_high)
    mean = normals.mean(axis=0) / np.linalg.norm(normals.mean(axis=0))
    worst_deg = max(math.degrees(math.acos(min(1.0, abs(float(n @ mean))))) for n in normals)
    if worst_deg > 2.0:
        reasons.append("boards_not_parallel")  # one of them is not lying flat
    spread = max(float(np.ptp(each[:len(low)])), float(np.ptp(each[len(low):])))
    if spread > 0.002:
        reasons.append("board_moved_within_a_height")
    # the data's own scatter: f from each low view paired with each high view
    pairs = [_solve([a], [b], size, lift_m) for a in low[:5] for b in high[:5]]
    return {"accepted": not reasons, "reasons": reasons, "f_px": round(f_px, 1),
            "f_pairs_px": [round(min(pairs), 1), round(max(pairs), 1)],
            "distance_low_m": round(d_low, 4), "distance_high_m": round(d_high, 4), "lift_m": lift_m,
            "normals_spread_deg": round(worst_deg, 2), "distance_spread_m": round(spread, 4),
            "views": [len(low), len(high)],
            "assumes": "principal point at image centre, no distortion; about 2 % in simulation"}


F_RANGE = (200.0, 2500.0)


def _gap(low, high, size, lift_m, f_px) -> float:
    """Distance gap between the two planes at this f, minus the lift: grows with f, zero at the true f."""
    return plane_distance(low, size, f_px)[0] - plane_distance(high, size, f_px)[0] - lift_m


def _solve(low, high, size, lift_m) -> float:
    lo, hi = F_RANGE
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _gap(low, high, size, lift_m, mid) < 0 else (lo, mid)
    return (lo + hi) / 2


def _frames(folder: Path) -> list:
    import cv2

    images = [cv2.imread(str(p)) for p in sorted(folder.iterdir()) if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    return [img for img in images if img is not None]


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("low", type=Path)
    ap.add_argument("high", type=Path)
    ap.add_argument("--lift-mm", type=float, required=True, help="raised surface above the lower one (CAD), mm")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    low, high = _frames(args.low), _frames(args.high)
    if not low or not high:
        raise SystemExit("no frames in one of the folders")
    size = (low[0].shape[1], low[0].shape[0])
    if any((img.shape[1], img.shape[0]) != size for img in low + high):
        raise SystemExit("frame sizes differ")
    result = focal_from_heights(detections(low), detections(high), size, args.lift_mm / 1000)
    text = json.dumps(result, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
