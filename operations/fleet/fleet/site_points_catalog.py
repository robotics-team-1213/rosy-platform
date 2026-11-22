"""Static cell-coordinate catalog, 3-frame mapping, conveyor bridge, and 6-stage summary for site-points full view."""
from __future__ import annotations

from typing import Any

PLANNED_VEHICLE_STOPS: tuple[dict[str, str], ...] = (
    {
        "id": "S_OUT",
        "name": "S_OUT 반출대 상차 정지선",
        "kind": "stop",
        "port_role": "outbound_pickup",
        "expected_rule_role": "load",
    },
)

SITE_HANDOFFS: tuple[dict[str, Any], ...] = (
    {
        "id": "s3_cell_s_unload",
        "kind": "intake",
        "direction": "vehicle_to_arm",
        "vehicle_stop_id": "S3",
        "intake_point_ref": "intake-s3",
        "cell_id": "cell_s",
        "arms": ["arm_s"],
        "arm_src": "not_places:vehicle_tray",
        "arm_dst": "not_places:belt",
        "target_cell_zones": ["yard"],
        "requires_arm_fold_for_align": True,
    },
    {
        "id": "outbound_stand_load",
        "kind": "outbound",
        "direction": "arm_to_vehicle",
        "vehicle_stop_id": "S_OUT",
        "vehicle_exit_stop_id": "S1",
        "cell_id": "cell_ab",
        "arms": ["arm_a"],
        "arm_src": "stand:r1-s1-t1",
        "arm_dst": "not_places:vehicle_tray",
        "cell_zone_id": "stand",
        "wire_slot_ref": "stand-r1-c1-l1",
        "requires_arm_fold_for_align": True,
    },
)


def build_zone_rules(cell_sites: dict[str, Any]) -> dict[str, Any]:
    """Summarize 3-tier x 9-slot topology and temporary-zone rehandling rules from cell_sites."""
    tier_counts = {1: 0, 2: 0, 3: 0}
    area_counts: dict[str, int] = {}
    yard_slot_counts: dict[int, int] = {}
    zones_by_id: dict[str, dict[str, Any]] = {
        str(z.get("id")): z for z in (cell_sites.get("zones") or ()) if isinstance(z, dict) and z.get("id")
    }

    for s in cell_sites.get("sites") or ():
        if not isinstance(s, dict):
            continue
        area = str(s.get("area") or "")
        tnum = int(s.get("tier") or 0)
        if tnum in tier_counts:
            tier_counts[tnum] += 1
        area_counts[area] = area_counts.get(area, 0) + 1
        if area == "yard":
            snum = int(s.get("slot") or 0)
            yard_slot_counts[snum] = yard_slot_counts.get(snum, 0) + 1

    block_specs = (
        ("yard:s1", "yard", [1, 3], yard_slot_counts.get(1, 0), "storage", ["arm_a", "arm_b"]),
        ("yard:s2", "yard", [4, 6], yard_slot_counts.get(2, 0), "storage", ["arm_a", "arm_b"]),
        ("temp_a", "temp_a", [1, 3], area_counts.get("temp_a", 0), "temporary", ["arm_a"]),
        ("temp_b", "temp_b", [1, 3], area_counts.get("temp_b", 0), "temporary", ["arm_b"]),
    )
    nine_slot_blocks = [
        {
            "id": bid, "zone": zid, "rows": ["r1", "r2", "r3"], "columns": cols,
            "tiers": [1, 2, 3], "count": cnt, "role": role,
            "arms": list((zones_by_id.get(zid) or {}).get("arms") or default_arms),
        }
        for bid, zid, cols, cnt, role, default_arms in block_specs
    ]

    return {
        "tier_height_mm": float(cell_sites.get("tier_height_mm") or 32.4),
        "tiers_per_stack": 3,
        "nine_slot_blocks": nine_slot_blocks,
        "outbound_single": {
            "id": "stand:r1-s1-t1", "zone": "stand", "tier": 1,
            "count": area_counts.get("stand", 0), "role": "outbound",
            "arms": list((zones_by_id.get("stand") or {}).get("arms") or ["arm_a"]),
        },
        "layer_counts": {
            "t1": tier_counts[1], "t2": tier_counts[2], "t3": tier_counts[3],
            "total": tier_counts[1] + tier_counts[2] + tier_counts[3],
        },
        "temporary_rehandling": {
            "zones": ["temp_a", "temp_b"],
            "arm_owner": {
                zid: list((zones_by_id.get(zid) or {}).get("arms") or default)
                for zid, default in (("temp_a", ["arm_a"]), ("temp_b", ["arm_b"]))
            },
            "policy": "lifo_rehandle_and_restore_to_yard",
            "long_term_storage_allowed": False,
            "forbidden_targets": ["not_places:belt", "stand:r1-s1-t1"],
            "hold_when_full": "NO_LEGAL_TEMPORARY_BAY",
        },
    }


