#!/usr/bin/env python3
"""Compile a verified 7-stage factory run (or extended 9-stage Fleet twin) into a Rosy World replay timeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from factory_flow_receipts import STAGES, verify  # noqa: E402
import omx_two_arm_kin as kin  # noqa: E402

SCHEMA = "rosy.world.factory-timeline.v1"
STAGE_META = (
    ("c2_departure", "1. C2 출발", "gazebo"),
    ("s1_yield", "2. S1 양보", "gazebo"),
    ("s3_stop", "3. S3 정차", "gazebo"),
    ("cell_claim", "4. 셀 점유", "gazebo"),
    ("arm_s_to_belt", "5. 암 S→벨트", "isaac"),
    ("belt_transit", "6. 벨트 이송", "isaac"),
    ("ab_stack", "7. A/B 적재", "mujoco"),
)
EXTENDED_META = STAGE_META + (
    ("ab_rehandle", "8. A↔B 임시대 정리", "mujoco"),
    ("outbound_dispatch", "9. 반출대 접안·출발", "mujoco"),
)

# Real rear J-v3 cargo tray sits behind wheel axle at x_local = -0.095 m, floor z = 0.044 m (container height 32.4 mm -> center z = 0.060 m).
TRAY_REAR_OFFSET_M = 0.095
TRAY_Z_SITE = 0.060
GRIP_OPEN_RAD = 0.72
GRIP_HOLD_RAD = 0.14

BELT_ENTRY_CELL = (0.350, -0.003, 0.0332)
BELT_PICK_CELL = (0.205, -0.003, 0.0332)
ARM_A_BASE_CELL = (0.077, -0.16675, 0.084)
ARM_B_BASE_CELL = (0.077, 0.16975, 0.084)
ARM_S_BASE_SITE = (0.975, -0.004, 0.072)
HOLD1_CENTER_X_CELL = 0.0484
ROW_Y_CELL = {0: -0.0365, 1: 0.0015, 2: 0.0395}
SLOT_RE = re.compile(r"ship-h(?P<hold>\d+)r(?P<row>[0-2])-l(?P<layer>[0-2])$")
TMP_SITES_CELL = {
    "tmp-a-1": (-0.1264, -0.2299, 0.090, 17.6),
    "tmp-a-2": (-0.1357, -0.1711, 0.090, 0.4),
    "tmp-a-3": (-0.1273, -0.1121, 0.090, -16.8),
    "tmp-b-1": (-0.1116, 0.1268, 0.090, 14.6),
    "tmp-b-2": (-0.1179, 0.1860, 0.090, -2.6),
    "tmp-b-3": (-0.1064, 0.2445, 0.090, -19.8),
}
STAND_CHUTE_CELL = (0.214, -0.166, 0.088)
OUTBOUND_DOCK_SITE = [0.627, -0.010, -math.pi / 2]

HOME_Q = [0.0, -0.82, 0.78, 0.65, 1.5708, GRIP_OPEN_RAD]
WAIT_SIDE_A_Q = [-0.62, -0.78, 0.72, 0.72, 1.5708, GRIP_OPEN_RAD]
WAIT_SIDE_B_Q = [0.62, -0.78, 0.72, 0.72, 1.5708, GRIP_OPEN_RAD]
WAIT_S_Q = [0.18, -0.78, 0.74, 0.72, 1.5708, GRIP_OPEN_RAD]


def _cell_to_site(xyz: tuple[float, float, float] | list[float], reg: dict[str, Any]) -> list[float]:
    yaw = float(reg["yaw_rad"])
    tx, ty, tz = (float(v) for v in reg["translation_m"])
    cx, cy, cz = float(xyz[0]), float(xyz[1]), float(xyz[2])
    c, s = math.cos(yaw), math.sin(yaw)
    return [round(tx + cx * c - cy * s, 5), round(ty + cx * s + cy * c, 5), round(tz + cz, 5)]


def _parse_site_native(ev: dict[str, Any]) -> dict[str, Any]:
    if isinstance(ev.get("trace"), list):
        return ev
    for line in str(ev.get("stdout", "")).splitlines():
        if line.startswith("SITE_NATIVE "):
            return json.loads(line.split(" ", 1)[1])
    raise ValueError("belt_transit evidence lacks SITE_NATIVE trace payload")


def _polyline_chain(edges: dict[str, dict[str, Any]], edge_ids: list[str], start_xy: tuple[float, float]) -> list[list[float]]:
    pts: list[list[float]] = []
    cur = start_xy
    for eid in edge_ids:
        edge = edges.get(eid)
        if not edge or not edge.get("polyline"):
            raise ValueError(f"missing site-map edge {eid!r}")
        poly = [[float(p[0]), float(p[1])] for p in edge["polyline"]]
        if math.hypot(poly[-1][0] - cur[0], poly[-1][1] - cur[1]) < math.hypot(poly[0][0] - cur[0], poly[0][1] - cur[1]):
            poly.reverse()
        if pts and math.hypot(poly[0][0] - pts[-1][0], poly[0][1] - pts[-1][1]) < 1e-4:
            poly = poly[1:]
        pts.extend(poly)
        cur = (pts[-1][0], pts[-1][1])
    return pts


def _resample_path(pts: list[list[float]], count: int) -> list[tuple[float, float, float]]:
    segs = [math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(len(pts) - 1)]
    total = sum(segs) or 1e-6
    out: list[tuple[float, float, float]] = []
    for k in range(count):
        target = total * k / max(1, count - 1)
        acc = 0.0
        for i, seg in enumerate(segs):
            if acc + seg >= target or i == len(segs) - 1:
                u = 0.0 if seg <= 1e-9 else max(0.0, min(1.0, (target - acc) / seg))
                x = pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u
                y = pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u
                yaw = math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0])
                out.append((round(x, 5), round(y, 5), round(yaw, 5)))
                break
            acc += seg
    return out


def _slot_site_xyz(target: str, reg: dict[str, Any]) -> list[float]:
    m = SLOT_RE.match(target)
    if m:
        hold_offset = 0.098 * (int(m.group("hold")) - 1)
        row, layer = int(m.group("row")), int(m.group("layer"))
        cz = 0.072 + 0.006 + 0.0324 * (layer + 0.5)
        return _cell_to_site((HOLD1_CENTER_X_CELL - hold_offset, ROW_Y_CELL[row], cz), reg)
    if target in TMP_SITES_CELL:
        cx, cy, cz, _yaw_deg = TMP_SITES_CELL[target]
        return _cell_to_site((cx, cy, cz), reg)
    raise ValueError(f"unsupported target site {target!r}")


def _slot_site_yaw(target: str, reg: dict[str, Any]) -> float:
    cell_yaw = float(reg["yaw_rad"])
    if target in TMP_SITES_CELL:
        return round(cell_yaw + math.radians(TMP_SITES_CELL[target][3]), 5)
    return round(cell_yaw, 5)


def _s3_in_bounds(xy_yaw: list[float], s3_box: dict[str, Any]) -> bool:
    cx, cy = s3_box["center"]
    cyaw = float(s3_box["yaw_rad"])
    dx, dy = xy_yaw[0] - cx, xy_yaw[1] - cy
    lon = abs(dx * math.cos(cyaw) + dy * math.sin(cyaw))
    lat = abs(-dx * math.sin(cyaw) + dy * math.cos(cyaw))
    dyaw = abs(math.remainder(xy_yaw[2] - cyaw, math.tau))
    return lon <= s3_box["longitudinal_m"] and lat <= s3_box["lateral_m"] and dyaw <= s3_box["heading_rad"]


def _solve_arm_q(arm: kin.Arm, prev_q: list[float], tip_xyz: list[float], yaw: float, grip: float) -> list[float]:
    best_q, best_cost = None, 1e9
    for candidate_yaw in (yaw, yaw + math.pi):
        q, pe, oe = arm.ik(prev_q, tip_xyz, candidate_yaw, iterations=90, tol=2e-4)
        cost = float(pe) * 100.0 + float(oe) * 2.0
        if cost < best_cost:
            best_cost = cost
            best_q = [round(float(v), 4) for v in q[:5]] + [round(float(grip), 4)]
    return best_q if best_q is not None else list(prev_q)


def compile_timeline(
    closed_dir: Path, site_map_path: Path, registration_path: Path, *, include_extended: bool = False,
) -> dict[str, Any]:
    receipts_path = closed_dir / "receipts.json"
    errors, _summary = verify(receipts_path)
    if errors:
        raise ValueError("unverified closed run: " + "; ".join(errors[:3]))

    receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
    by_stage = {r["stage"]: closed_dir / r["evidence"][0]["path"] for r in receipts}
    ev = {stage: json.loads(path.read_text(encoding="utf-8")) for stage, path in by_stage.items()}

    site_map = json.loads(site_map_path.read_text(encoding="utf-8"))["map"]
    places = {p["id"]: p for p in site_map.get("places", [])}
    edges = {e["id"]: e for e in site_map.get("edges", [])}
    reg_raw = json.loads(registration_path.read_text(encoding="utf-8"))
    reg = reg_raw["site_from_cell"]
    cell_yaw = round(float(reg["yaw_rad"]), 5)

    s3_place = places.get("S3", {})
    lim = s3_place.get("precision_stop") or {}
    s3_box = {
        "center": [float(s3_place.get("x", 0.745)), float(s3_place.get("y", -0.207))],
        "yaw_rad": float(lim.get("yaw_rad", math.pi)),
        "longitudinal_m": float(lim.get("longitudinal_m", 0.04)),
        "lateral_m": float(lim.get("lateral_m", 0.025)),
        "heading_rad": float(lim.get("heading_rad", 0.12)),
    }
    s3_sample = list(ev["s3_stop"]["samples"][-1]["pose_xy_yaw"])
    s3_pose = [round(float(s3_sample[0]), 5), round(float(s3_sample[1]), 5), round(float(s3_sample[2]), 5)]
    c1_pose = [float(places.get("C1", {"x": -0.414})["x"]), float(places.get("C1", {"y": 0.47})["y"]), -math.pi / 2]
    c2 = places.get("C2", {"x": -0.1914, "y": 0.47})
    c3 = places.get("C3", {"x": 0.032, "y": 0.47})
    c2_pose = [float(c2["x"]), float(c2["y"]), -math.pi / 2]
    c3_pose = [float(c3["x"]), float(c3["y"]), -math.pi / 2]

    c2_edges = list(ev["c2_departure"]["edges"])
    s1_edges = list(ev["s1_yield"]["route_edges"])
    leg1_pts = _polyline_chain(edges, c2_edges, (c2_pose[0], c2_pose[1]))
    leg2_pts = _polyline_chain(edges, s1_edges, (leg1_pts[-1][0], leg1_pts[-1][1]))
    leg2_pts[-1] = [s3_pose[0], s3_pose[1]]

    belt_entry_site = _cell_to_site(BELT_ENTRY_CELL, reg)
    belt_pick_site = _cell_to_site(BELT_PICK_CELL, reg)
    arm_a_site = _cell_to_site(ARM_A_BASE_CELL, reg)
    arm_b_site = _cell_to_site(ARM_B_BASE_CELL, reg)
    stand_chute_site = _cell_to_site(STAND_CHUTE_CELL, reg)

    arm_kin = {
        "arm_s": kin.Arm("arm_s", ARM_S_BASE_SITE, math.pi),
        "arm_a": kin.Arm("arm_a", arm_a_site, 0.0),
        "arm_b": kin.Arm("arm_b", arm_b_site, math.pi),
    }
    arm_q = {
        "arm_s": list(WAIT_S_Q),
        "arm_a": list(WAIT_SIDE_A_Q),
        "arm_b": list(WAIT_SIDE_B_Q),
    }

    def tray_on_pinky(xy_yaw: tuple[float, float, float] | list[float]) -> list[float]:
        return [
            round(xy_yaw[0] - TRAY_REAR_OFFSET_M * math.cos(xy_yaw[2]), 5),
            round(xy_yaw[1] - TRAY_REAR_OFFSET_M * math.sin(xy_yaw[2]), 5),
            TRAY_Z_SITE,
        ]

    tray_site = tray_on_pinky(s3_pose)

    p42_pose = list(c1_pose)
    p46_pose = list(c3_pose)

    keyframes: list[dict[str, Any]] = []
    stage_windows: list[dict[str, Any]] = []
    t = 0.0

    def push(
        stage: str, sim: str, phase: str, p45_pose: list[float], cargo_zone: str,
        cargo_xyz: list[float], cargo_yaw: float, *, has_cargo_45: bool = True,
        has_cargo_46: bool = False, color_idx: int = 0,
        arm_s_ee: list[float] | None = None, active_arm: str | None = None,
        active_step: str | None = None, stacked: dict[str, dict[str, Any]] | None = None,
        p46_override: list[float] | None = None,
    ) -> None:
        nonlocal p46_pose
        if p46_override is not None:
            p46_pose = list(p46_override)
        in_bounds = _s3_in_bounds(p45_pose, s3_box)
        pinkys = [
            {"id": "rosy_42", "hardware_id": "geg6", "pose_m": [p42_pose[0], p42_pose[1], 0.0],
             "yaw_rad": round(p42_pose[2], 5), "has_cargo": False, "s3_in_bounds": False},
            {"id": "rosy_45", "hardware_id": "y8xs", "pose_m": [p45_pose[0], p45_pose[1], 0.0],
             "yaw_rad": round(p45_pose[2], 5), "has_cargo": has_cargo_45, "s3_in_bounds": in_bounds},
            {"id": "rosy_46", "hardware_id": "b8xy", "pose_m": [p46_pose[0], p46_pose[1], 0.0],
             "yaw_rad": round(p46_pose[2], 5), "has_cargo": has_cargo_46, "s3_in_bounds": False},
        ]
        stacked_list = [dict(v) for v in (stacked or {}).values()]
        keyframes.append({
            "time_s": round(t, 4),
            "stage": stage,
            "simulator": sim,
            "phase": phase,
            "pinky": dict(pinkys[1]),
            "pinkys": pinkys,
            "arms": {k: list(v) for k, v in arm_q.items()},
            "cargo": {
                "zone": cargo_zone,
                "pose_m": list(cargo_xyz),
                "yaw_rad": round(cargo_yaw, 5),
                "color_idx": color_idx,
            },
            "arm_s_ee_m": arm_s_ee,
            "cell_ab": {
                "active_arm": active_arm,
                "active_step": active_step,
                "stacked": stacked_list,
            },
        })

    def emit_arm_move(
        stage: str, sim: str, step_id: str, arm_key: str, cid: str, color_idx: int,
        src_xyz: list[float], src_yaw: float, dst_xyz: list[float], dst_yaw: float,
        duration_s: float, stacked_map: dict[str, dict[str, Any]], *,
        remove_src: bool = True, add_dst: str | None = None,
        p45_pose: list[float] | None = None, p46_path: list[list[float]] | None = None,
    ) -> None:
        nonlocal t
        p45 = p45_pose or s3_pose
        kin_arm = arm_kin[arm_key]
        other_ab = "arm_b" if arm_key == "arm_a" else "arm_a" if arm_key == "arm_b" else None
        if other_ab:
            arm_q[other_ab] = list(WAIT_SIDE_A_Q if other_ab == "arm_a" else WAIT_SIDE_B_Q)

        z_lift = max(src_xyz[2], dst_xyz[2]) + 0.068
        mid_xy = [(src_xyz[0] + dst_xyz[0]) * 0.5, (src_xyz[1] + dst_xyz[1]) * 0.5, z_lift]
        waypoints = [
            ("approach", [src_xyz[0], src_xyz[1], src_xyz[2] + 0.065], src_yaw, GRIP_OPEN_RAD, "away", src_xyz),
            ("grasp", [src_xyz[0], src_xyz[1], src_xyz[2] + 0.014], src_yaw, GRIP_OPEN_RAD, "pick", src_xyz),
            ("close", [src_xyz[0], src_xyz[1], src_xyz[2] + 0.014], src_yaw, GRIP_HOLD_RAD, "hold", src_xyz),
            ("carry", mid_xy, (src_yaw + dst_yaw) * 0.5, GRIP_HOLD_RAD, "hold", [mid_xy[0], mid_xy[1], mid_xy[2] - 0.014]),
            ("lower", [dst_xyz[0], dst_xyz[1], dst_xyz[2] + 0.014], dst_yaw, GRIP_HOLD_RAD, "hold", dst_xyz),
            ("retreat", [dst_xyz[0], dst_xyz[1], dst_xyz[2] + 0.068], dst_yaw, GRIP_OPEN_RAD, "placed", dst_xyz),
        ]
        dt = duration_s / len(waypoints)
        for idx, (wname, tip, wyaw, grip, state_flag, c_xyz) in enumerate(waypoints):
            if state_flag == "hold" and remove_src:
                stacked_map.pop(cid, None)
            if state_flag == "placed" and add_dst is not None:
                stacked_map[cid] = {
                    "id": cid, "target": add_dst, "arm": arm_key,
                    "pose_m": list(dst_xyz), "yaw_rad": dst_yaw, "color_idx": color_idx,
                }
            arm_q[arm_key] = _solve_arm_q(kin_arm, arm_q[arm_key], tip, wyaw, grip)
            t += dt
            p46_now = p46_path[min(idx, len(p46_path) - 1)] if p46_path else None
            cargo_zone = "ship" if state_flag == "placed" else "cell_ab"
            push(
                stage, sim, f"{step_id}:{wname}", p45, cargo_zone, c_xyz,
                wyaw if state_flag == "hold" else (dst_yaw if state_flag == "placed" else src_yaw),
                has_cargo_45=False, color_idx=color_idx, active_arm=arm_key, active_step=step_id,
                stacked=stacked_map, p46_override=p46_now,
            )

    # Stage 1: c2_departure (0 -> 5s)
    t0 = t
    for i, p in enumerate(_resample_path(leg1_pts, 14)):
        if i:
            t += 5.0 / 13.0
        push("c2_departure", "gazebo", "drive_to_s1", list(p), "pinky_tray", tray_on_pinky(p), p[2])
    stage_windows.append({"id": "c2_departure", "label": STAGE_META[0][1], "simulator": "gazebo", "start_s": t0, "end_s": round(t, 4)})

    # Stage 2: s1_yield (5 -> 11s)
    t0 = t
    s1_hold = keyframes[-1]["pinky"]
    hold_pose = [s1_hold["pose_m"][0], s1_hold["pose_m"][1], s1_hold["yaw_rad"]]
    t += 0.8
    push("s1_yield", "gazebo", "s1_gate_granted", hold_pose, "pinky_tray", tray_on_pinky(hold_pose), hold_pose[2])
    loop_pts = _resample_path(leg2_pts, 20)
    for p in loop_pts[1:-1]:
        t += 5.2 / max(1, len(loop_pts) - 2)
        push("s1_yield", "gazebo", "loop_to_s3", list(p), "pinky_tray", tray_on_pinky(p), p[2])
    stage_windows.append({"id": "s1_yield", "label": STAGE_META[1][1], "simulator": "gazebo", "start_s": t0, "end_s": round(t, 4)})

    # Stage 3: s3_stop (11 -> 14s)
    t0 = t
    pre_p = list(loop_pts[-2])
    t += 1.2
    push("s3_stop", "gazebo", "precision_align", pre_p, "pinky_tray", tray_on_pinky(pre_p), pre_p[2])
    t += 1.8
    push("s3_stop", "gazebo", "s3_settled", s3_pose, "pinky_tray", tray_site, s3_pose[2])
    stage_windows.append({"id": "s3_stop", "label": STAGE_META[2][1], "simulator": "gazebo", "start_s": t0, "end_s": round(t, 4)})

    # Stage 4: cell_claim (14 -> 15.5s)
    t0 = t
    t += 1.5
    push("cell_claim", "gazebo", "cell_claimed", s3_pose, "pinky_tray", tray_site, s3_pose[2])
    stage_windows.append({"id": "cell_claim", "label": STAGE_META[3][1], "simulator": "gazebo", "start_s": t0, "end_s": round(t, 4)})

    # Stage 5: arm_s_to_belt (15.5 -> 20.5s) — real 6-DOF IK of arm_s following Isaac tray->belt trajectory
    t0 = t
    arm_samples = ev["arm_s_to_belt"]["samples"]
    fx_tray = list(arm_samples[0]["box_position"])
    fx_belt = list(arm_samples[-1]["box_position"])
    dx_span = (fx_belt[0] - fx_tray[0]) or 1e-6
    dy_span = (fx_belt[1] - fx_tray[1]) or 1e-6
    stride = max(1, len(arm_samples) // 16)
    picked = arm_samples[::stride]
    if picked[-1] is not arm_samples[-1]:
        picked.append(arm_samples[-1])
    for idx, sample in enumerate(picked):
        bp = sample["box_position"]
        ux = max(-0.2, min(1.2, (bp[0] - fx_tray[0]) / dx_span))
        uy = max(-0.2, min(1.2, (bp[1] - fx_tray[1]) / dy_span))
        lift = max(0.0, bp[2] - fx_tray[2])
        c_xyz = [
            round(tray_site[0] + (belt_entry_site[0] - tray_site[0]) * ux, 5),
            round(tray_site[1] + (belt_entry_site[1] - tray_site[1]) * uy, 5),
            round(tray_site[2] + (belt_entry_site[2] - tray_site[2]) * ((ux + uy) * 0.5) + lift * 0.85, 5),
        ]
        tip_xyz = [c_xyz[0], c_xyz[1], round(c_xyz[2] + 0.016, 5)]
        grip = GRIP_OPEN_RAD if idx == 0 or idx >= len(picked) - 1 else GRIP_HOLD_RAD
        arm_q["arm_s"] = _solve_arm_q(arm_kin["arm_s"], arm_q["arm_s"], tip_xyz, s3_pose[2], grip)
        t += 5.0 / len(picked)
        push("arm_s_to_belt", "isaac", str(sample.get("phase", "carry")), s3_pose,
             "arm_s", c_xyz, cell_yaw, has_cargo_45=(idx < 2), arm_s_ee=tip_xyz, active_arm="arm_s")
    arm_q["arm_s"] = list(WAIT_S_Q)
    stage_windows.append({"id": "arm_s_to_belt", "label": STAGE_META[4][1], "simulator": "isaac", "start_s": t0, "end_s": round(t, 4)})

    # Stage 6: belt_transit (20.5 -> 25.5s) — container rides belt while rosy_45 returns along upper lane
    t0 = t
    belt_native = _parse_site_native(ev["belt_transit"])
    trace = belt_native["trace"][::max(1, len(belt_native["trace"]) // 12)]
    if "upper_east" in edges and "upper_west" in edges:
        ret_poly = _polyline_chain(edges, ["upper_east", "upper_west"], (s3_pose[0], s3_pose[1]))
    else:
        ret_poly = [[s3_pose[0], s3_pose[1]], [c2_pose[0], s3_pose[1]], [c2_pose[0], 0.022], [c2_pose[0], c2_pose[1]]]
    return_pts = _resample_path(ret_poly, len(trace) + 1)
    for ridx, item in enumerate(trace):
        t += 5.0 / max(1, len(trace))
        c_xyz = _cell_to_site(item["xyz_m"], reg)
        push("belt_transit", "isaac", "belt_moving", list(return_pts[ridx]), "belt", c_xyz, cell_yaw, has_cargo_45=False)
    push("belt_transit", "isaac", "belt_settled", list(return_pts[-1]), "belt", belt_pick_site, cell_yaw, has_cargo_45=False)
    stage_windows.append({"id": "belt_transit", "label": STAGE_META[5][1], "simulator": "isaac", "start_s": t0, "end_s": round(t, 4)})

    # Stage 7: ab_stack (25.5 -> 36.0s) — full 6-waypoint MuJoCo IK for all 9 containers
    t0 = t
    rows = ev["ab_stack"]["rows"]
    stacked_map: dict[str, dict[str, Any]] = {}
    step_dt = 10.5 / max(1, len(rows))
    p45_parked = list(c2_pose)
    for idx, row in enumerate(rows):
        arm_k = str(row["arm"])
        cid = str(row["container"])
        target = str(row["target"])
        dst = _slot_site_xyz(target, reg)
        dyaw = _slot_site_yaw(target, reg)
        emit_arm_move(
            "ab_stack", "mujoco", str(row["step"]), arm_k, cid, idx % 6,
            belt_pick_site, cell_yaw, dst, dyaw, step_dt, stacked_map,
            remove_src=False, add_dst=target, p45_pose=p45_parked,
        )
    stage_windows.append({"id": "ab_stack", "label": STAGE_META[6][1], "simulator": "mujoco", "start_s": t0, "end_s": round(t, 4)})

    if include_extended:
        # Stage 8: ab_rehandle (A<->B cross-arm temp-slot sorting + rosy_46 approaching outbound dock)
        t0 = t
        p46_route = ["bay_3", "bar_32", "bar_21", "park_out", "park_gate_out", "loop_left", "loop_right", "upper_east"]
        if all(eid in edges for eid in p46_route):
            p46_leg_edges = _polyline_chain(edges, p46_route, (c3_pose[0], c3_pose[1]))
            p46_leg_edges[-1] = [0.627, -0.246]
        else:
            p46_leg_edges = [[c3_pose[0], c3_pose[1]], [c3_pose[0], -0.246], [0.627, -0.246]]
        p46_approach = _resample_path(p46_leg_edges, 36)
        rehandle_moves = [
            ("r1", "arm_a", "bar-8", "ship-h1r0-l2", "tmp-a-1"),
            ("r2", "arm_b", "bar-9", "ship-h1r2-l2", "tmp-b-1"),
            ("r3", "arm_b", "bar-7", "ship-h1r1-l2", "tmp-b-2"),
            ("r4", "arm_a", "bar-8", "tmp-a-1", "ship-h1r1-l2"),   # A->B handoff across center row
            ("r5", "arm_b", "bar-9", "tmp-b-1", "ship-h1r2-l2"),
            ("r6", "arm_a", "bar-5", "ship-h1r0-l1", "tmp-a-2"),
        ]
        # Note bar-7 rests cleanly on tmp-b-2 while ship-h1r0-l2 stays free, OR put bar-5 back! Let's re-stack bar-5 -> ship-h1r0-l1 & leave bar-7 ready on tmp-b-2
        p_Cursor = 0
        for mid, arm_k, cid, src_name, dst_name in rehandle_moves:
            cur = stacked_map[cid]
            dst = _slot_site_xyz(dst_name, reg)
            dyaw = _slot_site_yaw(dst_name, reg)
            seg = [list(p46_approach[min(p_Cursor + k, len(p46_approach) - 1)]) for k in range(6)]
            p_Cursor += 6
            emit_arm_move(
                "ab_rehandle", "mujoco", mid, arm_k, cid, int(cur.get("color_idx", 0)),
                list(cur["pose_m"]), float(cur["yaw_rad"]), dst, dyaw, 1.5, stacked_map,
                remove_src=True, add_dst=dst_name, p45_pose=p45_parked, p46_path=seg,
            )
        stage_windows.append({"id": "ab_rehandle", "label": EXTENDED_META[7][1], "simulator": "mujoco", "start_s": t0, "end_s": round(t, 4)})

        # Stage 9: outbound_dispatch (rosy_46 docks into white U outbound stand -> arm_a drops bar-8 on chute -> glides into tray -> departs!)
        t0 = t
        # Reverse rosy_46 from [0.627, -0.246] pointing south (-pi/2) straight north (+Y) into U-dock [0.627, -0.010]
        dock_steps = [
            [0.627, -0.246, -math.pi / 2],
            [0.627, -0.170, -math.pi / 2],
            [0.627, -0.090, -math.pi / 2],
            list(OUTBOUND_DOCK_SITE),
        ]
        bar8 = stacked_map.get("bar-8") or next(iter(stacked_map.values()))
        bar8_cidx = int(bar8.get("color_idx", 4))
        for pose in dock_steps:
            t += 0.45
            push("outbound_dispatch", "mujoco", "rosy46_dock_reverse", p45_parked,
                 "ship", list(bar8["pose_m"]), float(bar8["yaw_rad"]), has_cargo_45=False,
                 color_idx=bar8_cidx, stacked=stacked_map, p46_override=pose)

        # arm_a picks bar-8 from ship-h1r1-l2 and drops it onto outbound chute entrance
        emit_arm_move(
            "outbound_dispatch", "mujoco", "o1", "arm_a", bar8["id"], bar8_cidx,
            list(bar8["pose_m"]), float(bar8["yaw_rad"]), stand_chute_site, cell_yaw, 1.8, stacked_map,
            remove_src=True, add_dst=None, p45_pose=p45_parked,
        )
        arm_q["arm_a"] = list(WAIT_SIDE_A_Q)

        # Container glides down the 24-degree chute straight into rosy_46 rear cargo tray ([0.627, 0.085, 0.060])
        p46_tray_docked = tray_on_pinky(OUTBOUND_DOCK_SITE)
        slide_pts = [
            stand_chute_site,
            [round((stand_chute_site[0] + p46_tray_docked[0]) * 0.5, 5),
             round((stand_chute_site[1] + p46_tray_docked[1]) * 0.5, 5), 0.072],
            p46_tray_docked,
        ]
        for s_xyz in slide_pts:
            t += 0.35
            push("outbound_dispatch", "mujoco", "chute_slide_to_tray", p45_parked,
                 "outbound_chute", s_xyz, cell_yaw, has_cargo_45=False, has_cargo_46=True,
                 color_idx=bar8_cidx, active_arm="arm_a", active_step="o1",
                 stacked=stacked_map, p46_override=OUTBOUND_DOCK_SITE)

        # rosy_46 pulls forward out of U-dock carrying bar-8 in rear tray onto upper_east -> upper_west
        depart_pts = [
            [0.627, -0.090, -math.pi / 2],
            [0.627, -0.190, -math.pi / 2],
            [0.627, -0.246, math.pi],
            [0.350, -0.246, math.pi],
            [0.050, -0.246, math.pi],
            [-0.250, -0.246, math.pi],
        ]
        for dp in depart_pts:
            t += 0.45
            push("outbound_dispatch", "mujoco", "rosy46_depart_with_cargo", p45_parked,
                 "pinky46_tray", tray_on_pinky(dp), dp[2], has_cargo_45=False, has_cargo_46=True,
                 color_idx=bar8_cidx, stacked=stacked_map, p46_override=dp)
        stage_windows.append({"id": "outbound_dispatch", "label": EXTENDED_META[8][1], "simulator": "mujoco", "start_s": t0, "end_s": round(t, 4)})

    head = receipts[0]
    return {
        "schema": SCHEMA,
        "source_mode": "verified_replay",
        "run_id": head["run_id"],
        "task_id": head["task_id"],
        "robot_id": head["robot_id"],
        "cargo_id": head["cargo_id"],
        "receipts_sha256": hashlib.sha256(receipts_path.read_bytes()).hexdigest(),
        "site_map_sha256": head["site_map_sha256"],
        "duration_s": round(t, 4),
        "s3_box": s3_box,
        "fleet_robots": {
            "pinkys": ["rosy_42", "rosy_45", "rosy_46"],
            "arms": ["arm_s", "arm_a", "arm_b"],
        },
        "arm_bases_site": {
            "arm_s": {"pose_m": list(ARM_S_BASE_SITE), "yaw_rad": round(math.pi, 5)},
            "arm_a": {"pose_m": arm_a_site, "yaw_rad": 0.0},
            "arm_b": {"pose_m": arm_b_site, "yaw_rad": round(math.pi, 5)},
        },
        "stages": stage_windows,
        "keyframes": keyframes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closed-dir", required=True, type=Path)
    parser.add_argument("--site-map", required=True, type=Path)
    parser.add_argument("--registration", required=True, type=Path)
    parser.add_argument("--extended", action="store_true", help="Include Stages 8-9 (A<->B rehandle and outbound dispatch)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    try:
        timeline = compile_timeline(args.closed_dir, args.site_map, args.registration, include_extended=args.extended)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(timeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"error: {error}\n")
    print(f"timeline: {args.out} ({len(timeline['keyframes'])} keyframes, {timeline['duration_s']:.1f}s)")


if __name__ == "__main__":
    main()
