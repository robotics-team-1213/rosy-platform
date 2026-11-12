#!/usr/bin/env python3
"""OMX-AI Self-Profile-Anchored Z-Axis (`mm`) Calibration (A), 3D ContainerSpec ROI Projection, and Live Perception (B)."""
from __future__ import annotations

import math, subprocess, sys, tempfile, time
from pathlib import Path
from typing import Any, Sequence
import numpy as np

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = (HERE.parents[2] if len(HERE.parents) > 2 else HERE) / "middleware/devices/omx/adapter"
for _p in (HERE, ADAPTER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omx_adapter.z_profile import (  # noqa: E402
    CONTAINER_SPECS_MM, OMX_AI_PROFILE_MM, TIER_GRASP_Z_MM, TIER_MID_Z_MM, TIER_SURFACE_Z_MM, TIER_TOP_Z_MM,
    Z_PROFILE_SCHEMA, SideViewZProfile, TopDepthZProfile, evaluate_signed_tier_residual_mm, fk_landmarks_mm,
    reconcile_tcp_z_mm, reconcile_top_and_side_z_mm, resolve_container_spec,
)
import cell_arm_cal  # noqa: E402
import cell_depth  # noqa: E402

SIDE_COL_U_BOUNDS: dict[int, tuple[int, int]] = {1: (173, 238), 2: (239, 305), 3: (306, 377)}
TOP_SLOT_CENTER_PX: dict[tuple[int, int], tuple[float, float]] = {
    (1, 1): (341.5, 217.5), (2, 1): (395.0, 217.5), (3, 1): (452.5, 217.5),
    (1, 2): (341.5, 325.5), (2, 2): (395.0, 325.5), (3, 2): (452.5, 325.5),
}
_DEPTH_ALIGN_CACHE: dict[tuple[int, int], tuple[np.ndarray, np.ndarray, float]] = {}


def detect_side_self_profile_landmarks(side_img: np.ndarray | None, *, datum_z_offset_mm: float = 0.0) -> list[tuple[float, float]]:
    """Auto-detect `arm_b`'s physical CAD landmarks and the visual floor datum (`datum_z_offset_mm`) in a Side-view frame."""
    if side_img is None or not hasattr(side_img, "shape") or len(side_img.shape) != 3 or side_img.shape[1] < 580 or side_img.shape[0] < 400:
        return []
    import cv2
    ys, _ = np.where(cv2.cvtColor(side_img, cv2.COLOR_BGR2GRAY)[200:395, 500:570] < 60)
    if len(ys) < 400 or not (345.0 <= (v_datum := float(200.0 + np.percentile(ys, 98))) <= 390.0):
        return []
    mm_per_px, v_base_bottom = 90.0 / 175.0, v_datum + float(datum_z_offset_mm) / (90.0 / 175.0)
    return [(round(v_base_bottom, 1), 0.0), (round(v_datum, 1), round(float(datum_z_offset_mm), 2)),
            (round(v_base_bottom - 13.0 / mm_per_px, 1), 13.0), (round(v_base_bottom - 97.5 / mm_per_px, 1), 97.5)]


def fit_visual_datum_line(side_img: np.ndarray | None, *, datum_z_offset_mm: float | None = None, tactile_z_trim_mm: float = 0.0) -> dict[str, Any]:
    """Structured 4-layer calibration (`optics` -> `self_profile` -> `visual_datum` -> `closed_loop_residual`)."""
    prof, col_bottoms, v_robot_base_px = SideViewZProfile(datum_z_offset_mm=0.0, k1=-0.055, k2=0.010), {}, None
    if side_img is not None and hasattr(side_img, "shape") and len(side_img.shape) == 3 and side_img.shape[1] >= 580:
        import cv2
        ys_b, _ = np.where(cv2.cvtColor(side_img, cv2.COLOR_BGR2GRAY)[200:395, 500:570] < 60)
        if len(ys_b) >= 400:
            v_robot_base_px = round(prof.undistort_uv(535.0, 200.0 + float(np.percentile(ys_b, 98)))[1], 1)
        hsv = cv2.cvtColor(side_img, cv2.COLOR_BGR2HSV)
        sat_c = (hsv[..., 0] >= 4) & (hsv[..., 0] <= 36) & (hsv[..., 1] >= 110) & (hsv[..., 2] >= 140)
        for c_idx, (u0, u1) in SIDE_COL_U_BOUNDS.items():
            rows = np.where(sat_c[180:388, u0:u1].sum(axis=1) >= 24)[0]
            if len(rows) >= 12:
                col_bottoms[c_idx] = round(prof.undistort_uv(0.5 * (u0 + u1), 180.0 + float(rows[-1]))[1], 1)
    slope = max(-0.04, min(0.04, round((col_bottoms[2] - col_bottoms[1]) / 66.5, 5))) if (1 in col_bottoms and 2 in col_bottoms) else 0.0
    v_pallet_ref = col_bottoms.get(2, col_bottoms.get(1))
    visual_datum_z_mm = round(max(-4.0, min(6.0, ((v_robot_base_px + slope * (272.0 - 535.0)) - v_pallet_ref) * (90.0 / 175.0))), 2) if (v_robot_base_px is not None and v_pallet_ref is not None) else 0.0
    eff_datum_mm = round(float(datum_z_offset_mm) if datum_z_offset_mm is not None else (visual_datum_z_mm + float(tactile_z_trim_mm)), 2)
    return {"datum_z_offset_mm": eff_datum_mm, "visual_datum_z_mm": visual_datum_z_mm, "tactile_z_trim_mm": round(float(tactile_z_trim_mm), 2),
            "v_robot_base_px": v_robot_base_px, "k1": -0.055, "k2": 0.010, "col_bottom_v_px": col_bottoms, "datum_slope_v_per_u": slope}


def default_z_profile_mm(arm_id: str = "arm_b") -> dict[str, Any]:
    """Return the canonical OMX-AI self-profile-anchored Z-mm calibration dictionary for an arm."""
    return {"schema": Z_PROFILE_SCHEMA, "arm_id": arm_id, "cad_profile_mm": dict(OMX_AI_PROFILE_MM),
            "side_view": SideViewZProfile().to_dict(), "top_depth": TopDepthZProfile().to_dict(),
            "tier_grasp_z_mm": dict(TIER_GRASP_Z_MM), "tier_surface_z_mm": dict(TIER_SURFACE_Z_MM), "tier_top_z_mm": dict(TIER_TOP_Z_MM),
            "joint_zero_offset_deg": list(OMX_AI_PROFILE_MM["default_joint_zero_offset_deg"]), "table_fk_offset_mm": float(OMX_AI_PROFILE_MM["default_table_fk_offset_mm"])}


def _aligned_depth_heights(top_depth: np.ndarray, top_colour: np.ndarray | None = None, z_profile: dict[str, Any] | None = None) -> tuple[np.ndarray, np.ndarray, float]:
    key = (id(top_depth), int(top_depth.sum()))
    if key in _DEPTH_ALIGN_CACHE:
        return _DEPTH_ALIGN_CACHE[key]
    heights, td_cfg = cell_depth.height_map(top_depth, cell_depth.table_plane(top_depth)), (z_profile or {}).get("top_depth") or {}
    if td_cfg.get("to_depth_matrix"):
        to_depth, edge_px = np.array(td_cfg["to_depth_matrix"], dtype=np.float32), float(td_cfg.get("align_edge_px", 0.0))
    elif top_colour is not None and hasattr(top_colour, "shape"):
        to_depth, edge_px = cell_depth.align_edges(top_colour, heights)
    else:
        to_depth, edge_px = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32), 0.0
    if len(_DEPTH_ALIGN_CACHE) >= 8:
        _DEPTH_ALIGN_CACHE.clear()
    _DEPTH_ALIGN_CACHE[key] = (heights, to_depth, float(edge_px))
    return _DEPTH_ALIGN_CACHE[key]


