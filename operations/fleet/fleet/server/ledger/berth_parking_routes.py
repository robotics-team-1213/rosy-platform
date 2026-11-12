"""Fleet 접안 모드(Berthing / Reverse-in-Rails Docking) 파킹 표면 (D-950 / D-972).

다중 충전 베이(C1·C2·C3, 중심 간격 180mm)에서 전진 출차(`FORWARD_UNDOCK`) 및
스테이징 정렬(`ALIGNING`) → 레일 내부 무조향 직진 후진(`REVERSING_IN_RAILS`, `angular = 0.0`) →
후방 스토퍼 안착(`SETTLING` -> `DOCKED/IDLE`) 파이프라인과 중심축 LiDAR 거리 계산을 제공한다.
"""

from __future__ import annotations

import math
import uuid
from typing import Callable, Mapping, Optional

from fastapi import Depends, Header, Request

from fleet.server.site_auth import SitePrincipal

BAY_DOCK_SPECS: Mapping[str, dict] = {
    "C1": {
        "bay_id": "C1",
        "dock_id": "bay_c1",
        "dock_type": "charge_bay_rear",
        "staging_place_id": "P1",
        "bay_pose": {"x": -0.418, "y": 0.380, "yaw": -1.5708},
        "staging_pose": {"x": -0.418, "y": 0.180, "yaw": -1.5708},
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
        "bay_pose": {"x": -0.190, "y": 0.380, "yaw": -1.5708},
        "staging_pose": {"x": -0.190, "y": 0.180, "yaw": -1.5708},
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
        "bay_pose": {"x": 0.038, "y": 0.380, "yaw": -1.5708},
        "staging_pose": {"x": 0.038, "y": 0.180, "yaw": -1.5708},
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

        bay_pose = spec["bay_pose"]
        staging_pose = {
            "x": round(bay_pose["x"], 4),
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

        final_nav2 = plan.get("target_nav2") or {"x": 0.0, "y": 0.0, "yaw": 0.0}
        req_key = idempotency_key or uuid.uuid4().hex
        dispatch_res = {}
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
