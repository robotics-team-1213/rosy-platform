#!/usr/bin/env python3
"""Closed-loop grasp failure recovery and live top/side container perception (`cell_area_recovery.py`).

Split from `cell_area_zones.py` during multi-panel control modularization so ROI/stack verification
(`cell_area_zones.py`) and closed-loop pick recovery + live perception (`cell_area_recovery.py`)
each stay well below 400 lines. Re-exported by `cell_area_zones` and `cell_area_xyz`.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from cell_control_core import apply_wrist_xy_step


def diagnose_and_recover_pick(
    *,
    attempt: int,
    cur_directive: dict[str, Any],
    r_desc: dict[str, Any],
    r_grasp: dict[str, Any],
    cal: dict[str, Any],
    tried_xs: list[float],
    wrist_obs: dict[str, Any] | None = None,
    slipped_in_transfer: bool = False,
    debate_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Diagnose why a pick attempt failed (empty grasp / high z / lateral edge touch / skewed or partial grasp) and compute the
    recovered `AreaXYZ` pick coordinates and jaw opening for the next attempt."""
    state = r_grasp.get("state") or r_desc.get("state") or []
    jaw_pos = float(state[-1] if len(state) in (6, 7, 8) else state[5]) if len(state) >= 6 and state[5] is not None else 49.0
    curr_ma = float(r_grasp.get("gripper_current_ma") or 0.0)
    held_nominal = float(cal.get("held_30mm", 54.3))

    p_xyz = list(cur_directive["pick"]["effective_xyz_m"])
    cur_x, cur_y, cur_z = p_xyz[0], p_xyz[1], p_xyz[2]
    tried_xs.append(cur_x)

    tier = int(cur_directive["pick"].get("tier") or 2)
    area_name = str(cur_directive["pick"].get("area_id") or cur_directive["pick"].get("area") or "pallet")
    is_live = bool((cur_directive.get("execution") or {}).get("live_perceived"))
    min_grasp_z = (
        -0.0585
        if area_name in ("belt", "beltend")
        else (-0.0300 if area_name in ("ship", "pinky") else ({1: 0.0062 if is_live else 0.0051, 2: 0.0275, 3: 0.0560}.get(tier, 0.0051)))
    )
    new_x, new_y, new_z = cur_x, cur_y, cur_z
    pick_yaw = float(cur_directive["pick"].get("yaw_deg", -90.0))
    is_horiz = abs(abs(pick_yaw) - 90.0) > 45.0
    desc_contact = bool((r_desc and not r_desc.get("ok")) or (r_grasp and not r_grasp.get("ok")))
    deb_dx = float((debate_decision or {}).get("dx_mm") or 0.0)
    deb_dy = float((debate_decision or {}).get("dy_mm") or 0.0)
    deb_dz = float((debate_decision or {}).get("dz_mm") or 0.0)
    has_debate_shift = bool(
        isinstance(debate_decision, dict)
        and (
            ((debate_decision.get("vision") or {}).get("found") and (abs(deb_dx) >= 0.4 or abs(deb_dy) >= 0.4))
            or ((debate_decision.get("kinesthetic") or {}).get("verdict") == "reinsert")
        )
    )
    if has_debate_shift and not desc_contact:
        from cell_control_core import clamp_workspace_xy

        arm_id = str(cur_directive.get("arm_id") or "arm_b")
        new_x, new_y = clamp_workspace_xy(cur_x + deb_dx / 1000.0, cur_y + deb_dy / 1000.0, arm_id=arm_id)
        if deb_dz < 0.0:
            new_z = round(max(min_grasp_z, cur_z + deb_dz / 1000.0), 5)
        reason = f"council_debate_partial_grasp_recovery: shift=({deb_dx},{deb_dy},{deb_dz})mm -> xyz=({new_x},{new_y},{new_z})"
    elif slipped_in_transfer:
        if is_live:
            new_x = round(cur_x + (0.0018 if cur_x < 0.135 else -0.0012), 5)
        dz_step = min(-0.0008, deb_dz / 1000.0) if deb_dz < 0.0 else -0.0008
        new_z = round(max(min_grasp_z, cur_z + dz_step), 5)
        reason = f"shallow_tip_slip_recovery: shifted x={new_x}, lowered pick.z {cur_z} -> {new_z} after transfer slip"
    elif area_name in ("belt", "beltend"):
        new_x, new_z = round(cur_x + (0.0020 if desc_contact else -0.0020), 5), round(max(min_grasp_z, cur_z + (0.0030 if desc_contact else -0.0020)), 5)
        reason = f"belt_centered_recovery: x {cur_x} -> {new_x}, z {cur_z} -> {new_z}"
    elif desc_contact:
        col = int(cur_directive["pick"].get("col") or 1)
        new_x = round(max(0.055, min(0.234, cur_x + (-0.0012 if col == 1 else -0.0018))), 5)
        contact_z = r_desc.get("contact_z") if r_desc else None
        new_z_val = float(contact_z) + 0.0040 if contact_z is not None else cur_z + 0.0018
        new_y, new_z = round(cur_y, 5), round(max(min_grasp_z, new_z_val), 5)
        reason = f"descend_contact_clearance_recovery: shifted xyz ({cur_x},{cur_y},{cur_z}) -> ({new_x},{new_y},{new_z})"
    # 1. If wrist observation found a clear offset (and was not already applied), shift toward it
    elif wrist_obs and wrist_obs.get("found") and 1.5 < abs(float(wrist_obs.get("along_mm", 0.0))) <= 12.0:
        arm_id = str(cur_directive.get("arm_id") or "arm_b")
        stepped = apply_wrist_xy_step([cur_x, cur_y, cur_z], wrist_obs, arm_id=arm_id, cal=cal, yaw_deg=pick_yaw, gain_along=0.65)
        new_x, new_y = stepped[0], stepped[1]
        reason = f"wrist_offset_recovery: along_mm={wrist_obs['along_mm']} -> xy=({new_x},{new_y})"
    elif is_horiz:
        dy = 0.0065 if attempt == 0 else -0.0130
        new_y = round(max(-0.210, min(0.210, cur_y + dy)), 5)
        reason = f"horiz_y_bracket_recovery: y {cur_y} -> {new_y}"
    elif len(tried_xs) >= 2:
        new_x = round(0.5 * (tried_xs[-1] + tried_xs[-2]), 5)
        reason = f"bracket_midpoint_recovery: midpoint({tried_xs[-2]}, {tried_xs[-1]}) -> x={new_x}"
    elif is_live:
        step_x = 0.0050 if cur_x < 0.120 else (0.0180 if cur_x < 0.205 else -0.0040)
        new_x = round(cur_x + (step_x if attempt % 2 == 0 else -step_x), 5)
        reason = f"live_local_recovery: x {cur_x} -> {new_x}"
    else:
        col = int(cur_directive["pick"].get("col") or 3)
        canonical_x = {1: 0.1335, 2: 0.1580, 3: 0.1988}.get(col, cur_x)
        if cur_x < 0.115:
            new_x = round(max(0.055, cur_x + 0.0025), 5)
        elif 0.002 <= abs(cur_x - canonical_x) <= 0.012:
            new_x = round(canonical_x, 5)
        elif cur_x > 0.210:
            new_x = round(cur_x - 0.0035, 5)
        else:
            new_x = round(cur_x - 0.0060 if cur_x > 0.160 else cur_x + 0.0060, 5)
        reason = f"lateral_edge_recovery: x {cur_x} -> {new_x}"

    # 2. If jaws closed in thin air above the container (jaw_pos < held_nominal - 1.0 and low current), lower z into grasp band
    if not slipped_in_transfer and not desc_contact and jaw_pos < held_nominal - 1.0 and abs(curr_ma) < 75.0 and cur_z > min_grasp_z:
        step_z = 0.0020 if (area_name in ("belt", "beltend") or is_live) else (0.0035 if cur_x < 0.115 else 0.0095)
        new_z = round(max(min_grasp_z, cur_z - step_z), 5)
        reason += f"; lowered pick.z {cur_z} -> {new_z} (jaws closed at {jaw_pos:.2f} with {curr_ma:.0f}mA above grasp band)"

    cur_directive["pick"]["effective_xyz_m"] = [new_x, new_y, new_z]
    cur_directive["pick"]["x"] = new_x
    cur_directive["pick"]["y"] = new_y
    cur_directive["pick"]["z"] = new_z
    exec_cfg = dict(cur_directive.get("execution") or {})
    if desc_contact:
        exec_cfg["grip_open_override"] = 57.95
    else:
        exec_cfg["grip_open_override"] = min(58.15, float(exec_cfg.get("grip_open_override") or cal.get("grip_open_30mm", 57.85)) + 0.15)
    cur_directive["execution"] = exec_cfg
    return {
        "attempt": attempt,
        "fail_jaw_pos": jaw_pos,
        "fail_current_ma": curr_ma,
        "recovered_pick_xyz_m": [new_x, new_y, new_z],
        "grip_open_override": exec_cfg["grip_open_override"],
        "reason": reason,
    }


