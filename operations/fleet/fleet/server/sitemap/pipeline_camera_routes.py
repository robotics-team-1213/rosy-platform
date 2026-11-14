from __future__ import annotations

import time
from fastapi import HTTPException, Request
from fleet.charge_bays import ChargeBays, bays_from_map
from fleet.pipeline import evaluate_fleet_pipeline, resolve_omx_cells, evaluate_omx_cell_station
from fleet.site_rules import SiteRules

from fleet.server.sitemap.pipeline_routes import _enrich_task_health


def install_cameras_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    operator_guard = ctx.operator_guard
    _arm_live_catalog = ctx._arm_live_catalog
    _save_ledger = ctx._save_ledger
    _is_human_detected = ctx._is_human_detected
    rules = ctx.rules
    active_map = ctx.active_map
    # D-136: 이 모듈은 카메라 프레임을 서빙하지 않는다. 셀 카메라 미리보기는
    # POST /api/fleet/vision/lease -> Vision frame_path로만 얻는다(test_no_video_relay).

    @app.post("/api/fleet/pipeline/cell-quality", dependencies=read_guard)
    async def ingest_cell_quality(request: Request):
        body = await request.json()
        cams = body.get("cameras")
        if isinstance(cams, dict):
            for k, v in cams.items():
                if isinstance(v, dict):
                    app.state.cell_camera_quality[str(k)] = v
        holds = body.get("arm_holds")
        if isinstance(holds, dict):
            for arm_id in ("arm_s", "arm_a", "arm_b"):
                if isinstance(holds.get(arm_id), dict):
                    h = holds[arm_id]
                    if arm_id in app.state.pending_clear_arms:
                        continue
                    app.state.arm_holds[arm_id] = {
                        "arm": arm_id,
                        "held": bool(h.get("local_held") or h.get("fleet_held") or h.get("held")),
                        "reason": h.get("local_reason") or h.get("fleet_reason") or h.get("reason"),
                        "incident_ids": list(h.get("incident_ids") or []),
                    }
        arm_states = body.get("arm_states")
        if isinstance(arm_states, dict):
            now_ts = round(time.time(), 3)
            for arm_id in ("arm_s", "arm_a", "arm_b"):
                if isinstance(arm_states.get(arm_id), dict):
                    s = arm_states[arm_id]
                    prev = dict(app.state.arm_live_states.get(arm_id) or {})
                    joints = s.get("joints_deg") or s.get("state")
                    if isinstance(joints, list) and len(joints) >= 6:
                        prev["joints_deg"] = [round(float(x), 1) for x in joints[:6]]
                    if "folded" in s and s["folded"] is not None:
                        prev["folded"] = bool(s["folded"])
                    if s.get("temp_c") is not None:
                        prev["temp_c"] = round(float(s["temp_c"]), 1)
                    if s.get("current_ma") is not None:
                        prev["current_ma"] = round(float(s["current_ma"]), 1)
                    if s.get("voltage_v") is not None:
                        prev["voltage_v"] = round(float(s["voltage_v"]), 2)
                    prev["updated_at"] = float(s.get("updated_at") or now_ts)
                    prev["source"] = str(s.get("source") or "live_stream")
                    app.state.arm_live_states[arm_id] = prev
        pending = dict(app.state.pending_clear_arms)
        app.state.pending_clear_arms.clear()
        return {
            "ok": True,
            "schema": "rosy.pipeline.cell-quality.v1",
            "cameras_updated": len(app.state.cell_camera_quality),
            "arm_holds": app.state.arm_holds,
            "arm_live_states": _arm_live_catalog(),
            "pending_clear_arms": pending,
        }

    @app.post("/api/fleet/pipeline/arm-holds/clear", dependencies=operator_guard)
    async def clear_pipeline_arm_holds(request: Request):
        body = await request.json()
        target = str(body.get("arm_id") or body.get("cell_id") or "all")
        note = str(body.get("note") or "verified folded home and cleared hold from Fleet console").strip()
        if not note:
            raise HTTPException(400, detail={"code": "EMPTY_CLEAR_NOTE"})
        if target == "cell_s":
            arms = ["arm_s"]
        elif target == "cell_ab":
            arms = ["arm_a", "arm_b"]
        elif target in ("arm_s", "arm_a", "arm_b"):
            arms = [target]
        else:
            arms = ["arm_s", "arm_a", "arm_b"]
        for a in arms:
            app.state.arm_holds[a] = {"arm": a, "held": False, "reason": None, "incident_ids": [], "last_cleared_note": note}
            app.state.pending_clear_arms[a] = note
        return {"ok": True, "cleared_arms": arms, "note": note, "arm_holds": app.state.arm_holds}

    @app.post("/api/fleet/pipeline/cell-tasks/claim", dependencies=read_guard)
    async def claim_cell_task(request: Request):
        active = active_map()
        body = await request.json()
        cell_id = str(body.get("cell_id") or "cell_s")
        if _is_human_detected(cell_id):
            return {"claimed": False, "task": None, "blocked_by_human": True, "reason": "HUMAN_DETECTED_ESTOP"}
        req_id = body.get("task_id")
        candidates = [
            t for t in app.state.omx_cell_tasks.values()
            if t["cell_id"] == cell_id and t["status"] == "QUEUED" and (req_id is None or t["task_id"] == req_id)
        ]
        if not candidates:
            return {"claimed": False, "task": None}
        task = candidates[0]
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        if station is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
        robot = {
            "robot_id": task["robot_id"],
            "robot_kind": task["robot_kind"],
            "pose": dict(task["pose"]),
            "wheel_brake_locked": True,
            "bed_ready": True,
            "v_cmd_mps": 0.0,
        }
        state = {"phase": "ARM_IN_BED_ZONE", "tier": task["tier"], "robot_id": task["robot_id"], "stage_id": task["task_id"]}
        res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state,
                                        map_version=getattr(active[2], "version", None))
        app.state.omx_cell_states[cell_id] = {**state, "docked_robot": robot}
        task["status"] = "RUNNING"
        task["claimed_at"] = round(time.time(), 3)
        _enrich_task_health(task)
        _save_ledger()
        handoff = {
            **res["handoff"],
            "arm_id": task["arm_id"],
            "src_site": task["src_site"],
            "dst_site": task["dst_site"],
            "displaced_to": task.get("displaced_to"),
        }
        return {"claimed": True, "task": task, "handoff": handoff, "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/complete", dependencies=read_guard)
    async def complete_cell_task(task_id: str, request: Request):
        active = active_map()
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        body = await request.json()
        cell_id = task["cell_id"]
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        phase = str(body.get("phase") or "RELEASED")
        robot = {
            "robot_id": task["robot_id"],
            "robot_kind": task["robot_kind"],
            "pose": dict(task["pose"]),
            "wheel_brake_locked": True,
            "bed_ready": True,
            "v_cmd_mps": 0.0,
        }
        state = {
            "phase": phase,
            "tier": task["tier"],
            "robot_id": task["robot_id"],
            "stage_id": task_id,
            "goal_evidence_digest": body.get("goal_evidence_digest"),
            "reason": body.get("reason", "TRANSFER_CONFIRMED"),
        }
        res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state,
                                        map_version=getattr(active[2], "version", None))
        app.state.omx_cell_states[cell_id] = {**state, "docked_robot": robot}
        task["status"] = "COMPLETED" if phase == "RELEASED" else "ABORTED"
        task["completed_at"] = round(time.time(), 3)
        task["receipt"] = body.get("receipt") or state
        task["stage_result"] = body.get("stage_result")
        task["hardware_telemetry"] = body.get("hardware_telemetry")
        stop_ev = ((task.get("hardware_telemetry") or {}).get("stop_event") or {})
        arm_id = task.get("arm_id")
        if arm_id in ("arm_s", "arm_a", "arm_b") and isinstance(stop_ev.get("state"), list) and len(stop_ev["state"]) >= 6:
            prev = dict(app.state.arm_live_states.get(arm_id) or {})
            health = stop_ev.get("health") or {}
            temps = health.get("temp_c") or []
            curs = health.get("current_ma") or []
            prev["joints_deg"] = [round(float(x), 1) for x in stop_ev["state"][:6]]
            prev["folded"] = bool(stop_ev.get("folded", False))
            if temps:
                prev["temp_c"] = round(float(max(temps)), 1)
            if curs:
                prev["current_ma"] = round(float(max(curs)), 1)
            prev["updated_at"] = task["completed_at"]
            prev["source"] = "task_complete"
            prev["last_task_id"] = task_id
            app.state.arm_live_states[arm_id] = prev
        _enrich_task_health(task)
        _save_ledger()
        return {"ok": True, "task": task, "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/evaluate", dependencies=read_guard)
    async def pipeline_evaluate(request: Request):
        active = active_map()
        body = await request.json()
        body_robots = body.get("robots", [])
        robots = [type("PipelineRobot", (), {
            "robot_id": row["robot_id"], "kind": row.get("kind"), "online": row.get("online", True),
            "percent": row.get("percent"), "voltage": row.get("voltage"),
            "pose": (row["x"], row["y"]), "yaw": row.get("yaw"),
            "on_trip": row.get("on_trip", False),
        })() for row in body_robots]
        bays = bays_from_map(active[1])
        active_rules = rules()
        if body.get("order") is not None or body.get("exit_place") is not None:
            rule_body = active_rules.body() if active_rules is not None else SiteRules().body()
            if body.get("order") is not None:
                if body["order"] not in ("exit_nearest", "fair"):
                    raise HTTPException(422, detail={"code": "INVALID_ORDER"})
                rule_body["departure"]["order"] = body["order"]
            if body.get("exit_place") is not None:
                if body["exit_place"] not in {place.id for place in active[1].places}:
                    raise HTTPException(422, detail={"code": "INVALID_EXIT_PLACE"})
                rule_body["return"]["exit_place"] = body["exit_place"]
            active_rules = SiteRules.model_validate(rule_body)
        charge_bays = None
        if any(row.get("percent") is not None or row.get("voltage") is not None for row in body_robots):
            charge_bays = ChargeBays(
                rate_pct_per_min=15.0,
                thresholds=(lambda: (active_rules.return_.go_percent, active_rules.return_.leave_percent))
                if active_rules is not None else lambda: (15.0, 80.0))
            seed_t0 = [type("PipelineRobot", (), {
                "robot_id": r.robot_id, "kind": r.kind, "online": r.online,
                "percent": min(50.0, float(r.percent)) if r.percent is not None else 50.0,
                "voltage": 7.40, "pose": r.pose, "yaw": r.yaw, "on_trip": r.on_trip,
            })() for r in robots]
            seed_t1 = [type("PipelineRobot", (), {
                "robot_id": r.robot_id, "kind": r.kind, "online": r.online,
                "percent": min(50.0, float(r.percent)) if r.percent is not None else 50.0,
                "voltage": r.voltage if r.voltage is not None else 7.50,
                "pose": r.pose, "yaw": r.yaw, "on_trip": r.on_trip,
            })() for r in robots]
            charge_bays.observe(0.0, seed_t0, bays)
            charge_bays.observe(1.0, seed_t1, bays)
            charge_bays.observe(300.0 if any((r.percent or 0) >= 80.0 for r in robots) else 2.0, robots, bays)
        goals = {
            row["robot_id"]: tuple(row["goal"]) if isinstance(row["goal"], list) else row["goal"]
            for row in body_robots if row.get("goal") is not None
        }
        result = evaluate_fleet_pipeline(active[1], active[2], robots, bays, charge_bays=charge_bays,
                                         site_rules=active_rules, goals_by_robot=goals,
                                         cell_states={**getattr(app.state, "omx_cell_states", {}),
                                                      **(body.get("cell_states") or {})})
        return {**result, "dispatch": False}

