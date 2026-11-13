from __future__ import annotations

import time
import uuid
from pathlib import Path
from fastapi import HTTPException, Request
from fleet.pipeline import resolve_omx_cells
from fleet.pipeline.station_zones import load_station_zones, save_station_zones_yaml

from fleet.server.sitemap.pipeline_routes import _enrich_task_health, _storage_dir


def install_gates_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    zones_override_path = ctx.zones_override_path
    _save_ledger = ctx._save_ledger
    _is_human_detected = ctx._is_human_detected
    _evaluate_decision = ctx._evaluate_decision
    active_map = ctx.active_map
    CELL_TASK_PRESETS = ctx.CELL_TASK_PRESETS
    _enqueue_one_task = ctx._enqueue_one_task
    @app.get("/api/fleet/pipeline/human-safety-gate", dependencies=read_guard)
    async def get_human_safety_gate():
        return {
            "ok": True,
            "human_detected": dict(app.state.human_detected),
            "active_estop": _is_human_detected(),
            "cells": {cid: (app.state.omx_cell_states.get(cid) or {}).get("phase", "IDLE") for cid in ("cell_s", "cell_ab")},
            "paused_tasks": [t["task_id"] for t in app.state.omx_cell_tasks.values() if t["status"] == "PAUSED_HUMAN"],
        }

    @app.post("/api/fleet/pipeline/human-safety-gate", dependencies=read_guard)
    async def set_human_safety_gate(request: Request):
        active = active_map()
        body = await request.json()
        target_cell = str(body.get("cell_id") or "all")
        if target_cell not in ("cell_s", "cell_ab", "all"):
            target_cell = "all"
        if body.get("toggle"):
            detected = not _is_human_detected(None if target_cell == "all" else target_cell)
        else:
            detected = bool(body.get("human_detected", True))
        affected_cells = ["cell_s", "cell_ab"] if target_cell == "all" else [target_cell]
        if target_cell == "all":
            app.state.human_detected = {"cell_s": detected, "cell_ab": detected, "all": detected}
        else:
            app.state.human_detected[target_cell] = detected
            app.state.human_detected["all"] = bool(app.state.human_detected.get("cell_s") and app.state.human_detected.get("cell_ab"))

        stations = resolve_omx_cells(active[1], active[2])
        paused_tasks: list[str] = []
        resumed_tasks: list[str] = []
        pinky_estop = None

        if detected:
            for cid in affected_cells:
                st = stations[cid]
                prev = dict(app.state.omx_cell_states.get(cid) or {})
                prev_phase = prev.get("phase") if prev.get("phase") != "HUMAN_HOLD" else (prev.get("prev_phase") or "CLAIMED")
                docked = prev.get("docked_robot") or {
                    "robot_id": prev.get("robot_id") or "rosy_46",
                    "robot_kind": "pinky",
                    "pose": {"x": st.station_xy[0], "y": st.station_xy[1], "yaw": 0.0},
                    "wheel_brake_locked": True,
                    "bed_ready": True,
                    "v_cmd_mps": 0.0,
                }
                app.state.omx_cell_states[cid] = {
                    **prev,
                    "phase": "HUMAN_HOLD",
                    "prev_phase": prev_phase,
                    "amr_motion_inhibited": True,
                    "reason": str(body.get("reason") or "HUMAN_DETECTED_ESTOP"),
                    "docked_robot": docked,
                }
            for t in app.state.omx_cell_tasks.values():
                if t["cell_id"] in affected_cells and t["status"] in ("QUEUED", "RUNNING"):
                    t["paused_from_status"] = t["status"]
                    t["status"] = "PAUSED_HUMAN"
                    _enrich_task_health(t)
                    paused_tasks.append(t["task_id"])
            pid = f"pinky-estop-{uuid.uuid4().hex[:6]}"
            pinky_estop = {
                "task_id": pid,
                "robot_id": str(body.get("robot_id") or "rosy_46"),
                "action": "stop_now",
                "target_place": "HUMAN_ESTOP",
                "cable_guard_micro": True,
                "max_step_m": 0.0,
                "v_cmd_mps": 0.0,
                "duration_s": 0.0,
                "decision": _evaluate_decision(target_cell if target_cell != "all" else "cell_s", "arm_target", {"human_detected": True}),
                "spawned_cell_task_id": None,
                "status": "COMPLETED",
                "created_at": round(time.time(), 3),
            }
            app.state.pinky_tasks[pid] = pinky_estop
        else:
            for t in app.state.omx_cell_tasks.values():
                if t["cell_id"] in affected_cells and t["status"] == "PAUSED_HUMAN":
                    t["status"] = "QUEUED"
                    _enrich_task_health(t)
                    resumed_tasks.append(t["task_id"])
            for cid in affected_cells:
                prev = dict(app.state.omx_cell_states.get(cid) or {})
                has_queued = any(t["cell_id"] == cid and t["status"] == "QUEUED" for t in app.state.omx_cell_tasks.values())
                restored_phase = "CLAIMED" if has_queued else (prev.get("prev_phase") if prev.get("prev_phase") in ("CLAIMED", "RELEASED") else "RELEASED")
                app.state.omx_cell_states[cid] = {
                    **prev,
                    "phase": restored_phase,
                    "amr_motion_inhibited": restored_phase in ("CLAIMED", "ARM_IN_BED_ZONE"),
                    "reason": "HUMAN_CLEARED_AUTO_RESUME",
                }
            _evaluate_decision(target_cell if target_cell != "all" else "cell_s", "arm_target", {"human_detected": False})

        _save_ledger()
        return {
            "ok": True,
            "human_detected": dict(app.state.human_detected),
            "active_estop": _is_human_detected(),
            "paused_tasks": paused_tasks,
            "resumed_tasks": resumed_tasks,
            "pinky_estop": pinky_estop,
            "cells": {cid: app.state.omx_cell_states.get(cid) for cid in ("cell_s", "cell_ab")},
        }

    @app.get("/api/fleet/pipeline/station-zones", dependencies=read_guard)
    async def get_station_zones():
        return {"ok": True, **load_station_zones(zones_override_path)}

    @app.put("/api/fleet/pipeline/station-zones", dependencies=read_guard)
    async def update_station_zones(request: Request):
        body = await request.json()
        yaml_text = str(body.get("yaml_text") or "")
        if not yaml_text.strip():
            raise HTTPException(422, detail={"code": "EMPTY_YAML"})
        try:
            updated = save_station_zones_yaml(yaml_text, zones_override_path)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": "INVALID_STATION_ZONES_YAML", "message": str(exc)})
        return {"ok": True, **updated}

    @app.post("/api/fleet/pipeline/station-zones/dispatch", dependencies=read_guard)
    async def dispatch_station_zone(request: Request):
        active = active_map()
        body = await request.json()
        zone_id = str(body.get("zone_id") or "STG_C2")
        robot_id = str(body.get("robot_id") or "rosy_46")
        zones_info = load_station_zones(zones_override_path)
        zone = zones_info["zones_by_id"].get(zone_id)
        if zone is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_STATION_ZONE", "zone_id": zone_id})
        if _is_human_detected(zone.get("cell_id")):
            raise HTTPException(409, detail={"code": "HUMAN_ESTOP_ACTIVE", "message": "사람 감지 비상정지 중에는 구역 배차를 실행할 수 없습니다"})
        cable_guard = bool(app.state.cable_tangled)
        max_step_m = min(0.015 if cable_guard else 0.10, float(zone.get("max_step_m", 0.015)))
        v_cmd = min(0.02 if cable_guard else 0.08, float(zone.get("speed_cap_mps", 0.02)))
        spawned_cell_task = None
        if zone.get("kind") == "export" and zone.get("cell_id"):
            spawned_cell_task = _enqueue_one_task(
                active,
                {
                    "cell_id": zone["cell_id"],
                    "arm_id": zone.get("arm_id", "arm_s" if zone["cell_id"] == "cell_s" else "arm_a"),
                    "robot_id": robot_id,
                    "src_site": zone.get("src_site", "pinky" if zone["cell_id"] == "cell_s" else "belt"),
                    "dst_site": zone.get("dst_site", "belt" if zone["cell_id"] == "cell_s" else "pallet"),
                    "tier": int(zone.get("tier", 1)),
                    "preset": f"zone_{zone_id.lower()}",
                },
            )
        pid = f"pinky-zone-{uuid.uuid4().hex[:6]}"
        ptask = {
            "task_id": pid,
            "robot_id": robot_id,
            "action": f"zone_dispatch:{zone_id}",
            "zone_id": zone_id,
            "zone_kind": zone.get("kind"),
            "target_place": f"{zone_id} ({zone.get('place_id', '')})",
            "cable_guard_micro": cable_guard,
            "max_step_m": max_step_m,
            "v_cmd_mps": v_cmd,
            "duration_s": 0.35,
            "decision": _evaluate_decision(robot_id, "line_follow", {"tangled": cable_guard}),
            "spawned_cell_task_id": spawned_cell_task["task_id"] if spawned_cell_task else None,
            "status": "COMPLETED",
            "created_at": round(time.time(), 3),
        }
        app.state.pinky_tasks[pid] = ptask
        _save_ledger()
        return {"ok": True, "zone": zone, "pinky_task": ptask, "spawned_cell_task": spawned_cell_task}

    @app.post("/api/fleet/pipeline/cable-guard", dependencies=read_guard)
    async def set_cable_guard(request: Request):
        body = await request.json()
        if body.get("toggle"):
            app.state.cable_tangled = not bool(app.state.cable_tangled)
        else:
            app.state.cable_tangled = bool(body.get("cable_tangled", True))
        dec = _evaluate_decision(str(body.get("robot_id") or "rosy_46"), "line_follow", {"tangled": app.state.cable_tangled})
        _save_ledger()
        return {"ok": True, "cable_tangled": app.state.cable_tangled, "decision": dec}

    @app.post("/api/fleet/pipeline/vision-auto-check", dependencies=read_guard)
    async def run_vision_auto_check(request: Request):
        active = active_map()
        body = await request.json()
        cell_id = str(body.get("cell_id") or "cell_s")
        if cell_id not in ("cell_s", "cell_ab", "all"):
            cell_id = "cell_s"
        snap_bytes = 0
        for base in (_storage_dir(), Path("/tmp")):
            snap_file = base / f"rosy-cell-cam-{cell_id if cell_id != 'all' else 'cell_s'}.jpg"
            if snap_file.is_file():
                snap_bytes = snap_file.stat().st_size
                break
        intrusion_score = float(body.get("intrusion_score", 0.05))
        human_detected = bool(body["human_detected"]) if "human_detected" in body else (intrusion_score >= 0.35)
        displaced_to = body.get("displaced_to")
        if displaced_to in ("belt_far", "floor_front", None, ""):
            if "displaced_to" in body:
                app.state.detected_displaced_site = displaced_to or None

        was_detected = _is_human_detected(None if cell_id == "all" else cell_id)
        paused_tasks: list[str] = []
        resumed_tasks: list[str] = []
        affected_cells = ["cell_s", "cell_ab"] if cell_id == "all" else [cell_id]
        stations = resolve_omx_cells(active[1], active[2])

        if human_detected:
            for cid in affected_cells:
                app.state.human_detected[cid] = True
                st = stations[cid]
                prev = dict(app.state.omx_cell_states.get(cid) or {})
                prev_phase = prev.get("phase") if prev.get("phase") != "HUMAN_HOLD" else (prev.get("prev_phase") or "CLAIMED")
                docked = prev.get("docked_robot") or {
                    "robot_id": prev.get("robot_id") or "rosy_46",
                    "robot_kind": "pinky",
                    "pose": {"x": st.station_xy[0], "y": st.station_xy[1], "yaw": 0.0},
                    "wheel_brake_locked": True,
                    "bed_ready": True,
                    "v_cmd_mps": 0.0,
                }
                app.state.omx_cell_states[cid] = {
                    **prev,
                    "phase": "HUMAN_HOLD",
                    "prev_phase": prev_phase,
                    "amr_motion_inhibited": True,
                    "reason": "VISION_HUMAN_DETECTED_ESTOP",
                    "docked_robot": docked,
                }
            app.state.human_detected["all"] = bool(app.state.human_detected.get("cell_s") and app.state.human_detected.get("cell_ab"))
            for t in app.state.omx_cell_tasks.values():
                if t["cell_id"] in affected_cells and t["status"] in ("QUEUED", "RUNNING"):
                    t["paused_from_status"] = t["status"]
                    t["status"] = "PAUSED_HUMAN"
                    _enrich_task_health(t)
                    paused_tasks.append(t["task_id"])
        elif was_detected:
            for cid in affected_cells:
                app.state.human_detected[cid] = False
            app.state.human_detected["all"] = False
            for t in app.state.omx_cell_tasks.values():
                if t["cell_id"] in affected_cells and t["status"] == "PAUSED_HUMAN":
                    t["status"] = "QUEUED"
                    _enrich_task_health(t)
                    resumed_tasks.append(t["task_id"])
            for cid in affected_cells:
                prev = dict(app.state.omx_cell_states.get(cid) or {})
                has_queued = any(t["cell_id"] == cid and t["status"] == "QUEUED" for t in app.state.omx_cell_tasks.values())
                restored_phase = "CLAIMED" if has_queued else "RELEASED"
                app.state.omx_cell_states[cid] = {
                    **prev,
                    "phase": restored_phase,
                    "amr_motion_inhibited": restored_phase in ("CLAIMED", "ARM_IN_BED_ZONE"),
                    "reason": "VISION_HUMAN_CLEARED_AUTO_RESUME",
                }

        dec = _evaluate_decision(
            cell_id if cell_id != "all" else "cell_s",
            "arm_target",
            {"human_detected": human_detected},
        )
        _save_ledger()
        return {
            "ok": True,
            "vision_checked": True,
            "camera_snapshot_bytes": snap_bytes,
            "intrusion_score": intrusion_score,
            "human_detected": human_detected,
            "active_estop": _is_human_detected(),
            "detected_displaced_site": app.state.detected_displaced_site,
            "paused_tasks": paused_tasks,
            "resumed_tasks": resumed_tasks,
            "vision": {
                "cell_id": cell_id,
                "human_detected": human_detected,
                "intrusion_score": intrusion_score,
                "displaced_to": app.state.detected_displaced_site,
                "snapshot_bytes": snap_bytes,
            },
            "safety_event": {
                "active_estop": _is_human_detected(),
                "paused_tasks": paused_tasks,
                "resumed_tasks": resumed_tasks,
            },
            "decision": dec,
        }

    @app.get("/api/fleet/pipeline/decision-gate", dependencies=read_guard)
    async def list_pipeline_decisions(subject_id: str | None = None):
        rows = list(app.state.pipeline_decisions)
        if subject_id is not None:
            rows = [r for r in rows if r["subject_id"] == subject_id]
        return {
            "decisions": rows[-30:],
            "cable_tangled": app.state.cable_tangled,
            "detected_displaced_site": app.state.detected_displaced_site,
        }

    @app.post("/api/fleet/pipeline/decision-gate", dependencies=read_guard)
    async def run_pipeline_decision_gate(request: Request):
        active = active_map()
        body = await request.json()
        subject_id = str(body.get("subject_id") or "cell_s")
        domain = body.get("domain")
        auto_execute = bool(body.get("auto_execute", True))
        dec = _evaluate_decision(subject_id, domain, body.get("facts") or body)
        spawned_cell_task = None
        pinky_task = None
        if auto_execute:
            if dec["domain"] == "arm_target" and dec.get("auto_preset"):
                preset_spec = CELL_TASK_PRESETS[dec["auto_preset"]]
                spawned_cell_task = _enqueue_one_task(active, {**preset_spec, "cable_guard_micro": dec["cable_guard_micro"]})
            elif dec["domain"] == "line_follow" and dec.get("auto_pinky_action"):
                act = dec["auto_pinky_action"]
                rid = subject_id if subject_id.startswith("rosy_") else "rosy_46"
                cable_guard = dec["cable_guard_micro"]
                max_step_m = 0.015 if cable_guard else 0.10
                max_speed_mps = 0.02 if cable_guard else 0.08
                if act == "stop_now":
                    target_place, v_cmd, dur = "HOLD_STOP", 0.0, 0.0
                elif act == "micro_forward_2cm":
                    target_place, v_cmd, dur = "MICRO_FWD_1.5CM", max_speed_mps, 0.35
                elif act == "micro_reverse_2cm":
                    target_place, v_cmd, dur = "MICRO_REV_1.5CM", -max_speed_mps, 0.35
                else:
                    st = resolve_omx_cells(active[1], active[2])["cell_s"]
                    docked = {"robot_id": rid, "robot_kind": "pinky", "pose": {"x": st.station_xy[0], "y": st.station_xy[1], "yaw": 0.0},
                              "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}
                    app.state.omx_cell_states["cell_s"] = {"phase": "CLAIMED", "tier": 1, "robot_id": rid, "docked_robot": docked}
                    target_place, v_cmd, dur = "S3", max_speed_mps, round(max_step_m / max_speed_mps, 2)
                    spawned_cell_task = _enqueue_one_task(active, {**CELL_TASK_PRESETS["s3_shuttle"], "robot_id": rid})
                pid = f"pinky-dec-{uuid.uuid4().hex[:6]}"
                pinky_task = {
                    "task_id": pid,
                    "robot_id": rid,
                    "action": act,
                    "target_place": target_place,
                    "cable_guard_micro": cable_guard,
                    "max_step_m": max_step_m,
                    "v_cmd_mps": v_cmd,
                    "duration_s": dur,
                    "decision": dec,
                    "spawned_cell_task_id": spawned_cell_task["task_id"] if spawned_cell_task else None,
                    "status": "COMPLETED",
                    "created_at": round(time.time(), 3),
                }
                app.state.pinky_tasks[pid] = pinky_task
                _save_ledger()
        return {
            "ok": True,
            "decision": dec,
            "spawned_cell_task": spawned_cell_task,
            "pinky_task": pinky_task,
            "executed": {"task": spawned_cell_task, "pinky_task": pinky_task},
        }

    @app.get("/api/fleet/pipeline/pinky-tasks", dependencies=read_guard)
    async def list_pinky_tasks(robot_id: str | None = None, status: str | None = None):
        tasks = list(app.state.pinky_tasks.values())
        if robot_id is not None:
            tasks = [t for t in tasks if t["robot_id"] == robot_id]
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        return {"tasks": tasks}
