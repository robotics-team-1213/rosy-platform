"""Side-view Z references: the arm's CAD landmarks, the visual datum line, and the two fixed side markers.

Split out of `cell_z_profile` (400-line cap); that module re-exports these names.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = (HERE.parents[2] if len(HERE.parents) > 2 else HERE) / "middleware/devices/omx/adapter"
for _p in (HERE, ADAPTER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omx_adapter.z_profile import SideViewZProfile, fk_landmarks_mm, reconcile_tcp_z_mm  # noqa: E402
import cell_frame  # noqa: E402

SIDE_COL_U_BOUNDS: dict[int, tuple[int, int]] = {1: (173, 238), 2: (239, 305), 3: (306, 377)}


def detect_side_self_profile_landmarks(side_img: np.ndarray | None, *, datum_z_offset_mm: float = 0.0) -> list[tuple[float, float]]:
    """Auto-detect `arm_b`'s physical CAD landmarks and the visual floor datum (`datum_z_offset_mm`) in a Side-view frame."""
    if side_img is None or not hasattr(side_img, "shape") or len(side_img.shape) != 3 or side_img.shape[1] < 580 or side_img.shape[0] < 400:
        return []
    import cv2
    ys, _ = np.where(cv2.cvtColor(side_img[200:395, 500:570], cv2.COLOR_BGR2GRAY) < 60)
    if len(ys) < 400 or not (345.0 <= (v_datum := float(200.0 + np.percentile(ys, 98))) <= 390.0):
        return []
    mm_per_px, v_base_bottom = 90.0 / 175.0, v_datum + float(datum_z_offset_mm) / (90.0 / 175.0)
    return [(round(v_base_bottom, 1), 0.0), (round(v_datum, 1), round(float(datum_z_offset_mm), 2)), (round(v_base_bottom - 13.0 / mm_per_px, 1), 13.0), (round(v_base_bottom - 97.5 / mm_per_px, 1), 97.5)]


def fit_visual_datum_line(side_img: np.ndarray | None, *, datum_z_offset_mm: float | None = None, tactile_z_trim_mm: float = 0.0) -> dict[str, Any]:
    """Structured 4-layer calibration (`optics` -> `self_profile` -> `visual_datum` -> `closed_loop_residual`)."""
    prof, col_bottoms, v_robot_base_px = SideViewZProfile(datum_z_offset_mm=0.0, k1=-0.055, k2=0.010), {}, None
    if side_img is not None and hasattr(side_img, "shape") and len(side_img.shape) == 3 and side_img.shape[1] >= 580:
        import cv2
        ys_b, _ = np.where(cv2.cvtColor(side_img[200:395, 500:570], cv2.COLOR_BGR2GRAY) < 60)
        if len(ys_b) >= 400:
            v_robot_base_px = round(prof.undistort_uv(535.0, 200.0 + float(np.percentile(ys_b, 98)))[1], 1)
        hsv = cv2.cvtColor(side_img[180:388, 173:377], cv2.COLOR_BGR2HSV)
        sat_c = (hsv[..., 0] >= 4) & (hsv[..., 0] <= 36) & (hsv[..., 1] >= 110) & (hsv[..., 2] >= 140)
        for c_idx, (u0, u1) in SIDE_COL_U_BOUNDS.items():
            rows = np.where(sat_c[:, u0 - 173:u1 - 173].sum(axis=1) >= 24)[0]
            if len(rows) >= 12:
                col_bottoms[c_idx] = round(prof.undistort_uv(0.5 * (u0 + u1), 180.0 + float(rows[-1]))[1], 1)
    slope = max(-0.04, min(0.04, round((col_bottoms[2] - col_bottoms[1]) / 66.5, 5))) if (1 in col_bottoms and 2 in col_bottoms) else 0.0
    v_pallet_ref = col_bottoms.get(2, col_bottoms.get(1))
    visual_datum_z_mm = round(max(-4.0, min(6.0, ((v_robot_base_px + slope * (272.0 - 535.0)) - v_pallet_ref) * (90.0 / 175.0))), 2) if (v_robot_base_px is not None and v_pallet_ref is not None) else 0.0
    eff_datum_mm = round(float(datum_z_offset_mm) if datum_z_offset_mm is not None else (visual_datum_z_mm + float(tactile_z_trim_mm)), 2)
    return {"datum_z_offset_mm": eff_datum_mm, "visual_datum_z_mm": visual_datum_z_mm, "tactile_z_trim_mm": round(float(tactile_z_trim_mm), 2), "v_robot_base_px": v_robot_base_px, "k1": -0.055, "k2": 0.010, "col_bottom_v_px": col_bottoms, "datum_slope_v_per_u": slope}


def _side_reference_markers(side_img: np.ndarray) -> dict[int, np.ndarray]:
    """Return independent DICT_4X4_50 marker corners in OpenCV order."""
    import cv2

    grey = cv2.cvtColor(side_img, cv2.COLOR_BGR2GRAY)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if hasattr(cv2.aruco, "ArucoDetector"):
        corners, ids, _ = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters()).detectMarkers(grey)
    else:
        corners, ids, _ = cv2.aruco.detectMarkers(grey, dictionary)
    return {} if ids is None else {int(marker_id): pixels.reshape(4, 2) for pixels, marker_id in zip(corners, ids.flatten())}


