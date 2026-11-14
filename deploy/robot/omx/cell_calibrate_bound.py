"""Writers for the calibration map and the camera reference it is bound to (split out of `cell_calibrate`).

Single Responsibility: carry image regions to a new frame, and publish a remap together with the
actual reference JPEG bytes so an interrupted pair always fails the reader binding.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cell_attempts  # noqa: E402


def move_regions(config: dict, reference, current) -> dict:
    """Carry every image region (site polygons and ROIs) from the reference frame to the current one (ORB + RANSAC)."""
    import cv2

    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(reference, None)
    k2, d2 = orb.detectAndCompute(current, None)
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda x: x.distance)[:600]
    H, _ = cv2.findHomography(
        np.float32([k1[x.queryIdx].pt for x in m]), np.float32([k2[x.trainIdx].pt for x in m]), cv2.RANSAC, 3.0
    )
    tp = lambda pts: [[int(round(float(v))) for v in q] for q in cv2.perspectiveTransform(np.float32([pts]), H)[0]]  # noqa: E731
    for site in config["sites"].values():
        if site.get("surface_px"):
            site["surface_px"] = tp(site["surface_px"])
        if site.get("auto_roi"):
            r = site["auto_roi"]
            q = np.array(tp([[r[0], r[1]], [r[2], r[1]], [r[2], r[3]], [r[0], r[3]]]))
            site["auto_roi"] = [
                int(max(0, q[:, 0].min())),
                int(max(0, q[:, 1].min())),
                int(min(639, q[:, 0].max())),
                int(min(479, q[:, 1].max())),
            ]
    return config


def save_bound_map_reference(cal_path: Path, ref_path: Path, calibration: dict, config: dict, image) -> None:
    """Publish a remap and its actual JPEG bytes so an interrupted pair always fails the reader binding."""
    import cv2

    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_tmp = ref_path.with_name(ref_path.stem + ".pending" + ref_path.suffix)
    if not cv2.imwrite(str(ref_tmp), image):
        raise OSError("map reference JPEG write failed")
    raw = ref_tmp.read_bytes()
    if not raw:
        raise OSError("map reference JPEG is empty")
    calibration["reference_top_sha256"] = hashlib.sha256(raw).hexdigest()
    calibration["reference_map_sha"] = cell_attempts.digest(calibration["sites"])
    calibration["reference_geometry_sha"] = cell_attempts.digest({
        name: {key: site.get(key) for key in ("auto_roi", "surface_px", "map_from")}
        for name, site in config["sites"].items() if not site.get("tier_of")})
    cal_tmp = cal_path.with_suffix(".pending.json")
    with cal_tmp.open("w", encoding="utf-8") as stream:
        json.dump(calibration, stream)
        stream.flush()
        os.fsync(stream.fileno())
    ref_tmp.replace(ref_path)
    cal_tmp.replace(cal_path)