def capture_top_depth_z16(dev_path: str = "/dev/v4l/by-id/rosy-realsense-d435-depth", out_raw: Path | None = None, *, timeout_s: float = 1.8) -> np.ndarray | None:
    """Capture a warmed 640x480 Z16 depth frame (`mm`) from D435 at 6 fps, or load the latest warmed cell Z16 frame."""
    raw_path, dev = (Path(out_raw) if out_raw is not None else Path(tempfile.gettempdir()) / "rosy-top-depth-z16.raw"), (dev_path if Path(dev_path).exists() else "/dev/video6")
    if Path(dev).exists():
        try:
            subprocess.run(["v4l2-ctl", "-d", dev, "--set-fmt-video=width=640,height=480,pixelformat=Z16 ", "--set-parm=6", "--stream-mmap=3", "--stream-skip=12", "--stream-count=1", f"--stream-to={raw_path}"], timeout=float(timeout_s), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    for cand in (raw_path, Path("/home/robttt/rosy-test/runs/decision-vla-depth-1793890232940317053/depth.raw")):
        if cand.exists() and cand.stat().st_size == 640 * 480 * 2 and float(((arr := np.fromfile(cand, dtype=np.uint16)) > 0).mean()) >= 0.40:
            return arr.reshape(480, 640)
    return None


def project_container_spec_roi(col: int, tier: int = 1, spec_id: str = "C3", x_offset_mm: float = 0.0, row: int = 1, *, z_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Project 3D `ContainerSpec` (`C1`/`C2`/`C3`) into Side and Top camera 2D ROIs scaled by `length_mm / 90.0` and 3D frustum factor."""
    spec, side_prof = resolve_container_spec(spec_id), SideViewZProfile.from_dict((z_profile or {}).get("side_view"))
    length_scale = round(float(spec["length_mm"]) / 90.0, 4)
    frustum_scale = round(575.1 / max(300.0, 575.1 - float(TIER_TOP_Z_MM.get(int(tier), 30.0))), 4)
    u0_b, u1_b = SIDE_COL_U_BOUNDS.get(int(col), (239, 305))
    u_center, u_half, band = 0.5 * (u0_b + u1_b) + float(x_offset_mm) / max(0.25, side_prof.u_m_per_px * 1000.0), max(8.0, 0.5 * (u1_b - u0_b) * length_scale), side_prof.tier_band_mm(tier)
    side_roi = (max(0, int(round(u_center - u_half))), max(0, int(round(band["v_top_px"])) - 4), min(640, int(round(u_center + u_half))), min(480, int(round(band["v_bottom_px"])) + 4))
    top_uc, top_vc = TOP_SLOT_CENTER_PX.get((int(col), int(row)), (395.0, 217.5))
    v_center_top, v_half_top, u_half_top = top_vc + float(x_offset_mm) * (105.0 / 90.0) * frustum_scale, max(12.0, 52.5 * length_scale * frustum_scale), 26.0 * frustum_scale
    top_roi = (max(0, int(round(top_uc - u_half_top))), max(0, int(round(v_center_top - v_half_top))), min(640, int(round(top_uc + u_half_top))), min(480, int(round(v_center_top + v_half_top))))
    return {"col": int(col), "row": int(row), "tier": int(tier), "spec_id": spec["spec_id"], "length_mm": float(spec["length_mm"]), "width_mm": float(spec["width_mm"]),
            "height_mm": float(spec["height_mm"]), "length_scale": length_scale, "frustum_scale": frustum_scale, "x_offset_mm": round(float(x_offset_mm), 2),
            "side_roi": side_roi, "top_roi": top_roi, "side_roi_px": side_roi, "top_roi_px": top_roi,
            "side_width_px": side_roi[2] - side_roi[0], "top_length_px": top_roi[3] - top_roi[1], "expected_area_mm2": float(spec["expected_area_mm2"]), "slot_x_candidates_mm": list(spec["slot_x_candidates_mm"])}


def estimate_slot_x_from_spec(
    top_img: np.ndarray | None, depth_raw: np.ndarray | None = None, col: int = 2, row: int = 1, spec_id: str = "C3", *, tier: int = 1, z_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate `slot_x_candidates_mm` (`[0]` for `C3`, `[-15, +15]` for `C2`, `[-30, 0, +30]` for `C1`) and return `(x_hat_mm, sigma_x_mm, needs_reobserve)`."""
    spec = resolve_container_spec(spec_id)
    candidates, scores, has_evidence = [float(c) for c in spec["slot_x_candidates_mm"]], [], False
    for cand_mm in candidates:
        x0, y0, x1, y1 = project_container_spec_roi(col=col, tier=tier, spec_id=spec["spec_id"], x_offset_mm=cand_mm, row=row, z_profile=z_profile)["top_roi"]
        sc = 0.0
        if top_img is not None and hasattr(top_img, "shape") and len(top_img.shape) == 3:
            import cv2
            crop = top_img[max(0, y0):min(top_img.shape[0], y1), max(0, x0):min(top_img.shape[1], x1)]
            if crop.size > 0:
                hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                warm = (((hsv[..., 0] <= 38) | (hsv[..., 0] >= 158)) & (hsv[..., 1] >= 65) & (hsv[..., 2] >= 90)) | ((hsv[..., 0] >= 35) & (hsv[..., 0] <= 85) & (hsv[..., 1] >= 20) & (hsv[..., 2] >= 90))
                sc += float(warm.mean())
                has_evidence = has_evidence or (float(warm.mean()) >= 0.12)
        if depth_raw is not None and hasattr(depth_raw, "ndim") and depth_raw.ndim == 2:
            d_patch = depth_raw[max(0, y0):min(depth_raw.shape[0], y1), max(0, x0):min(depth_raw.shape[1], x1)]
            if d_patch.size > 0:
                d_ratio = float(((d_patch > 0) & (d_patch <= 638)).mean())
                sc += d_ratio
                has_evidence = has_evidence or (d_ratio >= 0.15)
        scores.append(round(sc, 4))
    if len(candidates) == 1:
        x_hat, sigma_x, best_cand = candidates[0], (1.2 if has_evidence else 1.8), candidates[0]
    elif has_evidence and (max(scores) - min(scores)) >= 0.12:
        exps = [math.exp(18.0 * s) for s in scores]
        probs = [e / sum(exps) for e in exps]
        best_cand = candidates[int(np.argmax(scores))]
        x_hat = best_cand
        sigma_x = math.sqrt(sum(p * ((c - best_cand) ** 2) for p, c in zip(probs, candidates)) + 1.1 ** 2)
    else:
        probs = [1.0 / len(candidates)] * len(candidates)
        x_hat = sum(p * c for p, c in zip(probs, candidates))
        sigma_x = math.sqrt(sum(p * ((c - x_hat) ** 2) for p, c in zip(probs, candidates)))
        best_cand = candidates[int(np.argmax(scores))]
    return {"col": int(col), "row": int(row), "spec_id": spec["spec_id"], "candidates_mm": candidates, "candidate_scores": {str(c): s for c, s in zip(candidates, scores)},
            "best_candidate_mm": best_cand, "x_hat_mm": round(float(x_hat), 2), "sigma_x_mm": round(float(sigma_x), 2), "needs_reobserve": bool(2.0 * float(sigma_x) > 5.0)}


def evaluate_slot_spec_gate(
    slot_obs_or_z_top_mm: dict[str, Any] | float, expected_tier: int = 1, *, spec_id: str = "C3",
    valid_depth_ratio: float | None = None, dz_top_side_mm: float | None = None, tilt_deg: float = 0.0, obs_area_mm2: float | None = None,
) -> dict[str, Any]:
    """Wrap `evaluate_signed_tier_residual_mm` for either a `perceive_slot_z_mm` observation dict or a raw `z_top_mm` float."""
    if isinstance(slot_obs_or_z_top_mm, dict):
        d = slot_obs_or_z_top_mm
        tier_k = int(d.get("expected_tier") or d.get("tier") or expected_tier)
        z_top = float(d.get("measured_top_z_mm") or d.get("fused_top_z_mm") or d.get("side_top_z_mm") or d.get("depth_top_z_mm") or 0.0)
        s_t, d_t = d.get("side_top_z_mm"), d.get("depth_top_z_mm")
        dz_ts = float(dz_top_side_mm) if dz_top_side_mm is not None else (float(s_t) - float(d_t) if (s_t is not None and d_t is not None) else float(d.get("side_vs_depth_top_dz_mm") or 0.0))
        v_ratio = float(valid_depth_ratio) if valid_depth_ratio is not None else float(d.get("valid_depth_ratio", 1.0 if d.get("found", True) else 0.0))
        return evaluate_signed_tier_residual_mm(z_top, tier_k, valid_depth_ratio=v_ratio, dz_top_side_mm=dz_ts, tilt_deg=tilt_deg, obs_area_mm2=obs_area_mm2 or d.get("obs_area_mm2"), spec_id=str(d.get("spec_id") or spec_id))
    return evaluate_signed_tier_residual_mm(float(slot_obs_or_z_top_mm), int(expected_tier), valid_depth_ratio=1.0 if valid_depth_ratio is None else float(valid_depth_ratio),
                                             dz_top_side_mm=0.0 if dz_top_side_mm is None else float(dz_top_side_mm), tilt_deg=tilt_deg, obs_area_mm2=obs_area_mm2, spec_id=spec_id)


def calibrate_z_profile_mm(
    config_or_work: dict[str, Any] | Path, arm_id: str = "arm_b", *, top_colour: np.ndarray | None = None, top_depth: np.ndarray | None = None, side_img: np.ndarray | None = None,
    base_px: tuple[float, float] = (120.0, 240.0), landmark_observations: Sequence[tuple[float, float]] | None = None, joint_state_deg: Sequence[float] | None = None, observed_gripper_v_px: float | None = None,
) -> dict[str, Any]:
    """(A) Calibrate and persist the OMX-AI self-profile Z-mm model from Top Depth + Side View + FK landmarks."""
    cal = cell_arm_cal.load(config_or_work, arm_id)
    z_prof = dict(cal.get("z_profile_mm") or default_z_profile_mm(arm_id))
    if top_depth is not None and hasattr(top_depth, "ndim") and top_depth.ndim == 2 and top_depth.size > 0:
        heights, to_depth, edge_px = _aligned_depth_heights(top_depth, top_colour)
        plate_mm = cell_depth.plate_top(heights, to_depth, base_px)
        td_prof = TopDepthZProfile(measured_plate_top_mm=plate_mm if plate_mm is not None else 13.0, cad_plate_top_mm=float(OMX_AI_PROFILE_MM["base_plate_top_z_mm"]))
        slot_heights_mm = {f"c{c_idx}_r{r_idx}": td_prof.raw_height_to_link0_z_mm(raw_h) for (c_idx, r_idx), px in TOP_SLOT_CENTER_PX.items() if np.isfinite(raw_h := cell_depth.height_at(heights, to_depth, px))}
        z_prof["top_depth"] = {**td_prof.to_dict(), "align_edge_px": round(float(edge_px), 2), "to_depth_matrix": to_depth.tolist(), "slot_heights_mm": slot_heights_mm}
    tactile_trim = float(z_prof.get("tactile_z_trim_mm", 0.0))
    datum_info = fit_visual_datum_line(side_img, tactile_z_trim_mm=tactile_trim) if side_img is not None else {"datum_z_offset_mm": tactile_trim, "datum_slope_v_per_u": 0.0, "k1": 0.0, "k2": 0.0}
    z_prof["visual_datum"] = datum_info
    pts = list(landmark_observations or []) or (detect_side_self_profile_landmarks(side_img, datum_z_offset_mm=float(datum_info.get("datum_z_offset_mm", 0.0))) if side_img is not None else [])
    if joint_state_deg is not None and len(joint_state_deg) >= 5:
        fk_info = fk_landmarks_mm(joint_state_deg[:5], unit="deg", tcp_x_mm=float(OMX_AI_PROFILE_MM["tcp_v21_x_mm"]), joint_zero_offset_deg=z_prof.get("joint_zero_offset_deg") or OMX_AI_PROFILE_MM["default_joint_zero_offset_deg"])
        z_prof["last_fk_landmarks_mm"] = fk_info
        if observed_gripper_v_px is not None:
            pts.append((float(observed_gripper_v_px), float(fk_info["landmarks_z_mm"]["jaw_tip"])))
            if len(pts) == 1:
                pts.append((SideViewZProfile.from_dict(z_prof.get("side_view")).z_mm_to_v(13.0), 13.0))
    if len(pts) >= 2:
        z_prof["side_view"] = SideViewZProfile.fit_from_landmarks(pts, datum_z_offset_mm=float(datum_info.get("datum_z_offset_mm", 0.0)), datum_slope_v_per_u=float(datum_info.get("datum_slope_v_per_u", 0.0)), k1=float(datum_info.get("k1", 0.0)), k2=float(datum_info.get("k2", 0.0))).to_dict()
    elif "side_view" not in z_prof:
        z_prof["side_view"] = SideViewZProfile().to_dict()
    if side_img is not None and hasattr(side_img, "shape") and len(side_img.shape) == 3:
        z_prof["side_observed_slots"] = {f"col_{c}": obs for c in (1, 2, 3) if (obs := perceive_slot_z_mm(side_img, col=c, tier=1, z_profile=z_prof))["found"]}
    cell_arm_cal.record_z_profile(config_or_work, z_prof, arm_id=arm_id)
    return z_prof


def perceive_slot_z_mm(
    side_img: np.ndarray | None, top_colour: np.ndarray | None = None, top_depth: np.ndarray | None = None, *,
    col: int = 2, row: int = 1, tier: int = 1, z_profile: dict[str, Any] | None = None, spec_id: str = "C3",
) -> dict[str, Any]:
    """(B) Live execution-time Z-axis `mm` perception for a slot `(col, row, tier)` from Side View + optional Top Depth."""
    side_prof = SideViewZProfile.from_dict((z_profile or {}).get("side_view"))
    expected_tier = int(tier) if int(tier) in (1, 2, 3) else 1
    expected_grasp_z_mm, expected_top_z_mm, expected_mid_z_mm = TIER_GRASP_Z_MM[expected_tier], TIER_TOP_Z_MM[expected_tier], TIER_MID_Z_MM[expected_tier]
    side_top_z_mm = side_mid_z_mm = v_top_px = v_centroid_px = None
    if side_img is not None and hasattr(side_img, "shape") and len(side_img.shape) == 3:
        import cv2
        if (z_profile is None or "side_view" not in (z_profile or {})) and len(auto_pts := detect_side_self_profile_landmarks(side_img)) >= 2:
            side_prof = SideViewZProfile.fit_from_landmarks(auto_pts)
        h, w = side_img.shape[:2]
        u0, u1 = SIDE_COL_U_BOUNDS.get(int(col), (239, 305))
        v0, v1 = 105, min(h, int(round(side_prof.v_z0_px)) + 4)
        crop = side_img[v0:v1, max(0, u0):min(w, u1)]
        if crop.size > 0:
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
            sat_c = (hue >= 4) & (hue <= 34) & (sat >= 115) & (val >= 145)
            warm = sat_c if int(sat_c.sum()) >= 200 else ((((hue <= 38) | (hue >= 158)) & (sat >= 65) & (val >= 90)) | ((hue >= 35) & (hue <= 75) & (sat >= 16) & (sat <= 115) & (val >= 140) & (val <= 228)))
            valid_rows = np.where(warm.sum(axis=1) >= 28)[0]
            if len(valid_rows) < 8:
                valid_rows = np.where(warm.sum(axis=1) >= 12)[0]
            if len(valid_rows) >= 8:
                v_exp_rel = side_prof.z_mm_to_v(expected_top_z_mm) - v0
                tier_rows = valid_rows[(valid_rows >= v_exp_rel - 28.0) & (valid_rows <= v_exp_rel + 32.0)]
                chosen_rows = tier_rows if len(tier_rows) >= 6 else valid_rows
                v_top_px, v_centroid_px = round(float(v0 + chosen_rows[0]), 1), round(float(v0 + chosen_rows.mean()), 1)
                side_top_z_mm, side_mid_z_mm = side_prof.v_to_z_mm(v_top_px), side_prof.v_to_z_mm(v_centroid_px)
    depth_top_z_mm: float | None = None
    if top_depth is not None and hasattr(top_depth, "ndim") and top_depth.ndim == 2 and top_depth.size > 0:
        heights, to_depth, _ = _aligned_depth_heights(top_depth, top_colour, z_profile)
        raw_h = cell_depth.height_at(heights, to_depth, TOP_SLOT_CENTER_PX.get((int(col), int(row)), (395.0, 217.5)), 16)
        if not np.isfinite(raw_h) or raw_h < 12.0:
            u_d, v_d = int(round(282.0 + (int(col) - 1) * 28.0)), (245 if int(row) == 1 else 315)
            patch = heights[max(0, v_d - 22):min(heights.shape[0], v_d + 22), max(0, u_d - 20):min(heights.shape[1], u_d + 20)]
            if (valid_p := patch[np.isfinite(patch) & (patch >= 14.0) & (patch <= 105.0)]).size >= 10:
                raw_h = float(np.percentile(valid_p, 85 if expected_tier >= 2 else 45))
        if np.isfinite(raw_h):
            td_cfg = (z_profile or {}).get("top_depth") or {}
            depth_top_z_mm = TopDepthZProfile(measured_plate_top_mm=td_cfg.get("measured_plate_top_mm", 13.0), cad_plate_top_mm=13.0, pallet_surface_mm=td_cfg.get("pallet_surface_mm", 0.0)).raw_height_to_pallet_z_mm(raw_h)
    if side_top_z_mm is not None and depth_top_z_mm is not None:
        fused_top_z_mm, basis = (round(0.65 * side_top_z_mm + 0.35 * depth_top_z_mm, 2) if abs(side_top_z_mm - depth_top_z_mm) <= 12.0 else side_top_z_mm), "side_view_and_top_depth"
    elif side_top_z_mm is not None:
        fused_top_z_mm, basis = side_top_z_mm, "side_view_profile"
    elif depth_top_z_mm is not None:
        fused_top_z_mm, basis = depth_top_z_mm, "top_depth_profile"
    else:
        return {"found": False, "basis": "none", "col": int(col), "row": int(row), "expected_tier": expected_tier, "expected_grasp_z_mm": expected_grasp_z_mm, "expected_top_z_mm": expected_top_z_mm}
    inferred_tier = min((1, 2, 3), key=lambda t: abs(TIER_TOP_Z_MM[t] - fused_top_z_mm))
    measured_grasp_z_mm = round(max(5.5, min(140.0, fused_top_z_mm - (expected_top_z_mm - expected_grasp_z_mm))), 2)
    dz_top_mm, dz_grasp_mm = round(fused_top_z_mm - expected_top_z_mm, 2), round(measured_grasp_z_mm - expected_grasp_z_mm, 2)
    dz_ts = round(float(side_top_z_mm) - float(depth_top_z_mm), 2) if (side_top_z_mm is not None and depth_top_z_mm is not None) else 0.0
    spec_gate = evaluate_signed_tier_residual_mm(fused_top_z_mm, expected_tier, dz_top_side_mm=dz_ts, spec_id=spec_id)
    return {"found": True, "basis": basis, "col": int(col), "row": int(row), "expected_tier": expected_tier, "inferred_tier": inferred_tier,
            "v_top_px": v_top_px, "v_centroid_px": v_centroid_px, "side_top_z_mm": side_top_z_mm, "side_mid_z_mm": side_mid_z_mm,
            "depth_top_z_mm": depth_top_z_mm, "measured_top_z_mm": fused_top_z_mm, "measured_mid_z_mm": side_mid_z_mm if side_mid_z_mm is not None else round(fused_top_z_mm - 15.0, 2),
            "measured_grasp_z_mm": measured_grasp_z_mm, "measured_grasp_z_m": round(measured_grasp_z_mm / 1000.0, 5), "expected_top_z_mm": expected_top_z_mm,
            "expected_mid_z_mm": expected_mid_z_mm, "expected_grasp_z_mm": expected_grasp_z_mm, "dz_top_mm": dz_top_mm, "dz_grasp_mm": dz_grasp_mm,
            "dz_m": round(dz_grasp_mm / 1000.0, 5), "r_k_mm": spec_gate["r_k_mm"], "spec_id": spec_gate["spec_id"], "spec_gate": spec_gate}


def perceive_all_columns_z_mm(
    side_img: np.ndarray | None, top_colour: np.ndarray | None = None, top_depth: np.ndarray | None = None, *, row: int = 1, tier: int | None = None, z_profile: dict[str, Any] | None = None, spec_id: str = "C3",
) -> dict[str, Any]:
    """Perceive and audit all 3 pallet columns (`col = 1, 2, 3`) with multi-view reconciliation and `evaluate_slot_spec_gate`."""
    cols: dict[int, dict[str, Any]] = {}
    for c_idx in (1, 2, 3):
        obs = perceive_slot_z_mm(side_img, top_colour, top_depth, col=c_idx, row=row, tier=tier or 1, z_profile=z_profile, spec_id=spec_id)
        if tier is None and obs.get("found") and int(obs["inferred_tier"]) != 1:
            obs = perceive_slot_z_mm(side_img, top_colour, top_depth, col=c_idx, row=row, tier=int(obs["inferred_tier"]), z_profile=z_profile, spec_id=spec_id)
        rec_views = reconcile_top_and_side_z_mm(obs.get("depth_top_z_mm"), obs.get("side_top_z_mm"))
        cols[c_idx] = {**obs, "reconcile_views": rec_views, "spec_gate": evaluate_slot_spec_gate(obs, expected_tier=int(tier or obs.get("inferred_tier") or 1), spec_id=spec_id)}
    return {"row": int(row), "spec_id": resolve_container_spec(spec_id)["spec_id"], "columns": cols, "col_1": cols[1], "col_2": cols[2], "col_3": cols[3],
            "all_found": all(cols[c].get("found", False) for c in (1, 2, 3)), "all_aligned": all(cols[c]["reconcile_views"]["aligned"] and cols[c]["spec_gate"]["verdict"] == "PASS" for c in (1, 2, 3) if cols[c].get("found"))}


def measure_side_gripper_pose_mm(
    side_img: np.ndarray | None, before_side: np.ndarray | None, col: int, *, target_u_px: float = 254.0, u_m_per_px: float = 0.00070,
    expected_z_mm: float | None = None, joint_state_deg: Sequence[float] | None = None, z_profile: dict[str, Any] | None = None, tol_u_px: float = 12.0, tol_z_mm: float = 14.0,
) -> dict[str, Any]:
    """(B) Measure both horizontal (`u_px -> dx_mm`) and vertical (`v_px -> gripper_z_mm, dz_mm`) gripper pose in Side View."""
    if side_img is None or before_side is None or not hasattr(side_img, "shape") or side_img.shape != before_side.shape:
        return {"found": False, "target_u_px": target_u_px}
    ys, xs = np.where(np.linalg.norm(side_img[70:165, 160:390].astype(np.float32) - before_side[70:165, 160:390].astype(np.float32), axis=2) > 32.0)
    if len(xs) < 40:
        return {"found": False, "target_u_px": target_u_px}
    side_prof, tip_mask = SideViewZProfile.from_dict((z_profile or {}).get("side_view")), (ys >= float(np.percentile(ys, 65)))
    u_gripper = round(float(160.0 + np.median(xs[tip_mask] if int(tip_mask.sum()) >= 10 else xs)), 1)
    v_gripper_tip, v_gripper_center = round(float(70.0 + np.percentile(ys, 90)), 1), round(float(70.0 + np.median(ys)), 1)
    du_px, dx_m, gripper_z_mm = round(target_u_px - u_gripper, 1), round((target_u_px - u_gripper) * float(u_m_per_px), 5), side_prof.v_to_z_mm(v_gripper_tip)
    fk_z_mm = float(fk_landmarks_mm(joint_state_deg[:5], unit="deg")["landmarks_z_mm"]["jaw_tip"]) if (joint_state_deg is not None and len(joint_state_deg) >= 5) else None
    ref_z_mm = float(expected_z_mm) if expected_z_mm is not None else fk_z_mm
    dz_mm = round(ref_z_mm - gripper_z_mm, 2) if ref_z_mm is not None else 0.0
    return {"found": True, "gripper_u_px": u_gripper, "gripper_v_tip_px": v_gripper_tip, "gripper_v_center_px": v_gripper_center,
            "target_u_px": target_u_px, "du_px": du_px, "dx_m": dx_m, "dx_mm": round(dx_m * 1000.0, 2), "gripper_z_mm": gripper_z_mm,
            "expected_z_mm": round(ref_z_mm, 2) if ref_z_mm is not None else None, "fk_jaw_tip_z_mm": round(fk_z_mm, 2) if fk_z_mm is not None else None,
            "dz_mm": dz_mm, "dz_m": round(dz_mm / 1000.0, 5), "within_zone": bool(abs(du_px) <= tol_u_px),
            "within_z_zone": True if ref_z_mm is None else (abs(dz_mm) <= tol_z_mm), "reconciled_tcp_mm": reconcile_tcp_z_mm(gripper_z_mm)}


def top_pixel_to_arm_xy_vanishing(u_px: float, v_px: float, *, h_top_m: float = 0.030, dx_reg_m: float = 0.0, dy_reg_m: float = 0.0) -> tuple[float, float]:
    """Map top-camera pixel `(u_px, v_px)` of a container top face at height `h_top_m` to `arm_b` IK `(x, y)`."""
    if float(v_px) < 150.0:
        return round(0.1695 + 0.000701 * (float(u_px) - 383.9) + dx_reg_m, 4), round(0.0712 - 0.000824 * (float(v_px) - 86.9) + dy_reg_m, 4)
    ug, vg = 322.0 + (float(u_px) - 322.0) * (1.0 - float(h_top_m) / 0.5751), 383.0 + (float(v_px) - 383.0) * (1.0 - float(h_top_m) / 0.5751)
    return round(0.1486 + (0.000630 if ug >= 352.24 else 0.000720) * (ug - 352.24) + dx_reg_m, 4), round(-0.0120 - 0.000645 * (vg - 229.07) + dy_reg_m, 4)


def measure_ik_tracking_mm(state_norm: list[float] | None, target_norm: list[float] | None, *, arm_id: str = "arm_b") -> dict[str, Any]:
    """Compare actual Dynamixel joint state (`state_norm`) vs commanded IK target (`target_norm`) in 3D `mm`."""
    if not state_norm or len(state_norm) < 5:
        return {"ok": False, "error_norm_mm": 0.0, "tracking_error_xyz_mm": [0.0, 0.0, 0.0], "recommended_jog_cmd": None}
    tcp_mm = 91.93 if arm_id == "arm_s" else float(OMX_AI_PROFILE_MM["tcp_v21_x_mm"])
    s_deg = [(float(v) + 100.0) / 200.0 * 360.0 - 180.0 for v in state_norm[:5]]
    t_deg = [(float(v) + 100.0) / 200.0 * 360.0 - 180.0 for v in (target_norm[:5] if target_norm and len(target_norm) >= 5 else state_norm[:5])]
    fk_s, fk_t = fk_landmarks_mm(s_deg, unit="deg", tcp_x_mm=tcp_mm), fk_landmarks_mm(t_deg, unit="deg", tcp_x_mm=tcp_mm)
    act_xyz, cmd_xyz = fk_s["landmarks_xyz_mm"]["tcp"], fk_t["landmarks_xyz_mm"]["tcp"]
    err_xyz = [round(act_xyz[i] - cmd_xyz[i], 2) for i in range(3)]
    norm_mm = round(float(np.hypot(np.hypot(err_xyz[0], err_xyz[1]), err_xyz[2])), 2)
    lags = [round(float(state_norm[i]) - float(target_norm[i]), 3) for i in range(5)] if target_norm and len(target_norm) >= 5 else [0.0] * 5
    names = ("shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos", "wrist_flex.pos", "wrist_roll.pos")
    jog_parts = [f"{names[i]} {max(-0.8, min(0.8, round(-0.65 * lags[i], 2)))}" for i in (1, 2, 3) if 0.22 <= abs(lags[i]) <= 1.5]
    return {"ok": True, "commanded_tcp_xyz_mm": [round(v, 2) for v in cmd_xyz], "actual_tcp_xyz_mm": [round(v, 2) for v in act_xyz],
            "tracking_error_xyz_mm": err_xyz, "droop_compensation_xyz_mm": [round(-v, 2) for v in err_xyz], "error_norm_mm": norm_mm,
            "tool_pitch_deg": round(s_deg[1] + s_deg[2] + s_deg[3], 2), "tool_pitch_error_deg": round((s_deg[1] + s_deg[2] + s_deg[3]) - (t_deg[1] + t_deg[2] + t_deg[3]), 2),
            "joint_lags_units": lags, "max_lag_units": round(max(abs(v) for v in lags), 3),
            "wrist_cam_xyz_mm": [round(v, 2) for v in fk_s["landmarks_xyz_mm"]["wrist_cam"]],
            "recommended_jog_cmd": f"jog {' '.join(jog_parts)}" if (jog_parts and norm_mm >= 1.0) else None}


def perceive_visual_distance_mm(
    side_img: np.ndarray | None, before_side: np.ndarray | None, *, col: int, row: int = 1, tier: int = 1,
    state_norm: list[float] | None = None, target_norm: list[float] | None = None, arm_id: str = "arm_b", z_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Real-time camera + FK distance sense (`mm`): clearance above container, straight descent stroke, and wrist-cam slant range."""
    ik_track = measure_ik_tracking_mm(state_norm, target_norm, arm_id=arm_id)
    slot_obs = perceive_slot_z_mm(before_side if before_side is not None else side_img, None, col=col, row=row, tier=tier, z_profile=z_profile)
    s_deg = [(float(v) + 100.0) / 200.0 * 360.0 - 180.0 for v in state_norm[:5]] if state_norm and len(state_norm) >= 5 else None
    grip_obs = measure_side_gripper_pose_mm(side_img, before_side, col=col, joint_state_deg=s_deg, z_profile=z_profile)
    top_z, grasp_z = float(slot_obs.get("measured_top_z_mm") or TIER_TOP_Z_MM.get(tier, 30.0)), float(slot_obs.get("measured_grasp_z_mm") or TIER_GRASP_Z_MM.get(tier, 8.5))
    grip_z = float(grip_obs.get("measured_z_mm") or (ik_track.get("actual_tcp_xyz_mm", [0.0, 0.0, top_z + 40.0])[2]))
    wcam_z = float((ik_track.get("wrist_cam_xyz_mm") or [0.0, 0.0, grip_z + 37.86])[2])
    return {"col": int(col), "row": int(row), "tier": int(tier), "container_top_z_mm": round(top_z, 2), "container_grasp_z_mm": round(grasp_z, 2),
            "gripper_z_mm": round(grip_z, 2), "vertical_clearance_mm": round(grip_z - top_z, 2), "vertical_descent_to_grasp_mm": round(grip_z - grasp_z, 2),
            "wrist_cam_slant_distance_mm": round(max(0.0, (wcam_z - top_z) / float(np.cos(np.radians(38.0)))), 2),
            "lateral_dx_mm": round(float(grip_obs.get("dx_mm", 0.0)), 2), "ik_tracking": ik_track}


def judge_z_axis_alignment_mm(
    side_img: np.ndarray | None, top_colour: np.ndarray | None = None, top_depth: np.ndarray | None = None, *,
    col: int = 2, row: int = 1, tier: int = 1, planned_z_mm: float | None = None,
    joint_state_deg: Sequence[float] | None = None, arm_id: str = "arm_b", z_profile: dict[str, Any] | None = None, tol_z_mm: float = 4.5,
) -> dict[str, Any]:
    """Pipeline stage: judge whether Side View (`v_to_z_mm`), Top View Depth (`D435 Z16`), and `planned_z_mm` are synchronized."""
    t0 = time.perf_counter()
    obs = perceive_slot_z_mm(side_img, top_colour, top_depth, col=col, row=row, tier=tier, z_profile=z_profile)
    t_slot = round((time.perf_counter() - t0) * 1000.0, 2)
    s_top, d_top = obs.get("side_top_z_mm"), obs.get("depth_top_z_mm")
    cross_diff = round(float(s_top) - float(d_top), 2) if (s_top is not None and d_top is not None) else None
    cross_sync = True if cross_diff is None else (abs(cross_diff) <= max(6.5, float(tol_z_mm) * 1.5))
    rec_z = float(obs.get("measured_grasp_z_mm") or TIER_GRASP_Z_MM.get(tier, 7.4))
    plan_z = float(planned_z_mm) if planned_z_mm is not None else rec_z
    z_err = round(plan_z - rec_z, 2)
    fk_jaw_z = round(float(fk_landmarks_mm(joint_state_deg[:5], unit="deg", tcp_x_mm=91.93 if arm_id == "arm_s" else 74.1)["landmarks_z_mm"]["jaw_tip"]), 2) if (joint_state_deg is not None and len(joint_state_deg) >= 5) else None
    aligned = bool(obs.get("found", False) and abs(z_err) <= float(tol_z_mm) and cross_sync)
    verdict = "aligned" if aligned else ("adjust_z_up" if z_err < -float(tol_z_mm) else ("adjust_z_down" if z_err > float(tol_z_mm) else "reconcile_views"))
    return {"ok": bool(obs.get("found", False)), "z_aligned": aligned, "verdict": verdict, "basis": obs.get("basis", "none"), "col": int(col), "row": int(row), "tier": int(tier),
            "inferred_tier": obs.get("inferred_tier", tier), "fk_jaw_tip_z_mm": fk_jaw_z, "side_top_z_mm": s_top, "depth_top_z_mm": d_top, "fused_top_z_mm": obs.get("measured_top_z_mm"),
            "side_vs_depth_top_dz_mm": cross_diff, "cross_view_diff_mm": cross_diff, "cross_view_synchronized": cross_sync, "planned_grasp_z_mm": round(plan_z, 2),
            "recommended_grasp_z_mm": round(rec_z, 2), "z_error_mm": z_err, "recommended_dz_mm": round(rec_z - plan_z, 2), "slot_z_obs": obs, "slot_obs": obs,
            "spec_gate": obs.get("spec_gate"), "stage_timings_ms": {"slot_z_ms": t_slot, "total_ms": round((time.perf_counter() - t0) * 1000.0, 2)}}


from cell_subzone_3d import (  # noqa: E402,F401
    SUBZONE_X_CENTERS_MM, build_slot_subzone_rois, evaluate_multiview_subzones, evaluate_subzones_split_2d,
    fuse_subzones_2d_to_3d, observe_subzones_2d, reconstruct_slot_voxel_column_3x3, select_optimal_subzone_mode,
)
from cell_z_shuttle import (  # noqa: E402,F401
    SNAPSHOT_DEFAULT_PATH, build_shuttle_roundtrip_directives, build_temp_plate_123_tier_loop_directives,
    execute_shuttle_roundtrip, execute_temp_plate_123_tier_recovery_loop, load_snapshot_bundle,
    perceive_live_base, perceive_live_pick_candidates, run_snapshot_verification,
)