def _place_pose(place: Any) -> dict[str, float | None] | None:
    if place is None:
        return None
    return {
        "x": round(float(place.x), 4),
        "y": round(float(place.y), 4),
        "yaw": round(float(place.yaw), 4) if place.yaw is not None else None,
    }


def build_coordinate_frames(
    site_map: Any,
    site_rules: Any,
    cell_sites: dict[str, Any],
) -> dict[str, Any]:
    """Build 3 separate coordinate-frame views (vehicle_world m, cell_s mm, cell_ab mm) without conflating origins."""
    active_by_id = {p.id: p for p in site_map.places}
    exit_place = site_rules.return_.exit_place if site_rules is not None else None
    stop_rules = {s.place: s.role for s in site_rules.stops} if site_rules is not None else {}

    s1_place = active_by_id.get("S1")
    s3_place = active_by_id.get("S3")
    j_stand_place = active_by_id.get("J_stand")
    s_out_place = active_by_id.get("S_OUT")

    charge_active = {cid: _place_pose(active_by_id[cid]) for cid in ("C1", "C2", "C3") if cid in active_by_id}
    wait_stops = {pid: _place_pose(active_by_id[pid]) for pid in ("S2", "S4", "S5") if pid in active_by_id}

    vehicle_world = {
        "frame_id": str(getattr(site_map, "map_id", None) or "world_261026"),
        "unit": "m",
        "source_schema": "rosy.site_map/1",
        "truth_status": "live_active_map",
        "waypoints": {
            "S1_pickup": {
                "place_id": "S1",
                "pose": _place_pose(s1_place),
                "role": stop_rules.get("S1", "load"),
                "dual_role_exit_place": exit_place == "S1",
                "route_to_intake": "S1 -> J_out -> S4 -> S5 -> S3",
            },
            "wait_stops": wait_stops,
            "S3_intake": {
                "place_id": "S3",
                "pose": _place_pose(s3_place),
                "role": stop_rules.get("S3", "unload"),
                "pinned": bool(s3_place.pinned) if s3_place is not None else False,
                "bridge_arm_frame": "cell_s_arm_base",
                "bridge_target": "vehicle_tray",
            },
            "J_stand_branch": {
                "place_id": "J_stand",
                "pose": _place_pose(j_stand_place) or {"x": 0.615, "y": -0.207, "yaw": None},
                "branch_edge": "upper_east",
                "planned": j_stand_place is None,
            },
            "S_OUT_outbound": {
                "place_id": "S_OUT",
                "pose": _place_pose(s_out_place),
                "ceiling_ref_m": {"x": 0.614, "y": 0.001, "yaw": 1.5708},
                "in_active_map": s_out_place is not None,
                "bridge_arm_frame": "cell_ab_fixture",
                "bridge_target": "stand:r1-s1-t1",
            },
            "C1_C3_charge": {
                "mode": "camera_pink_line",
                "adr": "D-1013",
                "physical_straight_x_m": {"C1": -0.4182, "C2": -0.1914, "C3": 0.0346},
                "active_poses": charge_active,
                "bay_1_distortion_note": (
                    "v348 bay_1 polyline bends left to x=-0.4328 (-1.5 cm) from left ceiling camera lens distortion; "
                    "physical rail is straight."
                ),
            },
        },
    }

    cell_s_arm_base = {
        "frame_id": "arm_s_base",
        "unit": "mm",
        "owner": "deploy/robot/omx/cell_spec_recovery_fsm.py",
        "calibration_status": "cell_local_reference",
        "vehicle_tray": {
            "xyz_mm": [53.5, 172.0, 20.0],
            "yaw_deg": -85.0,
            "top_roi_px": [10, 40, 260, 240],
            "bridge_vehicle_stop": "S3",
        },
        "belt_in": {
            "ref": "belt-in",
            "safe_place_xyz_mm": [134.0, -28.0, 58.0],
            "center_xyz_mm": [125.0, -55.0, 25.0],
            "front_rail_x_mm": 114.0,
            "safe_x_min_mm": 134.0,
            "safe_z_min_mm": 55.0,
            "yaw_deg": -85.0,
            "top_roi_px": [240, 90, 460, 270],
            "bridge_conveyor_end": "belt_in",
        },
    }

    temp_z = {"t1": 96.2, "t2": 128.6, "t3": 161.0}
    cell_ab_fixture = {
        "frame_id": "cell_ab_fixture",
        "unit": "mm",
        "owner": "tools/sim/omx_two_arm_sites.py",
        "calibration_status": "cell_local_reference",
        "arm_bases_mm": {
            "arm_a": {"measured_194": [91.0, -168.25, 84.0], "v24": [77.0, -164.65, 84.0], "yaw_deg": 90.0},
            "arm_b": {"measured_194": [91.0, 168.25, 84.0], "v24": [77.0, 167.65, 84.0], "yaw_deg": -90.0},
        },
        "belt_out": {
            "ref": "belt",
            "stop_x_mm": 158.0,
            "pickup_xyz_mm": [207.0, 7.0, 33.7],
            "v24_y_mm": -3.0,
            "top_px": [341, 112],
            "single_arm_area_xyz_mm": [15.0, 175.0],
            "arms": ["arm_a", "arm_b"],
            "bridge_conveyor_end": "belt_out",
        },
        "yard": {
            "count": sum(1 for s in (cell_sites.get("sites") or ()) if s.get("area") == "yard"),
            "rows_y_mm": {"r1": -38.0, "r2": 0.0, "r3": 38.0},
            "tier_z_mm": {"t1": 94.2, "t2": 126.6, "t3": 159.0},
            "arms": ["arm_a", "arm_b"],
        },
        "temp_a": {"count": 9, "fan_radius_mm": 200.0, "dir_deg": 180.0, "tier_z_mm": temp_z, "arms": ["arm_a"]},
        "temp_b": {"count": 9, "fan_radius_mm": 200.0, "dir_deg": 180.0, "tier_z_mm": dict(temp_z), "arms": ["arm_b"]},
        "stand": {
            "site_id": "stand:r1-s1-t1",
            "xyz_mm": [214.0, -168.25, 97.1],
            "v24_y_mm": -164.65,
            "rail_z_mm": 80.9,
            "yaw_deg": 90.0,
            "top_roi_px": [410, 30, 570, 125],
            "arms": ["arm_a"],
            "bridge_vehicle_stop": "S_OUT",
        },
    }

    return {
        "vehicle_world": vehicle_world,
        "cell_s_arm_base": cell_s_arm_base,
        "cell_ab_fixture": cell_ab_fixture,
    }


