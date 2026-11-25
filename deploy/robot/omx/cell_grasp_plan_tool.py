#!/usr/bin/env python3
"""Pre-grasp feasibility & planning tool (max jaw cm, angle budget deg, dual-twin IK, clearance cm)."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import cell_arm_cal  # noqa: E402
import cell_auto_pick_plan  # noqa: E402
import cell_auto_setup  # noqa: E402
import cell_control_core  # noqa: E402
import cell_envelope  # noqa: E402
from cell_finger_room import finger_room_view, free_mm, jaw_margin  # noqa: E402
import cell_objects  # noqa: E402
from cell_observe import predicted_pixel  # noqa: E402
import cell_params as prm  # noqa: E402
from cell_pick_geom import grasp_depth, surface_z  # noqa: E402
import cell_pivot  # noqa: E402
import grasp_planner  # noqa: E402


def _wrap180(deg: float) -> float:
    return round(((float(deg) + 180.0) % 360.0) - 180.0, 2)


def _wrap_axis(deg: float) -> float:
    """Fold an axial difference (mod 180 deg) into [-90, 90] so perpendicular (90) stays 90."""
    return ((float(deg) + 90.0) % 180.0) - 90.0


def _jaw_to_cm(units: float, held_30mm: float, gap_mm_per_unit: float) -> float:
    return (30.0 + (float(units) - float(held_30mm)) * float(gap_mm_per_unit)) / 10.0


def _cm_to_jaw(cm: float, held_30mm: float, gap_mm_per_unit: float) -> float:
    return float(held_30mm) + (10.0 * float(cm) - 30.0) / float(gap_mm_per_unit)


def _belt_axis_deg(config: dict, cal: dict, dest: str) -> float:
    site = (config.get("sites") or {}).get(dest, {})
    poly, rec, sz = site.get("surface_px"), cell_pivot.map_record(cal, dest), float(site.get("surface_z", 0.0))
    if rec is not None and isinstance(poly, list) and len(poly) >= 3:
        pts = [np.asarray(p, float) for p in poly[:4]]
        left, right = 0.5 * (pts[0] + pts[-1]), 0.5 * (pts[1] + pts[2])
        a = cell_pivot.mark_to_arm(rec, config, dest, (float(left[0]), float(left[1])), sz)
        b = cell_pivot.mark_to_arm(rec, config, dest, (float(right[0]), float(right[1])), sz)
        return round(_wrap_axis(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))), 1)
    return float(site.get("yaw_deg", -90.0))


def _resolve_place_xy(config: dict, cal: dict, dest: str, img=None) -> list[float]:
    site_cfg = (config.get("sites") or {}).get(dest, {})
    place = list(site_cfg.get("place") or [0.0, 0.0])
    rec, poly = cell_pivot.map_record(cal, dest), site_cfg.get("surface_px")
    if rec is not None and isinstance(poly, list) and len(poly) >= 3:
        h, w = (img.shape[:2] if img is not None else (480, 640))
        px, jaws = predicted_pixel(config, cal, dest, place), site_cfg.get("home_jaws_px")
        keep_out = float(site_cfg.get("home_keep_out_px", 30.0))
        near_jaws = jaws is not None and px is not None and math.hypot(px[0] - jaws[0], px[1] - jaws[1]) < keep_out + 20.0
        if px is None or not (20 <= px[0] < w - 20 and 10 <= px[1] < h - 15) or near_jaws:
            xs, ys = [float(p[0]) for p in poly], [float(p[1]) for p in poly]
            tx = min(max(min(xs) + 0.55 * (max(xs) - min(xs)), (float(jaws[0]) + 85.0) if jaws else min(xs) + 40.0), max(xs) - 60.0)
            ty = max(18.0, 0.5 * (min(ys) + max(ys)))
            xy = cell_pivot.mark_to_arm(rec, config, dest, (tx, ty), float(site_cfg.get("surface_z", 0.0)))
            return [round(float(xy[0]), 4), round(float(xy[1]), 4)]
    return [round(float(place[0]), 4), round(float(place[1]), 4)]


def _resolve_gripper(arm_id: str, config: dict, cal_profile: dict | None = None) -> dict[str, Any]:
    params = config.get("params") or {}
    plan = config.get("plan") if isinstance(config.get("plan"), dict) else {}
    tcp = config.get("tcp_x_m") if config.get("tcp_x_m") is not None else plan.get("tcp_x_m")
    cal_p = dict(cal_profile or {})
    if int(cal_p.get("samples", 0)) == 0 and arm_id == "arm_s" and tcp is not None and float(tcp) >= 0.073:
        held_30, gap_u, nom_margin, open_max = 54.3, 5.0, 9.5, 58.15
    else:
        held_30 = float(cal_p.get("held_30mm") or prm.get(params, "gripper.held_30mm", 52.3))
        gap_u = float(cal_p.get("gap_mm_per_unit") or prm.get(params, "gripper.gap_mm_per_unit", 10.4))
        nom_margin = float(cal_p.get("jaw_margin_mm") or prm.get(params, "auto.jaw_margin_mm", 8.0))
        open_max = min(58.15, float(prm.get(params, "gripper.open_max", 56.0)))
    offset = config.get("closing_axis_offset_deg")
    if offset is None:
        offset = prm.get(params, "gripper.closing_axis_offset_deg", prm.get(params, "auto.closing_theory_deg", 90.0))
    return {
        "tcp_x_m": float(tcp) if tcp is not None else None,
        "held_30mm": held_30, "gap_mm_per_unit": gap_u, "open_max_units": open_max,
        "grip_closed_units": float(cal_p.get("grip_closed") or plan.get("grip_closed") or prm.get(params, "gripper.closed", 48.8)),
        "closing_axis_offset_deg": float(offset) if offset is not None else None,
        "nominal_margin_cm": nom_margin / 10.0,
        "min_margin_cm": float(prm.get(params, "auto.min_jaw_margin_mm", 2.0)) / 10.0,
        "max_margin_cm": float(prm.get(params, "auto.jaw_margin_max_mm", 16.0)) / 10.0,
    }


def _solve_twins(planner: grasp_planner.Planner, x: float, y: float, z: float, cands_deg: list[float], ref_q5: float, standoff_m: float = 0.02):
    q5_lo, q5_hi = planner.limits.position_limits.get("joint5", (-math.pi, math.pi))
    best, last_reason = None, "ik_unreachable"
    for cand in cands_deg:
        ydeg = _wrap180(cand)
        res = planner.kin.solve_top_down(planner.TopDownPose(x, y, z, math.radians(ydeg)), planner.limits_at(x, y), reference_q5=ref_q5)
        if not res.ok:
            last_reason = "wrist_roll_out_of_range" if "joint5" in str(res.detail) or "yaw" in str(res.reason).lower() else "ik_unreachable"
            continue
        solved_yaw = _wrap180(math.degrees(res.yaw))
        rm_target, rm_hover = planner.reach_margin(x, y, z, solved_yaw), planner.reach_margin(x, y, z + standoff_m, solved_yaw)
        hover_res = planner.kin.solve_top_down(planner.TopDownPose(x, y, z + standoff_m, res.yaw), planner.limits_at(x, y), reference_q5=res.joints[4])
        if rm_target < grasp_planner.REACH_MARGIN_M or rm_hover < grasp_planner.REACH_MARGIN_M or not hover_res.ok:
            last_reason = "reach_out_of_limit" if rm_hover < grasp_planner.REACH_MARGIN_M else "ik_unreachable"
            continue
        q5 = float(res.joints[4])
        margin_deg = round(math.degrees(min(q5 - q5_lo, q5_hi - q5)), 2)
        if margin_deg < 0.0:
            last_reason = "wrist_roll_out_of_range"
            continue
        row = {
            "yaw_deg": solved_yaw, "joints_rad": list(res.joints), "q5_deg": round(math.degrees(q5), 2),
            "q5_margin_deg": margin_deg, "reach_margin_cm": round(min(rm_target, rm_hover) * 100.0, 2),
        }
        if best is None or (margin_deg > best["q5_margin_deg"] + 1e-6) or (abs(margin_deg - best["q5_margin_deg"]) < 1e-6 and abs(q5 - ref_q5) < abs(best["joints_rad"][4] - ref_q5)):
            best = row
    return best, (None if best is not None else last_reason)


def evaluate_grasp_feasibility(
    *, arm_id: str, object_spec: dict[str, Any], pick: dict[str, Any], gripper: dict[str, Any],
    plan: dict[str, Any], place: dict[str, Any] | None = None, operating_conditions: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate max jaw cm, angle tolerance deg, workspace/reach/pan, dual-twin IK, and payload."""
    refusals: list[str] = []
    warnings: list[str] = []
    offset = gripper.get("closing_axis_offset_deg")
    if offset is None:
        refusals.append("closing_offset_unmeasured")
        offset = 90.0

    w_cm, l_cm = float(object_spec.get("width_cm") or 3.0), float(object_spec.get("length_cm") or 6.0)
    long_deg = float(object_spec.get("long_axis_deg") or 0.0)
    jaw_from_long = float(object_spec.get("jaw_axis_deg_from_long", 90.0))
    angle_err_deg = abs(float(pick.get("angle_err_deg") or 0.0))
    ideal_yaw = _wrap180(long_deg + jaw_from_long - float(offset))
    yaw_ov = pick.get("yaw_override_deg")
    if yaw_ov is not None:
        theta_deg = abs(_wrap_axis((float(yaw_ov) + float(offset)) - (long_deg + jaw_from_long))) + angle_err_deg
        pick_cands = [float(yaw_ov)]
    else:
        theta_deg = angle_err_deg
        pick_cands = [ideal_yaw, _wrap180(ideal_yaw + 180.0)]

    held_30, gap_u, open_max = float(gripper["held_30mm"]), float(gripper["gap_mm_per_unit"]), float(gripper["open_max_units"])
    min_m, nom_m, max_m = float(gripper["min_margin_cm"]), float(gripper["nominal_margin_cm"]), float(gripper["max_margin_cm"])
    max_open_cm = round(_jaw_to_cm(open_max, held_30, gap_u), 3)
    base_w, base_l = (w_cm, l_cm) if round(jaw_from_long) % 180 != 0 else (l_cm, w_cm)
    span_cm = round(base_w * abs(math.cos(math.radians(theta_deg))) + base_l * abs(math.sin(math.radians(theta_deg))), 3)
    min_req_cm = round(span_cm + 2.0 * min_m, 3)
    min_hold_cm = round(max(1.0, _jaw_to_cm(float(gripper["grip_closed_units"]) + 2.0, held_30, gap_u)), 3)
    if min_req_cm > max_open_cm or base_w < min_hold_cm:
        refusals.append(f"jaw_span_exceeds_max: need {min_req_cm:.2f}cm > max {max_open_cm:.2f}cm (span {span_cm:.2f}cm, theta {theta_deg:.1f}deg)")
    eff_margin_cm = round(min(nom_m, max_m, max(0.0, (max_open_cm - span_cm) / 2.0)), 3)
    grip_open_u = round(max(held_30 + 0.5, _cm_to_jaw(span_cm + 2.0 * eff_margin_cm, held_30, gap_u)), 2)
    diag = math.hypot(base_w, base_l)
    max_err_rad = math.asin(min(1.0, max(0.0, max_open_cm - 2.0 * min_m) / max(diag, 1e-6))) - math.atan2(base_w, base_l)
    max_angle_err_deg = round(max(0.0, math.degrees(max_err_rad)), 2)

    raw_xy, bias_mm = pick["raw_xy_m"], pick.get("bias_mm") or [0.0, 0.0]
    px = round(float(raw_xy[0]) - float(bias_mm[0]) / 1000.0, 4)
    py = round(float(raw_xy[1]) - float(bias_mm[1]) / 1000.0, 4)
    pz = round(float(pick["z_m"]), 4)
    if pick.get("surface_z_m") is not None and pz < float(pick["surface_z_m"]) + 0.005:
        refusals.append(f"depth_below_surface: z={pz:.4f} < surface+0.005")

    lim = (plan.get("limits") or {})
    x_lo, x_hi, y_lim = cell_control_core.arm_workspace_xy_bounds(arm_id)
    if not (x_lo <= px <= x_hi and abs(py) <= y_lim):
        refusals.append(f"workspace_out_of_bounds: pick ({px:.4f},{py:.4f}) outside x=[{x_lo},{x_hi}], |y|<={y_lim}")
    park_reach_m, pick_reach_m = float(lim.get("park_reach_m", 0.20)), math.hypot(px, py)
    if pick_reach_m > park_reach_m + 1e-9:
        refusals.append(f"reach_out_of_limit: pick {pick_reach_m*100:.2f}cm > park {park_reach_m*100:.1f}cm")
    pan_lim = (lim.get("joints_rad") or {}).get("joint1")
    if pan_lim and not (pan_lim[0] <= math.atan2(py, px) <= pan_lim[1]):
        refusals.append("pan_out_of_limit: pick")

    eff_plan = {**plan, **({"tcp_x_m": float(gripper["tcp_x_m"])} if gripper.get("tcp_x_m") is not None else {})}
    planner = grasp_planner.Planner(eff_plan) if isinstance(eff_plan.get("limits"), dict) and "joints_rad" in eff_plan["limits"] else None
    pick_ik, pick_err = _solve_twins(planner, px, py, pz, pick_cands, 0.0) if planner else (None, None)
    if planner is None:
        warnings.append("ik_plan_limits_missing")
    elif pick_err:
        refusals.append(f"{pick_err}: pick ({px:.3f},{py:.3f},{pz:.3f})")
    chosen_pick_yaw, pick_q5_rad = (pick_ik["yaw_deg"], pick_ik["joints_rad"][4]) if pick_ik else (pick_cands[0], 0.0)
    if pick_ik and pick_ik["q5_margin_deg"] < 15.0:
        warnings.append(f"pick_q5_near_limit: {pick_ik['q5_margin_deg']}deg")

    place_ik, chosen_place_yaw, place_reach_m = None, float(place.get("dest_long_axis_deg", -90.0)) if place else -90.0, 0.0
    if place is not None:
        qx, qy, qz = round(float(place["xy_m"][0]), 4), round(float(place["xy_m"][1]), 4), round(float(place["z_m"]), 4)
        place_reach_m = math.hypot(qx, qy)
        if not (x_lo <= qx <= x_hi and abs(qy) <= y_lim):
            refusals.append(f"workspace_out_of_bounds: place ({qx:.4f},{qy:.4f})")
        if place_reach_m > park_reach_m + 1e-9:
            refusals.append(f"reach_out_of_limit: place {place_reach_m*100:.2f}cm > park {park_reach_m*100:.1f}cm")
        if place.get("corridor_width_cm") is not None and w_cm > float(place["corridor_width_cm"]):
            refusals.append("corridor_width_exceeded")
        ideal_place = _wrap180(float(place.get("dest_long_axis_deg", -90.0)) - (long_deg - chosen_pick_yaw))
        p_cands = [float(place["yaw_override_deg"])] if place.get("yaw_override_deg") is not None else [ideal_place, _wrap180(ideal_place + 180.0)]
        if planner is not None:
            place_ik, place_err = _solve_twins(planner, qx, qy, qz, p_cands, pick_q5_rad)
            if place_err:
                refusals.append(f"{place_err}: place ({qx:.3f},{qy:.3f},{qz:.3f})")
        chosen_place_yaw = place_ik["yaw_deg"] if place_ik else p_cands[0]

    pay_kg, pay_bound_kg, max_gross = object_spec.get("kg"), None, float(prm.get(params, "auto.max_gross_kg", 0.08))
    if isinstance(operating_conditions, dict) and "payload_max_kg" in operating_conditions:
        pc_cfg = {"params": {"auto.max_gross_kg": max_gross}, "_payload": {"kg": pay_kg, "source": object_spec.get("payload_source") or "catalog", "object": object_spec.get("object_id")}}
        facts, pay_err = cell_envelope.payload_check(pc_cfg, operating_conditions)
        if pay_err:
            refusals.append(pay_err)
        elif facts:
            pay_bound_kg = facts.get("bound_kg")
    elif pay_kg is not None and float(pay_kg) > max_gross:
        refusals.append(f"payload_over_limit: {float(pay_kg):.3f}kg > {max_gross:.3f}kg")
    elif object_spec.get("require_payload") and pay_kg is None:
        refusals.append("payload_unknown")

    metrics = {
        "max_jaw_open_cm": max_open_cm, "projected_span_cm": span_cm, "required_open_cm": min_req_cm, "effective_margin_cm": eff_margin_cm,
        "grip_open_units": grip_open_u, "max_angle_err_deg": max_angle_err_deg, "closing_axis_offset_deg": float(offset),
        "closing_axis_deg": _wrap180(chosen_pick_yaw + float(offset)), "pick_yaw_deg": chosen_pick_yaw, "place_yaw_deg": chosen_place_yaw,
        "pick_q5_deg": pick_ik["q5_deg"] if pick_ik else None, "pick_q5_margin_deg": pick_ik["q5_margin_deg"] if pick_ik else None,
        "place_q5_deg": place_ik["q5_deg"] if place_ik else None, "place_q5_margin_deg": place_ik["q5_margin_deg"] if place_ik else None,
        "delta_q5_deg": round(abs(place_ik["q5_deg"] - pick_ik["q5_deg"]), 2) if (pick_ik and place_ik) else None,
        "pick_reach_cm": round(pick_reach_m * 100.0, 2), "place_reach_cm": round(place_reach_m * 100.0, 2), "park_reach_cm": round(park_reach_m * 100.0, 2),
        "clearance_cm": None, "wall_shift_cm": 0.0, "payload_kg": pay_kg, "payload_bound_kg": pay_bound_kg,
    }
    place_xyz = [round(float(place["xy_m"][0]), 4), round(float(place["xy_m"][1]), 4), round(float(place["z_m"]), 4)] if place else None
    return {"feasible": not refusals, "refusal_reasons": refusals, "warnings": warnings, "metrics": metrics, "pick_xyz_m": [px, py, pz], "place_xyz_m": place_xyz}


