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

from fleet.hub.hub import HubError
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.task_store import IdempotencyConflict
from fleet.swarm.transport import RobotApiError
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
    require_named_operator,
    compute_road_plan: Callable | None = None,
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
        principal: SitePrincipal = Depends(require_named_operator),
    ) -> dict:
        if busy := console.trip_refusal([robot_id]):  # D-494 5
            raise HTTPException(409, {"code": busy.code, "message": f"{robot_id} is on a running trip"})
        if task_service is not None and not idempotency_key:
            raise HTTPException(status_code=400, detail={
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Idempotency-Key is required for navigation requests",
            })
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

        final_nav2 = plan.get("target_nav2")
        dispatch_res: dict[str, Any] = {}
        if physical_execution and physical_execution.get("executed"):
            dispatch_res = {"accepted": True, "physical_execution": physical_execution}
        else:
            if not final_nav2:
                raise HTTPException(status_code=409, detail={"code": "ROUTE_POSE_UNTRUSTED"})
            try:
                if task_service is not None:
                    task = await task_service.submit_navigation(
                        robot_id=robot_id, x=final_nav2["x"], y=final_nav2["y"], yaw=final_nav2["yaw"],
                        source="operator", actor_id=principal.principal_id, request_key=idempotency_key,
                    )
                    dispatch_res = {"accepted": task["status"] == "ACCEPTED",
                                    "queued": task["status"] == "QUEUED", "task": task}
                else:
                    res = await console.goal(robot_id, final_nav2["x"], final_nav2["y"], final_nav2["yaw"])
                    dispatch_res = {"accepted": bool(res.get("accepted")), "receipt": res}
            except IdempotencyConflict as exc:
                raise HTTPException(status_code=409, detail={
                    "code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}) from exc
            except ValueError as exc:
                code = str(exc)
                raise HTTPException(status_code=404 if code == "UNKNOWN_ROBOT" else 400,
                                    detail={"code": code}) from exc
            except (HubError, RobotApiError, OSError) as exc:
                raise http_error(exc) from exc
            if physical_execution is not None:
                dispatch_res["physical_execution"] = physical_execution

        return {
            "dispatched": bool(dispatch_res.get("accepted") or dispatch_res.get("queued")),
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
        principal: SitePrincipal = Depends(require_named_operator),
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
