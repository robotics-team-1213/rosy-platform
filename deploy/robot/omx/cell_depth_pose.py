#!/usr/bin/env python3
"""Where the top camera sits over the work board, from one D435 depth frame: height and tilt, no board, no arm.

Why (2026-11-13): the top camera gets bumped and must be re-placed fast, and an image-only re-registration cannot
split a bump into rotation and translation (1 deg and 10 mm both move the view about 10 px). The depth stream measures
the work board as a plane, and with the device's own factory calibration (depth K and depth -> colour transform,
`cell_device_intrinsics read`) that plane is known in the colour camera's frame: its distance is the camera's height
above the board and its normal the camera's tilt. On 2026-11-13 the board under the arms read 596.8 mm, and the
projected plane fell on the board's edges in the colour image.
Precision, measured on 30 frames that day (6 groups of 5): height +-0.3-0.6 mm, tilt only +-0.6 deg, since the depth
map itself steps between frames (about 1.2 deg once) and the board shares its height band with the ship deck and the
trays. So this settles height (a bump toward or away from the board, which the image cannot tell from a turn) and
only gross tilt; the reference-image shift (cell_preflight, about 0.1 deg per px) stays the tilt and yaw detector,
and markers (cell_frame) the full pose.

  cell_depth_pose.py measure --depth d.raw --factory factory.json --roi 40,150,620,470 --out pose.json
  cell_depth_pose.py compare pose.json reference.json        # exit 1 when the camera moved
  cell_depth_pose.py bump --image now.jpg --ref-image ref.jpg --pose pose.json --ref-pose reference.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_depth

TILT_MOVED_DEG = 2.0  # three times the measured +-0.6 deg; finer tilt is the image shift's job
HEIGHT_MOVED_MM = 6.0  # +-0.6 mm within a run, but D435 depth drifts up to ~1 % of 600 mm with warm-up across runs
MIN_SHARE, MAX_RMS_MM = 0.3, 3.0  # 2026-11-13 board: share 0.40, rms 2.2 mm


def calibration(factory: dict) -> tuple:
    """(depth K, colour K, R, t in mm) from a `cell_device_intrinsics read` record; R maps depth to colour, row-major."""
    try:
        depth_K = np.asarray(factory["depth"]["K"], float)
        colour_K = np.asarray(factory["K"], float)
        R = np.asarray(factory["depth_to_colour"]["R"], float)
        t = np.asarray(factory["depth_to_colour"]["t_m"], float) * 1000.0
    except (KeyError, TypeError) as exc:
        raise ValueError("factory record lacks depth K or the depth -> colour transform") from exc
    if depth_K.shape != (3, 3) or colour_K.shape != (3, 3) or R.shape != (3, 3) or t.shape != (3,):
        raise ValueError("factory record has malformed depth calibration")
    if not np.allclose(R @ R.T, np.eye(3), atol=1e-4):
        raise ValueError("depth -> colour rotation is not a rotation")
    return depth_K, colour_K, R, t


def surface(depth_mm: np.ndarray, factory: dict, roi: tuple, tol_mm: float = 4.0, seed: int = 0) -> dict:
    """The largest plane among depth points that land inside the colour-pixel box `roi` (x0, y0, x1, y1), in the colour
    camera frame: distance (camera height above it, mm), tilt of the optical axis from its normal, and fit quality."""
    depth_K, colour_K, R, t = calibration(factory)
    h, w = depth_mm.shape
    v, u = np.nonzero(depth_mm > 0)
    z = depth_mm[v, u].astype(float)
    pts = np.column_stack([(u - depth_K[0, 2]) * z / depth_K[0, 0], (v - depth_K[1, 2]) * z / depth_K[1, 1], z])
    in_colour = pts @ R.T + t
    pix = in_colour @ colour_K.T
    pix = pix[:, :2] / pix[:, 2:3]
    x0, y0, x1, y1 = roi
    keep = (pix[:, 0] >= x0) & (pix[:, 0] < x1) & (pix[:, 1] >= y0) & (pix[:, 1] < y1)
    sample = in_colour[keep][::3]
    if len(sample) < 500:
        return {"ok": False, "reason": "too_few_depth_points_in_roi", "points": int(len(sample))}
    best, _ = cell_depth._ransac(sample, tol_mm, 2000, np.random.default_rng(seed))
    if best is None:
        return {"ok": False, "reason": "no_plane", "points": int(len(sample))}
    normal, centre = best
    for _ in range(5):  # refit on the inliers of the refit plane
        near = sample[np.abs((sample - centre) @ normal) < tol_mm]
        if len(near) < 3:
            return {"ok": False, "reason": "no_plane", "points": int(len(sample))}
        centre = near.mean(axis=0)
        normal = np.linalg.svd(near - centre, full_matrices=False)[2][-1]
    distance = float(-normal @ centre)
    if distance < 0:
        normal, distance = -normal, -distance
    residual = (near - centre) @ normal
    tilt = math.degrees(math.acos(min(1.0, abs(float(normal[2])))))
    share, rms = len(near) / len(sample), float(np.sqrt((residual ** 2).mean()))
    clear = share >= MIN_SHARE and rms <= MAX_RMS_MM  # else a deck, tray or the far table may have won silently
    return {"ok": clear, "reason": None if clear else "plane_not_clear_in_roi", "height_mm": round(distance, 1), "tilt_deg": round(tilt, 2),
            "tilt_toward_deg": round(math.degrees(math.atan2(-normal[1], -normal[0])), 1),
            "normal": [round(float(x), 5) for x in normal], "share": round(share, 3),
            "rms_mm": round(rms, 2), "roi": list(roi)}


def compare(current: dict, reference: dict) -> dict:
    """How far the camera moved between two `surface` results of the same board."""
    if not (current.get("ok") and reference.get("ok")):
        return {"moved": None, "reason": "a measurement failed"}
    if current.get("roi") != reference.get("roi"):
        return {"moved": None, "reason": "different colour boxes measure different surfaces"}
    cosine = abs(float(np.dot(current["normal"], reference["normal"])))
    tilt = math.degrees(math.acos(min(1.0, cosine)))
    height = current["height_mm"] - reference["height_mm"]
    return {"moved": tilt > TILT_MOVED_DEG or abs(height) > HEIGHT_MOVED_MM,
            "tilt_change_deg": round(tilt, 2), "height_change_mm": round(height, 1)}


def bump(reference_image, current_image, reference_pose: dict, current_pose: dict, max_shift_px: float = 6.0) -> dict:
    """After a knock: the reference-image shift (cell_preflight, turns and slides) and the depth height (toward or
    away from the board, which the image cannot tell from a turn) in one verdict."""
    import cell_preflight

    shift = cell_preflight.camera_shift_px(reference_image, current_image)
    depth = compare(current_pose, reference_pose)
    if not shift.get("ok") or depth["moved"] is None:
        return {"moved": None, "reason": shift.get("why") or depth.get("reason"), "shift": shift, "depth": depth}
    turned = shift["max_px"] > max_shift_px
    kind = "none" if not (turned or depth["moved"]) else "height" if depth["moved"] else "view"
    return {"moved": kind != "none", "kind": kind, "shift_px": shift["max_px"], **depth}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    me = sub.add_parser("measure")
    me.add_argument("--depth", type=Path, required=True, help="raw Z16 (mm), one or more frames of the factory size")
    me.add_argument("--factory", type=Path, required=True, help="cell_device_intrinsics read output")
    me.add_argument("--roi", required=True, help="x0,y0,x1,y1 of the work board in colour pixels")
    me.add_argument("--out", type=Path)
    co = sub.add_parser("compare")
    co.add_argument("current", type=Path)
    co.add_argument("reference", type=Path)
    bu = sub.add_parser("bump", help="reference-image shift and depth height together")
    bu.add_argument("--image", type=Path, required=True)
    bu.add_argument("--ref-image", type=Path, required=True)
    bu.add_argument("--pose", type=Path, required=True, help="`measure` output now")
    bu.add_argument("--ref-pose", type=Path, required=True, help="`measure` output at the reference")
    bu.add_argument("--max-shift-px", type=float, default=6.0)
    args = ap.parse_args(argv)
    if args.verb == "bump":
        import cv2

        result = bump(cv2.imread(str(args.ref_image), cv2.IMREAD_GRAYSCALE), cv2.imread(str(args.image), cv2.IMREAD_GRAYSCALE),
                      json.loads(args.ref_pose.read_text()), json.loads(args.pose.read_text()), args.max_shift_px)
        print(json.dumps(result))
        return 1 if result["moved"] is not False else 0
    if args.verb == "compare":
        result = compare(json.loads(args.current.read_text()), json.loads(args.reference.read_text()))
        print(json.dumps(result))
        return 1 if result["moved"] is not False else 0
    factory = json.loads(args.factory.read_text())
    w, h = factory["depth"]["size"]
    frames = np.fromfile(args.depth, np.uint16)
    if frames.size % (w * h):
        raise SystemExit(f"depth file is not whole {w}x{h} frames")
    stack = frames.reshape(-1, h, w).astype(float)
    stack[stack == 0] = np.nan
    with np.errstate(all="ignore"):
        depth = np.nan_to_num(np.nanmedian(stack, axis=0), nan=0.0)  # median over frames, no return stays 0
    result = surface(depth, factory, tuple(int(v) for v in args.roi.split(",")))
    text = json.dumps(result, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