def _check_clearance_and_shift(img, mask, config: dict, cal: dict, site: str, roi, o: dict, entry: dict, closing_deg: float, span_cm: float):
    view = finger_room_view(img, config, site, roi, mask=mask)
    if view is None:
        return [None, None], 0.0, False, o
    rmask, rroi = view
    px_fn = lambda pt: predicted_pixel(config, cal, site, pt)  # noqa: E731
    room = jaw_margin(rmask, rroi, px_fn, o, closing_deg, config.get("params"), opening_width_mm=span_cm * 10.0)
    free_cm = [round(v / 10.0, 2) for v in room["free_mm"]]
    u = math.radians(float(o["long_axis_deg"]))
    dir_long = np.array([math.cos(u), math.sin(u)])
    half_len_mm = float(o.get("length_mm", entry.get("length_mm", 60.0))) / 2.0
    end_free = [free_mm(rmask, rroi, px_fn, np.asarray(o["raw_m"]) + s * (half_len_mm / 1000.0) * dir_long, s * dir_long, (-6.0, 0.0, 6.0), 30.0, own_mm=4.0) for s in (-1.0, 1.0)]
    shift_cm, best_o, max_shift = 0.0, o, min(1.2, max(0.0, half_len_mm / 10.0 - 1.5))
    if max_shift >= 0.4 and min(end_free) < 15.0 and max(end_free) >= 22.0:
        sign = 1.0 if end_free[1] > end_free[0] else -1.0
        cand_o = {**o, "raw_m": [o["raw_m"][0] + sign * (max_shift / 100.0) * dir_long[0], o["raw_m"][1] + sign * (max_shift / 100.0) * dir_long[1]]}
        cand_room = jaw_margin(rmask, rroi, px_fn, cand_o, closing_deg, config.get("params"), opening_width_mm=span_cm * 10.0)
        if cand_room["margin_mm"] is not None or min(cand_room["free_mm"]) >= min(room["free_mm"]):
            best_o, room, shift_cm = cand_o, cand_room, round(sign * max_shift, 2)
            free_cm = [round(v / 10.0, 2) for v in room["free_mm"]]
    return free_cm, shift_cm, (room["margin_mm"] is None and not room.get("unseen")), best_o


