#!/usr/bin/env python3
"""Points the top D435 sees, in millimetres, from its own depth: the corners of markers both cameras see, the side
camera's pose from them, and a check of the top focal length that does not use Intel's colour calibration.

Why (2026-11-13): the side camera's fixed-marker pose (cell_z_profile side reference) needs each marker's corners
in millimetres, which a person had to measure; the top camera can read them. Depth is registered onto the colour view
with the factory depth K and depth -> colour transform (`cell_device_intrinsics read`; on 2026-11-13 that projection
fell on the board's edges), so a colour pixel gets the depth around it and becomes a point in the top colour camera's
frame. With the factory colour K that is a marker corner; solving the side view's same corners gives the side camera
in the top camera's frame. The same points check the focal length: only the true f makes the printed board's corner
spacing come out at 20 mm, and depth supplies the distance. That f does not come from the colour calibration, but it
rests on the factory principal point, the factory depth scale (1 % of depth is 1 % of f) and the print being to scale.
Depth is good to about 1 % of the distance (6 mm at 600 mm) between runs, so these corners place the side camera to
millimetres, not tenths; markers at more than one height make the side solve better posed.

  cell_shared_markers.py corners --top top.jpg --depth d.raw --factory factory.json [--dictionary DICT_4X4_50]
  cell_shared_markers.py side --side side.jpg --side-intrinsics side.json --corners corners.json
  cell_shared_markers.py focal --top board.jpg --depth d.raw --factory factory.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_depth_pose as dp


def depth_in_colour(depth_mm: np.ndarray, factory: dict, size: tuple) -> np.ndarray:
    """Depth (mm, along the colour camera's axis) at each colour pixel; NaN where no depth point landed. The nearest
    point wins where several land on one pixel."""
    depth_K, colour_K, R, t = dp.calibration(factory)
    v, u = np.nonzero(depth_mm > 0)
    z = depth_mm[v, u].astype(float)
    pts = np.column_stack([(u - depth_K[0, 2]) * z / depth_K[0, 0], (v - depth_K[1, 2]) * z / depth_K[1, 1], z]) @ R.T + t
    pix = pts @ colour_K.T
    cu, cv = np.round(pix[:, 0] / pix[:, 2]).astype(int), np.round(pix[:, 1] / pix[:, 2]).astype(int)
    w, h = size
    keep = (cu >= 0) & (cu < w) & (cv >= 0) & (cv < h) & (pts[:, 2] > 0)
    out = np.full((h, w), np.inf)
    np.minimum.at(out, (cv[keep], cu[keep]), pts[keep, 2])
    out[np.isinf(out)] = np.nan
    return out


def points_at(pixels, colour_depth: np.ndarray, colour_K: np.ndarray, radius: int = 3) -> np.ndarray:
    """Top colour camera frame points (mm) for pixels, from the median depth within `radius`; NaN rows without depth."""
    out = []
    for u, v in np.asarray(pixels, float).reshape(-1, 2):
        x, y = int(round(u)), int(round(v))
        patch = colour_depth[max(0, y - radius):y + radius + 1, max(0, x - radius):x + radius + 1]
        z = float(np.nanmedian(patch)) if np.isfinite(patch).any() else math.nan
        out.append([(u - colour_K[0, 2]) * z / colour_K[0, 0], (v - colour_K[1, 2]) * z / colour_K[1, 1], z])
    return np.asarray(out)


def detect_markers(image, dictionary: str = "DICT_4X4_50") -> dict:
    import cv2

    grey = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
    params = cv2.aruco.DetectorParameters() if hasattr(cv2.aruco, "DetectorParameters") else cv2.aruco.DetectorParameters_create()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX  # unrefined corners sat ~1 px inside the marker
    if hasattr(cv2.aruco, "ArucoDetector"):
        corners, ids, _ = cv2.aruco.ArucoDetector(d, params).detectMarkers(grey)
    else:
        corners, ids, _ = cv2.aruco.detectMarkers(grey, d, parameters=params)
    return {} if ids is None else {int(i): c.reshape(4, 2) for c, i in zip(corners, ids.flatten())}


def marker_corners(top_image, depth_mm: np.ndarray, factory: dict, dictionary: str = "DICT_4X4_50",
                   edge_mm: dict | None = None) -> dict:
    """{id: {"corners_mm": 4x3 in the top colour camera frame, "edge_mm": mean side}} for markers with depth at all
    four corners. Left out: a marker whose sides differ by more than 4 mm (a corner on a step or an edge), and one
    whose printed size `edge_mm` (by id) is known and missed by more than 5 % (all four corners on a wrong level)."""
    colour_K = np.asarray(factory["K"], float)
    size = (top_image.shape[1], top_image.shape[0])
    colour_depth = depth_in_colour(depth_mm, factory, size)
    out = {}
    for marker_id, pix in detect_markers(top_image, dictionary).items():
        corners = points_at(pix, colour_depth, colour_K)
        if not np.isfinite(corners).all():
            continue
        sides = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
        printed = (edge_mm or {}).get(marker_id)
        if np.ptp(sides) > 4.0 or (printed and abs(sides.mean() / printed - 1) > 0.05):
            continue
        out[marker_id] = {"corners_mm": np.round(corners, 2).tolist(), "edge_mm": round(float(sides.mean()), 2)}
    return out


def side_pose(side_image, side_K, side_dist, corners: dict, dictionary: str = "DICT_4X4_50") -> dict:
    """The side camera in the top colour camera's frame (X_side = R X_top + t, mm) from the markers both saw."""
    import cell_frame

    table = {int(k): np.asarray(v["corners_mm"], float).reshape(4, 3) for k, v in corners.items()}  # JSON keys are str
    seen = detect_markers(side_image, dictionary)
    shared = sorted(set(seen) & set(table))
    if len(shared) < 2:
        return {"ok": False, "reason": "need two markers seen by both cameras", "shared": shared}
    obj = np.concatenate([table[i] for i in shared])
    pose, rms = cell_frame.solve(obj, np.concatenate([seen[i] for i in shared]),
                                 np.asarray(side_K, float), np.asarray(side_dist, float))
    if pose is None or rms is None or not math.isfinite(rms):
        return {"ok": False, "reason": "side solve failed", "shared": shared}
    R, t = pose
    centre = obj.mean(axis=0)
    off_plane = np.ptp((obj - centre) @ np.linalg.svd(obj - centre, full_matrices=False)[2][-1])
    return {"ok": rms <= 2.0, "reason": None if rms <= 2.0 else "side reprojection above 2 px", "shared": shared,
            "R": np.round(R, 6).tolist(), "t_mm": np.round(t, 2).tolist(), "rms_px": round(rms, 3),
            "marker_height_spread_mm": round(float(off_plane), 1)}


def focal_from_depth(obj, pix, depth_mm: np.ndarray, factory: dict, size: tuple) -> dict:
    """The colour focal length that makes the board's measured corner spacing equal the printed spacing; depth and
    the factory principal point supply the rest. Returns f and how far it is from the factory f."""
    colour_K = np.asarray(factory["K"], float)
    colour_depth = depth_in_colour(depth_mm, factory, size)
    pix = np.asarray(pix, float).reshape(-1, 2)
    obj = np.asarray(obj, float).reshape(-1, 3)
    z = points_at(pix, colour_depth, colour_K)[:, 2]
    keep = np.isfinite(z)
    if keep.sum() < 12:
        return {"ok": False, "reason": "board corners lack depth", "corners": int(keep.sum())}
    pix, obj, z = pix[keep], obj[keep], z[keep]
    i, j = np.triu_indices(len(obj), 1)
    true = np.linalg.norm(obj[i] - obj[j], axis=1) * 1000.0
    far = true > 60.0  # long baselines: a 2 mm depth error moves short ones too much
    if far.sum() < 20:
        return {"ok": False, "reason": "board too small in view", "corners": int(len(obj))}
    i, j, true = i[far], j[far], true[far]
    du = pix[:, 0] - colour_K[0, 2]
    dv = pix[:, 1] - colour_K[1, 2]

    def error(f):
        X = np.column_stack([du * z / f, dv * z / f, z])
        return float(np.median(np.linalg.norm(X[i] - X[j], axis=1) / true - 1))

    lo, hi = 0.5 * colour_K[0, 0], 2.0 * colour_K[0, 0]
    for _ in range(50):  # measured spacing shrinks as f grows
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if error(mid) > 0 else (lo, mid)
    f = float((lo + hi) / 2)
    if not 0.51 * colour_K[0, 0] < f < 1.99 * colour_K[0, 0]:
        return {"ok": False, "reason": "no focal length within half to twice the factory one fits", "f_px": round(f, 1)}
    off = float(f / colour_K[0, 0] - 1)
    ok = abs(off) <= 0.02  # depth is good to about 1 %
    return {"ok": ok, "reason": None if ok else "depth focal length differs from factory",
            "f_px": round(f, 1), "factory_f_px": round(float(colour_K[0, 0]), 1), "off": round(off, 4),
            "pairs": int(len(true))}


def _depth(path: Path, factory: dict) -> np.ndarray:
    w, h = factory["depth"]["size"]
    frames = np.fromfile(path, np.uint16)
    if frames.size % (w * h):
        raise SystemExit(f"depth file is not whole {w}x{h} frames")
    stack = frames.reshape(-1, h, w).astype(float)
    stack[stack == 0] = np.nan
    with np.errstate(all="ignore"):
        return np.nan_to_num(np.nanmedian(stack, axis=0), nan=0.0)


def main(argv=None) -> int:
    import argparse

    import cv2

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    co = sub.add_parser("corners")
    co.add_argument("--top", type=Path, required=True)
    co.add_argument("--depth", type=Path, required=True)
    co.add_argument("--factory", type=Path, required=True)
    co.add_argument("--dictionary", default="DICT_4X4_50")
    si = sub.add_parser("side")
    si.add_argument("--side", type=Path, required=True)
    si.add_argument("--side-intrinsics", type=Path, required=True, help="an accepted side intrinsics record (K, dist)")
    si.add_argument("--corners", type=Path, required=True, help="output of `corners`")
    si.add_argument("--dictionary", default="DICT_4X4_50")
    fo = sub.add_parser("focal")
    fo.add_argument("--top", type=Path, required=True, help="top frame with the printed board in view")
    fo.add_argument("--depth", type=Path, required=True)
    fo.add_argument("--factory", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.verb == "side":
        intr = json.loads(args.side_intrinsics.read_text())
        if intr.get("accepted") is not True:
            raise SystemExit("side intrinsics not accepted")
        result = side_pose(cv2.imread(str(args.side)), intr["K"], intr["dist"], json.loads(args.corners.read_text()),
                           args.dictionary)
    else:
        factory = json.loads(args.factory.read_text())
        top = cv2.imread(str(args.top))
        depth = _depth(args.depth, factory)
        if args.verb == "corners":
            import cell_checkerboard as cb

            board = {i: cb.PRINTED[3] * 1000 for i in range(35)} if args.dictionary == "DICT_4X4_50" else {}  # print sheet
            result = marker_corners(top, depth, factory, args.dictionary, edge_mm=board)
        else:
            import cell_checkerboard as cb

            found = cb.find_charuco(top, cb.charuco_board(*cb.PRINTED), min_corners=12)
            result = ({"ok": False, "reason": "board not seen"} if found is None
                      else focal_from_depth(*found, depth, factory, (top.shape[1], top.shape[0])))
    print(json.dumps(result, indent=1))
    return 0 if result.get("ok", bool(result)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
