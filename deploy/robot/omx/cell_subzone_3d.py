#!/usr/bin/env python3
"""Sub-Zone 2D<->3D Multi-View Perception, 9-Voxel 3x1x3 Column Reconstruction & Adaptive Judge (`cell_subzone_3d.py`)."""
from __future__ import annotations

import math, sys
from pathlib import Path
from typing import Any, Sequence
import numpy as np

HERE = Path(__file__).resolve().parent
ADAPTER_ROOT = (HERE.parents[2] if len(HERE.parents) > 2 else HERE) / "middleware/devices/omx/adapter"
for _p in (HERE, ADAPTER_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from omx_adapter.z_profile import TIER_TOP_Z_MM, SideViewZProfile, TopDepthZProfile, resolve_container_spec  # noqa: E402

SUBZONE_X_CENTERS_MM: tuple[float, float, float] = (-30.0, 0.0, 30.0)
SPEC_REQUIRED_VOXELS: dict[str, int] = {"C3": 3, "C2": 2, "C1": 1}
SPEC_VALID_MASKS: dict[str, tuple[tuple[int, int, int], ...]] = {
    "C3": ((1, 1, 1),), "C2": ((1, 1, 0), (0, 1, 1)), "C1": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
}
_SEV: dict[str, int] = {"PASS": 0, "UNKNOWN": 1, "FAIL": 2}


def build_slot_subzone_rois(col: int = 2, row: int = 1, tier: int = 1, *, z_profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Partition a 90x30 mm slot `(col, row, tier)` into 3 unit `30x30x30 mm` sub-zones (`-30, 0, +30 mm`)."""
    import cell_z_profile as czp
    return [
        {"subzone_idx": idx, "x_center_mm": float(x_mm), "top_roi_px": (p := czp.project_container_spec_roi(col=int(col), tier=int(tier), spec_id="C1", x_offset_mm=float(x_mm), row=int(row), z_profile=z_profile))["top_roi"], "side_roi_px": p["side_roi"], "frustum_scale": p["frustum_scale"]}
        for idx, x_mm in enumerate(SUBZONE_X_CENTERS_MM)
    ]


def observe_subzones_2d(
    side_img: np.ndarray | None = None, top_img: np.ndarray | None = None, top_depth: np.ndarray | None = None, *,
    col: int = 2, row: int = 1, tier: int = 1, z_profile: dict[str, Any] | None = None,
    synthetic_subzones: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Extract per-sub-zone (`i=0,1,2` at `x=-30,0,+30 mm`) 2D observations from Top View (`XY + Depth`) and Side View (`XZ`)."""
    expected_tier = int(tier) if int(tier) in (1, 2, 3) else 1
    expected_top_z_mm = float(TIER_TOP_Z_MM[expected_tier])
    rois = build_slot_subzone_rois(col=col, row=row, tier=expected_tier, z_profile=z_profile)

    if synthetic_subzones is not None:
        subs: list[dict[str, Any]] = []
        for idx, x_mm in enumerate(SUBZONE_X_CENTERS_MM):
            raw = dict(synthetic_subzones[idx]) if idx < len(synthetic_subzones) else {}
            t_occ, s_occ = float(raw.get("top_occ", raw.get("occ", 0.85))), float(raw.get("side_occ", raw.get("occ", 0.85)))
            t_z = raw.get("top_depth_z_mm", raw.get("z_mm", expected_top_z_mm))
            s_z = raw.get("side_top_z_mm", raw.get("z_mm", expected_top_z_mm))
            subs.append({
                "subzone_idx": idx, "x_center_mm": float(x_mm),
                "top_roi_px": rois[idx]["top_roi_px"], "side_roi_px": rois[idx]["side_roi_px"],
                "top_occ": round(t_occ, 4), "side_occ": round(s_occ, 4),
                "top_depth_z_mm": round(float(t_z), 2) if t_z is not None else None,
                "side_top_z_mm": round(float(s_z), 2) if s_z is not None else None,
                "valid_depth_ratio": round(float(raw.get("valid_depth_ratio", 0.90 if t_z is not None else 0.0)), 4),
                "dy_mm": round(float(raw.get("dy_mm", 0.0)), 2),
                "top_valid": bool(raw.get("top_valid", True)), "side_valid": bool(raw.get("side_valid", True)),
            })
        return {"col": int(col), "row": int(row), "expected_tier": expected_tier, "expected_top_z_mm": expected_top_z_mm, "subzones": subs}

    side_prof = SideViewZProfile.from_dict((z_profile or {}).get("side_view"))
    td_cfg = (z_profile or {}).get("top_depth") or {}
    td_prof = TopDepthZProfile(
        measured_plate_top_mm=td_cfg.get("measured_plate_top_mm", 13.0), cad_plate_top_mm=13.0,
        pallet_surface_mm=td_cfg.get("pallet_surface_mm", 0.0),
    )
    subs = []
    for idx, r_info in enumerate(rois):
        tx0, ty0, tx1, ty1 = r_info["top_roi_px"]
        sx0, sy0, sx1, sy1 = r_info["side_roi_px"]
        top_occ, dy_mm, top_valid = 0.0, 0.0, False
        if top_img is not None and hasattr(top_img, "shape") and len(top_img.shape) == 3:
            import cv2
            crop_t = top_img[max(0, ty0):min(top_img.shape[0], ty1), max(0, tx0):min(top_img.shape[1], tx1)]
            if crop_t.size > 0:
                top_valid = True
                hsv = cv2.cvtColor(crop_t, cv2.COLOR_BGR2HSV)
                warm = (((hsv[..., 0] <= 38) | (hsv[..., 0] >= 158)) & (hsv[..., 1] >= 65) & (hsv[..., 2] >= 90)) | (
                    (hsv[..., 0] >= 35) & (hsv[..., 0] <= 85) & (hsv[..., 1] >= 20) & (hsv[..., 2] >= 90)
                )
                top_occ = float(warm.mean())
                _, xs_w = np.where(warm)
                if len(xs_w) >= 8:
                    dy_mm = (float(np.median(xs_w)) - 0.5 * crop_t.shape[1]) * (30.0 / max(12.0, float(crop_t.shape[1])))

        top_depth_z_mm: float | None = None
        valid_d_ratio = 0.0
        if top_depth is not None and hasattr(top_depth, "ndim") and top_depth.ndim == 2:
            d_patch = top_depth[max(0, ty0):min(top_depth.shape[0], ty1), max(0, tx0):min(top_depth.shape[1], tx1)]
            if d_patch.size > 0:
                valid_mask = (d_patch > 0) & (d_patch <= 645)
                valid_d_ratio = float(valid_mask.mean())
                if valid_d_ratio >= 0.15:
                    raw_h = max(0.0, 588.0 - float(np.median(d_patch[valid_mask])))
                    top_depth_z_mm = td_prof.raw_height_to_pallet_z_mm(raw_h)
                    top_occ, top_valid = max(top_occ, min(1.0, valid_d_ratio)), True

        side_occ, side_top_z_mm, side_valid = 0.0, None, False
        if side_img is not None and hasattr(side_img, "shape") and len(side_img.shape) == 3:
            import cv2
            v_scan_top, v_scan_bot = max(80, sy0 - 24), min(side_img.shape[0], int(round(side_prof.v_z0_px)) + 4)
            crop_s = side_img[v_scan_top:v_scan_bot, max(0, sx0):min(side_img.shape[1], sx1)]
            if crop_s.size > 0:
                side_valid = True
                hsv_s = cv2.cvtColor(crop_s, cv2.COLOR_BGR2HSV)
                warm_s = (((hsv_s[..., 0] <= 38) | (hsv_s[..., 0] >= 158)) & (hsv_s[..., 1] >= 65) & (hsv_s[..., 2] >= 90)) | (
                    (hsv_s[..., 0] >= 35) & (hsv_s[..., 0] <= 85) & (hsv_s[..., 1] >= 18) & (hsv_s[..., 2] >= 95)
                )
                band_s = warm_s[max(0, sy0 - v_scan_top):max(1, sy1 - v_scan_top), :]
                side_occ = float(band_s.mean()) if band_s.size > 0 else float(warm_s.mean())
                valid_rows = np.where(warm_s.sum(axis=1) >= max(4, int(0.22 * crop_s.shape[1])))[0]
                if len(valid_rows) >= 4:
                    side_top_z_mm = side_prof.v_to_z_mm(float(v_scan_top + valid_rows[0]))

        subs.append({
            "subzone_idx": idx, "x_center_mm": float(r_info["x_center_mm"]),
            "top_roi_px": r_info["top_roi_px"], "side_roi_px": r_info["side_roi_px"],
            "top_occ": round(top_occ, 4), "side_occ": round(side_occ, 4),
            "top_depth_z_mm": round(float(top_depth_z_mm), 2) if top_depth_z_mm is not None else None,
            "side_top_z_mm": round(float(side_top_z_mm), 2) if side_top_z_mm is not None else None,
            "valid_depth_ratio": round(valid_d_ratio, 4), "dy_mm": round(dy_mm, 2),
            "top_valid": top_valid, "side_valid": side_valid,
        })
    return {"col": int(col), "row": int(row), "expected_tier": expected_tier, "expected_top_z_mm": expected_top_z_mm, "subzones": subs}


def select_optimal_subzone_mode(subzone_obs: dict[str, Any]) -> dict[str, Any]:
    """Compute Top vs Side view confidence across sub-zones and select whether to use `fused_3d`,
    `side_xz_promoted` (when D435 depth / Top RGB has specular dropout), or `top_xy_promoted` (when Side is arm-occluded)."""
    subs = list(subzone_obs.get("subzones") or [])
    if not subs:
        return {"selected_mode": "fused_3d", "top_confidence": 0.0, "side_confidence": 0.0, "reason": "empty_subzones"}
    top_valid_frac = sum(1.0 for s in subs if s.get("top_valid", True)) / len(subs)
    side_valid_frac = sum(1.0 for s in subs if s.get("side_valid", True)) / len(subs)
    depth_mean = float(np.mean([float(s.get("valid_depth_ratio", 0.0)) for s in subs]))
    top_conf = round(top_valid_frac * (0.55 * depth_mean + 0.45 * max((float(s.get("top_occ", 0.0)) for s in subs), default=0.0)), 3)
    side_conf = round(side_valid_frac * max((float(s.get("side_occ", 0.0)) for s in subs), default=0.0), 3)
    if (top_valid_frac < 0.5 or depth_mean < 0.45) and side_conf >= 0.65:
        return {"selected_mode": "side_xz_promoted", "top_confidence": top_conf, "side_confidence": side_conf, "reason": "top_depth_dropout_promote_side_xz"}
    if side_valid_frac < 0.5 and top_conf >= 0.65:
        return {"selected_mode": "top_xy_promoted", "top_confidence": top_conf, "side_confidence": side_conf, "reason": "side_occluded_promote_top_xy"}
    return {"selected_mode": "fused_3d", "top_confidence": top_conf, "side_confidence": side_conf, "reason": "both_views_healthy"}


def fuse_subzones_2d_to_3d(
    subzone_obs: dict[str, Any], *, expected_tier: int | None = None, spec_id: str = "C3", occ_threshold: float = 0.35,
) -> dict[str, Any]:
    """Mode 1 (`fused_3d` — "2D를 3D로 합쳐서 한번에 확인"): Intersect Top-2D and Side-2D sub-zones into 3 unit `30x30x30 mm` 3D voxels."""
    spec = resolve_container_spec(spec_id)
    sid, tier_k = spec["spec_id"], int(expected_tier or subzone_obs.get("expected_tier") or 1)
    h_k, subs = float(TIER_TOP_Z_MM.get(tier_k, 30.0)), list(subzone_obs.get("subzones") or [])
    voxels_3d, occ_mask = [], []
    for s in subs:
        t_v, s_v = bool(s.get("top_valid", True)), bool(s.get("side_valid", True))
        t_occ, s_occ = float(s.get("top_occ", 0.0)), float(s.get("side_occ", 0.0))
        occ_3d = min(t_occ, s_occ) if (t_v and s_v) else (t_occ if t_v else s_occ)
        occupied = occ_3d >= float(occ_threshold)
        occ_mask.append(1 if occupied else 0)
        tz, sz = s.get("top_depth_z_mm"), s.get("side_top_z_mm")
        d_ok = float(s.get("valid_depth_ratio", 0.90)) >= 0.45 and t_v
        if sz is not None and tz is not None and d_ok and s_v:
            dz_ts = round(float(sz) - float(tz), 2)
            z_3d = round(0.65 * float(sz) + 0.35 * float(tz), 2) if abs(dz_ts) <= 8.0 else round(float(sz), 2)
        elif sz is not None and s_v:
            z_3d, dz_ts = round(float(sz), 2), 0.0
        elif tz is not None and t_v:
            z_3d, dz_ts = round(float(tz), 2), 0.0
        else:
            z_3d, dz_ts = h_k, 0.0
        voxels_3d.append({
            "subzone_idx": int(s["subzone_idx"]), "x_center_mm": float(s["x_center_mm"]),
            "occupied_3d": bool(occupied), "occ_3d": round(occ_3d, 4), "z_3d_mm": z_3d,
            "r_k_mm": round(z_3d - h_k, 2), "dz_top_side_mm": dz_ts, "dy_mm": round(float(s.get("dy_mm", 0.0)), 2),
        })

    occ_vox = [v for v in voxels_3d if v["occupied_3d"]]
    span_matches_spec = tuple(occ_mask) in SPEC_VALID_MASKS.get(sid, ((1, 1, 1),))
    x_hat_mm = round(sum(v["x_center_mm"] * v["occ_3d"] for v in occ_vox) / max(1e-6, sum(v["occ_3d"] for v in occ_vox)), 2) if occ_vox else 0.0
    dy_mean_mm = round(float(np.mean([v["dy_mm"] for v in occ_vox])), 2) if occ_vox else 0.0
    if len(occ_vox) >= 2:
        dx_span = max(30.0, occ_vox[-1]["x_center_mm"] - occ_vox[0]["x_center_mm"])
        dz_span_mm, dy_span_mm = round(occ_vox[-1]["z_3d_mm"] - occ_vox[0]["z_3d_mm"], 2), round(occ_vox[-1]["dy_mm"] - occ_vox[0]["dy_mm"], 2)
        pitch_3d_deg, yaw_3d_deg = round(math.degrees(math.atan2(dz_span_mm, dx_span)), 2), round(math.degrees(math.atan2(dy_span_mm, dx_span)), 2)
    else:
        dz_span_mm = pitch_3d_deg = yaw_3d_deg = 0.0

    r_vals = [v["r_k_mm"] for v in (occ_vox or voxels_3d)]
    r_min, r_max, r_med = min(r_vals), max(r_vals), float(np.median(r_vals))
    max_dz_ts = max((abs(v["dz_top_side_mm"]) for v in (occ_vox or voxels_3d)), default=0.0)
    slumped_subs = [v["subzone_idx"] for v in (occ_vox or voxels_3d) if v["r_k_mm"] <= -4.0]
    perched_subs = [v["subzone_idx"] for v in (occ_vox or voxels_3d) if 1.0 <= v["r_k_mm"] <= 3.5]

    if not occ_vox:
        verdict, code = "FAIL", "S4_EMPTY_OR_SHALLOW"
    elif max_dz_ts > 8.0:
        verdict, code = "UNKNOWN", "S5_VIEW_OR_GATE_MISMATCH"
    elif slumped_subs or abs(pitch_3d_deg) > 5.0 or abs(dz_span_mm) > 4.5:
        verdict, code = "FAIL", "S2_TOPPLED_OR_SLUMPED"
    elif perched_subs:
        verdict, code = "FAIL", "S6_UNSEATED_CONE"
    elif not span_matches_spec or abs(dy_mean_mm) > 3.0 or abs(yaw_3d_deg) > 4.0:
        verdict, code = "FAIL", "S1_POSE_OFFSET_OR_YAW"
    else:
        verdict, code = "PASS", None

    perched_x_mm = max((v for v in voxels_3d if v["subzone_idx"] in perched_subs), key=lambda v: v["r_k_mm"])["x_center_mm"] if perched_subs else None
    slumped_x_mm = min((v for v in voxels_3d if v["subzone_idx"] in slumped_subs), key=lambda v: v["r_k_mm"])["x_center_mm"] if slumped_subs else None
    return {
        "mode": "fused_3d", "verdict": verdict, "failure_code": code, "spec_id": sid, "expected_tier": tier_k,
        "occupied_mask": list(occ_mask), "span_matches_spec": span_matches_spec,
        "x_hat_mm": x_hat_mm, "dy_mm": dy_mean_mm, "yaw_3d_deg": yaw_3d_deg,
        "dz_span_mm": dz_span_mm, "pitch_3d_deg": pitch_3d_deg,
        "r_k_min_mm": round(r_min, 2), "r_k_max_mm": round(r_max, 2), "r_k_median_mm": round(r_med, 2),
        "slumped_subzones": slumped_subs, "perched_subzones": perched_subs,
        "perched_subzone_x_mm": perched_x_mm, "slumped_subzone_x_mm": slumped_x_mm, "voxels_3d": voxels_3d,
    }


def evaluate_subzones_split_2d(
    subzone_obs: dict[str, Any], *, expected_tier: int | None = None, spec_id: str = "C3", occ_threshold: float = 0.35,
) -> dict[str, Any]:
    """Mode 2 (`split_2d` — "나눠서 처리"): Independently evaluate Top-View 2D (`XY+Yaw`) and Side-View 2D (`XZ+Pitch/Seating`)."""
    spec = resolve_container_spec(spec_id)
    sid, tier_k = spec["spec_id"], int(expected_tier or subzone_obs.get("expected_tier") or 1)
    h_k, subs = float(TIER_TOP_Z_MM.get(tier_k, 30.0)), list(subzone_obs.get("subzones") or [])

    top_mask = tuple(1 if float(s.get("top_occ", 0.0)) >= occ_threshold else 0 for s in subs)
    top_active = [s for s, m in zip(subs, top_mask) if m == 1]
    top_span_ok = top_mask in SPEC_VALID_MASKS.get(sid, ((1, 1, 1),))
    x_top_mm = round(sum(float(s["x_center_mm"]) * float(s["top_occ"]) for s in top_active) / max(1e-6, sum(float(s["top_occ"]) for s in top_active)), 2) if top_active else 0.0
    dy_top_mm = round(float(np.mean([float(s.get("dy_mm", 0.0)) for s in (top_active or subs)])), 2)
    yaw_top_deg = round(math.degrees(math.atan2(float(top_active[-1]["dy_mm"]) - float(top_active[0]["dy_mm"]), max(30.0, float(top_active[-1]["x_center_mm"]) - float(top_active[0]["x_center_mm"])))), 2) if len(top_active) >= 2 else 0.0
    if not top_active:
        top_verdict, top_code = "FAIL", "S4_EMPTY_OR_SHALLOW"
    elif not top_span_ok and sid in ("C2", "C1"):
        top_verdict, top_code = "UNKNOWN", "S5_X_BIMODAL_AMBIGUOUS"
    elif not top_span_ok or abs(dy_top_mm) > 3.0 or abs(yaw_top_deg) > 4.0:
        top_verdict, top_code = "FAIL", "S1_POSE_OFFSET_OR_YAW"
    else:
        top_verdict, top_code = "PASS", None

    side_mask = tuple(1 if float(s.get("side_occ", 0.0)) >= occ_threshold else 0 for s in subs)
    side_active = [s for s, m in zip(subs, side_mask) if m == 1] or subs
    side_zs = [float(s["side_top_z_mm"]) if s.get("side_top_z_mm") is not None else (float(s["top_depth_z_mm"]) if s.get("top_depth_z_mm") is not None else h_k) for s in side_active]
    side_rs = [round(z - h_k, 2) for z in side_zs]
    pitch_xz_deg = round(math.degrees(math.atan2(side_zs[-1] - side_zs[0], max(30.0, float(side_active[-1]["x_center_mm"]) - float(side_active[0]["x_center_mm"])))), 2) if len(side_active) >= 2 else 0.0
    perched_idx = [int(s["subzone_idx"]) for s, r in zip(side_active, side_rs) if 1.0 <= r <= 3.5]
    slumped_idx = [int(s["subzone_idx"]) for s, r in zip(side_active, side_rs) if r <= -4.0]
    side_span_ok = side_mask in SPEC_VALID_MASKS.get(sid, ((1, 1, 1),))
    if slumped_idx or abs(pitch_xz_deg) > 5.0:
        side_verdict, side_code = "FAIL", "S2_TOPPLED_OR_SLUMPED"
    elif perched_idx:
        side_verdict, side_code = "FAIL", "S6_UNSEATED_CONE"
    elif not side_span_ok:
        side_verdict, side_code = "FAIL", "S1_POSE_OFFSET_OR_YAW"
    elif any(r > 3.5 for r in side_rs):
        side_verdict, side_code = "UNKNOWN", "S5_HEIGHT_ANOMALY"
    else:
        side_verdict, side_code = "PASS", None

    combined_verdict = top_verdict if _SEV[top_verdict] >= _SEV[side_verdict] else side_verdict
    combined_code = side_code if _SEV[side_verdict] >= _SEV[top_verdict] and side_code else top_code
    return {
        "mode": "split_2d", "verdict": combined_verdict, "failure_code": combined_code, "spec_id": sid, "expected_tier": tier_k,
        "top_xy_pass": {
            "verdict": top_verdict, "failure_code": top_code, "occupied_mask": list(top_mask),
            "span_matches_spec": top_span_ok, "x_hat_mm": x_top_mm, "dy_mm": dy_top_mm, "yaw_deg": yaw_top_deg,
            "control_axes": {"dx_mm": round(-x_top_mm, 2) if sid == "C3" else 0.0, "dy_mm": round(-dy_top_mm, 2), "dyaw_deg": round(-yaw_top_deg, 2)},
        },
        "side_xz_pass": {
            "verdict": side_verdict, "failure_code": side_code, "occupied_mask": list(side_mask),
            "span_matches_spec": side_span_ok, "r_k_per_subzone_mm": side_rs, "pitch_xz_deg": pitch_xz_deg,
            "perched_subzones": perched_idx, "slumped_subzones": slumped_idx,
            "nudge_x_mm": SUBZONE_X_CENTERS_MM[perched_idx[0]] if perched_idx else 0.0,
            "control_axes": {"dz_mm": -3.0 if perched_idx else round(-float(np.median(side_rs)), 2), "nudge_x_mm": SUBZONE_X_CENTERS_MM[perched_idx[0]] if perched_idx else 0.0},
        },
    }


def evaluate_multiview_subzones(
    side_img: np.ndarray | None = None, top_img: np.ndarray | None = None, top_depth: np.ndarray | None = None, *,
    col: int = 2, row: int = 1, tier: int = 1, spec_id: str = "C3", mode: str = "hybrid",
    z_profile: dict[str, Any] | None = None, synthetic_subzones: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Unified multi-view sub-zone judge supporting `mode='fused_3d'`, `mode='split_2d'`, `mode='hybrid'`, or `mode='adaptive_hybrid'`."""
    import cell_spec_recovery_fsm as csrf

    obs = observe_subzones_2d(
        side_img, top_img, top_depth, col=col, row=row, tier=tier, z_profile=z_profile, synthetic_subzones=synthetic_subzones,
    )
    fused = fuse_subzones_2d_to_3d(obs, expected_tier=tier, spec_id=spec_id)
    split = evaluate_subzones_split_2d(obs, expected_tier=tier, spec_id=spec_id)
    mode_sel = select_optimal_subzone_mode(obs)

    if mode == "fused_3d":
        verdict, code, active_mode = fused["verdict"], fused["failure_code"], "fused_3d"
    elif mode == "split_2d":
        verdict, code, active_mode = split["verdict"], split["failure_code"], "split_2d"
    elif mode == "adaptive_hybrid" and mode_sel["selected_mode"] == "side_xz_promoted":
        s_pass = split["side_xz_pass"]
        verdict, code, active_mode = s_pass["verdict"], s_pass["failure_code"], "side_xz_promoted"
    elif mode == "adaptive_hybrid" and mode_sel["selected_mode"] == "top_xy_promoted":
        t_pass = split["top_xy_pass"]
        verdict, code, active_mode = t_pass["verdict"], t_pass["failure_code"], "top_xy_promoted"
    else:
        active_mode = mode_sel["selected_mode"] if mode == "adaptive_hybrid" else "hybrid"
        verdict = fused["verdict"] if _SEV[fused["verdict"]] >= _SEV[split["verdict"]] else split["verdict"]
        code = fused["failure_code"] if _SEV[fused["verdict"]] >= _SEV[split["verdict"]] and fused["failure_code"] else split["failure_code"]

    r_k_eff = float(fused["r_k_min_mm"] if code == "S2_TOPPLED_OR_SLUMPED" else (fused["r_k_max_mm"] if code == "S6_UNSEATED_CONE" else fused["r_k_median_mm"]))
    skill = (
        {"level": "NONE", "skill": "proceed", "failure_code": None, "params": {}}
        if verdict == "PASS"
        else csrf.select_recovery_skill(
            str(code or "S5_VIEW_OR_GATE_MISMATCH"),
            gate_ok=(verdict != "UNKNOWN"),
            dy_mm=float(split["top_xy_pass"]["dy_mm"]),
            dx_mm=float(fused["x_hat_mm"]),
            yaw_err_deg=float(split["top_xy_pass"]["yaw_deg"]),
            r_k_mm=r_k_eff,
            tilt_deg=max(abs(float(fused["pitch_3d_deg"])), abs(float(split["side_xz_pass"]["pitch_xz_deg"]))),
        )
    )
    if skill["skill"] == "seat_nudge" and fused["perched_subzone_x_mm"] is not None:
        skill["params"]["nudge_x_mm"] = float(fused["perched_subzone_x_mm"])
    return {
        "mode": mode, "active_mode": active_mode, "mode_selection": mode_sel,
        "verdict": verdict, "failure_code": code, "spec_id": fused["spec_id"],
        "col": int(col), "row": int(row), "expected_tier": int(tier),
        "fused_3d": fused, "split_2d": split, "recovery_skill": skill, "subzone_obs": obs,
    }


def reconstruct_slot_voxel_column_3x3(
    *,
    top_occ_by_subzone: Sequence[float] = (0.9, 0.9, 0.9),
    side_tier_occ_grid: Sequence[Sequence[float]] | None = None,
    subzone_top_z_mm: Sequence[float] | None = None,
    occ_threshold: float = 0.35,
) -> dict[str, Any]:
    """Reconstruct the full `3 (sub_x: -30, 0, +30 mm) x 1 (sub_y) x 3 (tier: 1..3) = 9` unit `30x30x30 mm`
    3D voxel grid of a slot, detecting unsupported overhangs and multi-tier stair-step profiles."""
    if side_tier_occ_grid is None:
        zs = list(subzone_top_z_mm or (30.0, 30.0, 30.0))
        side_grid = [
            [1.0 if float(zs[i]) >= (TIER_TOP_Z_MM[t] - 12.0) else 0.0 for i in range(3)]
            for t in (1, 2, 3)
        ]
    else:
        side_grid = [[float(side_tier_occ_grid[t_idx][i]) for i in range(3)] for t_idx in range(3)]

    voxel_grid_3x3: list[list[int]] = []
    for t_idx in range(3):
        row_vox = [
            1 if min(float(top_occ_by_subzone[i]), float(side_grid[t_idx][i])) >= float(occ_threshold) else 0
            for i in range(3)
        ]
        voxel_grid_3x3.append(row_vox)

    unsupported_overhangs: list[dict[str, Any]] = []
    stair_step_tiers: list[int] = [0, 0, 0]
    for i, x_mm in enumerate(SUBZONE_X_CENTERS_MM):
        for t_idx in range(3):
            if voxel_grid_3x3[t_idx][i] == 1:
                stair_step_tiers[i] = t_idx + 1
                if t_idx >= 1 and voxel_grid_3x3[t_idx - 1][i] == 0:
                    unsupported_overhangs.append({"subzone_idx": i, "x_center_mm": x_mm, "overhang_tier": t_idx + 1, "missing_support_tier": t_idx})

    has_overhang = len(unsupported_overhangs) > 0
    is_stair_step = len({t for t in stair_step_tiers if t > 0}) > 1
    return {
        "voxel_grid_3x3": voxel_grid_3x3,
        "stair_step_tiers": stair_step_tiers,
        "is_stair_step": is_stair_step,
        "unsupported_overhang": has_overhang,
        "unsupported_overhangs": unsupported_overhangs,
        "verdict": "FAIL" if has_overhang else "PASS",
        "failure_code": "S2_TOPPLED_OR_SLUMPED" if has_overhang else None,
    }