def check_area_pick_feasibility(
    *, arm_id: str, config: dict, catalog: list[dict[str, Any]], object_id: str,
    pick_xyz: list[float], pick_yaw_deg: float, place_xyz: list[float], place_yaw_deg: float,
) -> dict[str, Any]:
    """Validate explicit `area_xyz_pick` arguments against physical jaw cm, angle, IK, and payload limits."""
    from cell_area_zones import normalize_pick_yaw_deg

    entry = next((e for e in catalog if e.get("id") == object_id), None)
    if entry is None:
        return {"feasible": False, "refusal_reasons": [f"unknown_object: {object_id}"], "warnings": [], "metrics": {}}
    work_dir = Path(str(config.get("work_dir", "."))).expanduser()
    grip = _resolve_gripper(arm_id, config, cell_arm_cal.load(work_dir, arm_id) if work_dir.is_dir() else {})
    pay = cell_objects.payload(catalog, object_id) or {}
    plan = config.get("plan") or {}
    q5_lim = [0.16, 2.89] if arm_id == "arm_b" else (plan.get("limits") or {}).get("joints_rad", {}).get("joint5")
    q5_bounds = tuple(q5_lim) if isinstance(q5_lim, (list, tuple)) and len(q5_lim) == 2 else None
    eff_yaw = normalize_pick_yaw_deg(float(pick_yaw_deg), pick_xyz[0], pick_xyz[1], q5_bounds_rad=q5_bounds)
    jaw_from = float((entry.get("grasp") or {}).get("jaw_axis_deg_from_long", 90.0))
    offset = float(grip["closing_axis_offset_deg"] or 90.0)
    obj_spec = {
        "object_id": object_id, "width_cm": float(entry["width_mm"]) / 10.0, "length_cm": float(entry["length_mm"]) / 10.0,
        "height_cm": float(entry.get("top_height_mm", 30.0)) / 10.0,
        "long_axis_deg": _wrap180(eff_yaw + offset - jaw_from), "jaw_axis_deg_from_long": jaw_from,
        "kg": pay.get("kg"), "payload_source": pay.get("source"), "require_payload": True,
    }
    return evaluate_grasp_feasibility(
        arm_id=arm_id, object_spec=obj_spec,
        pick={"raw_xy_m": pick_xyz[:2], "bias_mm": [0.0, 0.0], "z_m": pick_xyz[2], "yaw_override_deg": eff_yaw, "angle_err_deg": 0.0},
        gripper=grip, plan=plan,
        place={"xy_m": place_xyz[:2], "z_m": place_xyz[2], "dest_long_axis_deg": float(place_yaw_deg), "yaw_override_deg": place_yaw_deg},
        operating_conditions=config.get("operating_conditions"), params=config.get("params"),
    )


