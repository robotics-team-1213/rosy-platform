#!/usr/bin/env python3
"""A camera's own factory intrinsics, checked against real board frames, as a D-933 intrinsics record.

Why (2026-11-13): the cell A·B top camera is a RealSense D435 whose colour calibration is stored in the device. Every
survey had assumed f 615 px; the device says 618.5/618.7 px at (322.3, 236.6), no distortion, for the native 640x480
stream. The hand-held board set could not fit f itself (one pose fixes only f/Z), but it can check a given K: the
factory K, held fixed, re-projects those 60 real views at 0.28 px, as well as a free five-parameter fit does.
So: read the factory K (no streaming; pyrealsense2 in its own venv, the colour node stays with camera_source), then
`verify` holds it on >= 25 receipted board frames of the same stream and writes the record cell_frame accepts, but
only when the frames reach the image edges (the record claims zero distortion everywhere) and also find that K on
their own (f within 2 %, principal point within 10 px, from guesses 15 % off on both sides). That needs the board
across the image and tilted +-20 deg or more; one pose, or one tilt carried to several spots, is refused.
Not checked: that the frames came from the device with this serial (frame receipts carry no serial).

  python cell_device_intrinsics.py read --width 640 --height 480 --out factory.json     # needs pyrealsense2
  python cell_device_intrinsics.py verify FRAMES --camera top --factory factory.json --scale-bar-mm 50 --out intr.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import cell_checkerboard as cb


def read_realsense(width: int, height: int, fps: int = 30) -> dict:
    """Factory colour intrinsics of the one attached RealSense for a stream size; queries the calibration, streams nothing."""
    import pyrealsense2 as rs

    devices = list(rs.context().query_devices())
    if len(devices) != 1:
        raise RuntimeError(f"expected one RealSense, found {len(devices)}")
    dev = devices[0]
    found = {}
    for sensor in dev.query_sensors():
        for p in sensor.get_stream_profiles():
            if p.fps() != fps or not p.is_video_stream_profile() or p.stream_type() not in (rs.stream.color, rs.stream.depth):
                continue
            v = p.as_video_stream_profile()
            if (v.width(), v.height()) == (width, height):
                found.setdefault(p.stream_type(), v)
    colour, depth = found.get(rs.stream.color), found.get(rs.stream.depth)
    if colour is None:
        raise RuntimeError(f"no {width}x{height}@{fps} colour profile")

    def matrix(i):
        return [[i.fx, 0.0, i.ppx], [0.0, i.fy, i.ppy], [0.0, 0.0, 1.0]]

    i = colour.get_intrinsics()
    record = {"kind": "device_factory", "device": dev.get_info(rs.camera_info.name),
              "serial": dev.get_info(rs.camera_info.serial_number),
              "firmware": dev.get_info(rs.camera_info.firmware_version),
              "stream": "color", "size": [width, height], "fps": fps, "K": matrix(i),
              "model": str(i.model).split(".")[-1], "coeffs": [float(c) for c in i.coeffs]}
    if depth is not None:  # cell_depth_pose: the depth stream of the same size and its place in the colour frame
        d = depth.get_intrinsics()
        e = depth.get_extrinsics_to(colour)
        record["depth"] = {"size": [width, height], "K": matrix(d), "model": str(d.model).split(".")[-1],
                           "coeffs": [float(c) for c in d.coeffs]}
        # librealsense stores the rotation column-major; written here row-major, so colour = R @ depth + t
        record["depth_to_colour"] = {"R": np.asarray(e.rotation, float).reshape(3, 3).T.tolist(),
                                     "t_m": [float(x) for x in e.translation]}
    return record


ZERO_MEANS_IDENTITY = ("none", "brown_conrady", "inverse_brown_conrady", "modified_brown_conrady")


def _fit_f_and_centre(objects: list, pixels: list, size, K: np.ndarray, sign: int) -> dict:
    import cv2

    guess = K.copy()
    guess[0, 0] *= 1 + 0.15 * sign
    guess[1, 1] *= 1 + 0.15 * sign
    guess[:2, 2] += (15 * sign, -15 * sign)
    flags = (cv2.CALIB_USE_INTRINSIC_GUESS | cv2.CALIB_FIX_ASPECT_RATIO | cv2.CALIB_ZERO_TANGENT_DIST
             | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2 | cv2.CALIB_FIX_K3)
    try:
        fitted = cv2.calibrateCamera([np.asarray(o, np.float32) for o in objects],
                                     [np.asarray(p, np.float32) for p in pixels], tuple(size), guess, np.zeros(5),
                                     flags=flags)[1]
    except cv2.error:
        fitted = np.full((3, 3), np.nan)
    f_off = abs(float(fitted[0, 0]) / float(K[0, 0]) - 1)
    pp_off = float(np.hypot(*(fitted[:2, 2] - K[:2, 2])))
    ok = math.isfinite(f_off) and math.isfinite(pp_off)
    return {"start": "+15%" if sign > 0 else "-15%",
            "f_px": round(float(fitted[0, 0]), 1) if ok else None,
            "principal_px": [round(float(v), 1) for v in fitted[:2, 2]] if ok else None,
            "f_off": round(f_off, 4) if ok else None, "principal_off_px": round(pp_off, 1) if ok else None}


def verify(folder: Path, camera: str, factory: dict, scale_bar_mm: float) -> dict:
    """Hold the factory K fixed on receipted board frames; accepted records have the shape cell_frame reads."""
    import cv2

    spec = cb.board_spec(scale_bar_mm)
    observations, objects, pixels, size, unique, binding = cb.board_observations(folder, camera)
    checks = {"valid_views": len(observations), "unique_views": unique, "reasons": []}
    source = {key: factory.get(key) for key in ("kind", "device", "serial", "firmware", "stream", "size", "fps", "model")}
    result = {"camera": camera, "size": list(size) if size else None, "accepted": False, "board": spec,
              "source": source, "source_frames": observations, "device_binding": binding, "checks": checks}
    K = np.asarray(factory.get("K"), float)
    coeffs = np.asarray(factory.get("coeffs", []), float)
    if (factory.get("kind") != "device_factory" or K.shape != (3, 3) or not np.isfinite(K).all()
            or coeffs.shape != (5,) or factory.get("model") not in ZERO_MEANS_IDENTITY):
        raise ValueError("factory record lacks a device K, five coefficients or a Brown-Conrady model")
    if np.any(coeffs != 0):
        # RealSense's inverse Brown-Conrady maps the other way from OpenCV's; only an all-zero model carries over as is
        checks["reasons"].append("factory_distortion_model_not_opencv")
    if list(factory.get("size") or []) != result["size"]:
        checks["reasons"].append("frame_size_differs_from_factory_stream")
    if len(observations) < 25:
        checks["reasons"].append("need_at_least_25_valid_views")
    elif max(item["corners"] for item in observations) < 30:
        checks["reasons"].append("printed_board_layout_not_seen")
    else:
        # the record claims K and zero distortion for the whole image, so the frames must reach its edges too
        checks["image_coverage"] = cb.view_coverage(pixels, [item["scale_px_per_m"] for item in observations], size)
        checks["reasons"] += cb.coverage_reasons(checks["image_coverage"])
    if checks["reasons"]:
        return result
    dist = np.zeros(5)
    squared, count = 0.0, 0
    for obj, pix in zip(objects, pixels):
        ok, rvec, tvec = cv2.solvePnP(np.asarray(obj, np.float64), np.asarray(pix, np.float64), K, dist)
        if not ok:
            checks["reasons"].append("board_pose_failed")
            return result
        proj = cv2.projectPoints(np.asarray(obj, np.float64), rvec, tvec, K, dist)[0].reshape(-1, 2)
        squared += float(((proj - np.asarray(pix, float).reshape(-1, 2)) ** 2).sum())
        count += len(proj)
    rms = math.sqrt(squared / count)
    checks["rms_px"] = round(rms, 4)
    if rms > 0.5:
        checks["reasons"].append("rms_above_0_5_px")  # the device K does not explain these frames: wrong stream or lens
    # A fixed K re-projects one-pose frames equally well at f +-10 % (2026-11-13: 0.284 vs 0.296/0.288 px), so the
    # frames must also find the factory K on their own: f and principal point fitted from two guesses 15 % / 15 px off
    # on either side; a flat valley leaves one of them stranded.
    fits = [_fit_f_and_centre(objects, pixels, size, K, sign) for sign in (1, -1)]
    checks["independent_fits"] = fits
    if not all(fit["f_off"] is not None and fit["f_off"] <= 0.02 and fit["principal_off_px"] <= 10 for fit in fits):
        checks["reasons"].append("frames_do_not_reproduce_factory_k")  # one pose or flat views: tilt the board
    if binding is None or binding.get("unique_hardware_identity") is not True:
        checks["reasons"].append("camera_identity_unverified")
    elif not factory.get("serial") or factory["serial"] != binding.get("serial"):
        checks["reasons"].append("factory_camera_serial_differs_from_frames")
    if checks["reasons"] == ["camera_identity_unverified"]:
        result["diagnostic_fit"] = {"factory_K": K.tolist(), "rms_px": checks["rms_px"], "independent_fits": fits}
    if not checks["reasons"]:
        result.update({"accepted": True, "K": K.tolist(), "dist": dist.tolist(), "rms_px": checks["rms_px"]})
    return result


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    rd = sub.add_parser("read")
    rd.add_argument("--width", type=int, required=True)
    rd.add_argument("--height", type=int, required=True)
    rd.add_argument("--out", type=Path, required=True)
    vf = sub.add_parser("verify")
    vf.add_argument("frames", type=Path)
    vf.add_argument("--camera", required=True)
    vf.add_argument("--factory", type=Path, required=True)
    vf.add_argument("--scale-bar-mm", type=float, required=True, help="measured length of the printed 50 mm bar")
    vf.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.verb == "read":
        record = read_realsense(args.width, args.height)
        args.out.write_text(json.dumps(record, indent=1))
        print(json.dumps(record))
        return 0
    result = verify(args.frames, args.camera, json.loads(args.factory.read_text()), args.scale_bar_mm)
    args.out.write_text(json.dumps(result, indent=1, allow_nan=False))
    print(json.dumps({"accepted": result["accepted"], "checks": result["checks"]}))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
