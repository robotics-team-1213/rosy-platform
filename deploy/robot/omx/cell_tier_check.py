#!/usr/bin/env python3
"""Does the top camera's model place points right at every stacking height? The printed board, not the arm, says so.

Why (2026-11-14): the mentor asked to validate the camera calibration with one camera in a restricted work area before
changing the pipeline, and to see whether the position error improves. The arm cannot be the yardstick (its FK is
~8 mm off in z, and the existing map points scatter ~7 mm), and those points all lie on one plane, which hides the
height error: simulated, a one-height map is 6-11 mm off per 30 mm of height in arm_b's zone. So: the printed board
lies flat on the table (the reference plane), then on container stacks (+30, +60, +90 mm); for each tier frame every
corner's ray meets the tier's plane, and the points must match the printed layout (a rigid 2-D fit, mm). That is the
camera model a pick from the top view uses, checked where the arm is not involved. Each tier's height is also solved
from its own board, so a stack that is not the height it is said to be shows as that, not as a camera error.
Gate per tier (from simulation at 0.5 px corner noise: rms 0.7-1.0 mm, p95 1.5-1.7): rms <= 1.5 mm, max <= 2.5 mm,
height within 1.5 mm. A model off by one tier reads 8-9 mm, so the gate separates the two (simulated: a 60 mm board read
at table height, rms 7.0 / max 10.9 mm). Not a test of K itself: a focal length 2 % off still passes inside the boards'
area (the table pose absorbs it, heights read ~1 % off); K is checked by cell_device_intrinsics verify.

  cell_tier_check.py --intrinsics K.json --table TABLE_DIR --tier 30=DIR30 --tier 60=DIR60 --tier 90=DIR90
  K.json: an intrinsics record ("K", optional "dist"), e.g. cell_device_intrinsics verify or cell_checkerboard output.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_checkerboard as cb

MAX_RMS_MM, MAX_ERR_MM, MAX_HEIGHT_MM = 1.5, 2.5, 1.5
MAX_TILT_DEG = 1.0  # a board not flat on its stack (1 deg moves its far corner ~2.6 mm) says nothing about the tier
MAX_TABLE_RMS_PX = 1.0


def _pose(found: list, K, dist) -> tuple:
    """(R, t mm) of the board in the camera from one or more detections of the same placement."""
    import cv2

    obj = np.concatenate([np.asarray(o, np.float64).reshape(-1, 3) for o, _ in found]) * 1000.0
    pix = np.concatenate([np.asarray(p, np.float64).reshape(-1, 2) for _, p in found])
    ok, rvec, tvec = cv2.solvePnP(obj, pix, K, dist)
    if not ok:
        raise ValueError("board pose failed")
    back = cv2.projectPoints(obj, rvec, tvec, K, dist)[0].reshape(-1, 2)
    return cv2.Rodrigues(rvec)[0], tvec.reshape(3), float(np.sqrt(((back - pix) ** 2).sum(axis=1).mean()))


def _rigid_fit_2d(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Residuals (mm) after the best rotation + translation of src onto dst (no scale: the print is to scale)."""
    a, b = src - src.mean(axis=0), dst - dst.mean(axis=0)
    u, _, vt = np.linalg.svd(a.T @ b)
    rot = (u @ vt).T
    if np.linalg.det(rot) < 0:
        vt[-1] *= -1
        rot = (u @ vt).T
    return np.linalg.norm(a @ rot.T - b, axis=1)


def check(table: list, tiers: dict, K, dist) -> dict:
    """table: detections of the board flat on the table (one placement); tiers: {height mm: [detections]}."""
    import cv2

    K, dist = np.asarray(K, float), np.asarray(dist, float).reshape(-1)
    R0, t0, table_rms = _pose(table, K, dist)
    centre = -R0.T @ t0  # the camera in the table-board frame; the board's +z points away from the camera
    if centre[2] >= 0:
        raise ValueError("camera is not in front of the table board")
    if table_rms > MAX_TABLE_RMS_PX:  # the frames do not agree: the board moved between them, or a bad fit
        return {"accepted": False, "reason": "table board pose does not fit its frames",
                "table_rms_px": round(table_rms, 2), "tiers": {}}
    rows, accepted = {}, True
    for height, frames in sorted(tiers.items()):
        rms_list, worst, heights, tilts = [], 0.0, [], []
        for obj, pix in frames:
            rays = cv2.undistortPoints(np.asarray(pix, np.float64).reshape(-1, 1, 2), K, dist).reshape(-1, 2)
            dirs = np.column_stack([rays, np.ones(len(rays))]) @ R0  # rows: R0.T @ d
            s = (-height - centre[2]) / dirs[:, 2]  # the tier plane is `height` mm toward the camera
            hit = centre + dirs * s[:, None]
            err = _rigid_fit_2d(np.asarray(obj, float).reshape(-1, 3)[:, :2] * 1000.0, hit[:, :2])
            rms_list.append(float(np.sqrt((err ** 2).mean())))
            worst = max(worst, float(err.max()))
            R1, t1, _ = _pose([(obj, pix)], K, dist)
            middle = np.asarray(obj, float).reshape(-1, 3).mean(axis=0) * 1000.0  # its centre: a tilt barely moves it
            heights.append(float(-(R0.T @ (R1 @ middle + t1 - t0))[2]))
            tilts.append(math.degrees(math.acos(min(1.0, abs(float((R0.T @ R1)[2, 2]))))))
        rms, solved, tilt = float(np.median(rms_list)), float(np.median(heights)), float(max(tilts))
        ok = (rms <= MAX_RMS_MM and worst <= MAX_ERR_MM and abs(solved - height) <= MAX_HEIGHT_MM
              and tilt <= MAX_TILT_DEG)
        accepted &= ok
        rows[str(height)] = {"ok": ok, "frames": len(frames), "rms_mm": round(rms, 2), "max_mm": round(worst, 2),
                             "height_solved_mm": round(solved, 1), "tilt_to_table_deg": round(tilt, 2)}
    return {"accepted": accepted and bool(rows), "camera_above_table_mm": round(float(-centre[2]), 1),
            "table_rms_px": round(table_rms, 2),
            "gate": {"rms_mm": MAX_RMS_MM, "max_mm": MAX_ERR_MM, "height_mm": MAX_HEIGHT_MM, "tilt_deg": MAX_TILT_DEG},
            "tiers": rows}


def _detections(folder: Path) -> list:
    import cv2

    board = cb.charuco_board(*cb.PRINTED)
    found = [cb.find_charuco(cv2.imread(str(p)), board, min_corners=12)
             for p in sorted(folder.iterdir()) if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    return [f for f in found if f is not None]


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--intrinsics", type=Path, required=True)
    ap.add_argument("--table", type=Path, required=True, help="frames of the board flat on the table, not moved")
    ap.add_argument("--tier", action="append", required=True, help="HEIGHT_MM=DIR, frames of the board on that stack")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    intr = json.loads(args.intrinsics.read_text())
    table = _detections(args.table)
    if not table:
        raise SystemExit("board not seen in the table frames")
    tiers = {}
    for item in args.tier:
        height, folder = item.split("=", 1)
        found = _detections(Path(folder))
        if not found:
            raise SystemExit(f"board not seen in {folder}")
        tiers[float(height)] = found
    result = check(table, tiers, intr["K"], intr.get("dist", [0.0] * 5))
    text = json.dumps(result, indent=1)
    if args.out:
        args.out.write_text(text)
    print(text)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
