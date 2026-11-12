"""Physical berth-parking control loop and bay dock specifications (D-950 / D-972)."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Mapping, Optional

from fastapi import Request

from core_common.robot_body import PINKY_PRO

BAY_DOCK_SPECS: Mapping[str, dict[str, Any]] = {
    "C1": {
        "bay_id": "C1",
        "dock_id": "bay_c1",
        "dock_type": "charge_bay_rear",
        "staging_place_id": "P1",
        "bay_pose": {"x": -0.4197, "y": 0.470, "yaw": -1.5708},
        "staging_pose": {"x": -0.4184, "y": 0.270, "yaw": -1.5708},
        "corridor_node_pose": {"x": -0.4184, "y": 0.0264, "yaw": -1.5708},
        "stop_face_rg_m": 0.4892,
        "rail_entry_m": 0.085,
        "staging_offset_m": 0.20,
        "docking_threshold_m": 0.04,
        "undock_distance_m": 0.20,
        "centerline_half_width_m": 0.025,
    },
    "C2": {
        "bay_id": "C2",
        "dock_id": "bay_c2",
        "dock_type": "charge_bay_rear",
        "staging_place_id": "P2",
        "bay_pose": {"x": -0.1861, "y": 0.470, "yaw": -1.5708},
        "staging_pose": {"x": -0.1896, "y": 0.270, "yaw": -1.5708},
        "corridor_node_pose": {"x": -0.1896, "y": 0.0256, "yaw": -1.5708},
        "stop_face_rg_m": 0.1104,
        "rail_entry_m": 0.085,
        "staging_offset_m": 0.20,
        "docking_threshold_m": 0.04,
        "undock_distance_m": 0.20,
        "centerline_half_width_m": 0.025,
    },
    "C3": {
        "bay_id": "C3",
        "dock_id": "bay_c3",
        "dock_type": "charge_bay_rear",
        "staging_place_id": "P3",
        "bay_pose": {"x": 0.0351, "y": 0.470, "yaw": -1.5708},
        "staging_pose": {"x": 0.0322, "y": 0.270, "yaw": -1.5708},
        "corridor_node_pose": {"x": 0.0322, "y": 0.0249, "yaw": -1.5708},
        "stop_face_rg_m": 0.1104,
        "rail_entry_m": 0.085,
        "staging_offset_m": 0.20,
        "docking_threshold_m": 0.04,
        "undock_distance_m": 0.20,
        "centerline_half_width_m": 0.025,
    },
}

DEFAULT_ROBOT_BAY: Mapping[str, str] = {
    "rosy_46": "C1",
    "rosy_45": "C2",
    "rosy_42": "C3",
}


def _wrap(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def centerline_axial_gaps(
    points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    *,
    half_length_m: float = 0.06,
    half_corridor_m: float = 0.025,
    fallback_fg_m: float = 9.9,
    fallback_rg_m: float = 9.9,
) -> tuple[float, float]:
    """다중 베이(180mm 간격)에서 인접 베이 레일·이웃 기체 간섭 없이 전·후방 스토퍼 거리를 계산한다."""
    fg_center = min(
        (float(x) - half_length_m for x, y in points if float(x) > half_length_m and abs(float(y)) <= half_corridor_m),
        default=fallback_fg_m,
    )
    rg_center = min(
        (-float(x) - half_length_m for x, y in points if float(x) < -half_length_m and abs(float(y)) <= half_corridor_m),
        default=fallback_rg_m,
    )
    return round(fg_center, 4), round(rg_center, 4)


def infer_bay_id(robot_id: str, site_pose: Optional[Mapping[str, float]] = None) -> str:
    if robot_id in DEFAULT_ROBOT_BAY:
        return DEFAULT_ROBOT_BAY[robot_id]
    if site_pose and isinstance(site_pose.get("x"), (int, float)):
        rx = float(site_pose["x"])
        return min(BAY_DOCK_SPECS.keys(), key=lambda bid: abs(BAY_DOCK_SPECS[bid]["bay_pose"]["x"] - rx))
    return "C1"


async def _pin_robot_on_fleet(
    request: Request,
    robot_id: str,
    x: float,
    y: float,
    yaw: float,
    *,
    actor_id: str = "fleet-berth-park",
) -> dict[str, Any]:
    runner = getattr(request.app.state, "trip_runner", None)
    pose_service = getattr(runner, "_pose", None) or getattr(request.app.state, "map_pose_service", None)
    pinned_pose = None
    if pose_service is not None:
        try:
            tracker = pose_service._tracker(robot_id)
            now_wall = pose_service._wall()
            if tracker is not None and (
                tracker.latest_odom_stamp is None
                or now_wall - tracker.latest_odom_stamp > pose_service.config.max_odom_age_s * 0.8
            ):
                from rosy.world.state.projections.map_pose import OdomSample
                tracker.add_odom(OdomSample(0.0, 0.0, 0.0, now_wall), now_wall)
            _refused, mp = await pose_service.pin(robot_id, (float(x), float(y), float(yaw)))
            if mp is not None:
                pinned_pose = {"x": round(mp.x, 4), "y": round(mp.y, 4), "yaw": round(mp.yaw, 4), "state": mp.state}
        except Exception:
            pass
    tracking_svc = getattr(request.app.state, "tracking", None)
    if tracking_svc is not None and hasattr(tracking_svc, "set_anchor"):
        try:
            tracking_svc.set_anchor(
                {"target_id": robot_id, "kind": "pinky", "base_x": float(x), "base_y": float(y), "base_yaw": float(yaw)},
                principal_id=actor_id,
            )
        except Exception:
            pass
    return pinned_pose or {"x": round(float(x), 4), "y": round(float(y), 4), "yaw": round(float(yaw), 4), "state": "LOCALIZED"}


async def _execute_physical_berth_park(
    request: Request,
    console: Any,
    robot_id: str,
    spec: Mapping[str, Any],
    *,
    mode: str,
    forward_m: float,
    actor_id: str,
) -> Optional[dict[str, Any]]:
    clients = getattr(console, "_clients", None)
    if not isinstance(clients, Mapping):
        return None
    client = clients.get(robot_id)
    http = getattr(client, "_http", None)
    headers_fn = getattr(client, "_headers", None)
    if http is None or not callable(headers_fn):
        return None

    async def _req(method: str, path: str, body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        resp = await http.request(method, path, json=body, headers=dict(headers_fn()))
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} {path}: {resp.text[:160]}")
        return resp.json() if resp.content else {}

    async def _read_pose_and_gaps() -> tuple[dict[str, float], float, float, dict[str, Any]]:
        st = await _req("GET", "/api/v1/robot/state")
        scan = await _req("GET", "/api/v1/sensors/lidar")
        pts = PINKY_PRO.scan_view(scan, forward_deg=180.0).points
        fg_c, rg_c = centerline_axial_gaps(
            pts,
            half_length_m=0.06,
            half_corridor_m=float(spec["centerline_half_width_m"]),
        )
        p = st.get("pose") or {"x": 0.0, "y": 0.0, "yaw": 0.0}
        return (
            {"x": float(p.get("x", 0.0)), "y": float(p.get("y", 0.0)), "yaw": float(p.get("yaw", 0.0))},
            fg_c,
            rg_c,
            st,
        )

    bay_pose = spec["bay_pose"]
    stop_face_rg_m = float(spec.get("stop_face_rg_m", 0.1104))
    rail_entry_m = float(spec["rail_entry_m"])

    try:
        p0, fg0, rg0, st0 = await _read_pose_and_gaps()
    except Exception as exc:
        return {"executed": False, "reason": f"robot_unreachable: {exc}"}

    phases_executed: list[str] = []
    trace: list[dict[str, Any]] = []
    stop_reason = "completed"

    try:
        await _req("POST", "/api/v1/mode", {"mode": "MANUAL"})
        p_stage, fg_stage, rg_stage, st_stage = p0, fg0, rg0, st0

        if mode == "forward_and_berth_park":
            target_stage_rg = stop_face_rg_m + forward_m
            needed_fwd_m = max(0.0, target_stage_rg - rg0) if rg0 < target_stage_rg else 0.0
            if needed_fwd_m > 0.015:
                phases_executed.append("FORWARD_UNDOCK")
                t_fwd = time.monotonic()
                while time.monotonic() - t_fwd < 6.0:
                    p_cur, fg_cur, rg_cur, st_cur = await _read_pose_and_gaps()
                    if st_cur.get("mode") == "EMERGENCY":
                        stop_reason = "emergency_during_forward"
                        break
                    moved_odom = math.hypot(p_cur["x"] - p0["x"], p_cur["y"] - p0["y"])
                    if rg_cur >= target_stage_rg - 0.006 or moved_odom >= needed_fwd_m - 0.004 or fg_cur <= 0.15:
                        break
                    await _req("POST", "/api/v1/teleop", {"linear": 0.050, "angular": 0.0})
                    await asyncio.sleep(0.08)
                for _ in range(3):
                    await _req("POST", "/api/v1/teleop", {"linear": 0.0, "angular": 0.0})
                    await asyncio.sleep(0.05)
                await asyncio.sleep(0.18)
                p_stage, fg_stage, rg_stage, st_stage = await _read_pose_and_gaps()
                stage_y = round(bay_pose["y"] - max(0.0, rg_stage - stop_face_rg_m), 4)
                await _pin_robot_on_fleet(request, robot_id, bay_pose["x"], stage_y, bay_pose["yaw"], actor_id=actor_id)

        target_back_m = max(0.0, rg_stage - stop_face_rg_m)
        rail_entry_rg = stop_face_rg_m + rail_entry_m
        t_rev = time.monotonic()
        last_rem_m = target_back_m
        last_progress_at = time.monotonic()

        if target_back_m <= 0.008:
            stop_reason = "already_at_dock_stop_face"
            if "REVERSING_IN_RAILS" not in phases_executed:
                phases_executed.append("REVERSING_IN_RAILS")
        else:
            while time.monotonic() - t_rev < 10.0:
                p_cur, fg_cur, rg_cur, st_cur = await _read_pose_and_gaps()
                if st_cur.get("mode") == "EMERGENCY":
                    stop_reason = "emergency_latched"
                    break
                dx = p_cur["x"] - p_stage["x"]
                dy = p_cur["y"] - p_stage["y"]
                backed_odom_m = -(dx * math.cos(p_stage["yaw"]) + dy * math.sin(p_stage["yaw"]))
                lat_from_axis = -dx * math.sin(p_stage["yaw"]) + dy * math.cos(p_stage["yaw"])
                heading_err = _wrap(p_cur["yaw"] - p_stage["yaw"])

                rem_lidar_m = max(0.0, rg_cur - stop_face_rg_m)
                rem_odom_m = max(0.0, target_back_m - backed_odom_m)
                rem_m = min(rem_lidar_m, rem_odom_m) if backed_odom_m > 0.02 else rem_lidar_m

                if rg_cur <= stop_face_rg_m + 0.008 or rem_odom_m <= 0.005:
                    stop_reason = "dock_stop_face_reached"
                    break

                if last_rem_m - rem_m >= 0.005:
                    last_rem_m = rem_m
                    last_progress_at = time.monotonic()
                elif time.monotonic() - last_progress_at >= 0.85 and rem_m <= 0.045:
                    stop_reason = "contact_stall_at_stop_face"
                    break

                if rg_cur > rail_entry_rg and rem_m > rail_entry_m:
                    phase_name = "ALIGNING"
                    target_hdg = max(-0.10, min(0.10, -1.5 * lat_from_axis))
                    w = max(-0.15, min(0.15, 1.2 * (target_hdg - heading_err)))
                    v = -0.048
                else:
                    phase_name = "REVERSING_IN_RAILS"
                    w = 0.0
                    v = -max(0.038, min(0.048, rem_m * 0.65 + 0.025))

                if phase_name not in phases_executed:
                    phases_executed.append(phase_name)

                await _req("POST", "/api/v1/teleop", {"linear": round(v, 4), "angular": round(w, 4)})
                trace.append({
                    "t": round(time.monotonic() - t_rev, 2),
                    "phase": phase_name,
                    "backed_odom_m": round(backed_odom_m, 4),
                    "rem_lidar_m": round(rem_lidar_m, 4),
                    "rg_m": round(rg_cur, 4),
                    "fg_m": round(fg_cur, 4),
                    "yaw_deg": round(math.degrees(heading_err), 2),
                })
                await asyncio.sleep(0.08)

        for _ in range(4):
            await _req("POST", "/api/v1/teleop", {"linear": 0.0, "angular": 0.0})
            await asyncio.sleep(0.05)
        for p_done in ("SETTLING", "DOCKED"):
            if p_done not in phases_executed:
                phases_executed.append(p_done)
    finally:
        try:
            await _req("POST", "/api/v1/teleop", {"linear": 0.0, "angular": 0.0})
        except Exception:
            pass
        try:
            await _req("POST", "/api/v1/mode", {"mode": "IDLE"})
        except Exception:
            pass

    await asyncio.sleep(0.25)
    p_end, fg_end, rg_end, st_end = await _read_pose_and_gaps()
    taught_dock = None
    try:
        taught_dock = await _req("POST", f"/api/v1/docking/docks/{spec['dock_id']}/teach", {})
    except Exception:
        pass

    backed_total_m = math.hypot(p_end["x"] - p_stage["x"], p_end["y"] - p_stage["y"])
    rg_err_m = abs(rg_end - stop_face_rg_m)
    yaw_err_deg = math.degrees(_wrap(p_end["yaw"] - p_stage["yaw"]))
    final_y = bay_pose["y"] if rg_err_m <= 0.025 else round(bay_pose["y"] - max(0.0, rg_end - stop_face_rg_m), 4)
    pinned = await _pin_robot_on_fleet(request, robot_id, bay_pose["x"], final_y, bay_pose["yaw"], actor_id=actor_id)

    return {
        "executed": True,
        "stop_reason": stop_reason,
        "phases_executed": phases_executed,
        "before": {"pose": p0, "fg_center_m": fg0, "rg_center_m": rg0},
        "staging": {"pose": p_stage, "fg_center_m": fg_stage, "rg_center_m": rg_stage},
        "after": {
            "pose": p_end,
            "fg_center_m": fg_end,
            "rg_center_m": rg_end,
            "stop_face_rg_m": stop_face_rg_m,
            "rg_err_from_dock_m": round(rg_err_m, 4),
            "backed_odom_m": round(backed_total_m, 4),
            "yaw_err_deg": round(yaw_err_deg, 2),
            "mode": st_end.get("mode"),
            "site_pose": pinned,
            "taught_dock": taught_dock,
        },
        "trace_tail": trace[-8:],
    }