def top_pixel_to_arm_xy_vanishing(
    u_px: float,
    v_px: float,
    *,
    h_top_m: float = 0.030,
    dx_reg_m: float = 0.0,
    dy_reg_m: float = 0.0,
) -> tuple[float, float]:
    """Map top-camera pixel `(u_px, v_px)` of a container top face at height `h_top_m` to `arm_b` IK `(x, y)`
    using the D435 stern-tilt vanishing point `(322, 383)` at height `0.5751 m` and physical transfer calibration."""
    if float(v_px) < 150.0:
        x = 0.1695 + 0.000701 * (float(u_px) - 383.9) + dx_reg_m
        y = 0.0712 - 0.000824 * (float(v_px) - 86.9) + dy_reg_m
        return round(x, 4), round(y, 4)
    scale = 1.0 - float(h_top_m) / 0.5751
    ug = 322.0 + (float(u_px) - 322.0) * scale
    vg = 383.0 + (float(v_px) - 383.0) * scale
    kx = 0.000630 if ug >= 352.24 else 0.000720
    x = 0.1486 + kx * (ug - 352.24) + dx_reg_m
    y = -0.0120 - 0.000645 * (vg - 229.07) + dy_reg_m
    return round(x, 4), round(y, 4)


def perceive_live_base(
    top_frame: np.ndarray | None,
    side_frame: np.ndarray | None = None,
    *,
    preferred_col: int = 2,
) -> dict[str, Any]:
    """Dynamically perceive the live base container in Row 1 from `top` and `side` camera frames and compute
    its live `arm_xy` plus base-anchored `side` and `top` target ROIs for Tiers 1, 2, and 3."""
    out: dict[str, Any] = {"found": False, "arm_xy": (0.1540, -0.0120), "top_uv": None, "top_roi": None, "side_roi_by_tier": {}}
    if top_frame is not None and top_frame.ndim == 3 and top_frame.shape[0] >= 300:
        import cv2

        hsv_t = cv2.cvtColor(top_frame[160:275, 320:415], cv2.COLOR_BGR2HSV)
        ym_t = (hsv_t[..., 0] >= 20) & (hsv_t[..., 0] <= 42) & (hsv_t[..., 1] >= 100) & (hsv_t[..., 2] >= 120)
        ys_t, xs_t = np.where(ym_t)
        if len(xs_t) >= 120:
            u_b, v_b = 320.0 + float(xs_t.mean()), 160.0 + float(ys_t.mean())
            out["found"] = True
            out["top_uv"] = (round(u_b, 1), round(v_b, 1))
            bx, by = top_pixel_to_arm_xy_vanishing(u_b, v_b, h_top_m=0.030)
            out["arm_xy"] = (bx, round(max(-0.0155, min(-0.0105, by)), 4))
            out["top_roi"] = (max(0, int(u_b - 26)), max(0, int(v_b - 55)), min(640, int(u_b + 26)), min(480, int(v_b + 55)))
    if side_frame is not None and side_frame.ndim == 3 and side_frame.shape[0] >= 300:
        import cv2

        hsv_s = cv2.cvtColor(side_frame[180:275, 140:330], cv2.COLOR_BGR2HSV)
        ym_s = ((hsv_s[..., 0] >= 18) & (hsv_s[..., 0] <= 42) & (hsv_s[..., 1] >= 75) & (hsv_s[..., 2] >= 110)) | (
            (hsv_s[..., 0] >= 36) & (hsv_s[..., 0] <= 72) & (hsv_s[..., 1] >= 22) & (hsv_s[..., 1] <= 115) & (hsv_s[..., 2] >= 145)
        )
        ys_s, xs_s = np.where(ym_s)
        if len(xs_s) >= 40:
            u_s, y_t1 = 140.0 + float(xs_s.mean()), 180.0 + float(np.percentile(ys_s, 5))
        elif out["top_uv"] is not None:
            u_s, y_t1 = 205.0 + (float(out["top_uv"][0]) - 347.0) * 1.15, 246.0
        else:
            u_s, y_t1 = 245.0, 246.0
        x0, x1 = max(0, int(u_s - 34)), min(640, int(u_s + 34))
        out["side_roi_by_tier"] = {
            1: (x0, int(y_t1), x1, int(y_t1 + 32)),
            2: (x0, max(0, int(y_t1 - 62)), x1, int(y_t1 - 2)),
            3: (x0, max(0, int(y_t1 - 124)), x1, max(0, int(y_t1 - 62))),
        }
    return out


