"""Fleet 접안 모드(Berthing / Reverse-in-Rails Docking) 파킹 및 시나리오 실행 표면 (D-950 / D-972).

다중 충전 베이(C1·C2·C3, 중심 간격 180mm)에서 전진 출차(`FORWARD_UNDOCK`) 및
스테이징 정렬(`ALIGNING`) → 레일 내부 무조향 직진 후진(`REVERSING_IN_RAILS`, `angular = 0.0`) →
후방 스토퍼 안착(`SETTLING` -> `DOCKED/IDLE`) 실물 폐루프 제어 파이프라인과
`world_261026` 순차 출차·접안·S3 셀 핸드오프 시나리오 실행 표면을 제공한다.
"""

from __future__ import annotations

import math
from functools import partial
from typing import Any, Callable, Optional

from fastapi import Depends, Header, HTTPException, Request

from .berth_parking_helpers import (
    BAY_DOCK_SPECS,
    DEFAULT_ROBOT_BAY,
    _execute_physical_berth_park,
    _pin_robot_on_fleet,
    _wrap,
    centerline_axial_gaps,
    infer_bay_id,
)
from .task_dispatch_helpers import compute_road_plan as _compute_road_plan

__all__ = [
    "BAY_DOCK_SPECS",
    "DEFAULT_ROBOT_BAY",
    "_execute_physical_berth_park",
    "_pin_robot_on_fleet",
    "_wrap",
    "centerline_axial_gaps",
    "infer_bay_id",
    "install_berth_parking_routes",
]


def install_berth_parking_routes(
    app,
    *,
    console,
    task_service,
    read_guard,
    operator_guard,
    require_operator,
    require_named_operator,
    compute_road_plan: Callable | None = None,
    dispatch_nav: Callable | None = None,
) -> None:
    if compute_road_plan is None:
        compute_road_plan = partial(_compute_road_plan, console)
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
        principal=Depends(require_named_operator),  # D-540 9: a goal moves the robot
    ) -> dict:
        if busy := console.trip_refusal([robot_id]):  # D-494 5: refused before a task is queued for it
            raise busy
        if task_service is not None and not idempotency_key:
            raise HTTPException(status_code=400, detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key is required for navigation requests"})
        body = await request.json()
        target_x = float(body.get("x", 0.0))
        target_y = float(body.get("y", 0.0))
        target_yaw = float(body.get("yaw")) if body.get("yaw") is not None else None
        place_id = body.get("place_id") or None
        label = str(body.get("label") or "")

        plan = await compute_road_plan(request, robot_id, target_x, target_y, target_yaw, place_id, label)
        final_nav2 = plan["target_nav2"]
        if dispatch_nav is None:
            raise HTTPException(status_code=503, detail={"code": "DISPATCH_UNAVAILABLE"})
        dispatch_res = await dispatch_nav(
            task_service=task_service, console=console, robot_id=robot_id,
            target=final_nav2, actor_id=principal.principal_id, idempotency_key=idempotency_key,
        )
        return {**plan, **dispatch_res, "dispatched": bool(dispatch_res.get("accepted"))}  # QUEUED is not sent

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
        principal=Depends(require_named_operator),  # D-540 9: a berth park moves the robot
    ) -> dict:
        if busy := console.trip_refusal([robot_id]):  # D-494 5
            raise busy
        if task_service is not None and not idempotency_key:
            raise HTTPException(status_code=400, detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key is required for navigation requests"})
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

        final_nav2 = plan["target_nav2"]  # compute_road_plan refuses instead of inventing one
        dispatch_res: dict[str, Any] = {}
        if physical_execution and physical_execution.get("executed"):
            dispatch_res = {"accepted": bool(physical_execution.get("succeeded")), "physical_execution": physical_execution}
        else:
            if dispatch_nav is None:
                raise HTTPException(status_code=503, detail={"code": "DISPATCH_UNAVAILABLE"})
            dispatch_res = await dispatch_nav(
                task_service=task_service, console=console, robot_id=robot_id,
                target=final_nav2, actor_id=principal.principal_id, idempotency_key=idempotency_key,
            )
            if physical_execution is not None:
                dispatch_res["physical_execution"] = physical_execution

        return {
            "dispatched": bool(dispatch_res.get("accepted")),  # QUEUED is reported as queued, not sent
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
