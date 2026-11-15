from __future__ import annotations

import hashlib
import json
import time
from fastapi import HTTPException, Request
from fleet.charge_bays import ChargeBays, bays_from_map
from fleet.pipeline import evaluate_fleet_pipeline, resolve_omx_cells, evaluate_omx_cell_station
from fleet.site_rules import SiteRules

from fleet.server.sitemap.pipeline_routes import _enrich_task_health


def install_cameras_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    operator_guard = ctx.operator_guard
    proposer_guard = getattr(ctx, "proposer_guard", operator_guard)
    _arm_live_catalog = ctx._arm_live_catalog
    _save_ledger = ctx._save_ledger
    _is_human_detected = ctx._is_human_detected
    rules = ctx.rules
    _ready_amr = ctx._ready_amr
    omx_evidence_fn = ctx.omx_evidence_fn
    active_map = ctx.active_map
    # D-136: 이 모듈은 카메라 프레임을 서빙하지 않는다. 셀 카메라 미리보기는
    # POST /api/fleet/vision/lease -> Vision frame_path로만 얻는다(test_no_video_relay).

    @app.post("/api/fleet/pipeline/cell-quality", dependencies=proposer_guard)
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
                    new_held = bool(h.get("local_held") or h.get("fleet_held") or h.get("held"))
                    if arm_id in app.state.pending_clear_arms:
                        if not new_held:
                            app.state.pending_clear_arms.pop(arm_id, None)
                        continue
                    prev_held = bool((app.state.arm_holds.get(arm_id) or {}).get("held"))
                    if prev_held and not new_held:
                        continue  # Clearing an arm hold requires POST /arm-holds/clear.
                    app.state.arm_holds[arm_id] = {
                        "arm": arm_id,
                        "held": new_held,
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
        for ack_arm in body.get("clear_ack_arms") or ():
            app.state.pending_clear_arms.pop(str(ack_arm), None)
        pending = dict(app.state.pending_clear_arms)
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

    @app.post("/api/fleet/pipeline/cell-tasks/claim", dependencies=proposer_guard)
    async def claim_cell_task(request: Request):
        if app.state._pipeline_ledger_fault:
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})
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
        if type(task.get("tier")) is not int or task["tier"] not in (1, 2, 3):
            return {"claimed": False, "task": task, "reason": "INVALID_CELL_TIER"}
        predecessor = task.get("depends_on")
        if predecessor and (app.state.omx_cell_tasks.get(predecessor) or {}).get("status") != "COMPLETED":
            return {"claimed": False, "task": task, "reason": "PREVIOUS_TIER_NOT_VERIFIED"}
        active_task = next((t for t in app.state.omx_cell_tasks.values()
                            if t["cell_id"] == cell_id and t["status"] == "RUNNING"), None)
        cell_state = app.state.omx_cell_states.get(cell_id) or {}
        if active_task is not None or cell_state.get("phase") in ("ARM_IN_BED_ZONE", "HUMAN_HOLD") or cell_state.get("amr_motion_inhibited"):
            return {"claimed": False, "task": task, "reason": "CELL_BUSY_OR_HELD"}
        amr = _ready_amr(task)
        if amr is None:
            return {"claimed": False, "task": task, "reason": "AMR_BRAKE_BED_VELOCITY_UNMEASURED"}
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        if station is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
        robot = {
            "robot_id": task["robot_id"],
            "robot_kind": task["robot_kind"],
            "pose": dict(amr["pose"]),
            "wheel_brake_locked": amr["wheel_brake_locked"],
            "bed_ready": amr["bed_ready"],
            "v_cmd_mps": amr["v_cmd_mps"],
        }
        state = {"phase": "ARM_IN_BED_ZONE", "tier": task["tier"], "robot_id": task["robot_id"], "stage_id": task["task_id"]}
        res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state,
                                        map_version=getattr(active[2], "version", None))
        if res["gate"].get("cell_can_claim") is not True or res.get("handoff") is None:
            return {"claimed": False, "task": task, "gate": res["gate"]}
        app.state.omx_cell_states[cell_id] = {**state, "docked_robot": robot}
        task["status"] = "RUNNING"
        task["amr_claim_evidence"] = dict(amr)
        task["handoff_lease_id"] = res["handoff"].get("handoff_lease_id")
        task["claimed_at"] = round(time.time(), 3)
        _enrich_task_health(task)
        _save_ledger()
        handoff = {
            **res["handoff"],
            "task_id": task["task_id"],
            "arm_id": task["arm_id"],
            "tier": task["tier"],
            "directive": task.get("directive"),
            "src_site": task["src_site"],
            "dst_site": task["dst_site"],
            "displaced_to": task.get("displaced_to"),
        }
        return {"claimed": True, "task": task, "handoff": handoff, "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/complete", dependencies=proposer_guard)
    async def complete_cell_task(task_id: str, request: Request):
        if app.state._pipeline_ledger_fault:
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"})
        active = active_map()
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, detail={"code": "INVALID_CELL_COMPLETION"})
        try:
            json.dumps(body, allow_nan=False)
        except (TypeError, ValueError):
            raise HTTPException(422, detail={"code": "INVALID_CELL_COMPLETION"}) from None
        cell_id = task["cell_id"]
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        phase = body.get("phase")
        if task.get("status") != "RUNNING" or phase not in ("RELEASED", "ABORTED"):
            raise HTTPException(409, detail={"code": "CELL_TASK_NOT_RUNNING_OR_PHASE_MISSING"})
        if phase == "RELEASED" and (_is_human_detected(cell_id)
                                    or (app.state.omx_cell_states.get(cell_id) or {}).get("phase") == "HUMAN_HOLD"):
            raise HTTPException(409, detail={"code": "HUMAN_HOLD_ACTIVE"})
        amr = _ready_amr(task) if phase == "RELEASED" else task.get("amr_claim_evidence")
        if phase == "RELEASED" and amr is None:
            raise HTTPException(422, detail={"code": "AMR_BRAKE_BED_VELOCITY_UNMEASURED"})
        if phase == "RELEASED":
            trusted = omx_evidence_fn(task) if callable(omx_evidence_fn) else None
            if not isinstance(trusted, dict):
                raise HTTPException(422, detail={"code": "OMX_OWNER_EVIDENCE_UNAVAILABLE"})
            receipt = body.get("receipt") if isinstance(body.get("receipt"), dict) else {}
            stage_result = body.get("stage_result") if isinstance(body.get("stage_result"), dict) else {}
            verification = stage_result.get("verification") if isinstance(stage_result.get("verification"), dict) else {}
            hardware = body.get("hardware_telemetry") if isinstance(body.get("hardware_telemetry"), dict) else {}
            if trusted != {"receipt": receipt, "stage_result": stage_result, "hardware_telemetry": hardware}:
                raise HTTPException(422, detail={"code": "OMX_OWNER_EVIDENCE_MISMATCH"})
            stop_event = hardware.get("stop_event") if isinstance(hardware.get("stop_event"), dict) else {}
            evidence = {"task_id": task_id, "lease": receipt.get("handoff_lease_id"),
                        "stage_result": stage_result, "hardware_telemetry": hardware}
            digest = "sha256:" + hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
            verified = (type(task.get("tier")) is int and task["tier"] in (1, 2, 3)
                        and receipt.get("physical_completion") is True
                        and receipt.get("simulated_success") is False
                        and receipt.get("phase") == "RELEASED"
                        and receipt.get("stage_id") == task_id and receipt.get("cell_id") == cell_id
                        and bool(task.get("handoff_lease_id"))
                        and receipt.get("handoff_lease_id") == task.get("handoff_lease_id")
                        and receipt.get("goal_evidence_digest") == body.get("goal_evidence_digest") == digest
                        and stage_result.get("directive_id") == task_id
                        and stage_result.get("arm_id") == task.get("arm_id")
                        and stage_result.get("task_verified") is True
                        and verification.get("verified") is True
                        and verification.get("basis") == "predefined_side_and_top_target_zones"
                        and stop_event.get("ok") is True and stop_event.get("folded") is True)
            if cell_id == "cell_ab":
                place = stage_result.get("place") or {}
                z_gate = verification.get("z_gate") if isinstance(verification.get("z_gate"), dict) else {}
                if not isinstance(place, dict):
                    place = {}
                verified = (verified and z_gate.get("verdict") == "PASS"
                            and str(place.get("area") or place.get("area_id") or "").lower() == "pallet"
                            and type(place.get("tier")) is int and place["tier"] == task["tier"])
            if not verified:
                raise HTTPException(422, detail={"code": "UNVERIFIED_CELL_COMPLETION"})
        robot = {
            "robot_id": task["robot_id"],
            "robot_kind": task["robot_kind"],
            "pose": dict((amr or {}).get("pose") or task["pose"]),
            "wheel_brake_locked": bool((amr or {}).get("wheel_brake_locked")),
            "bed_ready": bool((amr or {}).get("bed_ready")),
            "v_cmd_mps": float((amr or {}).get("v_cmd_mps", 1.0)),
        }
        state = {
            "phase": phase,
            "tier": task["tier"],
            "robot_id": task["robot_id"],
            "stage_id": task_id,
            "goal_evidence_digest": body.get("goal_evidence_digest"),
            "reason": body.get("reason") or ("TRANSFER_CONFIRMED" if phase == "RELEASED" else "TASK_ABORTED"),
            "amr_motion_inhibited": phase == "ABORTED",
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