def _orange_mask(crop: np.ndarray, cv2) -> np.ndarray:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (((h <= 18) | (h >= 168)) & (s >= 145) & (v >= 130)).astype(np.uint8)


def perceive_live_pick_candidates(top_frame: np.ndarray | None) -> list[dict[str, Any]]:
    """Detect all pickable orange containers from the live `top` frame, automatically splitting adjacent
    containers into individual `~38 px` columns and computing live `(x, y, z, yaw_deg)`."""
    if top_frame is None or top_frame.ndim != 3:
        return []
    import cv2
    from cell_area_zones import classify_container_orientation

    candidates: list[dict[str, Any]] = []

    om_r1 = _orange_mask(top_frame[155:290, 280:530], cv2)
    num, labels, stats, cents = cv2.connectedComponentsWithStats(om_r1)
    for k in range(1, num):
        x, y, w, h_px, area = stats[k]
        if area < 900:
            continue
        n_cols = max(1, int(round(w / 38.0)))
        if n_cols == 1:
            u = 280.0 + float(x) + 0.5 * float(w)
            v = 155.0 + float(cents[k][1])
            px, py = top_pixel_to_arm_xy_vanishing(u, v, h_top_m=0.030)
            col_idx = 1 if u < 355.0 else (2 if u < 410.0 else 3)
            pz = 0.0085 if u < 335.0 else 0.0064
            candidates.append(
                {"label": f"live_r1_u{int(round(u))}_c1", "area": "pallet", "col": col_idx, "row": 1, "tier": 1, "u_px": round(u, 1), "v_px": round(v, 1), "x": px, "y": py, "z": pz, "yaw_deg": -90.0, "isolated": True}
            )
            continue
        sub_labels = labels[y : y + h_px]
        for c in range(n_cols):
            cx0, cx1 = x + c * 38, min(x + w, x + (c + 1) * 38)
            if cx1 <= cx0:
                continue
            ys, xs = np.where(sub_labels[:, cx0:cx1] == k)
            if len(xs) < 200:
                continue
            u, v = 280.0 + cx0 + 0.5 * float(cx1 - cx0), 155.0 + float(y) + float(ys.mean())
            px, py = top_pixel_to_arm_xy_vanishing(u, v, h_top_m=0.030)
            col_idx = 1 if u < 355.0 else (2 if u < 410.0 else 3)
            pz = 0.0085 if u < 335.0 else 0.0064
            candidates.append(
                {"label": f"live_r1_u{int(round(u))}_c{c+1}", "area": "pallet", "col": col_idx, "row": 1, "tier": 1, "u_px": round(u, 1), "v_px": round(v, 1), "x": px, "y": py, "z": pz, "yaw_deg": -90.0, "isolated": False}
            )

    om_b = _orange_mask(top_frame[35:148, 355:415], cv2)
    ys_b, xs_b = np.where(om_b > 0)
    if len(xs_b) >= 350:
        u_b, v_b = 355.0 + float(xs_b.mean()), 35.0 + float(ys_b.mean())
        bx, by = top_pixel_to_arm_xy_vanishing(u_b, v_b, h_top_m=0.030)
        candidates.append(
            {"label": f"live_belt_u{int(round(u_b))}", "area": "belt", "col": 2, "row": 1, "tier": 1, "u_px": round(u_b, 1), "v_px": round(v_b, 1), "x": bx, "y": by, "z": -0.0285, "yaw_deg": -90.0, "isolated": True}
        )

    om_h = _orange_mask(top_frame[365:468, 310:448], cv2)
    ys_h, xs_h = np.where(om_h > 0)
    if len(xs_h) >= 300:
        u_h, v_h = 310.0 + float(xs_h.mean()), 365.0 + float(ys_h.mean())
        hx, hy = top_pixel_to_arm_xy_vanishing(u_h, v_h, h_top_m=0.030)
        orient = classify_container_orientation(xs_h, ys_h)
        candidates.append(
            {"label": f"live_r2_horiz_u{int(round(u_h))}", "area": "pallet", "col": 2, "row": 2, "tier": 1, "u_px": round(u_h, 1), "v_px": round(v_h, 1), "x": hx, "y": hy, "z": 0.0064, "yaw_deg": float(orient.get("long_axis_deg", 179.0)), "isolated": True}
        )

    def _cand_prio(d: dict[str, Any]) -> tuple[int, float]:
        u = float(d["u_px"])
        if d["area"] == "belt":
            return (0, u)
        if d["area"] == "pallet" and d["row"] == 2:
            return (1, u)
        if d["area"] == "pallet" and d["row"] == 1 and bool(d.get("isolated")):
            return (2, u)
        return (3, u)

    candidates.sort(key=_cand_prio)
    return candidates