def build_conveyor_transfer() -> dict[str, Any]:
    """Describe the conveyor belt bridge between cell_s (belt-in) and cell_ab (belt) and its runtime gaps."""
    return {
        "id": "belt_s_to_ab",
        "in_point": {
            "ref": "belt-in",
            "arm_frame": "cell_s_arm_base",
            "arm_id": "arm_s",
            "safe_place_xyz_mm": [134.0, -28.0, 58.0],
            "observer_camera": "arm_s_top",
        },
        "out_point": {
            "ref": "belt",
            "arm_frame": "cell_ab_fixture",
            "arms": ["arm_a", "arm_b"],
            "pickup_xyz_mm": [207.0, 7.0, 33.7],
            "stop_x_mm": 158.0,
            "observer_camera": "top",
        },
        "transport": {
            "motor_control": "none_manual_power_continuous",
            "direct_model_actuation_forbidden": "D-429",
            "physical_stop": "v24_concave_stopper_x158mm",
        },
        "handover_state_machine": {
            "module": "deploy/robot/omx/cell_belt_handover.py",
            "states": ["empty", "reserved", "placed", "at_end", "picked", "missing"],
            "wired_to_runtime": False,
        },
        "occupancy_gate": {
            "module": "deploy/robot/omx/cell_belt_occupancy.py",
            "s_load_requires": "empty",
            "ab_pick_requires": "occupied",
            "wired_to_runtime": False,
        },
        "identity_gate": {
            "adr": "D-996",
            "module": "operations/fleet/fleet/server/work/intake_readings.py",
            "belt_end_event": "container.received_at_intake",
            "wrist_store_event": "container.stored",
            "marker_dict": "DICT_4X4_250_100_199",
            "wired_in_fleet": True,
            "hardware_markers_verified": False,
        },
    }