def _fixed_side_reference_diagnostic(side_img: np.ndarray | None, z_profile: dict[str, Any] | None) -> dict[str, Any]:
    """Measure two fixed markers and camera pose; keep height acceptance closed until stack-plane gauge verification."""
    out = {"ok": False, "fiducials_detected": [], "stack_plane_projection_verified": False,
           "three_height_gauge_verified": False, "device_identity_verified": False,
           "reason": "fixed side reference unavailable"}
    ref = (z_profile or {}).get("side_reference") or {}
    if side_img is None or not isinstance(ref, dict) or not ref:
        return out
    try:
        K, dist, size = cell_frame.validated_intrinsics(ref["intrinsics"], camera="side")
        if list(size) != [side_img.shape[1], side_img.shape[0]]:
            return {**out, "reason": "side camera resolution differs from intrinsics"}
        markers = ref["markers"]
        if not isinstance(markers, list) or len(markers) != 2:
            return {**out, "reason": "two measured side markers required"}
        ids = [marker["id"] for marker in markers]
        if (any(type(marker_id) is not int or not 0 <= marker_id < 50 for marker_id in ids)
                or ids[0] == ids[1]):
            return {**out, "reason": "two distinct side marker IDs required"}
        world = [np.asarray(marker["corners_world_mm"], dtype=float) for marker in markers]
        if any(points.shape != (4, 3) or not np.isfinite(points).all() for points in world):
            return {**out, "reason": "measured side marker corners invalid"}
        pixels = _side_reference_markers(side_img)
        seen = [marker_id for marker_id in ids if marker_id in pixels]
        if len(seen) != 2:
            return {**out, "fiducials_detected": seen, "reason": "fixed side marker missing in current frame"}
        pose, rms = cell_frame.solve(np.concatenate(world), np.concatenate([pixels[marker_id] for marker_id in ids]), K, dist)
        if pose is None or rms is None or not math.isfinite(rms) or rms > 1.0:
            return {**out, "fiducials_detected": seen, "reason": "fixed side marker reprojection failed"}
        installed = ref["installed_pose"]
        R0, t0 = np.asarray(installed["R"], dtype=float), np.asarray(installed["t_mm"], dtype=float)
        if R0.shape != (3, 3) or t0.shape != (3,) or not np.isfinite(R0).all() or not np.isfinite(t0).all():
            return {**out, "fiducials_detected": seen, "reason": "installed side camera pose invalid"}
        delta_mm = float(np.linalg.norm(pose[1] - t0))
        delta_deg = math.degrees(math.acos(float(np.clip((np.trace(pose[0] @ R0.T) - 1) / 2, -1, 1))))
        return {**out, "fiducials_detected": seen, "reprojection_rms_px": round(float(rms), 3),
                "pose_delta_mm": round(delta_mm, 3), "pose_delta_deg": round(delta_deg, 3),
                "reason": "stack-plane projection, three-height gauge and device identity not verified"}
    except Exception:
        return {**out, "reason": "fixed side reference data invalid"}


def measure_side_gripper_pose_mm(
    side_img: np.ndarray | None, before_side: np.ndarray | None, col: int, *, target_u_px: float = 254.0, u_m_per_px: float = 0.00070,
    expected_z_mm: float | None = None, joint_state_deg: Sequence[float] | None = None, z_profile: dict[str, Any] | None = None, tol_u_px: float = 12.0, tol_z_mm: float = 14.0,
) -> dict[str, Any]:
    """(B) Measure both horizontal (`u_px -> dx_mm`) and vertical (`v_px -> gripper_z_mm, dz_mm`) gripper pose in Side View."""
    if side_img is None or before_side is None or not hasattr(side_img, "shape") or side_img.shape != before_side.shape:
        return {"found": False, "target_u_px": target_u_px}
    diff = side_img[70:165, 160:390].astype(np.int32) - before_side[70:165, 160:390].astype(np.int32)
    ys, xs = np.where((diff[..., 0] * diff[..., 0] + diff[..., 1] * diff[..., 1] + diff[..., 2] * diff[..., 2]) > 1024)
    if len(xs) < 40:
        return {"found": False, "target_u_px": target_u_px}
    p65, p90 = np.percentile(ys, (65, 90))
    side_prof, tip_mask = SideViewZProfile.from_dict((z_profile or {}).get("side_view")), (ys >= p65)
    u_gripper = round(float(160.0 + np.median(xs[tip_mask] if int(tip_mask.sum()) >= 10 else xs)), 1)
    v_gripper_tip, v_gripper_center = round(float(70.0 + p90), 1), round(float(70.0 + np.median(ys)), 1)
    du_px, dx_m, gripper_z_mm = round(target_u_px - u_gripper, 1), round((target_u_px - u_gripper) * float(u_m_per_px), 5), side_prof.v_to_z_mm(v_gripper_tip)
    fk_z_mm = float(fk_landmarks_mm(joint_state_deg[:5], unit="deg")["landmarks_z_mm"]["jaw_tip"]) if (joint_state_deg is not None and len(joint_state_deg) >= 5) else None
    ref_z_mm = float(expected_z_mm) if expected_z_mm is not None else fk_z_mm
    dz_mm = round(ref_z_mm - gripper_z_mm, 2) if ref_z_mm is not None else 0.0
    return {"found": True, "gripper_u_px": u_gripper, "gripper_v_tip_px": v_gripper_tip, "gripper_v_center_px": v_gripper_center,
            "target_u_px": target_u_px, "du_px": du_px, "dx_m": dx_m, "dx_mm": round(dx_m * 1000.0, 2), "gripper_z_mm": gripper_z_mm,
            "expected_z_mm": round(ref_z_mm, 2) if ref_z_mm is not None else None, "fk_jaw_tip_z_mm": round(fk_z_mm, 2) if fk_z_mm is not None else None,
            "dz_mm": dz_mm, "dz_m": round(dz_mm / 1000.0, 5), "within_zone": bool(abs(du_px) <= tol_u_px),
            "within_z_zone": True if ref_z_mm is None else (abs(dz_mm) <= tol_z_mm), "reconciled_tcp_mm": reconcile_tcp_z_mm(gripper_z_mm)}
