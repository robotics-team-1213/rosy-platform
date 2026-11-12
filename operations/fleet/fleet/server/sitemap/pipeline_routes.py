from __future__ import annotations

import hashlib
import inspect
import json
import os
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException, Request
from fastapi.responses import Response

from fleet.charge_bays import ChargeBays, bays_from_map
from fleet.pipeline import evaluate_fleet_pipeline, resolve_omx_cells, evaluate_omx_cell_station
from fleet.pipeline.cell_fleet_contract import contract_spec_dict, validate_boundary_separation
from fleet.pipeline.station_zones import load_station_zones, save_station_zones_yaml
from fleet.site_rules import SiteRules


def _storage_dir() -> Path:
    var_lib = Path("/var/lib/rosy")
    if var_lib.is_dir() and os.access(var_lib, os.W_OK):
        d = var_lib / "pipeline"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path("/tmp")


def _enrich_task_health(task: dict) -> dict:
    stop_ev = ((task.get("hardware_telemetry") or {}).get("stop_event") or {})
    health = stop_ev.get("health") or {}
    temps = health.get("temp_c") or []
    currents = health.get("current_ma") or []
    status = task.get("status") or "QUEUED"
    if status == "COMPLETED":
        substage = "Fold Home 완료" if stop_ev.get("folded") else "Place 완료"
    elif status == "RUNNING":
        substage = "Grasp → Lift → Place 실행 중"
    elif status == "PAUSED_HUMAN":
        substage = "사람 감지 비상정지 대기 (이탈 시 자동 재개)"
    elif status in ("CANCELLED", "ABORTED"):
        substage = "작업 취소·중단 (인터락 해제)"
    else:
        substage = "큐 대기 (Approach 준비)"
    task["health_summary"] = {
        "max_temp_c": max(temps) if temps else None,
        "max_current_ma": max(currents) if currents else None,
        "substage": substage,
        "folded": bool(stop_ev.get("folded", False)),
    }
    return task