def plan_site_grasp(
    *, arm_id: str, config: dict, config_name: str, catalog: list[dict[str, Any]], catalog_name: str,
    cal: dict, source: str, dest: str, roi=None, object_id: str | None = None, colour: str | None = None,
    image=None, bias_data: dict | None = None, obb_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Observe source topview (or explicit OBB) -> compute optimal short-axis grasp & `area_xyz_pick` payload."""
    site_cfg = (config.get("sites") or {})[source]
    eff_roi = list(roi or site_cfg.get("detect_roi") or site_cfg.get("auto_roi") or [0, 0, 640, 480])
    img, mask = image, None
    if obb_override is not None:
        objs = [obb_override]
    else:
        import urllib.request, cv2

        if img is None:
            with urllib.request.urlopen((config.get("cameras") or {}).get("top", {}).get("url"), timeout=3.0) as r:
                img = cv2.imdecode(np.frombuffer(r.read(), np.uint8), cv2.IMREAD_COLOR)
        _, mask, objs, err = cell_auto_pick_plan.observe(None, config, cal, source, eff_roi, catalog, image=img)
        if err:
            return {"feasible": False, "refusal_reasons": [err], "warnings": [], "metrics": {}}
    wanted = [o for o in objs if o.get("matched") and (not object_id or o.get("object") == object_id) and (not colour or o.get("colour") == colour)]
    if not wanted:
        return {"feasible": False, "refusal_reasons": ["no_matching_object"], "warnings": [], "metrics": {}}
    o = wanted[0]
    entry = next((e for e in catalog if e.get("id") == o.get("object")), None) or catalog[0]
    cal_prof = cell_arm_cal.load(Path(str(config.get("work_dir", "."))).expanduser(), arm_id) if config.get("work_dir") else {}
    grip, pay = _resolve_gripper(arm_id, config, cal_prof), (cell_objects.payload(catalog, entry["id"]) or {})
    obj_spec = {
        "object_id": entry["id"], "width_cm": float(o.get("width_mm", entry["width_mm"])) / 10.0,
        "length_cm": float(o.get("length_mm", entry["length_mm"])) / 10.0, "height_cm": float(entry.get("top_height_mm", 30.0)) / 10.0,
        "long_axis_deg": float(o["long_axis_deg"]), "jaw_axis_deg_from_long": float((entry.get("grasp") or {}).get("jaw_axis_deg_from_long", 90.0)),
        "kg": pay.get("kg"), "payload_source": pay.get("source"), "require_payload": True,
    }
    o_work = {**o, "raw_m": o.get("raw_m") or [c / 1000.0 for c in o["centre_mm"]]}
    c_off = float(grip["closing_axis_offset_deg"] or 90.0)
    prelim_yaw = _wrap180(float(o["long_axis_deg"]) + obj_spec["jaw_axis_deg_from_long"] - c_off)
    free_cm, shift_cm, clear_bad, o_work = ([None, None], 0.0, False, o_work) if img is None else _check_clearance_and_shift(
        img, mask, config, cal, source, eff_roi, o_work, entry, prelim_yaw + c_off, float(entry["width_mm"]) / 10.0)
    reg = cell_pivot.bias_at(bias_data or {}, source, o_work["raw_m"], params=config.get("params")) if bias_data else None
    bias_mm = list(reg["bias_mm"]) if reg and "bias_mm" in reg else [0.0, 0.0]
    pick_z = round(surface_z(config, source) + entry["top_height_mm"] / 1000.0 - grasp_depth(config, source), 4)
    dest_cfg, place_xy = (config.get("sites") or {}).get(dest, {}), _resolve_place_xy(config, cal, dest, img=img)
    place_z = round(surface_z(config, dest) + entry["top_height_mm"] / 1000.0 - grasp_depth(config, dest) + float(dest_cfg.get("place_dz", 0.0)), 4)
    out = evaluate_grasp_feasibility(
        arm_id=arm_id, object_spec=obj_spec,
        pick={"raw_xy_m": o_work["raw_m"], "bias_mm": bias_mm, "z_m": pick_z, "surface_z_m": surface_z(config, source), "angle_err_deg": 5.0},
        gripper=grip, plan=config["plan"],
        place={"xy_m": place_xy, "z_m": place_z, "dest_long_axis_deg": _belt_axis_deg(config, cal, dest), "corridor_width_cm": 8.5 if dest == "belt" else None},
        operating_conditions=config.get("operating_conditions"), params=config.get("params"))
    out["metrics"]["clearance_cm"], out["metrics"]["wall_shift_cm"] = free_cm, shift_cm
    if clear_bad:
        out["feasible"] = False
        out["refusal_reasons"].append(f"clearance_insufficient: {free_cm}")
    if out["feasible"]:
        out["ready_job_body"] = {
            "arm": arm_id, "config": config_name, "catalog": catalog_name, "object": entry["id"],
            "pick_area": source, "pick_x": out["pick_xyz_m"][0], "pick_y": out["pick_xyz_m"][1], "pick_z": out["pick_xyz_m"][2],
            "pick_yaw_deg": out["metrics"]["pick_yaw_deg"], "place_area": dest, "place_x": out["place_xyz_m"][0],
            "place_y": out["place_xyz_m"][1], "place_z": out["place_xyz_m"][2], "place_yaw_deg": out["metrics"]["place_yaw_deg"],
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pre-grasp feasibility planner (max angle deg & jaw cm)")
    for k, req in (("--arm", True), ("--config", True), ("--catalog", True), ("--dest", True), ("--object", False), ("--colour", False)):
        ap.add_argument(k, required=req, choices=("arm_s", "arm_a", "arm_b") if k == "--arm" else None)
    ap.add_argument("--from", dest="source", required=True)
    ap.add_argument("--roi", nargs=4, type=int, default=None)
    for k in ("--image", "--obb-json", "--out"):
        ap.add_argument(k, type=Path, default=None)
    args = ap.parse_args(argv)
    config = cell_auto_setup.load_config(Path(args.config))
    cal_p = Path(config["calibration_path"]).expanduser()
    cal, bp = json.loads(cal_p.read_text(encoding="utf-8")), cell_pivot.bias_path(cal_p)
    bias, catalog = (cell_pivot.load_bias(bp, config.get("params")) if bp.is_file() else {}), cell_objects.load_catalog(Path(args.catalog))
    img = __import__("cv2").imread(str(args.image)) if args.image is not None else None
    obb = json.loads(args.obb_json.read_text(encoding="utf-8")) if args.obb_json is not None else None
    res = plan_site_grasp(arm_id=args.arm, config=config, config_name=Path(args.config).name, catalog=catalog, catalog_name=Path(args.catalog).name,
                          cal=cal, source=args.source, dest=args.dest, roi=args.roi, object_id=args.object, colour=args.colour, image=img, bias_data=bias, obb_override=obb)
    txt = json.dumps(res, indent=1)
    if args.out is not None:
        p = args.out if args.out.is_absolute() else Path(str(config.get("work_dir", "."))).expanduser() / args.out
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt + "\n", encoding="utf-8")
    print(txt)
    return 0 if res.get("feasible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
