from __future__ import annotations

from contextlib import nullcontext, suppress
import json
import time
import uuid
from types import SimpleNamespace
from fastapi import HTTPException, Request
from fleet.charge_bays import ChargeBays
from fleet.pipeline import evaluate_fleet_pipeline, resolve_omx_cells, evaluate_omx_cell_station
from fleet.pipeline.cell_fleet_contract import contract_spec_dict, validate_boundary_separation
from fleet.pipeline.cell_site_targets import expand_multi_tier_specs, list_canonical_sites, resolve_cell_task_targets
from fleet.pipeline.station_zones import load_station_zones

from fleet.server.pipeline_pinky_dispatch import dispatch_fields, enabled as pinky_dispatch_enabled, install_pinky_dispatch
from fleet.server.pipeline_port_events import (
    IDENTITY_INPUT_FIELDS, TASK_IDENTITY_FIELDS, has_identity_input, task_view_for_request, validate_task_identity,
)
from .pipeline_governance_store import (
    admit_cell_task_guarded, build_cell_readiness, deterministic_idempotency_id, is_named_operator,
    prepare_task_governance, safe_canonical_digest, scoped_idempotency_key, validate_request_key,
)
from fleet.server.sitemap.pipeline_routes import _enrich_task_health
from fleet.server.sitemap.pipeline_task_input import checked_finite_float, checked_json_value, checked_task_pose
from fleet.server.sitemap.pipeline_unload_release import (
    exit_target, install_unload_release_routes, manifest_count, unload_release,
)
from fleet.server.pipeline_recovery_tools import collect_unresolved_failures


_LEGACY_VEHICLE_SITE = "pinky"
#: The place a pinky-task action drives to (move_* take their zone's place_id); others are not place goals.
PLACE_OF_ACTION = {"dock_s3": "S3", "dock_and_unload_s3": "S3", "dock_s5": "S5", "charge_c1": "C1",
                   "charge_c2": "C2", "depart_s1": "S1"}


