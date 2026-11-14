"""Offline print-sheet intrinsics: view coverage, receipted-frame observations and the K/dist fit gates.

Split out of `cell_checkerboard` (400-line cap); import that module, which re-exports these names.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import cell_checkerboard as cb  # the calls go through it so a patched `cb.find_charuco` etc. reaches this code

CELLS = ("top-left", "top", "top-right", "left", "centre", "right", "bottom-left", "bottom", "bottom-right")


def board_view(obj, pix) -> tuple | None:
    """(pixels per board metre, perspective tilt in 1/m) at the board's centre, from the view's homography.

    The scale is the larger singular value of the homography's Jacobian there: the axis the tilt does not foreshorten
    keeps f/Z, so it follows distance and not tilt. The tilt vector flips sign between mirrored tilts.
    """
    import cv2

    plane = np.asarray(obj, np.float64)[:, :2]
    if len(plane) < 4:
        return None
    try:
        H, _ = cv2.findHomography(plane, np.asarray(pix, np.float64).reshape(-1, 2))
    except cv2.error:
        return None
    if H is None or not np.isfinite(H).all():
        return None
    centre = np.append(plane.mean(axis=0), 1.0)
    w = float(H[2] @ centre)
    if abs(w) < 1e-12:
        return None
    u = H[:2] @ centre / w
    jac = (H[:2, :2] - np.outer(u, H[2, :2])) / w
    scale = float(np.linalg.svd(jac, compute_uv=False)[0])
    return (scale, H[2, :2] / w) if math.isfinite(scale) and scale > 0 else None


def board_scale(obj, pix) -> float | None:
    view = board_view(obj, pix)
    return view[0] if view else None


def view_coverage(pixel_sets: list, scales: list, size: tuple) -> dict:
    """Image extents, centre spread, distance spread and the 3x3 cells no corner reached, over a set of board views."""
    w, h = size
    views = [np.asarray(p, float).reshape(-1, 2) for p in pixel_sets]
    pts = np.concatenate(views)
    centres = np.asarray([v.mean(axis=0) for v in views])
    hit = set(zip(np.clip(pts[:, 0] * 3 // w, 0, 2).astype(int).tolist(), np.clip(pts[:, 1] * 3 // h, 0, 2).astype(int).tolist()))
    known = [s for s in scales if s]
    return {"left": round(float(pts[:, 0].min() / w), 3), "right": round(float(pts[:, 0].max() / w), 3),
            "top": round(float(pts[:, 1].min() / h), 3), "bottom": round(float(pts[:, 1].max() / h), 3),
            "center_span_x": round(float(np.ptp(centres[:, 0]) / w), 3),
            "center_span_y": round(float(np.ptp(centres[:, 1]) / h), 3),
            "distance_ratio": round(max(known) / min(known), 3) if known else 1.0,
            "missing_cells": [CELLS[r * 3 + c] for r in range(3) for c in range(3) if (c, r) not in hit]}


def coverage_reasons(coverage: dict) -> list:
    # distance_ratio is guidance, not a gate: tilt alone can fix f (the 2026-11-13 side set, ratio 1.14 and tilts to
    # 37 deg, gave f 889-906 under every distortion model); the fit's focal_change check refuses a set that cannot.
    if not (coverage["left"] <= 0.2 and coverage["right"] >= 0.8 and coverage["top"] <= 0.2 and coverage["bottom"] >= 0.8
            and coverage["center_span_x"] >= 0.15 and coverage["center_span_y"] >= 0.15):
        return ["board_not_seen_across_image"]
    return []


def board_spec(scale_bar_mm: float) -> dict:
    if not math.isfinite(scale_bar_mm) or not 49.5 <= scale_bar_mm <= 50.5:
        raise ValueError("printed 50 mm scale bar must be measured within 0.5 mm")
    return {"cols": 7, "rows": 10, "square_m": 0.020, "marker_m": 0.015,
            "dictionary": "DICT_4X4_50", "scale_bar_mm": scale_bar_mm}


def intrinsics_from_frames(folder: Path, camera: str, scale_bar_mm: float) -> dict:
    """Fit a stored ROSY print-sheet board; rejected observations never supply K/dist."""
    spec = board_spec(scale_bar_mm)
    observations, objects, pixels, size, unique, binding = board_observations(folder, camera)
    checks = {"valid_views": len(observations), "unique_views": unique, "reasons": []}
    result = {"camera": camera, "size": list(size) if size else None, "accepted": False,
              "board": spec, "source_frames": observations, "device_binding": binding, "checks": checks}
    if len(observations) < 25:
        checks["reasons"].append("need_at_least_25_valid_views")
        return result
    if max(item["corners"] for item in observations) < 30:
        checks["reasons"].append("printed_board_layout_not_seen")
        return result
    coverage = view_coverage(pixels, [item["scale_px_per_m"] for item in observations], size)
    checks["image_coverage"] = coverage
    if coverage_reasons(coverage):
        checks["reasons"] += coverage_reasons(coverage)
        # 2026-11-14: a set short of the image's edges still tells something (the side set, no view below y 300, fit
        # f ~898, k1 ~-0.35): keep it as a labelled diagnostic, never as K, naming the centre axis it cannot pin
        try:
            fitted = cb.calibrate_intrinsics(pixels, objects, size)
            result["diagnostic_fit"] = {
                "K": np.asarray(fitted["K"]).tolist(), "dist": np.asarray(fitted["dist"]).ravel().tolist(),
                "rms_px": round(float(fitted["rms_px"]), 4),
                "unpinned": [axis for axis, span in (("cx", coverage["center_span_x"]), ("cy", coverage["center_span_y"]))
                             if span < 0.15],
                "not_a_calibration": "image coverage failed; extrapolates beyond the views"}
        except Exception:  # a diagnostic must never turn a refusal into a crash
            pass
        return result
    result = _fit(result, checks, objects, pixels, size)
    if binding is None or binding.get("unique_hardware_identity") is not True:
        checks["reasons"].append("camera_identity_unverified")
        if result.get("accepted") is True:
            result["diagnostic_fit"] = {key: result.pop(key) for key in ("K", "dist", "rms_px")}
            result["accepted"] = False
    return result


def board_observations(folder: Path, camera: str) -> tuple:
    """(observations, objects, pixels, size, unique views) of the print-sheet board in receipted frames, in source order;
    a frame without a matching receipt or with a non-advancing source sequence refuses the whole set."""
    import cv2

    board = cb.charuco_board(*cb.PRINTED)
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    observations, objects, pixels, seen_hashes = [], [], [], set()
    size = None
    sources, bindings = [], []
    for path in files:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        sidecar = path.with_suffix(".json")
        if not sidecar.is_file():
            raise ValueError("captured camera frame has no source receipt")
        source_meta = json.loads(sidecar.read_text())
        if not isinstance(source_meta, dict) or source_meta.get("sha256") != digest or source_meta.get("camera") != camera:
            raise ValueError("captured camera frame differs from its source receipt")
        seq, stamp = source_meta.get("source_seq"), source_meta.get("source_stamp")
        if (isinstance(seq, bool) or not isinstance(seq, int) or seq < 0
                or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp) or stamp <= 0):
            raise ValueError("captured camera source sequence or stamp did not advance")
        bindings.append(source_meta.get("device_binding"))
        sources.append((seq, stamp, path, digest, data))
    if bindings and any(binding != bindings[0] for binding in bindings[1:]):
        raise ValueError("captured camera identity changed")
    previous_seq, previous_stamp = -1, -math.inf
    for seq, stamp, path, digest, data in sorted(sources, key=lambda item: item[0]):
        if seq <= previous_seq or stamp <= previous_stamp:
            raise ValueError("captured camera source sequence or stamp did not advance")
        previous_seq, previous_stamp = seq, stamp
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        current_size = (img.shape[1], img.shape[0])
        if size is not None and current_size != size:
            raise ValueError("camera frame size changed within calibration set")
        size = current_size
        found = cb.find_charuco(img, board, min_corners=12)
        if found is None:
            continue
        obj, pix = found
        xy = pix.reshape(-1, 2)
        observations.append({"file": path.name, "sha256": digest, "corners": len(obj),
                             "center_px": np.mean(xy, axis=0).round(2).tolist(),
                             "span_px": np.ptp(xy, axis=0).round(2).tolist(),
                             "scale_px_per_m": board_scale(obj, pix),
                             "source_seq": seq, "source_stamp": stamp})
        objects.append(obj)
        pixels.append(pix)
    return observations, objects, pixels, size, len(seen_hashes), bindings[0] if bindings and isinstance(bindings[0], dict) else None


def _fit(result: dict, checks: dict, objects: list, pixels: list, size: tuple) -> dict:
    import cv2

    try:
        fitted = cb.calibrate_intrinsics(pixels, objects, size)
        # A well-posed set gives the same focal length without tangential terms; a degenerate one swings (2026-11-13:
        # 60 top views at one spot and tilt fit rms 0.28 px with f 2229 vs 1229 px; the side sets moved under 1 %).
        no_tangent = cb.calibrate_intrinsics(pixels, objects, size, cv2.CALIB_ZERO_TANGENT_DIST)
        normals = [cb.board_pose(pix, obj, fitted["K"], fitted["dist"])[0][:, 2]
                   for obj, pix in zip(objects, pixels)]
    except (cv2.error, TypeError, ValueError, IndexError):
        checks["reasons"].append("camera_fit_failed")
        return result
    fx = float(fitted["K"][0][0])
    focal_change = abs(float(no_tangent["K"][0][0]) / fx - 1) if fx > 0 else math.inf
    checks["focal_change"] = round(focal_change, 4) if math.isfinite(focal_change) else None
    if not math.isfinite(focal_change) or focal_change > 0.03:
        checks["reasons"].append("focal_length_unstable")
    tilts = [math.degrees(math.acos(np.clip(abs(float(normal[2])), 0, 1))) for normal in normals]
    tilt_spread = max(math.degrees(math.acos(np.clip(abs(float(a @ b)), 0, 1)))
                      for a in normals for b in normals)
    checks.update({"rms_px": round(float(fitted["rms_px"]), 4),
                   "max_tilt_deg": round(max(tilts), 2), "tilt_spread_deg": round(tilt_spread, 2)})
    if not np.isfinite(fitted["K"]).all() or not np.isfinite(fitted["dist"]).all() or not math.isfinite(fitted["rms_px"]):
        checks["reasons"].append("nonfinite_camera_fit")
    if fitted["rms_px"] > 0.5:
        checks["reasons"].append("rms_above_0_5_px")
    if max(tilts) < 20 or tilt_spread < 15:
        checks["reasons"].append("board_tilt_diversity_missing")
    if not checks["reasons"]:
        result.update({"accepted": True, "K": fitted["K"].tolist(),
                       "dist": fitted["dist"].ravel().tolist(), "rms_px": checks["rms_px"]})
    return result


def _same_look(a: tuple, b: tuple) -> bool:
    """Two views a fit cannot tell apart: centre within 15 px, distance scale within 5 %, tilt within 0.3 /m
    (about 7 deg at 0.4 m; mirrored tilts differ). A view whose homography failed is never called a repeat."""
    if a[2] is None or b[2] is None:
        return False
    return (abs(a[0] - b[0]) < 15 and abs(a[1] - b[1]) < 15
            and abs(a[2] - b[2]) <= 0.05 * max(a[2], b[2]) and float(np.linalg.norm(a[3] - b[3])) < 0.3)


POSE_LOO_SLACK_MM = 2.0  # mark noise (3-5 mm on real marks) hides the upright pose's extrapolation gain in-patch


def _rays(pixels, K, dist) -> np.ndarray:
    import cv2

    ray = cv2.undistortPoints(np.asarray(pixels, np.float64).reshape(-1, 1, 2), np.asarray(K, float),
                              np.asarray(dist, float)).reshape(-1, 2)
    return np.column_stack([ray, np.ones(len(ray))])


def _upright(points, rays, up, height=None) -> tuple:
    """Camera pose in the base (object pose in the camera) with the base z axis fixed to `up` (the table normal in
    the camera, pointing at the camera, from depth): only the yaw and the translation are fitted. For a yaw the
    translation is linear in the rays; the yaw is scanned, then refined, on the ray-angle residual. (A joint linear
    solve collapses to zero when every point has the same z, as remap marks do.) With ``height`` (the camera's
    distance to the marks' plane along the normal, from depth) only the yaw and the camera's x, y are fitted:
    a patch of marks a few cm wide cannot tell height from scale (2026-11-15: 0.636 m fitted, 0.46 m true)."""
    up = np.asarray(up, float) / np.linalg.norm(up)
    a = np.cross(up, [1.0, 0, 0] if abs(up[0]) < 0.9 else [0, 1.0, 0])
    a /= np.linalg.norm(a)
    R0 = np.column_stack([a, np.cross(up, a), up])  # base x, y, z in the camera, before the yaw
    P = np.asarray(points, float)
    D = np.asarray(rays, float) / np.linalg.norm(rays, axis=1, keepdims=True)
    Qs = [np.array([[0, -d[2], d[1]], [d[2], 0, -d[0]], [-d[1], d[0], 0]]) for d in D]

    def at(theta):
        c, s = np.cos(theta), np.sin(theta)
        R = R0 @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        if height is None:
            t, *_ = np.linalg.lstsq(np.vstack(Qs), np.concatenate([-Q @ (R @ p) for Q, p in zip(Qs, P)]), rcond=None)
        else:  # camera centre C = (cx, cy, marks z + height); X = R (P - C), linear in cx, cy
            cz = float(P[:, 2].mean()) + float(height)
            A = np.vstack([Q @ R[:, :2] for Q in Qs])
            b = np.concatenate([Q @ (R @ p) - Q @ R[:, 2] * cz for Q, p in zip(Qs, P)])
            (cx, cy), *_ = np.linalg.lstsq(A, b, rcond=None)
            t = -R @ np.array([cx, cy, cz])
        X = P @ R.T + t
        if np.any(X[:, 2] <= 0):
            return np.inf, R, t
        return float(np.sum(np.cross(D, X / np.linalg.norm(X, axis=1, keepdims=True)) ** 2)), R, t

    best = min(np.radians(np.arange(0, 360, 1.0)), key=lambda th: at(th)[0])
    for step in np.radians([0.5, 0.1, 0.02, 0.004]):
        best = min((best - step, best, best + step), key=lambda th: at(th)[0])
    cost, R, t = at(best)
    if not np.isfinite(cost):
        raise ValueError("no yaw puts the marks in front of the camera with this table normal")
    return R, t


def plane_pose_map(marks, z: float, K, dist, up=None, height=None) -> dict:
    """The jaw marks of a remap ((pixel, (x, y)) at height z) as a camera pose with known intrinsics (the D435's
    factory K), and the pixel -> arm map on the plane z that pose implies. An affine map fitted on a patch near
    the base extrapolates its error across the pallet; a pose has the perspective right everywhere. With `up`
    (the table normal in the camera, from depth) only the yaw and the position are fitted. Leave-one-out in mm."""
    import cell_frame

    if np.any(np.asarray(dist, float)):
        raise ValueError("plane_pose_map: a distortion-free K only (the homography below has no distortion)")
    pts = [(x, y, z) for _, (x, y) in marks]
    pix = [p for p, _ in marks]

    def fit(i=None):
        keep = [k for k in range(len(pts)) if k != i]
        P, D = [pts[k] for k in keep], [pix[k] for k in keep]
        if up is not None:
            return _upright(P, _rays(D, K, dist), up, height)
        pose, _ = cell_frame.solve(P, D, np.asarray(K, float), np.asarray(dist, float))
        if pose is None:
            raise ValueError("solvePnP found no camera pose from the marks")
        return pose

    R, t = fit()
    H = np.linalg.inv(np.asarray(K, float) @ np.column_stack([R[:, 0], R[:, 1], R[:, 2] * z + t]))
    H = H / H[2, 2]
    back = [cell_frame.project(p, K, dist, cell_frame.inverse((R, t))) for p in pts]
    errors = []
    for i, (x, y, _) in enumerate(pts):
        Ri, ti = fit(i)
        hit = cb.pixel_to_plane(pix[i], np.asarray(K, float), np.asarray(dist, float), cell_frame.inverse((Ri, ti)), z)
        errors.append(1000 * float(np.hypot(hit[0] - x, hit[1] - y)))
    rms = float(np.sqrt(np.mean([(b[0] - p[0]) ** 2 + (b[1] - p[1]) ** 2 for b, p in zip(back, pix)])))
    cb_pose = cell_frame.inverse((R, t))
    return {"homography": H, "camera_in_base": {"R": cb_pose[0].tolist(), "t": cb_pose[1].tolist()},
            "rms_px": round(rms, 2), "upright": up is not None,
            "loo_error_mm": {"max": round(max(errors), 2), "mean": round(sum(errors) / len(errors), 2)}}


def fitted_map(config: dict, marks: list, z_view: float) -> dict:
    """The affine map, or the camera pose upright on the depth-measured table normal (config calibrate.intrinsics,
    a cell_device_intrinsics record, and calibrate.up from cell_depth_pose) when its leave-one-out is within
    POSE_LOO_SLACK_MM of the affine one."""
    import cell_calibration as cal

    affine = {"homography": cal.fit(marks).round(9).tolist(), "loo_error_mm": cal.loo_error_mm(marks)}
    c = config.get("calibrate", {})
    if not c.get("intrinsics") or c.get("up") is None or len(marks) < 4:
        return affine
    lens = json.loads(Path(c["intrinsics"]).expanduser().read_text())
    try:
        pose = plane_pose_map(marks, z_view, lens["K"], lens.get("dist", [0.0] * 5), c["up"])
    except ValueError as exc:
        return dict(affine, pose_refused=str(exc)[:120])
    if pose["loo_error_mm"]["max"] > affine["loo_error_mm"]["max"] + POSE_LOO_SLACK_MM:
        return dict(affine, pose_fit={k: v for k, v in pose.items() if k != "homography"})
    return dict(pose, homography=pose["homography"].round(9).tolist(), affine_fit=affine)