def install_pipeline_routes(app, *, console=None, site_maps=None, read_guard=()) -> None:
    if getattr(app.state, "_pipeline_routes_installed", False):
        return
    app.state._pipeline_routes_installed = True
    app.state.omx_cell_states = getattr(app.state, "omx_cell_states", None) or {}
    app.state.omx_cell_tasks = getattr(app.state, "omx_cell_tasks", None) or {}
    app.state.pinky_tasks = getattr(app.state, "pinky_tasks", None) or {}
    app.state.pipeline_decisions = getattr(app.state, "pipeline_decisions", None) or []
    app.state.detected_displaced_site = getattr(app.state, "detected_displaced_site", None)
    app.state.cable_tangled = getattr(app.state, "cable_tangled", True)
    app.state.human_detected = getattr(app.state, "human_detected", None) or {"cell_s": False, "cell_ab": False, "all": False}

    ledger_path = _storage_dir() / "rosy-pipeline-ledger.json"
    zones_override_path = _storage_dir() / "station_zones.yaml"
    if not os.environ.get("PYTEST_CURRENT_TEST") and ledger_path.is_file():
        try:
            saved = json.loads(ledger_path.read_text(encoding="utf-8"))
            app.state.omx_cell_states.update(saved.get("omx_cell_states") or {})
            app.state.omx_cell_tasks.update(saved.get("omx_cell_tasks") or {})
            app.state.pinky_tasks.update(saved.get("pinky_tasks") or {})
            app.state.pipeline_decisions = list(saved.get("pipeline_decisions") or [])[-100:]
            app.state.detected_displaced_site = saved.get("detected_displaced_site")
            if "cable_tangled" in saved:
                app.state.cable_tangled = bool(saved["cable_tangled"])
            if isinstance(saved.get("human_detected"), dict):
                app.state.human_detected.update({k: bool(v) for k, v in saved["human_detected"].items()})
        except Exception:
            pass

    def _save_ledger() -> None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        try:
            ledger_path.write_text(
                json.dumps(
                    {
                        "omx_cell_states": app.state.omx_cell_states,
                        "omx_cell_tasks": app.state.omx_cell_tasks,
                        "pinky_tasks": app.state.pinky_tasks,
                        "pipeline_decisions": app.state.pipeline_decisions[-100:],
                        "detected_displaced_site": app.state.detected_displaced_site,
                        "cable_tangled": app.state.cable_tangled,
                        "human_detected": app.state.human_detected,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _is_human_detected(subject_id: str | None = None) -> bool:
        hd = app.state.human_detected or {}
        if hd.get("all"):
            return True
        if subject_id in ("cell_s", "cell_ab"):
            return bool(hd.get(subject_id))
        return any(bool(v) for v in hd.values())

    def _evaluate_decision(subject_id: str, domain: str | None = None, facts_override: dict | None = None) -> dict:
        ov = dict(facts_override or {})
        if "tangled" in ov and ov["tangled"] is not None:
            app.state.cable_tangled = bool(ov["tangled"])
        if "displaced_to" in ov and ov["displaced_to"] in ("belt_far", "floor_front", None, ""):
            app.state.detected_displaced_site = ov["displaced_to"] or None
        if "human_detected" in ov and ov["human_detected"] is not None:
            key = subject_id if subject_id in ("cell_s", "cell_ab") else "all"
            app.state.human_detected[key] = bool(ov["human_detected"])
        tangled = bool(app.state.cable_tangled)
        displaced = app.state.detected_displaced_site
        human_near = _is_human_detected(subject_id)
        resolved_domain = domain or ("arm_target" if subject_id in ("cell_s", "cell_ab") else "line_follow")
        now_ts = round(time.time(), 3)
        decision_id = f"dec-{uuid.uuid4().hex[:8]}"

        if resolved_domain == "arm_target":
            target_state = "human_intrusion" if human_near else ("missing" if (subject_id == "cell_s" and displaced) else "present")
            facts = {
                "state": target_state,
                "target_state": target_state,
                "displaced_to": displaced if subject_id == "cell_s" else None,
                "tangled": tangled,
                "human_detected": human_near,
            }
            choices = ["object_reacquire", "reobserve", "human"]
            if human_near:
                chosen = "human"
                auto_preset = None
                objections = ["unsafe", "human_near_arm"]
                reason = f"Decision(arm_target): {subject_id} 작업 반경 내 사람 감지(HUMAN_HOLD) → 즉시 비상정지 및 클레임 차단"
            elif subject_id == "cell_s" and displaced == "floor_front":
                chosen = "object_reacquire"
                auto_preset = "s3_recover_floor_front"
                objections = ["unsafe"] if tangled else []
                reason = f"Decision(arm_target): 전방 바닥 이탈(floor_front) 감지 → object_reacquire 바닥 복구 자동 선택 (미세 조그 {'ON' if tangled else 'OFF'})"
            elif subject_id == "cell_s" and displaced == "belt_far":
                chosen = "object_reacquire"
                auto_preset = "s3_recover_belt_far"
                objections = ["unsafe"] if tangled else []
                reason = f"Decision(arm_target): 벨트 원거리 이탈(belt_far) 감지 → object_reacquire 벨트 복구 자동 선택 (미세 조그 {'ON' if tangled else 'OFF'})"
            else:
                chosen = "reobserve"
                auto_preset = "s3_shuttle" if subject_id == "cell_s" else "s5_tier1_arm_a"
                objections = ["unsafe"] if tangled else []
                reason = f"Decision(arm_target): 용기 정위치(present) 확인 → {auto_preset} 자동 선택 (미세 조그 {'ON' if tangled else 'OFF'})"
            auto_pinky_action = None
        else:
            cell_locked = any((cs.get("phase") in ("ARM_IN_BED_ZONE", "HUMAN_HOLD")) for cs in app.state.omx_cell_states.values())
            state_str = "human_estop" if human_near else ("blocked" if (tangled or cell_locked) else "normal")
            facts = {
                "state": state_str,
                "tangled": tangled,
                "cell_locked": cell_locked,
                "human_detected": human_near,
                "recovery": {
                    "phase": "ASKING",
                    "attempts": 1,
                    "max_attempts": 3,
                    "local_enabled": True,
                    "cause": "human_intrusion" if human_near else ("no_motion" if tangled else ("obstacle_ahead" if cell_locked else "lane_lost")),
                },
            }
            choices = ["back_and_retry", "reobserve", "human"]
            if human_near:
                chosen = "human"
                auto_pinky_action = "stop_now"
                objections = ["unsafe", "human_near_arm"]
                reason = "Decision(line_follow): 셀/주행 구역 사람 접근 감지(HUMAN_HOLD) → stop_now 즉시 비상정지"
            elif cell_locked:
                chosen = "reobserve"
                auto_pinky_action = "stop_now"
                objections = ["unsafe"]
                reason = "Decision(line_follow): OMX 셀 작업 중(ARM_IN_BED_ZONE) 인터락 감지 → stop_now 즉시 정지 유지"
            elif tangled:
                chosen = "back_and_retry"
                auto_pinky_action = str(ov.get("preferred_micro_action") or "micro_forward_2cm")
                objections = ["unsafe"]
                reason = "Decision(line_follow): 선 꼬임(tangled=true) 감지 → 장거리 주행 차단 및 1.5cm(0.02m/s) 미세 이동(back_and_retry) 자동 전환"
            else:
                chosen = "reobserve"
                auto_pinky_action = "dock_and_unload_s3"
                objections = []
                reason = "Decision(line_follow): 선 꼬임 없음·경로 정상(normal) → S3 도킹+하역(dock_and_unload_s3) 자동 승인"
            auto_preset = None

        recommended = auto_preset or auto_pinky_action or "stop_now"
        digest = hashlib.sha256(
            json.dumps({"subject_id": subject_id, "domain": resolved_domain, "facts": facts, "choices": choices}, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        row = {
            "schema": "rosy.omx-cell-decision.v1",
            "decision_id": decision_id,
            "subject_id": subject_id,
            "domain": resolved_domain,
            "input_hash": digest,
            "facts": facts,
            "options": choices,
            "chosen": chosen,
            "choice": chosen,
            "recommended_action": recommended,
            "objections": objections,
            "cable_guard_micro": tangled,
            "human_detected": human_near,
            "auto_preset": auto_preset,
            "auto_pinky_action": auto_pinky_action,
            "by": "decision_engine",
            "reason": reason,
            "t": now_ts,
        }
        app.state.pipeline_decisions.append(row)
        if len(app.state.pipeline_decisions) > 100:
            app.state.pipeline_decisions = app.state.pipeline_decisions[-100:]
        _save_ledger()
        return row

    def _maps():
        return site_maps if site_maps is not None else getattr(app.state, "site_maps", None)

    async def inputs(active):
        fn = getattr(app.state, "bay_inputs", None)
        if callable(fn):
            result = fn()
            if inspect.isawaitable(result):
                result = await result
            _, robots, bays = result
            return list(robots), list(bays)
        return [], bays_from_map(active[1])

    def rules():
        m = _maps()
        return (m.rules.active_rules() if m is not None and
                getattr(m, "rules", None) is not None else None)

    def active_map():
        m = _maps()
        active = m.active() if m is not None else None
        if active is None:
            raise HTTPException(404, detail={"code": "NO_ACTIVE_MAP"})
        return active

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
        station = resolve_omx_cells(active[1], active[2]).get(body.get("cell_id"))
        if station is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
        robot = {"robot_id": body["robot_id"], "robot_kind": body["robot_kind"],
                 "pose": {"x": float(body["x"]), "y": float(body["y"]), "yaw": float(body["yaw"])},
                 "wheel_brake_locked": body["wheel_brake_locked"], "bed_ready": body["bed_ready"],
                 "v_cmd_mps": float(body["v_cmd_mps"])}
        state = {key: body[key] for key in ("phase", "tier", "robot_id", "stage_id",
                                             "goal_evidence_digest", "reason") if key in body}
        res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state,
                                        map_version=getattr(active[2], "version", None))
        app.state.omx_cell_states[body["cell_id"]] = {**state, "robot_id": body["robot_id"],
                                                       "docked_robot": robot}
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
    }

    @app.post("/api/fleet/pipeline/displaced-detection", dependencies=read_guard)
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
        tier = int(spec.get("tier", 1))
        default_arm = "arm_s" if cell_id == "cell_s" else ("arm_a" if tier % 2 == 1 else "arm_b")
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
            "arm_id": str(spec.get("arm_id") or default_arm),
            "robot_id": str(spec.get("robot_id") or "rosy_01"),
            "robot_kind": str(spec.get("robot_kind") or "pinky"),
            "src_site": str(spec.get("src_site") or ("pinky" if cell_id == "cell_s" else "belt")),
            "dst_site": str(spec.get("dst_site") or ("belt" if cell_id == "cell_s" else f"pallet-l{max(0, min(2, tier - 1))}")),
            "tier": tier,
            "displaced_to": resolved_disp,
            "auto_recovered": bool(raw_disp == "auto" or resolved_disp),
            "cable_guard_micro": bool(spec.get("cable_guard_micro", dec_row["cable_guard_micro"])),
            "decision": dec_row,
            "preset": spec.get("preset"),
            "pose": {
                "x": float(spec.get("x", station.station_xy[0])),
                "y": float(spec.get("y", station.station_xy[1])),
                "yaw": float(spec.get("yaw", 0.0)),
            },
            "status": "QUEUED",
            "created_at": round(time.time(), 3),
        })
        app.state.omx_cell_tasks[task_id] = task
        _save_ledger()
        return task

    @app.post("/api/fleet/pipeline/cell-tasks", dependencies=read_guard)
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
                created_tasks = [
                    _enqueue_one_task(active, {**CELL_TASK_PRESETS[s], "robot_id": body.get("robot_id", "rosy_01"), "task_id": f"{base_id}-{idx+1}-{s}"})
                    for idx, s in enumerate(preset["steps"])
                ]
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
            "decisions": list(app.state.pipeline_decisions[-20:]),
            "pinky_tasks": list(app.state.pinky_tasks.values()),
        }

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/cancel", dependencies=read_guard)
    async def cancel_cell_task(task_id: str):
        active = active_map()
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        cell_id = task["cell_id"]
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        robot = {"robot_id": task["robot_id"], "robot_kind": task["robot_kind"], "pose": dict(task["pose"]),
                 "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}
        state = {"phase": "RELEASED", "tier": task["tier"], "robot_id": task["robot_id"], "stage_id": task_id, "reason": "CANCELLED_BY_OPERATOR"}
        res = evaluate_omx_cell_station(station, docked_robot=robot, cell_state=state, map_version=getattr(active[2], "version", None))
        app.state.omx_cell_states[cell_id] = {**state, "docked_robot": robot}
        task["status"] = "CANCELLED"
        task["completed_at"] = round(time.time(), 3)
        _enrich_task_health(task)
        _save_ledger()
        return {"ok": True, "task": task, "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/retry", dependencies=read_guard)
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

    @app.post("/api/fleet/pipeline/pinky-tasks", dependencies=read_guard)
    async def create_pinky_task(request: Request):
        active = active_map()
        body = await request.json()
        robot_id = str(body.get("robot_id") or "rosy_46")
        action = str(body.get("action") or "dock_s3")
        task_id = str(body.get("task_id") or f"pinky-task-{uuid.uuid4().hex[:8]}")
        cable_guard = bool(body.get("cable_guard_micro", True))
        max_step_m = min(0.02, float(body.get("max_step_m", 0.015))) if cable_guard else float(body.get("max_step_m", 0.10))
        max_speed_mps = min(0.02, float(body.get("max_speed_mps", 0.02))) if cable_guard else float(body.get("max_speed_mps", 0.08))
        stations = resolve_omx_cells(active[1], active[2])
        spawned_cell_task = None
        v_cmd = 0.0
        duration_s = 0.0
        if action in ("dock_s3", "dock_and_unload_s3"):
            st = stations["cell_s"]
            docked = {"robot_id": robot_id, "robot_kind": "pinky", "pose": {"x": st.station_xy[0], "y": st.station_xy[1], "yaw": 0.0},
                      "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}
            app.state.omx_cell_states["cell_s"] = {"phase": "CLAIMED", "tier": 1, "robot_id": robot_id, "docked_robot": docked}
            target_place = "S3"
            v_cmd = max_speed_mps
            duration_s = round(max_step_m / max(0.005, max_speed_mps), 2)
            if action == "dock_and_unload_s3":
                spawned_cell_task = _enqueue_one_task(active, {**CELL_TASK_PRESETS["s3_shuttle"], "robot_id": robot_id})
        elif action == "dock_s5":
            st = stations["cell_ab"]
            docked = {"robot_id": robot_id, "robot_kind": "pinky", "pose": {"x": st.station_xy[0], "y": st.station_xy[1], "yaw": 0.0},
                      "wheel_brake_locked": True, "bed_ready": True, "v_cmd_mps": 0.0}
            app.state.omx_cell_states["cell_ab"] = {"phase": "CLAIMED", "tier": 1, "robot_id": robot_id, "docked_robot": docked}
            target_place = "S5"
            v_cmd = max_speed_mps
            duration_s = round(max_step_m / max(0.005, max_speed_mps), 2)
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
            v_cmd = min(max_speed_mps, float(z.get("speed_cap_mps", max_speed_mps)))
            max_step_m = min(max_step_m, float(z.get("max_step_m", max_step_m)))
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
            for cid, cstate in list(app.state.omx_cell_states.items()):
                if cstate.get("robot_id") == robot_id:
                    cstate["phase"] = "RELEASED"
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
            "status": "QUEUED" if body.get("await_hardware") else "COMPLETED",
            "created_at": round(time.time(), 3),
        }
        app.state.pinky_tasks[task_id] = ptask
        _save_ledger()
        return {"ok": True, "pinky_task": ptask, "decision": dec_row, "spawned_cell_task": spawned_cell_task}

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

    @app.get("/api/fleet/pipeline/cell-camera/{view_id}")
    async def cell_camera_preview(view_id: str):
        safe_id = "".join(c for c in view_id if c.isalnum() or c in ("_", "-"))[:32] or "cell_s"
        for base in (_storage_dir(), Path("/tmp")):
            snap_file = base / f"rosy-cell-cam-{safe_id}.jpg"
            if snap_file.is_file():
                return Response(content=snap_file.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
        tasks = [t for t in app.state.omx_cell_tasks.values() if view_id.startswith(t["cell_id"]) or view_id == "pinky"]
        last = tasks[-1] if tasks else {}
        stop_ev = ((last.get("hardware_telemetry") or {}).get("stop_event") or {})
        state_vals = stop_ev.get("state") or ([0.0, -58.0, 50.0, 50.0, -5.0, 58.1] if "cell_s" in view_id else [0.8, -62.5, 53.3, 51.7, 45.0, 50.0])
        joints_txt = " ".join(f"J{i+1}:{float(v):.1f}" for i, v in enumerate(state_vals[:6]))
        cstate = app.state.omx_cell_states.get("cell_s" if "cell_s" in view_id else "cell_ab") or {}
        phase = cstate.get("phase") or last.get("status") or "IDLE"
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180" width="320" height="180">'
            f'<rect width="320" height="180" rx="8" fill="#0f172a"/>'
            f'<rect x="12" y="34" width="90" height="68" rx="4" fill="#1e293b" stroke="#38bdf8" stroke-width="1.5"/>'
            f'<text x="18" y="50" fill="#38bdf8" font-family="monospace" font-size="10">PINKY / S3</text>'
            f'<rect x="114" y="34" width="92" height="68" rx="4" fill="#1e293b" stroke="#22c55e" stroke-width="1.5"/>'
            f'<text x="120" y="50" fill="#22c55e" font-family="monospace" font-size="10">BELT ROI</text>'
            f'<rect x="218" y="34" width="90" height="68" rx="4" fill="#1e293b" stroke="#f59e0b" stroke-width="1.5"/>'
            f'<text x="224" y="50" fill="#f59e0b" font-family="monospace" font-size="10">PALLET / FAR</text>'
            f'<circle cx="160" cy="72" r="10" fill="#f97316" opacity="0.85"/>'
            f'<text x="12" y="20" fill="#f8fafc" font-family="monospace" font-weight="bold" font-size="12">CAM · {view_id.upper()} [{phase}]</text>'
            f'<text x="12" y="126" fill="#cbd5e1" font-family="monospace" font-size="10">{joints_txt}</text>'
            f'<text x="12" y="146" fill="#94a3b8" font-family="monospace" font-size="10">task: {last.get("task_id", "ready")} · folded: {stop_ev.get("folded", True)}</text>'
            f'<text x="12" y="166" fill="#64748b" font-family="monospace" font-size="9">LIVE TELEMETRY HUD · ROSY WORKCELL</text>'
            f'</svg>'
        )
        return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})

    @app.post("/api/fleet/pipeline/cell-camera/{view_id}", dependencies=read_guard)
    async def upload_cell_camera_preview(view_id: str, request: Request):
        safe_id = "".join(c for c in view_id if c.isalnum() or c in ("_", "-"))[:32] or "cell_s"
        raw = await request.body()
        if not raw:
            raise HTTPException(400, detail={"code": "EMPTY_IMAGE"})
        target = _storage_dir() / f"rosy-cell-cam-{safe_id}.jpg"
        target.write_bytes(raw)
        Path(f"/tmp/rosy-cell-cam-{safe_id}.jpg").write_bytes(raw)
        return {"ok": True, "view_id": safe_id, "bytes": len(raw), "persisted": str(target)}

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
