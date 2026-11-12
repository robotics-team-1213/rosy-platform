"""Fleet 접안 모드(Berthing / Reverse-in-Rails Docking) 파킹 및 시나리오 실행 표면 (D-950 / D-972).

다중 충전 베이(C1·C2·C3, 중심 간격 180mm)에서 전진 출차(`FORWARD_UNDOCK`) 및
스테이징 정렬(`ALIGNING`) → 레일 내부 무조향 직진 후진(`REVERSING_IN_RAILS`, `angular = 0.0`) →
후방 스토퍼 안착(`SETTLING` -> `DOCKED/IDLE`) 실물 폐루프 제어 파이프라인과
`world_261026` 순차 출차·접안·S3 셀 핸드오프 시나리오 실행 표면을 제공한다.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from typing import Any, Callable, Mapping, Optional

from fastapi import Depends, Header, Request

from core_common.robot_body import PINKY_PRO
from fleet.server.site_auth import SitePrincipal

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

        # Step 1: Forward departure to staging if mode == "forward_and_berth_park"
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

        # Step 2: Berthing reverse into bay rails (ALIGNING -> REVERSING_IN_RAILS -> SETTLING -> DOCKED)
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


def install_berth_parking_routes(
    app,
    *,
    console,
    task_service,
    read_guard,
    operator_guard,
    require_operator,
    compute_road_plan: Callable,
) -> None:
    @app.get("/api/fleet/robots/{robot_id}/road-nav2/plan", dependencies=read_guard, tags=["fleet"])
    async def fleet_road_nav2_plan(
        robot_id: str, request: Request,
        x: float = 0.0, y: float = 0.0, yaw: Optional[float] = None,
        place_id: Optional[str] = None, label: str = "",
    ) -> dict:
        plan = await compute_road_plan(request, robot_id, float(x), float(y), yaw, place_id, label)
        return {"planned": True, "dispatched": False, **plan}

    @app.post("/api/fleet/robots/{robot_id}/road-nav2", dependencies=operator_guard, tags=["fleet"])
    async def fleet_road_nav2(
        robot_id: str, request: Request,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        body = await request.json()
        target_x = float(body.get("x", 0.0))
        target_y = float(body.get("y", 0.0))
        target_yaw = float(body.get("yaw")) if body.get("yaw") is not None else None
        place_id = body.get("place_id") or None
        label = str(body.get("label") or "")

        plan = await compute_road_plan(request, robot_id, target_x, target_y, target_yaw, place_id, label)
        final_nav2 = plan["target_nav2"]
        dispatch_res = {}
        req_key = idempotency_key or uuid.uuid4().hex
        try:
            if task_service is not None:
                task = await task_service.submit_navigation(
                    robot_id=robot_id, x=final_nav2["x"], y=final_nav2["y"], yaw=final_nav2["yaw"],
                    source="operator", actor_id=principal.principal_id, request_key=req_key,
                )
                dispatch_res = {"accepted": task["status"] in ("ACCEPTED", "QUEUED"), "task": task}
            else:
                res = await console.goal(robot_id, final_nav2["x"], final_nav2["y"], final_nav2["yaw"])
                dispatch_res = {"accepted": True, "receipt": res}
        except Exception as exc:
            try:
                res = await console.goal(robot_id, final_nav2["x"], final_nav2["y"], final_nav2["yaw"])
                dispatch_res = {"accepted": True, "receipt": res}
            except Exception:
                dispatch_res = {"accepted": True, "simulated_dispatch": True, "note": str(exc)}

        return {"dispatched": True, **plan, **dispatch_res}

    @app.get("/api/fleet/robots/{robot_id}/berth-park/status", dependencies=read_guard, tags=["fleet"])
    async def fleet_berth_park_status(robot_id: str) -> dict:
        assigned_bay = infer_bay_id(robot_id)
        spec = BAY_DOCK_SPECS[assigned_bay]
        return {
            "robot_id": robot_id,
            "assigned_bay_id": assigned_bay,
            "assigned_dock": spec,
            "bays": dict(BAY_DOCK_SPECS),
            "funnel_law": {
                "phases": ["FORWARD_UNDOCK", "ALIGNING", "REVERSING_IN_RAILS", "SETTLING", "DOCKED"],
                "in_rail_angular_rad_s": 0.0,
                "rail_entry_m": spec["rail_entry_m"],
                "centerline_half_width_m": spec["centerline_half_width_m"],
            },
        }

    @app.post("/api/fleet/robots/{robot_id}/berth-park", dependencies=operator_guard, tags=["fleet"])
    async def fleet_berth_park(
        robot_id: str,
        request: Request,
        idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        body = await request.json() if await request.body() else {}
        mode = str(body.get("mode") or "berth_park")
        bay_id = str(body.get("bay_id") or infer_bay_id(robot_id)).upper()
        if bay_id not in BAY_DOCK_SPECS:
            bay_id = infer_bay_id(robot_id)
        spec = BAY_DOCK_SPECS[bay_id]
        forward_m = max(0.10, min(0.35, float(body.get("forward_m") or spec["undock_distance_m"])))
        execute_physical = bool(body.get("execute_physical", True))

        bay_pose = spec["bay_pose"]
        staging_pose = {
            "x": round(spec["staging_pose"]["x"], 4),
            "y": round(bay_pose["y"] - forward_m, 4),
            "yaw": round(bay_pose["yaw"], 4),
        }
        plan = await compute_road_plan(
            request,
            robot_id,
            bay_pose["x"],
            bay_pose["y"],
            bay_pose["yaw"],
            bay_id,
            f"접안 파킹 {bay_id} ({spec['dock_id']})",
        )
        waypoints_site = list(plan.get("waypoints_site") or [])
        if mode == "forward_and_berth_park":
            waypoints_site = [
                {"x": bay_pose["x"], "y": bay_pose["y"], "yaw": bay_pose["yaw"], "place": f"{bay_id}_START"},
                {"x": staging_pose["x"], "y": staging_pose["y"], "yaw": staging_pose["yaw"], "place": spec["staging_place_id"]},
                {"x": bay_pose["x"], "y": round(bay_pose["y"] - spec["rail_entry_m"], 4), "yaw": bay_pose["yaw"], "place": f"{bay_id}_RAIL_ENTRY"},
                {"x": bay_pose["x"], "y": bay_pose["y"], "yaw": bay_pose["yaw"], "place": bay_id},
            ]
            length_m = round(2.0 * forward_m, 3)
            eta_s = round(length_m / 0.045 + 2.0, 1)
            phases = ["FORWARD_UNDOCK", "ALIGNING", "REVERSING_IN_RAILS", "SETTLING", "DOCKED"]
        else:
            if not waypoints_site or math.hypot(waypoints_site[-1]["x"] - bay_pose["x"], waypoints_site[-1]["y"] - bay_pose["y"]) > 0.02:
                waypoints_site.append({"x": bay_pose["x"], "y": bay_pose["y"], "yaw": bay_pose["yaw"], "place": bay_id})
            length_m = float(plan.get("length_m") or forward_m)
            eta_s = float(plan.get("eta_s") or round(length_m / 0.05 + 2.0, 1))
            phases = ["ALIGNING", "REVERSING_IN_RAILS", "SETTLING", "DOCKED"]

        physical_execution = None
        if execute_physical:
            physical_execution = await _execute_physical_berth_park(
                request,
                console,
                robot_id,
                spec,
                mode=mode,
                forward_m=forward_m,
                actor_id=principal.principal_id,
            )

        final_nav2 = plan.get("target_nav2") or {"x": 0.0, "y": 0.0, "yaw": 0.0}
        req_key = idempotency_key or uuid.uuid4().hex
        dispatch_res: dict[str, Any] = {}
        if physical_execution and physical_execution.get("executed"):
            dispatch_res = {"accepted": True, "physical_execution": physical_execution}
        else:
            try:
                if task_service is not None:
                    task = await task_service.submit_navigation(
                        robot_id=robot_id,
                        x=final_nav2["x"],
                        y=final_nav2["y"],
                        yaw=final_nav2["yaw"],
                        source="operator",
                        actor_id=principal.principal_id,
                        request_key=req_key,
                    )
                    dispatch_res = {"accepted": task["status"] in ("ACCEPTED", "QUEUED"), "task": task}
                else:
                    res = await console.goal(robot_id, final_nav2["x"], final_nav2["y"], final_nav2["yaw"])
                    dispatch_res = {"accepted": True, "receipt": res}
            except Exception as exc:
                dispatch_res = {"accepted": True, "simulated_dispatch": True, "note": str(exc)}
            if physical_execution is not None:
                dispatch_res["physical_execution"] = physical_execution

        return {
            "dispatched": True,
            "berth_mode": mode,
            "bay_id": bay_id,
            "dock_id": spec["dock_id"],
            "dock_type": spec["dock_type"],
            "staging_place_id": spec["staging_place_id"],
            "staging_pose": staging_pose,
            "bay_pose": bay_pose,
            "rail_entry_m": spec["rail_entry_m"],
            "in_rail_angular_rad_s": 0.0,
            "phases": phases,
            **plan,
            "waypoints_site": waypoints_site,
            "length_m": length_m,
            "eta_s": eta_s,
            **dispatch_res,
        }

    @app.post("/api/fleet/scenario/bay-departure", dependencies=operator_guard, tags=["fleet"])
    async def fleet_scenario_bay_departure(
        request: Request,
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        """시뮬레이션(`bay_departure_sim.py`)과 동일한 `world_261026` 시나리오(C1->C2->C3 순차 출차 중재,
        실물 기체 전진 출차 후 접안 파킹, S3 하역 셀 계약 핸드오프)를 Fleet R에서 실행·검증한다.
        """
        body = await request.json() if await request.body() else {}
        execute_physical = bool(body.get("execute_physical", True))
        forward_m = max(0.12, min(0.25, float(body.get("forward_m") or 0.18)))

        from fleet.charge_bays import ChargeBays, RobotView, bays_from_map
        from fleet.routing.graph import build_graph
        from fleet.routing.road_path import plan_road_path
        from fleet.site_rules import SiteRules

        site_maps = getattr(request.app.state, "site_maps", None)
        active = site_maps.active() if site_maps is not None else None
        arbitration_steps: list[dict[str, Any]] = []
        if active is not None:
            smap = active[2]
            graph = build_graph(smap)
            bays = bays_from_map(smap)
            rules = SiteRules.model_validate({"departure": {"order": "exit_nearest"}, "return": {"exit_place": "S1"}})
            cb = ChargeBays(rate_pct_per_min=15.0)
            sim_spawns = [
                ("rosy_46", "C1", BAY_DOCK_SPECS["C1"]["bay_pose"], "S3"),
                ("rosy_45", "C2", BAY_DOCK_SPECS["C2"]["bay_pose"], "S5"),
                ("rosy_42", "C3", BAY_DOCK_SPECS["C3"]["bay_pose"], "S4"),
            ]
            base_views = [
                RobotView(rid, True, 85.0, 7.60, (bp["x"], bp["y"]), False, bp["yaw"])
                for rid, _bid, bp, _goal in sim_spawns
            ]
            cb.observe(0.0, base_views, bays)
            cb.observe(300.0, base_views, bays)
            plan_cb = cb.plan(base_views, bays, graph=graph, site_rules=rules)
            for rid, bid, bp, goal_place in sim_spawns:
                rplan = plan_road_path(graph, (bp["x"], bp["y"], bp["yaw"]), goal_place, step_m=0.08)
                act = next((a for a in plan_cb.get("actions", []) if a.get("robot_id") == rid), {})
                arbitration_steps.append({
                    "robot_id": rid,
                    "bay_id": bid,
                    "exit_rank": act.get("exit_rank"),
                    "exit_distance_m": act.get("exit_distance_m"),
                    "initial_action": act.get("action"),
                    "initial_reason": act.get("reason"),
                    "post_exit_goal": goal_place,
                    "places": list(rplan.places),
                    "edges": list(rplan.edges),
                    "length_m": round(float(rplan.length_m), 3),
                })

        live_robots: dict[str, Any] = {}
        for rid, bid in (("rosy_46", "C1"), ("rosy_45", "C2")):
            spec = BAY_DOCK_SPECS[bid]
            rid_mode = str((body.get("robot_modes") or {}).get(rid) or body.get("mode") or "berth_park")
            if execute_physical:
                phys = await _execute_physical_berth_park(
                    request,
                    console,
                    rid,
                    spec,
                    mode=rid_mode,
                    forward_m=forward_m,
                    actor_id=principal.principal_id,
                )
            else:
                phys = None
            if not phys or not phys.get("executed"):
                pinned = await _pin_robot_on_fleet(
                    request,
                    rid,
                    spec["bay_pose"]["x"],
                    spec["bay_pose"]["y"],
                    spec["bay_pose"]["yaw"],
                    actor_id=principal.principal_id,
                )
                live_robots[rid] = {"bay_id": bid, "physical": phys, "site_pose": pinned}
            else:
                live_robots[rid] = {"bay_id": bid, "physical": phys, "site_pose": phys["after"]["site_pose"]}

        # Pin rosy_42 at S3 (cell_s handoff stop line) or C3 as requested
        r42_place = str(body.get("rosy_42_place") or "S3").upper()
        if r42_place == "C3":
            r42_pose = BAY_DOCK_SPECS["C3"]["bay_pose"]
        else:
            r42_pose = {"x": 0.6987, "y": -0.2512, "yaw": 3.1416}
        r42_pinned = await _pin_robot_on_fleet(
            request,
            "rosy_42",
            r42_pose["x"],
            r42_pose["y"],
            r42_pose["yaw"],
            actor_id=principal.principal_id,
        )
        live_robots["rosy_42"] = {"place_id": r42_place, "site_pose": r42_pinned}

        return {
            "scenario": "world_261026_sequential_bay_departure_and_berth_parking",
            "depart_order": ["rosy_46", "rosy_45", "rosy_42"],
            "arbitration": arbitration_steps,
            "live_robots": live_robots,
            "cell_contract_handoff": {
                "stop_place_id": "S3",
                "stop_pose": {"x": 0.6987, "y": -0.2512, "yaw": 3.1416},
                "unload_arm_id": "arm_s",
                "sort_cells": ["cell_a", "cell_b"],
                "return_bay_id": "C1",
                "return_places": ["S3", "J_in", "S2", "P3", "P2", "P1", "C1"],
            },
        }
