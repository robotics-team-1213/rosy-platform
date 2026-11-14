from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from fastapi import HTTPException, Request
from fleet.charge_bays import ChargeBays
from fleet.pipeline import evaluate_fleet_pipeline, resolve_omx_cells, evaluate_omx_cell_station
from fleet.pipeline.cell_fleet_contract import contract_spec_dict, validate_boundary_separation
from fleet.pipeline.station_zones import load_station_zones

from fleet.server.sitemap.pipeline_routes import _enrich_task_health
from fleet.server.sitemap.pipeline_task_input import checked_finite_float, checked_json_value, checked_task_pose


def install_cell_tasks_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    operator_guard = ctx.operator_guard
    STATION_CAMERA_LINKS = ctx.STATION_CAMERA_LINKS
    _arm_live_catalog = ctx._arm_live_catalog
    zones_override_path = ctx.zones_override_path
    _save_ledger = ctx._save_ledger
    _is_human_detected = ctx._is_human_detected
    _evaluate_decision = ctx._evaluate_decision
    inputs = ctx.inputs
    rules = ctx.rules
    active_map = ctx.active_map

    def _aborted(cell_id: str) -> bool:
        state = app.state.omx_cell_states.get(cell_id) or {}
        return state.get("phase") == "ABORTED" or state.get("prev_phase") == "ABORTED"
    @app.get("/api/fleet/pipeline/status", dependencies=read_guard)
    async def pipeline_status():
        active = active_map()
        charge_bays = getattr(app.state, "charge_bays", None) or ChargeBays()
        robots, bays = await inputs(active)
        known_ids = {robot.robot_id for robot in robots}
        for cell_state in app.state.omx_cell_states.values():
            docked = cell_state.get("docked_robot")
            if docked is not None and docked["robot_id"] not in known_ids:
                pose = docked["pose"]
                robots.append(SimpleNamespace(robot_id=docked["robot_id"], kind=docked["robot_kind"],
                                              online=True, pose=(pose["x"], pose["y"]), yaw=pose["yaw"]))
                known_ids.add(docked["robot_id"])
        out = evaluate_fleet_pipeline(active[1], active[2], robots, bays,
                                      charge_bays=charge_bays, site_rules=rules(),
                                      cell_states=getattr(app.state, "omx_cell_states", None))
        out["omx_cell_tasks"] = list(app.state.omx_cell_tasks.values())
        out["pinky_tasks"] = list(app.state.pinky_tasks.values())
        return out

    @app.get("/api/fleet/pipeline/contract", dependencies=read_guard)
    async def pipeline_contract():
        active = active_map()
        cells = resolve_omx_cells(active[1], active[2])
        boundary = validate_boundary_separation(
            ["site_map", "lane_graph", "road_nav2", "corridor_arbitration", "charge_bays"],
            ["omx_arm_ik", "wrist_servo_vision", "area_xyz_directive", "pallet_tier_stacking"])
        return {**contract_spec_dict(), "boundary_check": boundary,
                "omx_cells": {cid: station.to_dict() for cid, station in cells.items()}}

    @app.post("/api/fleet/pipeline/cell-handoff", dependencies=read_guard)
    async def pipeline_cell_handoff(request: Request):
        active = active_map()
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, detail={"code": "INVALID_CELL_HANDOFF"})
        checked_json_value(body)
        cell_id = body.get("cell_id")
        current = app.state.omx_cell_states.get(cell_id) or {}
        active_task = any(t["cell_id"] == cell_id and t["status"] in ("RUNNING", "PAUSED_HUMAN")
                          for t in app.state.omx_cell_tasks.values())
        if (current.get("phase") == "ABORTED" or current.get("prev_phase") == "ABORTED"
                or (active_task and body.get("phase") != "HUMAN_HOLD")):
            raise HTTPException(409, detail={"code": "CELL_TASK_OWNS_HANDOFF"})
        if body.get("phase") not in ("HUMAN_HOLD", "ABORTED"):
            raise HTTPException(409, detail={"code": "CELL_TASK_OWNS_HANDOFF"})
        station = resolve_omx_cells(active[1], active[2]).get(body.get("cell_id"))
        if station is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
        robot = {"robot_id": body["robot_id"], "robot_kind": body["robot_kind"],
                 "pose": {"x": checked_finite_float(body["x"]), "y": checked_finite_float(body["y"]), "yaw": checked_finite_float(body["yaw"])},
                 "wheel_brake_locked": False, "bed_ready": False,
                 "v_cmd_mps": checked_finite_float(body["v_cmd_mps"])}
        state = {key: body[key] for key in ("phase", "tier", "robot_id", "stage_id",
                                             "goal_evidence_digest", "reason") if key in body}
        state["amr_motion_inhibited"] = True
        res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state,
                                        map_version=getattr(active[2], "version", None))
        app.state.omx_cell_states[body["cell_id"]] = {**state, "robot_id": body["robot_id"],
                                                       "docked_robot": robot}
        if body["phase"] == "HUMAN_HOLD":
            app.state.human_detected[cell_id] = True
            app.state.human_detected["all"] = bool(app.state.human_detected.get("cell_s") and app.state.human_detected.get("cell_ab"))
            for task in app.state.omx_cell_tasks.values():
                if task["cell_id"] == cell_id and task["status"] in ("QUEUED", "RUNNING"):
                    task["paused_from_status"] = task["status"]
                    task["status"] = "PAUSED_HUMAN"
                    _enrich_task_health(task)
        _save_ledger()
        return res

    CELL_TASK_PRESETS: dict[str, dict] = {
        "s3_shuttle": {"preset": "s3_shuttle", "label": "S3 셔틀 (arm_s: Pinky -> Belt)", "cell_id": "cell_s", "arm_id": "arm_s", "src_site": "pinky", "dst_site": "belt", "tier": 1, "displaced_to": None},
        "s3_auto_recover_or_shuttle": {"preset": "s3_auto_recover_or_shuttle", "label": "S3 자동 감지·복구 셔틀 (arm_s: Auto ROI -> Belt)", "cell_id": "cell_s", "arm_id": "arm_s", "src_site": "pinky", "dst_site": "belt", "tier": 1, "displaced_to": "auto"},
        "s3_recover_belt_far": {"preset": "s3_recover_belt_far", "label": "S3 이탈 복구 (arm_s: Belt-Far -> Belt)", "cell_id": "cell_s", "arm_id": "arm_s", "src_site": "pinky", "dst_site": "belt", "tier": 1, "displaced_to": "belt_far"},
        "s3_recover_floor_front": {"preset": "s3_recover_floor_front", "label": "S3 바닥 복구 (arm_s: Floor-Front -> Belt)", "cell_id": "cell_s", "arm_id": "arm_s", "src_site": "pinky", "dst_site": "belt", "tier": 1, "displaced_to": "floor_front"},
        "s5_tier1_arm_a": {"preset": "s5_tier1_arm_a", "label": "S5 적재 1층 (arm_a: Belt -> Pallet L0)", "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "pallet-l0", "tier": 1, "displaced_to": None},
        "s5_tier2_arm_b": {"preset": "s5_tier2_arm_b", "label": "S5 적재 2층 (arm_b: Belt -> Pallet L1)", "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "belt", "dst_site": "pallet-l1", "tier": 2, "displaced_to": None},
        "s5_tier3_arm_a": {"preset": "s5_tier3_arm_a", "label": "S5 적재 3층 (arm_a: Belt -> Pallet L2)", "cell_id": "cell_ab", "arm_id": "arm_a", "src_site": "belt", "dst_site": "pallet-l2", "tier": 3, "displaced_to": None},
        "export_s3_belt": {"preset": "export_s3_belt", "label": "반출대 3 반출 (EXP_S3_BELT · arm_s)", "cell_id": "cell_s", "arm_id": "arm_s", "src_site": "pinky", "dst_site": "belt", "tier": 1, "displaced_to": None, "zone_id": "EXP_S3_BELT"},
        "export_s5_pallet": {"preset": "export_s5_pallet", "label": "반출대 2 반출 (EXP_S5_PALLET · arm_b)", "cell_id": "cell_ab", "arm_id": "arm_b", "src_site": "belt", "dst_site": "pallet-l1", "tier": 2, "displaced_to": None, "zone_id": "EXP_S5_PALLET"},
        "full_s3_to_s5_pipeline": {"preset": "full_s3_to_s5_pipeline", "label": "연속 파이프라인 (S3 셔틀 -> S5 1·2층 적재)", "steps": ["s3_shuttle", "s5_tier1_arm_a", "s5_tier2_arm_b"]},
        "full_s3_to_s5_3tier_pipeline": {"preset": "full_s3_to_s5_3tier_pipeline", "label": "연속 파이프라인 (S3 셔틀 -> S5 1·2·3층 적재)", "steps": ["s3_shuttle", "s5_tier1_arm_a", "s5_tier2_arm_b", "s5_tier3_arm_a"]},
    }

    @app.post("/api/fleet/pipeline/displaced-detection", dependencies=operator_guard)
    async def report_displaced_detection(request: Request):
        body = await request.json()
        site = body.get("displaced_to")
        if site not in (None, "", "belt_far", "floor_front"):
            raise HTTPException(422, detail={"code": "INVALID_DISPLACED_SITE"})
        app.state.detected_displaced_site = site or None
        _save_ledger()
        return {"ok": True, "detected_displaced_site": app.state.detected_displaced_site}

    def _enqueue_one_task(active, spec: dict) -> dict:
        cell_id = str(spec.get("cell_id") or "cell_s")
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        if station is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
        task_id = str(spec.get("task_id") or f"cell-task-{uuid.uuid4().hex[:8]}")
        if task_id in app.state.omx_cell_tasks:
            raise HTTPException(409, detail={"code": "CELL_TASK_ID_EXISTS"})
        tier, pose = checked_task_pose(spec, station)
        default_arm = "arm_s" if cell_id == "cell_s" else ("arm_a" if tier % 2 == 1 else "arm_b")
        arm_id = str(spec.get("arm_id") or default_arm)
        directive = spec.get("directive")
        if directive is not None and (not isinstance(directive, dict)
                                      or directive.get("schema") != "rosy.omx-cell-area-xyz-directive.v1"
                                      or directive.get("directive_id") != task_id
                                      or directive.get("arm_id") != arm_id):
            raise HTTPException(422, detail={"code": "INVALID_CELL_DIRECTIVE"})
        raw_disp = spec.get("displaced_to")
        dec_ov = {"displaced_to": raw_disp} if raw_disp in ("belt_far", "floor_front") else {}
        dec_row = _evaluate_decision(cell_id, "arm_target", dec_ov)
        if raw_disp == "auto" or (raw_disp is None and cell_id == "cell_s" and app.state.detected_displaced_site):
            resolved_disp = app.state.detected_displaced_site or "belt_far"
            app.state.detected_displaced_site = None
        else:
            resolved_disp = raw_disp or None
        task = _enrich_task_health({
            "task_id": task_id,
            "cell_id": cell_id,
            "arm_id": arm_id,
            "directive": directive,
            "robot_id": str(spec.get("robot_id") or "rosy_01"),
            "robot_kind": str(spec.get("robot_kind") or "pinky"),
            "src_site": str(spec.get("src_site") or ("pinky" if cell_id == "cell_s" else "belt")),
            "dst_site": str(spec.get("dst_site") or ("belt" if cell_id == "cell_s" else f"pallet-l{max(0, min(2, tier - 1))}")),
            "tier": tier,
            "depends_on": spec.get("depends_on"),
            "displaced_to": resolved_disp,
            "auto_recovered": bool(raw_disp == "auto" or resolved_disp),
            "cable_guard_micro": bool(spec.get("cable_guard_micro", dec_row["cable_guard_micro"])),
            "decision": dec_row,
            "preset": spec.get("preset"),
            "pose": pose,
            "status": "QUEUED",
            "created_at": round(time.time(), 3),
        })
        app.state.omx_cell_tasks[task_id] = task
        _save_ledger()
        return task

    @app.post("/api/fleet/pipeline/cell-tasks", dependencies=operator_guard)
    async def create_cell_task(request: Request):
        active = active_map()
        body = await request.json()
        preset_key = body.get("preset")
        if preset_key:
            preset = CELL_TASK_PRESETS.get(str(preset_key))
            if preset is None:
                raise HTTPException(422, detail={"code": "UNKNOWN_PRESET"})
            if "steps" in preset:
                base_id = str(body.get("task_id") or f"pipe-{uuid.uuid4().hex[:6]}")
                created_tasks = []
                for idx, step in enumerate(preset["steps"]):
                    created_tasks.append(_enqueue_one_task(active, {
                        **CELL_TASK_PRESETS[step], "robot_id": body.get("robot_id", "rosy_01"),
                        "task_id": f"{base_id}-{idx+1}-{step}",
                        "depends_on": created_tasks[-1]["task_id"] if created_tasks else None,
                    }))
                return {"ok": True, "task": created_tasks[0], "tasks": created_tasks}
            merged = {**preset, **{k: v for k, v in body.items() if v is not None}}
            task = _enqueue_one_task(active, merged)
            return {"ok": True, "task": task, "tasks": [task]}
        task = _enqueue_one_task(active, body)
        return {"ok": True, "task": task, "tasks": [task]}

    @app.get("/api/fleet/pipeline/cell-tasks", dependencies=read_guard)
    async def list_cell_tasks(cell_id: str | None = None, status: str | None = None):
        active = active_map()
        all_tasks = [_enrich_task_health(t) for t in app.state.omx_cell_tasks.values()]
        tasks = list(all_tasks)
        if cell_id is not None:
            tasks = [t for t in tasks if t["cell_id"] == cell_id]
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        stations = resolve_omx_cells(active[1], active[2])
        cells_info = {}
        for cid, st in stations.items():
            cstate = app.state.omx_cell_states.get(cid) or {}
            ev = evaluate_omx_cell_station(st, docked_robot=cstate.get("docked_robot"), cell_state=cstate,
                                           map_version=getattr(active[2], "version", None))
            running_t = next((t["task_id"] for t in all_tasks if t["cell_id"] == cid and t["status"] == "RUNNING"), None)
            cells_info[cid] = {**ev, "active_task_id": running_t}
        summary = {
            "total": len(all_tasks),
            "queued": sum(1 for t in all_tasks if t["status"] == "QUEUED"),
            "running": sum(1 for t in all_tasks if t["status"] == "RUNNING"),
            "paused_human": sum(1 for t in all_tasks if t["status"] == "PAUSED_HUMAN"),
            "completed": sum(1 for t in all_tasks if t["status"] == "COMPLETED"),
            "aborted": sum(1 for t in all_tasks if t["status"] in ("ABORTED", "CANCELLED")),
        }
        zones_data = load_station_zones(zones_override_path)
        return {
            "tasks": tasks,
            "summary": summary,
            "cells": cells_info,
            "presets": list(CELL_TASK_PRESETS.values()),
            "detected_displaced_site": app.state.detected_displaced_site,
            "cable_tangled": app.state.cable_tangled,
            "human_safety": {
                "human_detected": dict(app.state.human_detected),
                "active_estop": _is_human_detected(),
            },
            "station_zones": {
                "schema": zones_data["schema"],
                "site_id": zones_data["site_id"],
                "staging_bays": zones_data["staging_bays"],
                "export_stations": zones_data["export_stations"],
            },
            "arm_holds": dict(app.state.arm_holds),
            "arm_live_states": _arm_live_catalog(),
            "station_camera_links": STATION_CAMERA_LINKS,
            "decisions": list(app.state.pipeline_decisions[-20:]),
            "pinky_tasks": list(app.state.pinky_tasks.values()),
        }

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/cancel", dependencies=operator_guard)
    async def cancel_cell_task(task_id: str):
        active = active_map()
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        if task.get("status") != "QUEUED":
            raise HTTPException(409, detail={"code": "CELL_TASK_ALREADY_CLAIMED"})
        cell_id = task["cell_id"]
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        state = app.state.omx_cell_states.get(cell_id) or {}
        res = evaluate_omx_cell_station(station, docked_robot=state.get("docked_robot"), cell_state=state,
                                        map_version=getattr(active[2], "version", None))
        task["status"] = "CANCELLED"
        task["completed_at"] = round(time.time(), 3)
        _enrich_task_health(task)
        _save_ledger()
        return {"ok": True, "task": task, "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/retry", dependencies=operator_guard)
    async def retry_cell_task(task_id: str):
        active = active_map()
        orig = app.state.omx_cell_tasks.get(task_id)
        if orig is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        new_id = f"{task_id}-retry-{uuid.uuid4().hex[:4]}"
        retried = _enqueue_one_task(
            active,
            {
                "task_id": new_id,
                "cell_id": orig["cell_id"],
                "arm_id": orig["arm_id"],
                "robot_id": orig["robot_id"],
                "robot_kind": orig["robot_kind"],
                "src_site": orig["src_site"],
                "dst_site": orig["dst_site"],
                "tier": orig["tier"],
                "displaced_to": orig.get("displaced_to"),
                "preset": orig.get("preset"),
            },
        )
        return {"ok": True, "task": retried, "retried_from": task_id}

    @app.post("/api/fleet/pipeline/pinky-tasks", dependencies=operator_guard)
    async def create_pinky_task(request: Request):
        active = active_map()
        body = await request.json()
        checked_json_value(body)
        robot_id = str(body.get("robot_id") or "rosy_46")
        action = str(body.get("action") or "dock_s3")
        if action != "stop_now" and (_is_human_detected()
                                     or any(state.get("phase") == "HUMAN_HOLD"
                                            for state in app.state.omx_cell_states.values())):
            raise HTTPException(409, detail={"code": "HUMAN_HOLD_ACTIVE"})
        task_id = str(body.get("task_id") or f"pinky-task-{uuid.uuid4().hex[:8]}")
        cable_guard = bool(body.get("cable_guard_micro", True))
        max_step_m = checked_finite_float(body.get("max_step_m", 0.015 if cable_guard else 0.10))
        max_speed_mps = checked_finite_float(body.get("max_speed_mps", 0.02 if cable_guard else 0.08))
        if cable_guard:
            max_step_m, max_speed_mps = min(0.02, max_step_m), min(0.02, max_speed_mps)
        spawned_cell_task = None
        v_cmd = 0.0
        duration_s = 0.0
        if action in ("dock_s3", "dock_and_unload_s3"):
            if _aborted("cell_s"):
                raise HTTPException(409, detail={"code": "CELL_ABORTED_HOLD"})
            target_place = "S3"
            v_cmd = max_speed_mps
            duration_s = round(checked_finite_float(max_step_m / max(0.005, max_speed_mps)), 2)
            if action == "dock_and_unload_s3":
                spawned_cell_task = _enqueue_one_task(active, {**CELL_TASK_PRESETS["s3_shuttle"], "robot_id": robot_id})
        elif action == "dock_s5":
            if _aborted("cell_ab"):
                raise HTTPException(409, detail={"code": "CELL_ABORTED_HOLD"})
            target_place = "S5"
            v_cmd = max_speed_mps
            duration_s = round(checked_finite_float(max_step_m / max(0.005, max_speed_mps)), 2)
        elif action == "micro_forward_2cm":
            target_place = "MICRO_FWD_1.5CM"
            v_cmd = max_speed_mps
            duration_s = 0.35
        elif action == "micro_reverse_2cm":
            target_place = "MICRO_REV_1.5CM"
            v_cmd = -max_speed_mps
            duration_s = 0.35
        elif action == "stop_now":
            target_place = "HOLD_STOP"
            v_cmd = 0.0
            duration_s = 0.0
        elif action in ("charge_c1", "charge_c2"):
            target_place = "C1" if action == "charge_c1" else "C2"
            v_cmd = max_speed_mps
            duration_s = 0.35
        elif action in ("move_staging_c2", "move_staging_s3", "move_export_s1"):
            zones = load_station_zones(zones_override_path)["zones_by_id"]
            zid = "STG_C2" if action == "move_staging_c2" else ("STG_S3_WAIT" if action == "move_staging_s3" else "EXP_S1")
            z = zones.get(zid) or {"id": zid, "place_id": "C2" if "c2" in action else ("S3" if "s3" in action else "S1")}
            target_place = f"{z['id']} ({z.get('place_id', 'S1')})"
            v_cmd = min(max_speed_mps, checked_finite_float(z.get("speed_cap_mps", max_speed_mps)))
            max_step_m = min(max_step_m, checked_finite_float(z.get("max_step_m", max_step_m)))
            duration_s = 0.35
            if action == "move_export_s1" and z.get("cell_id"):
                spawned_cell_task = _enqueue_one_task(active, {
                    "cell_id": z["cell_id"],
                    "arm_id": z.get("arm_id", "arm_a"),
                    "robot_id": robot_id,
                    "src_site": z.get("src_site", "belt"),
                    "dst_site": z.get("dst_site", "pallet"),
                    "tier": int(z.get("tier", 1)),
                    "preset": "export_s1",
                })
        else:
            if any(cstate.get("robot_id") == robot_id and _aborted(cid)
                   for cid, cstate in app.state.omx_cell_states.items()):
                raise HTTPException(409, detail={"code": "CELL_ABORTED_HOLD"})
            target_place = "S1"
            v_cmd = max_speed_mps
            duration_s = 0.35
        dec_row = _evaluate_decision(robot_id, "line_follow", {"tangled": cable_guard})
        ptask = {
            "task_id": task_id,
            "robot_id": robot_id,
            "action": action,
            "target_place": target_place,
            "cable_guard_micro": cable_guard,
            "max_step_m": max_step_m,
            "v_cmd_mps": v_cmd,
            "duration_s": duration_s,
            "decision": dec_row,
            "spawned_cell_task_id": spawned_cell_task["task_id"] if spawned_cell_task else None,
            "status": "QUEUED",
            "created_at": round(time.time(), 3),
        }
        app.state.pinky_tasks[task_id] = ptask
        _save_ledger()
        return {"ok": True, "pinky_task": ptask, "decision": dec_row, "spawned_cell_task": spawned_cell_task}
    ctx.CELL_TASK_PRESETS = CELL_TASK_PRESETS
    ctx._enqueue_one_task = _enqueue_one_task