def build_end_to_end_stages(
    *,
    active_by_id: dict[str, Any],
    stop_rules: dict[str, dict[str, Any]],
    exit_place: str | None,
    s3_berth_ready: bool,
    s_out_berth_ready: bool,
) -> list[dict[str, Any]]:
    """Return ordered 6-stage pickup -> conveyor -> store -> rehandle -> outbound flow with honest gaps."""
    s1_ready = "S1" in active_by_id
    s1_role = (stop_rules.get("S1") or {}).get("role")
    return [
        {
            "stage": "stage_1_vehicle_pickup",
            "label": "S1 수령구 적재 및 S3 하역장 이동",
            "frame": "vehicle_world",
            "from": "S1",
            "to": "S3",
            "runtime_status": "ready_dual_role_exit" if (s1_ready and exit_place == "S1") else (
                "ready" if s1_ready else "planned_unverified"
            ),
            "s1_rule_role": s1_role,
            "dual_role_note": (
                "S1 serves both operator pickup load and return.exit_place until S_EXIT is split."
                if exit_place == "S1" else f"return.exit_place={exit_place}"
            ),
            "gaps": ["dedicated S1 operator scan / separate S_EXIT not yet split"] if exit_place == "S1" else [],
        },
        {
            "stage": "stage_2_cell_s_unload",
            "label": "S3 접안 후 arm_s 하역 (vehicle_tray -> belt-in)",
            "frame": "cell_s_arm_base",
            "from": "vehicle_tray",
            "to": "belt-in",
            "runtime_status": "berth_unready" if not s3_berth_ready else "partial_unwired_belt_gate",
            "gaps": [
                *([] if s3_berth_ready else ["S3 stop_zone/approach_m missing in active site_map"]),
                "read_belt_occupancy not wired to arm_s unload guard",
            ],
        },
        {
            "stage": "stage_3_conveyor_transit",
            "label": "컨베이어 벨트 이송 (belt-in -> v24 스토퍼 belt-out)",
            "frame": "conveyor_belt",
            "from": "belt-in",
            "to": "belt",
            "runtime_status": "manual_power_unwired_gates",
            "gaps": [
                "no ROS/PLC conveyor motor driver (manual power continuous)",
                "BeltHandover & read_belt_occupancy exist as modules only (unwired)",
                "D-996 ArUco 100-199 markers not printed/attached/verified",
            ],
        },
        {
            "stage": "stage_4_cell_ab_store",
            "label": "belt-out 픽업 후 arm_a/b yard 적재 (1~3단)",
            "frame": "cell_ab_fixture",
            "from": "belt",
            "to": "yard",
            "runtime_status": "sim_verified_real_uncalibrated",
            "gaps": [
                "read_belt_occupancy not wired to arm_a/arm_b pick guard",
                "cell PC 37-site live camera remap/calibration pending",
            ],
        },
        {
            "stage": "stage_5_rehandle_and_outbound",
            "label": "temp_a/b 임시 재취급 후 stand:r1-s1-t1 반출 적재",
            "frame": "cell_ab_fixture",
            "from": "yard",
            "to": "stand:r1-s1-t1",
            "runtime_status": "contract_verified_real_uncalibrated",
            "gaps": ["r05 chute mounting + live 37-site calibration + wrist marker read pending"],
        },
        {
            "stage": "stage_6_vehicle_outbound",
            "label": "J_stand 북쪽 분기 -> S_OUT 상차 -> 출구 출발",
            "frame": "vehicle_world",
            "from": "S_OUT",
            "to": exit_place or "S_EXIT",
            "runtime_status": "ready" if s_out_berth_ready else "planned_unverified",
            "gaps": [] if s_out_berth_ready else [
                "S_OUT/J_stand/S_EXIT not measured/registered in active world_261026 map",
            ],
        },
    ]
