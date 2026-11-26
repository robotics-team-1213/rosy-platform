"""Read-only comparison of the shared pallet work surface in two arm-specific camera frames."""
import json
import os
from pathlib import Path

import cv2
import numpy as np

import cell_params as prm
from cell_auto_evidence import bound_map_error


def _read_binding(config, calibration=None):
    if calibration is None:
        calibration = json.loads(Path(config["calibration_path"]).expanduser().read_bytes())
    raw = Path(config["preflight"]["reference_top"]).expanduser().read_bytes()
    if bound_map_error(calibration, config, raw):
        raise ValueError("unbound_reference")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("invalid_reference")
    return img


def _quad(config):
    q = np.asarray(config["sites"]["pallet"]["surface_px"], np.float32)
    if q.shape != (4, 2) or not np.isfinite(q).all() or not cv2.isContourConvex(q):
        raise ValueError("invalid_pallet_work_surface")
    return q


def _background_features(image, quad):
    mask = np.full(image.shape, 255, dtype=np.uint8)
    cv2.fillConvexPoly(mask, np.int32(np.rint(quad)), 0)
    mask = cv2.erode(mask, np.ones((21, 21), np.uint8))
    return cv2.ORB_create(4000, edgeThreshold=21, fastThreshold=15).detectAndCompute(image, mask)


def compare_surfaces(peer_img, image, peer_quad, quad, tolerance):
    """Register fixed background features. Compare corresponding cyclic vertices in either winding."""
    if peer_img.shape != image.shape or peer_img.ndim != 2:
        return {"status": "unverified", "reason": "different_image_shapes"}
    keys0, desc0 = _background_features(peer_img, peer_quad)
    keys1, desc1 = _background_features(image, quad)
    if desc0 is None or desc1 is None:
        return {"status": "unverified", "reason": "no_background_features"}
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(desc0, desc1)
    if len(matches) < 30:
        return {"status": "unverified", "reason": "too_few_background_features"}
    src = np.float32([keys0[m.queryIdx].pt for m in matches])
    dst = np.float32([keys1[m.trainIdx].pt for m in matches])
    h, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if h is None or mask is None or int(mask.sum()) < 30 or not np.isfinite(h).all() or np.linalg.matrix_rank(h) < 3:
        return {"status": "unverified", "reason": "unstable_background_registration"}
    keep = mask.ravel().astype(bool)
    if keep.mean() < .30:
        return {"status": "unverified", "reason": "ambiguous_background_registration"}
    fitted = cv2.perspectiveTransform(src[keep][None], h)[0]
    residual = np.linalg.norm(fitted - dst[keep], axis=1)
    for points, corners in ((src[keep], peer_quad), (dst[keep], quad)):
        outline = cv2.convexHull(points)
        if any(cv2.pointPolygonTest(outline, tuple(map(float, point)), False) < 0 for point in corners):
            return {"status": "unverified", "reason": "work_surface_outside_registration_support"}
    mapped = cv2.perspectiveTransform(peer_quad[None], h)[0]
    matches = [np.roll(order, n, axis=0) for order in (mapped, mapped[::-1]) for n in range(4)]
    best = min(matches, key=lambda candidate: float(np.max(np.linalg.norm(candidate - quad, axis=1))))
    errors = np.linalg.norm(best - quad, axis=1)
    registration_p95 = float(np.quantile(residual, .95))
    worst = float(max(errors))
    if worst - registration_p95 > tolerance:
        status = "mismatch"
    elif worst + registration_p95 > tolerance:
        status = "near_tolerance"
    else:
        status = "consistent"
    return {"status": status, "site": "pallet",
            "geometry_role": "configured_work_surface", "peer_surface_in_frame_px": best.astype(float).round(2).tolist(),
            "configured_surface_px": quad.tolist(), "corner_error_px": errors.astype(float).round(2).tolist(),
            "tolerance_px": tolerance, "registration_inliers": int(keep.sum()),
            "registration_median_residual_px": round(float(np.median(residual)), 2),
            "registration_p95_residual_px": round(registration_p95, 2)}


def shared_pallet(config, calibration, *, candidate_frame=None, peer_path=None):
    arm, peer = config.get("arm_id"), config.get("zone_peer")
    if (arm, peer) not in (("arm_a", "arm_b"), ("arm_b", "arm_a")):
        return {"status": "not_applicable"}
    try:
        if peer_path is None:
            registry = Path(os.environ.get("ROSY_CALIBRATION_REGISTRY", "~/.config/rosy/calibration/cells.json")).expanduser()
            peer_path = json.loads(registry.read_bytes())["arms"][peer]["config"]
        other = json.loads(Path(peer_path).expanduser().read_bytes())
        camera = (config.get("cameras") or {}).get("top", {}).get("url")
        if other.get("arm_id") != peer or other.get("zone_peer") != arm or not camera or camera != other["cameras"]["top"]["url"]:
            return {"status": "not_applicable"}
        if not all("pallet" in c.get("sites", {}) for c in (config, other)):
            return {"status": "not_applicable"}
        peer_img = _read_binding(other)
        image = _read_binding(config, calibration) if candidate_frame is None else cv2.cvtColor(candidate_frame, cv2.COLOR_BGR2GRAY)
        report = compare_surfaces(peer_img, image, _quad(other), _quad(config),
                                  prm.get(config.get("params"), "calibrate.consensus_px"))
        return {**report, "arm": arm, "peer": peer}
    except (KeyError, TypeError, OSError, ValueError, cv2.error, np.linalg.LinAlgError) as exc:
        return {"status": "unverified", "arm": arm, "peer": peer, "reason": type(exc).__name__ + ": " + str(exc)}

def fixture_check_frame(cell, config, calibration, step, config_path):
    """The regular check and the fixture report use one timestamped camera sample."""
    if config.get("arm_id") not in ("arm_a", "arm_b"):
        return cell.frame("top"), {}
    report = {"shared_pallet_surface": shared_pallet(config, calibration)}
    if step != "check":
        return cell.frame("top"), report
    from cell_calibration_view_frame import bind_frame

    receipt = None
    reason = "source_stamp_missing"
    if hasattr(cell, "frame_receipt"):
        try:
            receipt = cell.frame_receipt("top", max_age_s=2.0)
        except (OSError, TimeoutError, ValueError) as exc:
            reason = str(exc)
    if receipt is None:
        report["fixture_observation"] = {"status": "unverified", "reason": reason}
        return cell.frame("top"), report
    _, binding = bind_frame({"config_path": str(config_path)}, "live", receipt["jpeg_bytes"], include_fixtures=True)
    report["fixture_observation"] = {**binding.get("fixture_observation", {"status": "unverified"}),
                                     "source_stamp": receipt["source_stamp"], "source_seq": receipt["source_seq"]}
    return receipt["image"], report