def install_cell_tasks_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    operator_guard = ctx.operator_guard
    proposer_guard = getattr(ctx, "proposer_guard", operator_guard)
    STATION_CAMERA_LINKS = ctx.STATION_CAMERA_LINKS
    _arm_live_catalog = ctx._arm_live_catalog
    gov = getattr(ctx, "gov", None) or getattr(app.state, "pipeline_governance", None)
    zones_override_path = ctx.zones_override_path
    _save_ledger = ctx._save_ledger
    _commit_ledger = getattr(ctx, "_commit_ledger", None)
    _is_human_detected = ctx._is_human_detected
    _evaluate_decision = ctx._evaluate_decision
    inputs = ctx.inputs
    rules = ctx.rules
    active_map = ctx.active_map

    def _aborted(cell_id: str) -> bool:
        state = app.state.omx_cell_states.get(cell_id) or {}
        return state.get("phase") == "ABORTED" or state.get("prev_phase") == "ABORTED"

    def _resolve_cell_robot_id(cell_id: str, spec: dict) -> str:
        if "robot_id" in spec:
            raw_robot_id = spec["robot_id"]
            if not isinstance(raw_robot_id, str) or not raw_robot_id.strip():
                raise HTTPException(422, detail={"code": "INVALID_ROBOT_ID"})
            return raw_robot_id.strip()
        docked = (app.state.omx_cell_states.get(cell_id) or {}).get("docked_robot") or {}
        if isinstance(docked.get("robot_id"), str) and docked["robot_id"].strip():
            return docked["robot_id"].strip()
        return "rosy_01"
    @app.get("/api/fleet/pipeline/status", dependencies=read_guard)
    async def pipeline_status(request: Request):
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
        out["omx_cell_tasks"] = [task_view_for_request(t, request) for t in app.state.omx_cell_tasks.values()]
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

    @app.post("/api/fleet/pipeline/cell-handoff", dependencies=proposer_guard)
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
        _commit_ledger(bump_stop=True) if callable(_commit_ledger) else (_save_ledger(), gov and gov.bump_stop_generation())
        return res

    CELL_TASK_PRESETS: dict[str, dict] = {
        "s3_shuttle": {"preset": "s3_shuttle", "label": "S3 셔틀 (arm_s: Pinky -> Belt)", "cell_id": "cell_s", "arm_id": "arm_s", "src_site": "pinky", "dst_site": "belt", "tier": 1, "displaced_to": None},
        "s3_act_policy": {"preset": "s3_act_policy", "label": "S3 ACT 정책 구동 (arm_s · 최신 모델)", "cell_id": "cell_s", "arm_id": "arm_s", "src_site": "pinky", "dst_site": "belt", "tier": 1, "displaced_to": None, "execution_mode": "act_policy", "max_chunks": 4},
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

    @app.get("/api/fleet/pipeline/cell-sites", dependencies=read_guard)
    async def list_cell_sites():
        return list_canonical_sites(getattr(app.state, "web_common", None))

    def _build_cell_task(active, spec: dict, seen_ids: set[str] | None = None, *,
                         principal_id: str | None = None, principal_role: str | None = None) -> dict:
        cell_id = str(spec.get("cell_id") or "cell_s")
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        if station is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_CELL"})
        task_id = str(spec.get("task_id") or f"cell-task-{uuid.uuid4().hex[:8]}")
        if task_id in app.state.omx_cell_tasks or (seen_ids is not None and task_id in seen_ids):
            raise HTTPException(409, detail={"code": "CELL_TASK_ID_EXISTS"})
        web_common = getattr(app.state, "web_common", None)
        try:
            targets = resolve_cell_task_targets(
                cell_id, spec, web_common=web_common, default_cell_s_src=_LEGACY_VEHICLE_SITE,
                legacy_sites=("belt", _LEGACY_VEHICLE_SITE),
            )
            identity_meta = validate_task_identity(spec, cell_id=cell_id, principal_id=principal_id)
        except ValueError as exc:
            raise HTTPException(422, detail={"code": str(exc) or "INVALID_CELL_TASK_INPUT"}) from None
        tier, pose = checked_task_pose({**spec, "tier": targets["tier"]}, station)
        arm_id = targets["arm_id"]
        tier_hint = spec.get("tier_hint")
        if tier_hint is not None and not isinstance(tier_hint, dict):
            raise HTTPException(422, detail={"code": "INVALID_TIER_HINT"})
        execution_mode = spec.get("execution_mode")
        if execution_mode is not None and execution_mode not in ("guarded_pick", "act_policy"):
            raise HTTPException(422, detail={"code": "INVALID_EXECUTION_MODE"})
        if execution_mode == "act_policy" and (cell_id != "cell_s" or arm_id != "arm_s"):
            raise HTTPException(422, detail={"code": "ACT_POLICY_UNSUPPORTED_ARM"})
        max_chunks = spec.get("max_chunks")
        if max_chunks is not None and (execution_mode != "act_policy" or type(max_chunks) is not int or not 1 <= max_chunks <= 6):
            raise HTTPException(422, detail={"code": "INVALID_MAX_CHUNKS"})
        directive = spec.get("directive")
        if directive is not None and (not isinstance(directive, dict)
                                      or directive.get("schema") != "rosy.omx-cell-area-xyz-directive.v1"
                                      or directive.get("directive_id") != task_id
                                      or directive.get("arm_id") != arm_id):
            raise HTTPException(422, detail={"code": "INVALID_CELL_DIRECTIVE"})
        raw_disp = spec.get("displaced_to")
        if execution_mode == "act_policy" and raw_disp is not None:
            raise HTTPException(422, detail={"code": "INVALID_EXECUTION_MODE"})
        resolved_robot_id = _resolve_cell_robot_id(cell_id, spec)
        dec_ov = {"displaced_to": raw_disp} if raw_disp in ("belt_far", "floor_front") else {}
        dec_row = _evaluate_decision(cell_id, "arm_target", dec_ov)
        site_meta = (
            {"src_site_id": targets["src_site_id"], "dst_site_id": targets["dst_site_id"],
             "dst_wire_ref": targets["dst_wire_ref"],
             "dst_area": targets["dst_area"], "dst_slot": targets["dst_slot"]}
            if cell_id == "cell_ab" else {}
        )
        target_status, gov_meta = prepare_task_governance(
            app, spec, principal_id=principal_id, principal_role=principal_role,
            cell_id=cell_id, src_site=targets["src_site"], dst_site=targets["dst_site"], gov=gov,
            active_map_fn=active_map, resolve_cells_fn=resolve_omx_cells,
            is_human_detected_fn=_is_human_detected, arm_live_catalog_fn=_arm_live_catalog,
            vehicle_sites=(_LEGACY_VEHICLE_SITE,),
        )
        if execution_mode != "act_policy" and (raw_disp == "auto" or (raw_disp is None and cell_id == "cell_s" and app.state.detected_displaced_site)):
            resolved_disp = app.state.detected_displaced_site or "belt_far"
            app.state.detected_displaced_site = None
        else:
            resolved_disp = raw_disp or None
        return _enrich_task_health({
            "task_id": task_id,
            "cell_id": cell_id,
            "arm_id": arm_id,
            "directive": directive,
            "robot_id": resolved_robot_id,
            "robot_kind": str(spec.get("robot_kind") or "pinky"),
            "src_site": targets["src_site"],
            "dst_site": targets["dst_site"],
            **site_meta,
            **identity_meta,
            "tier": tier,
            "depends_on": spec.get("depends_on"),
            "displaced_to": resolved_disp,
            "auto_recovered": bool(raw_disp == "auto" or resolved_disp),
            "cable_guard_micro": bool(spec.get("cable_guard_micro", dec_row["cable_guard_micro"])),
            "decision": dec_row,
            "preset": spec.get("preset"),
            **{k: spec[k] for k in ("unload_batch_id", "unload_expected", "unload_index", "repark_root", "zone_id", "col", "row", "tier_hint", "requires_presence_confirm")
               if k in spec},
            **{k: spec[k] for k in ("execution_mode", "max_chunks") if spec.get(k) is not None},
            **gov_meta,
            "pose": pose,
            "status": target_status,
            "created_at": round(time.time(), 3),
        })

    def _enqueue_many(active, specs: list[dict], *, principal_id: str | None = None,
                      principal_role: str | None = None, save: bool = True,
                      idempotency: tuple[str, str] | None = None) -> list[dict]:
        seen_ids: set[str] = set()
        built = []
        for idx, s in enumerate(specs):
            if idempotency is not None and len(specs) == 1 and not s.get("task_id"):
                s = {**s, "task_id": deterministic_idempotency_id("cell", idempotency[0])}
            task = _build_cell_task(active, s, seen_ids=seen_ids, principal_id=principal_id, principal_role=principal_role)
            if idempotency is not None:
                task["idempotency_key"], task["idempotency_body_sha256"] = idempotency[0], idempotency[1]
            seen_ids.add(task["task_id"])
            built.append(task)
        for task in built:
            app.state.omx_cell_tasks[task["task_id"]] = task
        written = False
        try:
            if save:
                bump = any(t["status"] == "QUEUED" for t in built)
                idemp_row = (idempotency[0], idempotency[1], 200, {"ok": True, "task": built[0], "tasks": built}) if idempotency else None
                if callable(_commit_ledger):
                    written = True
                    _commit_ledger(bump_dispatch=bump, idempotency=idemp_row)
                else:
                    _save_ledger()
                    written = True
                    if gov is not None and (bump or idemp_row is not None):
                        if hasattr(gov, "commit_enqueue"):
                            gov.commit_enqueue(bump_dispatch=bump, idempotency=idemp_row)
                        else:
                            if idemp_row is not None and hasattr(gov, "record_idempotency"):
                                gov.record_idempotency(*idemp_row)
                            if bump:
                                gov.bump_dispatch_generation()
        except Exception:
            for t in built:
                app.state.omx_cell_tasks.pop(t["task_id"], None)
            if written and not getattr(app.state, "_pipeline_ledger_fault", False):
                with suppress(Exception):
                    if callable(_commit_ledger):
                        _commit_ledger(commit=False)
                    else:
                        _save_ledger()
            raise
        return built

    def _enqueue_one_task(active, spec: dict, *, principal_id: str | None = None,
                          principal_role: str | None = None, save: bool = True,
                          idempotency: tuple[str, str] | None = None) -> dict:
        return _enqueue_many(active, [spec], principal_id=principal_id, principal_role=principal_role, save=save, idempotency=idempotency)[0]

    @app.post("/api/fleet/pipeline/cell-tasks", dependencies=proposer_guard)
    async def create_cell_task(request: Request):
        active = active_map()
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"})
        principal = getattr(request.state, "site_principal", None)
        principal_id = getattr(principal, "principal_id", None)
        principal_role = getattr(principal, "role", None)
        raw_key = body["request_key"] if "request_key" in body else request.headers.get("Idempotency-Key")
        req_key = validate_request_key(raw_key)
        scoped_key = scoped_idempotency_key(req_key, principal_id, principal_role) if req_key else None
        body_hash = safe_canonical_digest({"principal_id": principal_id, "principal_role": principal_role, "body": body}) if scoped_key else None
        idempotency = (scoped_key, body_hash) if scoped_key else None
        with (gov._lock if gov is not None else nullcontext()):
            if scoped_key and gov is not None and (cached := gov.check_idempotency(scoped_key, body_hash)):
                return cached[1]
            if body.get("tiers") is not None:
                base_id = str(body.get("task_id") or (deterministic_idempotency_id("stack", scoped_key) if scoped_key else f"stack-{uuid.uuid4().hex[:6]}"))
                try:
                    specs = expand_multi_tier_specs(
                        body, base_id=base_id, web_common=getattr(app.state, "web_common", None),
                        legacy_sites=("belt", _LEGACY_VEHICLE_SITE),
                    )
                except ValueError as exc:
                    raise HTTPException(422, detail={"code": str(exc) or "INVALID_CELL_TASK_INPUT"}) from None
                created = _enqueue_many(active, specs, principal_id=principal_id, principal_role=principal_role, idempotency=idempotency)
                return {"ok": True, "task": created[0], "tasks": created}
            if preset_key := body.get("preset"):
                preset = CELL_TASK_PRESETS.get(str(preset_key))
                if preset is None:
                    raise HTTPException(422, detail={"code": "UNKNOWN_PRESET"})
                if "steps" in preset:
                    if has_identity_input(body):
                        raise HTTPException(422, detail={"code": "INVALID_CELL_TASK_INPUT"})
                    base_id = str(body.get("task_id") or (deterministic_idempotency_id("pipe", scoped_key) if scoped_key else f"pipe-{uuid.uuid4().hex[:6]}"))
                    step_specs = []
                    for idx, step in enumerate(preset["steps"]):
                        sid = f"{base_id}-{idx+1}-{step}"
                        step_spec = {**CELL_TASK_PRESETS[step], "robot_id": body.get("robot_id", "rosy_01"),
                                     "task_id": sid, "depends_on": step_specs[-1]["task_id"] if step_specs else None}
                        if "propose" in body:
                            step_spec["propose"] = body["propose"]
                        step_specs.append(step_spec)
                    created_tasks = _enqueue_many(active, step_specs, principal_id=principal_id, principal_role=principal_role, idempotency=idempotency)
                    return {"ok": True, "task": created_tasks[0], "tasks": created_tasks}
                merged = {**preset, **{k: v for k, v in body.items()
                                       if k in (*IDENTITY_INPUT_FIELDS, "emit_release_permit", "robot_id", "propose", "request_key") or v is not None}}
                task = _enqueue_one_task(active, merged, principal_id=principal_id, principal_role=principal_role, idempotency=idempotency)
                return {"ok": True, "task": task, "tasks": [task]}
            task = _enqueue_one_task(active, body, principal_id=principal_id, principal_role=principal_role, idempotency=idempotency)
            return {"ok": True, "task": task, "tasks": [task]}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/admit", dependencies=operator_guard)
    async def admit_cell_task(task_id: str, request: Request):
        return admit_cell_task_guarded(
            app, task_id, await request.body(), getattr(request.state, "site_principal", None),
            active_map_fn=active_map, resolve_cells_fn=resolve_omx_cells, is_human_detected_fn=_is_human_detected,
            arm_live_catalog_fn=_arm_live_catalog, enrich_fn=_enrich_task_health, save_ledger_fn=_save_ledger, gov=gov,
            ledger_payload_fn=getattr(ctx, "_ledger_payload", None),
            write_ledger_fn=getattr(ctx, "_write_ledger_only", None),
        )

    @app.get("/api/fleet/pipeline/cells/{cell_id}/readiness", dependencies=read_guard)
    async def cell_readiness(cell_id: str):
        return build_cell_readiness(app, cell_id, active_map_fn=active_map, resolve_cells_fn=resolve_omx_cells,
                                    is_human_detected_fn=_is_human_detected, arm_live_catalog_fn=_arm_live_catalog, gov=gov)

    @app.get("/api/fleet/pipeline/cell-tasks", dependencies=read_guard)
    async def list_cell_tasks(request: Request, cell_id: str | None = None, status: str | None = None):
        active = active_map()
        all_tasks = [_enrich_task_health(t) for t in app.state.omx_cell_tasks.values()]
        tasks = list(all_tasks)
        if cell_id is not None:
            tasks = [t for t in tasks if t["cell_id"] == cell_id]
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        # D-1057 named-operator confirmations not yet used up by a claim, if installed.
        # bed_confirm_status, not bed_confirmation: D-1057 claim writes its own bed_confirmation onto the row.
        stores = {field: getattr(app.state, attr, None) or {} for field, attr in (
            ("bed_confirm_status", "cell_bed_confirmations"), ("presence_confirmation", "cell_presence"))}
        refusals = getattr(app.state, "cell_task_refusals", None) or {}  # last claim/complete refusal (camera routes)
        tasks = [{**task_view_for_request(t, request),
                  **{field: {"principal_id": rec.get("principal_id"), "invalid": bool(rec.get("invalid")),
                             "age_s": round(time.time() - rec["confirmed_at"], 1),
                             "bound": bool(rec.get("lease")) and rec.get("lease") == t.get("handoff_lease_id")}
                     for field, store in stores.items() if (rec := store.get(t["task_id"]))},
                  **({"last_refusal": refusals[t["task_id"]]} if t["task_id"] in refusals else {})} for t in tasks]
        stations = resolve_omx_cells(active[1], active[2])
        cells_info = {}
        for cid, st in stations.items():
            cstate = app.state.omx_cell_states.get(cid) or {}
            ev = evaluate_omx_cell_station(st, docked_robot=cstate.get("docked_robot"), cell_state=cstate,
                                           map_version=getattr(active[2], "version", None))
            running_t = next((t["task_id"] for t in all_tasks if t["cell_id"] == cid and t["status"] == "RUNNING"), None)
            cells_info[cid] = {**ev, "active_task_id": running_t}
        summary = {
            "total": len(all_tasks), "proposed": sum(1 for t in all_tasks if t["status"] == "PROPOSED"),
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
            **({"authority": gov.snapshot()} if gov is not None else {}),
            "cells": cells_info,
            "presets": list(CELL_TASK_PRESETS.values()),
            "detected_displaced_site": app.state.detected_displaced_site,
            "cable_tangled": app.state.cable_tangled,
            "human_safety": {"human_detected": dict(app.state.human_detected), "active_estop": _is_human_detected()},
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
            "pinky_dispatch_enabled": pinky_dispatch_enabled(),
            "auto_events": list(getattr(app.state, "cell_auto_events", None) or [])[-30:],
            "repark_requests": dict(getattr(app.state, "repark_requests", None) or {}),
            "recovery_handoff": {
                "active_failures": collect_unresolved_failures(
                    app.state, time.time(), human_detected=bool(_is_human_detected()),
                    active=active, dispatch_enabled=pinky_dispatch_enabled(),
                ),
                "homing_sessions": dict(getattr(app.state, "pipeline_homing_sessions", None) or {}),
                "recent_invocations": list((getattr(app.state, "pipeline_recovery_ledger", None) or [])[-10:]),
            },
        }

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/cancel", dependencies=operator_guard)
    async def cancel_cell_task(task_id: str):
        active = active_map()
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        if task.get("status") not in ("PROPOSED", "QUEUED"):
            raise HTTPException(409, detail={"code": "CELL_TASK_ALREADY_CLAIMED"})
        cell_id = task["cell_id"]
        station = resolve_omx_cells(active[1], active[2]).get(cell_id)
        state = app.state.omx_cell_states.get(cell_id) or {}
        res = evaluate_omx_cell_station(station, docked_robot=state.get("docked_robot"), cell_state=state,
                                        map_version=getattr(active[2], "version", None))
        prev = {k: task.get(k) for k in ("status", "completed_at", "health_summary")}
        task["status"], task["completed_at"] = "CANCELLED", round(time.time(), 3)
        try:
            _enrich_task_health(task)
            if callable(_commit_ledger):
                _commit_ledger(bump_dispatch=True)
            else:
                _save_ledger()
                if gov is not None:
                    gov.bump_dispatch_generation()
        except Exception:
            for k, v in prev.items():
                task.pop(k, None) if v is None else task.__setitem__(k, v)
            if callable(_commit_ledger) and not getattr(app.state, "_pipeline_ledger_fault", False):
                with suppress(Exception):
                    _commit_ledger(commit=False)
            raise
        return {"ok": True, "task": task, "gate": res["gate"]}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/retry", dependencies=operator_guard)
    async def retry_cell_task(task_id: str, request: Request):
        active = active_map()
        orig = app.state.omx_cell_tasks.get(task_id)
        if orig is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        new_id = f"{task_id}-retry-{uuid.uuid4().hex[:4]}"
        principal_id = getattr(getattr(request.state, "site_principal", None), "principal_id", None)
        spec = {k: orig[k] for k in ("cell_id", "arm_id", "robot_id", "robot_kind", "src_site", "dst_site", "tier", *TASK_IDENTITY_FIELDS) if k in orig}
        spec.update({k: orig.get(k) for k in ("depends_on", "displaced_to", "preset")})
        spec.update({"task_id": new_id, **{k: orig[k] for k in ("execution_mode", "max_chunks") if orig.get(k) is not None}})
        retried = _enqueue_one_task(active, spec, principal_id=principal_id)
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
        spawned_cell_task = unload_batch_id = None
        v_cmd, duration_s = 0.0, 0.0
        place_id = PLACE_OF_ACTION.get(action)  # None: not a place goal, the dispatcher refuses it
        if action in ("dock_s3", "dock_and_unload_s3"):
            if _aborted("cell_s"):
                raise HTTPException(409, detail={"code": "CELL_ABORTED_HOLD"})
            target_place = "S3"
            v_cmd = max_speed_mps
            duration_s = round(checked_finite_float(max_step_m / max(0.005, max_speed_mps)), 2)
            if action == "dock_and_unload_s3":
                batch_id = f"unload-{uuid.uuid4().hex[:8]}"  # the camera adds the next carry (continue_unload)
                spawned_cell_task = _enqueue_one_task(active, {
                    **CELL_TASK_PRESETS["s3_shuttle"], "robot_id": robot_id, "task_id": f"{batch_id}-1",
                    "unload_batch_id": batch_id, "unload_expected": manifest_count(body), "unload_index": 0,
                })
        elif action == "depart_s3":
            release = unload_release(app.state, robot_id, now=time.time(), human_detected=bool(_is_human_detected()))
            if not release["ready"]:
                raise HTTPException(409, detail={"code": "DEPART_NOT_PERMITTED", "reasons": release["reasons"]})
            target = exit_target(rules(), active[1])
            if target is None:
                raise HTTPException(409, detail={"code": "NO_EXIT_PLACE"})
            principal = getattr(request.state, "site_principal", None)
            unload_batch_id = release["batch_id"]
            app.state.unload_releases[unload_batch_id] = {
                "robot_id": robot_id, "task_id": task_id, "at": round(time.time(), 3), "state": "OPERATOR",
                "operator": getattr(principal, "principal_id", None), "target": target[0], "release": release}
            place_id = target[0]
            target_place = target[0]
            v_cmd = max_speed_mps
            duration_s = 0.35
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
            place_id = z.get("place_id")
            v_cmd = min(max_speed_mps, checked_finite_float(z.get("speed_cap_mps", max_speed_mps)))
            max_step_m = min(max_step_m, checked_finite_float(z.get("max_step_m", max_step_m)))
            duration_s = 0.35
            if action == "move_export_s1" and z.get("cell_id"):
                spawned_cell_task = _enqueue_one_task(active, {
                    "cell_id": z["cell_id"], "arm_id": z.get("arm_id", "arm_a"), "robot_id": robot_id,
                    "src_site": z.get("src_site", "belt"), "dst_site": z.get("dst_site", "pallet"),
                    "tier": int(z.get("tier", 1)), "preset": "export_s1",
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
            "task_id": task_id, "robot_id": robot_id, "action": action, "target_place": target_place,
            "cable_guard_micro": cable_guard, "max_step_m": max_step_m, "v_cmd_mps": v_cmd, "duration_s": duration_s,
            "decision": dec_row, "spawned_cell_task_id": spawned_cell_task["task_id"] if spawned_cell_task else None,
            **({"unload_batch_id": unload_batch_id} if unload_batch_id else {}),
            "status": "QUEUED", "created_at": round(time.time(), 3), **dispatch_fields(active, request, place_id),
        }
        app.state.pinky_tasks[task_id] = ptask
        _save_ledger()
        return {"ok": True, "pinky_task": ptask, "decision": dec_row, "spawned_cell_task": spawned_cell_task}
    def record_depart_task(robot_id, batch, place, now):
        app.state.pinky_tasks[f"depart-{batch}"] = {"task_id": f"depart-{batch}", "robot_id": robot_id, "action": "depart_s3",
                                                    "target_place": place, "status": "SENT", "auto": True, "created_at": round(now, 3)}
    ctx.record_depart_task = record_depart_task
    install_pinky_dispatch(app, ctx)
    install_unload_release_routes(app, ctx)
    ctx.CELL_TASK_PRESETS, ctx._enqueue_one_task = CELL_TASK_PRESETS, _enqueue_one_task