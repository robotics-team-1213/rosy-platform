"""Decision-layer navigation dispatch and bay-departure scenario route for berth parking."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request

from fleet.charge_bays import ChargeBays, RobotView, bays_from_map
from fleet.hub.hub import HubError
from fleet.routing.graph import build_graph
from fleet.routing.road_path import plan_road_path
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.task_store import IdempotencyConflict
from fleet.site_rules import SiteRules
from fleet.swarm.transport import RobotApiError

from .berth_parking_helpers import BAY_DOCK_SPECS, _execute_physical_berth_park, _pin_robot_on_fleet


async def dispatch_nav_target(
    *,
    task_service,
    console,
    robot_id: str,
    target: dict[str, Any],
    actor_id: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """One dispatch path; HTTP error on failure, queued reported separately from sent."""
    try:
        if task_service is not None:
            task = await task_service.submit_navigation(
                robot_id=robot_id,
                x=target["x"],
                y=target["y"],
                yaw=target["yaw"],
                source="operator",
                actor_id=actor_id,
                request_key=idempotency_key,
            )
            return {
                "accepted": task["status"] == "ACCEPTED",
                "queued": task["status"] == "QUEUED",
                "task": task,
            }
        res = await console.goal(robot_id, target["x"], target["y"], target["yaw"])
        return {"accepted": bool(res.get("accepted")), "receipt": res}
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc)}) from exc
    except ValueError as exc:
        code = str(exc)
        raise HTTPException(status_code=404 if code == "UNKNOWN_ROBOT" else 400, detail={"code": code}) from exc
    except (HubError, RobotApiError, OSError) as exc:
        raise http_error(exc) from exc


def install_berth_scenario_routes(app, *, console, operator_guard, require_operator) -> None:
    """Install the world_261026 sequential bay-departure scenario route."""

    @app.post("/api/fleet/scenario/bay-departure", dependencies=operator_guard, tags=["fleet"])
    async def fleet_scenario_bay_departure(
        request: Request,
        principal: SitePrincipal = Depends(require_operator),
    ) -> dict:
        """시뮬레이션(`bay_departure_sim.py`)과 동일한 `world_261026` 시나리오(C1->C2->C3 순차 출차 중재,
        실물 기체 전진 출차 후 접안 파킹, S3 하역 셀 계약 핸드오프)를 Fleet R에서 실행·검증한다.
        """
        body = await request.json() if await request.body() else {}
        execute_physical = body.get("execute_physical") is True  # opt-in: direct teleop bypasses the Fleet task queue and CORE gate
        forward_m = max(0.12, min(0.25, float(body.get("forward_m") or 0.18)))

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
