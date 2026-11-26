from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from fastapi import HTTPException, Request
from fleet.pipeline import resolve_omx_cells
from fleet.pipeline.station_zones import load_station_zones, save_station_zones_yaml

from fleet.server.pipeline_pinky_dispatch import dispatch_fields, enabled as pinky_dispatch_enabled
from fleet.server.sitemap.pipeline_routes import _enrich_task_health, _storage_dir
from fleet.server.sitemap.pipeline_task_input import checked_finite_float


def install_gates_routes(app, ctx) -> None:
    read_guard = ctx.read_guard
    operator_guard = ctx.operator_guard
    zones_override_path = ctx.zones_override_path
    _save_ledger = ctx._save_ledger
    _commit_ledger = getattr(ctx, "_commit_ledger", None)
    _is_human_detected = ctx._is_human_detected
    _evaluate_decision = ctx._evaluate_decision
    active_map = ctx.active_map
    gov = getattr(ctx, "gov", None) or getattr(app.state, "pipeline_governance", None)
    def _aborted(cell_id: str) -> bool:
        state = app.state.omx_cell_states.get(cell_id) or {}
        return state.get("phase") == "ABORTED" or state.get("prev_phase") == "ABORTED"
    CELL_TASK_PRESETS = ctx.CELL_TASK_PRESETS
    _enqueue_one_task = ctx._enqueue_one_task

    def _mark_pinky_stops_pending(principal_id: str) -> list[dict]:
        from fleet.server.pipeline_pinky_dispatch import IN_FLIGHT, _end
        now_ts = time.time()
        inflight: list[dict] = []
        for t in list(app.state.pinky_tasks.values()):
            if t.get("action") != "stop_now" and t.get("status") in (*IN_FLIGHT, "QUEUED"):
                t.update(cancelled_by=principal_id, cancel_requested=True)
                if t.get("status") == "QUEUED":
                    _end(t, "CANCELLED", "HUMAN_ESTOP", now_ts, state=app.state)
                else:
                    inflight.append(t)
        return inflight

    async def _stop_active_pinky_tasks(targets: list[dict], principal_id: str) -> list[str]:
        from fleet.server.pipeline_pinky_dispatch import IN_FLIGHT, _unconfirmed, cancel_task
        runner = getattr(app.state, "trip_runner", None)
        console = getattr(ctx, "console", None)
        now_ts = time.time()
        for t in targets:
            if t.get("status") in IN_FLIGHT:
                await cancel_task(app.state, t, runner=runner, principal_id=principal_id, now=now_ts, console=console)
        return [t["task_id"] for t in targets
                if t.get("status") in IN_FLIGHT or _unconfirmed(t.get("cancel_receipt"))]

    def _commit_human_stop(*, bump_stop: bool = True) -> None:
        try:
            _commit_ledger(bump_stop=bump_stop) if callable(_commit_ledger) else (_save_ledger(), bump_stop and gov and gov.bump_stop_generation())
        except Exception as exc:
            app.state._pipeline_ledger_fault = True
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(503, detail={"code": "PIPELINE_LEDGER_UNAVAILABLE"}) from exc
    def _close_runner_trips(stop_reason: str) -> list:
        from fleet.server.pipeline_pinky_dispatch import _unconfirmed
        runner = getattr(app.state, "trip_runner", None)
        if runner is None or not callable(getattr(runner, "close_all", None)):
            return []
        closed = list(runner.close_all(stop_reason))
        retries = [lv for lv in (getattr(runner, "_live", None) or {}).values()
                   if lv not in closed and lv.view.get("state") in ("canceled", "stopped") and _unconfirmed(lv.view)]
        return [*closed, *retries]

    async def _commit_and_halt_human_stop(pending_inflight: list[dict], halt_targets: list, stop_reason: str, *,
                                          target_robot_id: str | None = None, pinky_estop: dict | None = None) -> list[str]:
        from fleet.server.pipeline_pinky_dispatch import IN_FLIGHT, _cancel_native_goal, _unconfirmed
        runner = getattr(app.state, "trip_runner", None)
        console = getattr(ctx, "console", None)

        async def _run_core_stop() -> tuple[list[str], set[str]]:
            core_unconf: list[str] = []
            estopped: set[str] = set()
            site_estop_fn = getattr(app.state, "execute_site_estop", None)
            if callable(site_estop_fn):
                try:
                    estop_res = await site_estop_fn(stop_reason)
                except Exception:
                    return [f"estop:{target_robot_id or 'all'}", "dispatch_latch:unconfirmed"], estopped
                ctrl = estop_res.get("fleet_dispatch_control") if isinstance(estop_res, dict) else None
                if getattr(app.state, "task_service", None) is not None and (
                    not isinstance(ctrl, dict) or ctrl.get("dispatch_enabled") is not False
                ):
                    core_unconf.append("dispatch_latch:unconfirmed")
                omx_stop = estop_res.get("omx_local_stop") if isinstance(estop_res, dict) else None
                if not isinstance(omx_stop, dict):
                    core_unconf.append("omx_local_stop:unconfirmed")
                else:
                    added_omx = False
                    for inst in (omx_stop.get("instances") or ()):
                        if not isinstance(inst, dict) or inst.get("state") != "LOCAL_LATCHED":
                            iid = (inst.get("instance_id") or inst.get("workcell_id") or "unknown") if isinstance(inst, dict) else "unknown"
                            tag = f"omx_stop:{iid}"
                            if tag not in core_unconf:
                                core_unconf.append(tag)
                            added_omx = True
                    omx_state = omx_stop.get("state")
                    if omx_state not in ("NOT_CONFIGURED", "LOCAL_LATCHED") and not added_omx:
                        core_unconf.append(f"omx_local_stop:{omx_state or 'unconfirmed'}")
                rows = (estop_res.get("robots") if isinstance(estop_res, dict) else None) or []
                for row in rows:
                    if isinstance(row, dict):
                        rid = row.get("robot_id")
                        if row.get("stopped") and rid:
                            estopped.add(rid)
                        elif not row.get("stopped"):
                            core_unconf.append(f"estop:{rid or target_robot_id or 'unknown'}")
                if target_robot_id:
                    target_ok = target_robot_id in estopped
                    if not target_ok and console is not None and callable(getattr(console, "cancel", None)):
                        target_ok = not _unconfirmed(await _cancel_native_goal(console, target_robot_id))
                    if not target_ok:
                        core_unconf.append(f"pinky:{target_robot_id}")
                elif not rows:
                    core_unconf.append("estop:no_robots_confirmed")
                return core_unconf, estopped
            core_unconf.append("omx_local_stop:unavailable")
            task_svc = getattr(app.state, "task_service", None)
            if task_svc is not None:
                app.state._fleet_estop_latch_unresolved = True
                try:
                    ctrl = task_svc.store.trip_stop_latch(actor_id=stop_reason)
                    if not isinstance(ctrl, dict) or ctrl.get("dispatch_enabled") is not False:
                        core_unconf.append("dispatch_latch:unconfirmed")
                    else:
                        app.state._fleet_estop_latch_unresolved = False
                except Exception:
                    core_unconf.append("dispatch_latch:unconfirmed")
            if console is not None and callable(getattr(console, "estop_all", None)):
                target_ok = False
                try:
                    estop_res = await console.estop_all()
                    rows = (estop_res.get("robots") if isinstance(estop_res, dict) else None) or []
                    for row in rows:
                        if isinstance(row, dict):
                            rid = row.get("robot_id")
                            if row.get("stopped") and rid:
                                estopped.add(rid)
                            elif not row.get("stopped"):
                                core_unconf.append(f"estop:{rid or target_robot_id or 'unknown'}")
                    if target_robot_id:
                        if target_robot_id in estopped:
                            target_ok = True
                        elif callable(getattr(console, "cancel", None)):
                            receipt = await _cancel_native_goal(console, target_robot_id)
                            if isinstance(pinky_estop, dict):
                                pinky_estop["cancel_receipt"] = receipt
                            target_ok = not _unconfirmed(receipt)
                        if not target_ok:
                            core_unconf.append(f"pinky:{target_robot_id}")
                    elif not rows:
                        core_unconf.append("estop:no_robots_confirmed")
                except Exception:
                    core_unconf.append(f"estop:{target_robot_id or 'all'}")
            elif console is not None and callable(getattr(console, "cancel", None)) and target_robot_id:
                receipt = await _cancel_native_goal(console, target_robot_id)
                if isinstance(pinky_estop, dict):
                    pinky_estop["cancel_receipt"] = receipt
                if _unconfirmed(receipt):
                    core_unconf.append(f"pinky:{target_robot_id}")
                core_unconf.append("core_estop:unavailable")
            else:
                core_unconf.append(f"pinky:{target_robot_id}" if target_robot_id else "pinky:console_unavailable")
                core_unconf.append("core_estop:unavailable")
            return core_unconf, estopped

        commit_err: BaseException | None = None
        try:
            _commit_human_stop(bump_stop=True)
        except BaseException as exc:
            commit_err = exc
        core_stop_unconf, estop_confirmed = await _run_core_stop()
        if halt_targets and runner is not None and callable(getattr(runner, "halt_closed", None)):
            await runner.halt_closed(halt_targets)
        align_targets = runner.aligning_robots() if (runner is not None and callable(getattr(runner, "aligning_robots", None))) else []
        if align_targets and callable(getattr(runner, "halt_aligning", None)):
            try:
                await runner.halt_aligning(align_targets, estop_confirmed_robots=estop_confirmed)
            except TypeError:
                await runner.halt_aligning(align_targets)
        halts = getattr(runner, "halts", None)
        unresolved_restarted = ()
        if halts is not None:
            if callable(getattr(halts, "halt_unresolved", None)):
                unresolved_restarted = await halts.halt_unresolved()
            elif getattr(halts, "restarted", None) and callable(getattr(halts, "halt_restarted", None)):
                await halts.halt_restarted()
                unresolved_restarted = getattr(halts, "restarted", ()) or ()
        unconfirmed = await _stop_active_pinky_tasks(pending_inflight, stop_reason) if pending_inflight else []
        for tag in core_stop_unconf:
            if tag not in unconfirmed:
                unconfirmed.append(tag)
        for batch_id, rec in list((getattr(app.state, "unload_releases", None) or {}).items()):
            if not isinstance(rec, dict):
                continue
            rstate = rec.get("state")
            ptask = app.state.pinky_tasks.get(f"depart-{batch_id}")
            if rstate == "SENDING" or (rstate == "SENT" and (ptask is None or ptask.get("status") not in (*IN_FLIGHT, "CANCELLED"))):
                in_flight_submit = batch_id in (getattr(app.state, "_depart_submitting", None) or ())
                estop_latched = rec.get("robot_id") in estop_confirmed
                receipt = await _cancel_native_goal(console, rec.get("robot_id"))
                if _unconfirmed(receipt) or (in_flight_submit and not estop_latched):
                    depart_id = f"depart-{batch_id}"
                    row = app.state.pinky_tasks.get(depart_id)
                    if not isinstance(row, dict):
                        row = {
                            "task_id": depart_id, "robot_id": rec.get("robot_id"), "action": "depart_s3",
                            "target_place": rec.get("target") or "S1", "status": "SENT", "auto": True,
                            "created_at": round(time.time(), 3),
                        }
                        app.state.pinky_tasks[depart_id] = row
                    row.update(
                        cancel_requested=True, cancelled_by=stop_reason,
                        cancel_receipt=receipt if _unconfirmed(receipt) else {"error": "DEPART_SUBMIT_IN_FLIGHT"},
                    )
                    tag = f"depart:{batch_id}"
                    if tag not in unconfirmed:
                        unconfirmed.append(tag)
                elif rstate == "SENDING":
                    rec.update(state="HELD", reason="HUMAN_HOLD_CANCELLED")
        for lv in halt_targets:
            tid = lv.view.get("trip_id") if isinstance(getattr(lv, "view", None), dict) else None
            if tid and _unconfirmed(lv.view) and tid not in unconfirmed:
                unconfirmed.append(tid)
        for tr in unresolved_restarted:
            tid = tr.get("trip_id") if isinstance(tr, dict) else None
            if tid and (_unconfirmed(tr) or bool((tr.get("detail") or {}).get("named_stop_handoff_pending"))) and tid not in unconfirmed:
                unconfirmed.append(tid)
        for rid in (
            *(getattr(runner, "_unconfirmed_align_stops", None) or ()),
            *(getattr(runner, "_align_submitting", None) or ()),
            *(getattr(runner, "_align_outcome_unknown", None) or ()),
        ):
            tag = f"align:{rid}"
            if tag not in unconfirmed:
                unconfirmed.append(tag)
        if isinstance(pinky_estop, dict):
            rid = pinky_estop.get("robot_id") or target_robot_id
            failed = (
                bool(rid and (f"pinky:{rid}" in unconfirmed or f"estop:{rid}" in unconfirmed))
                or any(u.startswith(("estop:", "pinky:", "core_estop:", "omx_local_stop:", "omx_stop:")) for u in unconfirmed)
            )
            if failed:
                pinky_estop["status"] = "UNCONFIRMED"
            else:
                pinky_estop["status"] = "COMPLETED"
                pinky_estop["confirmed_at"] = round(time.time(), 3)
        if commit_err is not None:
            raise commit_err
        _commit_human_stop(bump_stop=False)
        return unconfirmed

    @app.get("/api/fleet/pipeline/human-safety-gate", dependencies=read_guard)
    async def get_human_safety_gate():
        return {
            "ok": True,
            "human_detected": dict(app.state.human_detected),
            "active_estop": _is_human_detected(),
            "cells": {cid: (app.state.omx_cell_states.get(cid) or {}).get("phase", "IDLE") for cid in ("cell_s", "cell_ab")},
            "paused_tasks": [t["task_id"] for t in app.state.omx_cell_tasks.values() if t["status"] == "PAUSED_HUMAN"],
        }

    @app.post("/api/fleet/pipeline/human-safety-gate", dependencies=operator_guard)
    async def set_human_safety_gate(request: Request):
        body = await request.json()
        target_cell = str(body.get("cell_id") or "all")
        if target_cell not in ("cell_s", "cell_ab", "all"):
            target_cell = "all"
        if body.get("toggle"):
            detected = not _is_human_detected(None if target_cell == "all" else target_cell)
        else:
            detected = bool(body.get("human_detected", True))
        if not detected:
            raise HTTPException(409, detail={"code": "HUMAN_CLEAR_EVIDENCE_UNAVAILABLE"})
        affected_cells = ["cell_s", "cell_ab"] if target_cell == "all" else [target_cell]
        app.state.safety_stop_generation = int(getattr(app.state, "safety_stop_generation", 0)) + 1
        if target_cell == "all":
            app.state.human_detected = {"cell_s": detected, "cell_ab": detected, "all": detected}
        else:
            app.state.human_detected[target_cell] = detected
            app.state.human_detected["all"] = bool(app.state.human_detected.get("cell_s") and app.state.human_detected.get("cell_ab"))

        paused_tasks: list[str] = []
        resumed_tasks: list[str] = []
        for cid in affected_cells:
            prev = dict(app.state.omx_cell_states.get(cid) or {})
            prev_phase = prev.get("phase") if prev.get("phase") != "HUMAN_HOLD" else (prev.get("prev_phase") or "IDLE")
            docked = dict(prev["docked_robot"], v_cmd_mps=0.0) if isinstance(prev.get("docked_robot"), dict) else None
            app.state.omx_cell_states[cid] = {
                **prev, "phase": "HUMAN_HOLD", "prev_phase": prev_phase,
                "amr_motion_inhibited": True, "reason": str(body.get("reason") or "HUMAN_DETECTED_ESTOP"), "docked_robot": docked,
            }
        for t in app.state.omx_cell_tasks.values():
            if t["cell_id"] in affected_cells and t["status"] in ("QUEUED", "RUNNING"):
                t["paused_from_status"], t["status"] = t["status"], "PAUSED_HUMAN"
                _enrich_task_health(t)
                paused_tasks.append(t["task_id"])
        pending_inflight = _mark_pinky_stops_pending("human_estop")
        halt_targets = _close_runner_trips("human_estop")
        raw_rid = body.get("robot_id")
        target_robot_id = str(raw_rid).strip() if isinstance(raw_rid, str) and raw_rid.strip() else None
        pid = f"pinky-estop-{uuid.uuid4().hex[:6]}"
        pinky_estop = {
            "task_id": pid, "robot_id": target_robot_id, "action": "stop_now",
            "target_place": "HUMAN_ESTOP", "cable_guard_micro": True, "max_step_m": 0.0, "v_cmd_mps": 0.0, "duration_s": 0.0,
            "decision": _evaluate_decision(target_cell if target_cell != "all" else "cell_s", "arm_target", {"human_detected": True}, save=False),
            "spawned_cell_task_id": None, "status": "QUEUED", "created_at": round(time.time(), 3),
        }
        app.state.pinky_tasks[pid] = pinky_estop
        unconfirmed_stops = await _commit_and_halt_human_stop(
            pending_inflight, halt_targets, "human_estop", target_robot_id=target_robot_id, pinky_estop=pinky_estop,
        )
        return {
            "ok": not unconfirmed_stops,
            "stop_confirmed": not unconfirmed_stops,
            "unconfirmed_pinky_stops": unconfirmed_stops,
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

    @app.put("/api/fleet/pipeline/station-zones", dependencies=operator_guard)
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

    @app.post("/api/fleet/pipeline/station-zones/dispatch", dependencies=operator_guard)
    async def dispatch_station_zone(request: Request):
        active = active_map()
        body = await request.json()
        zone_id = str(body.get("zone_id") or "STG_C2")
        robot_id = str(body.get("robot_id") or "rosy_46")
        zones_info = load_station_zones(zones_override_path)
        zone = zones_info["zones_by_id"].get(zone_id)
        if zone is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_STATION_ZONE", "zone_id": zone_id})
        if _is_human_detected() or any(state.get("phase") == "HUMAN_HOLD"
                                       for state in app.state.omx_cell_states.values()):
            raise HTTPException(409, detail={"code": "HUMAN_ESTOP_ACTIVE", "message": "사람 감지 비상정지 중에는 구역 배차를 실행할 수 없습니다"})
        cable_guard = bool(app.state.cable_tangled)
        max_step_m = min(0.015 if cable_guard else 0.10, checked_finite_float(zone.get("max_step_m", 0.015)))
        v_cmd = min(0.02 if cable_guard else 0.08, checked_finite_float(zone.get("speed_cap_mps", 0.02)))
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
            "status": "QUEUED",
            "created_at": round(time.time(), 3),
            **dispatch_fields(active, request, zone.get("place_id")),
        }
        app.state.pinky_tasks[pid] = ptask
        _save_ledger()
        return {"ok": True, "zone": zone, "pinky_task": ptask, "spawned_cell_task": spawned_cell_task}

    @app.post("/api/fleet/pipeline/cable-guard", dependencies=operator_guard)
    async def set_cable_guard(request: Request):
        body = await request.json()
        if body.get("toggle"):
            app.state.cable_tangled = not bool(app.state.cable_tangled)
        else:
            app.state.cable_tangled = bool(body.get("cable_tangled", True))
        dec = _evaluate_decision(str(body.get("robot_id") or "rosy_46"), "line_follow", {"tangled": app.state.cable_tangled})
        _save_ledger()
        return {"ok": True, "cable_tangled": app.state.cable_tangled, "decision": dec}

    @app.post("/api/fleet/pipeline/vision-auto-check", dependencies=operator_guard)
    async def run_vision_auto_check(request: Request):
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
        if not human_detected:
            raise HTTPException(409, detail={"code": "VISION_CLEAR_EVIDENCE_UNAVAILABLE"})
        displaced_to = body.get("displaced_to")
        if displaced_to in ("belt_far", "floor_front", None, "") and "displaced_to" in body:
            app.state.detected_displaced_site = displaced_to or None
        paused_tasks: list[str] = []
        resumed_tasks: list[str] = []
        affected_cells = ["cell_s", "cell_ab"] if cell_id == "all" else [cell_id]
        app.state.safety_stop_generation = int(getattr(app.state, "safety_stop_generation", 0)) + 1
        for cid in affected_cells:
            app.state.human_detected[cid] = True
            prev = dict(app.state.omx_cell_states.get(cid) or {})
            prev_phase = prev.get("phase") if prev.get("phase") != "HUMAN_HOLD" else (prev.get("prev_phase") or "IDLE")
            docked = dict(prev["docked_robot"], v_cmd_mps=0.0) if isinstance(prev.get("docked_robot"), dict) else None
            app.state.omx_cell_states[cid] = {
                **prev, "phase": "HUMAN_HOLD", "prev_phase": prev_phase,
                "amr_motion_inhibited": True, "reason": "VISION_HUMAN_DETECTED_ESTOP", "docked_robot": docked,
            }
        app.state.human_detected["all"] = bool(app.state.human_detected.get("cell_s") and app.state.human_detected.get("cell_ab"))
        for t in app.state.omx_cell_tasks.values():
            if t["cell_id"] in affected_cells and t["status"] in ("QUEUED", "RUNNING"):
                t["paused_from_status"], t["status"] = t["status"], "PAUSED_HUMAN"
                _enrich_task_health(t)
                paused_tasks.append(t["task_id"])
        pending_inflight = _mark_pinky_stops_pending("vision_human_estop")
        halt_targets = _close_runner_trips("vision_human_estop")
        dec = _evaluate_decision(cell_id if cell_id != "all" else "cell_s", "arm_target", {"human_detected": True}, save=False)
        raw_rid = body.get("robot_id")
        target_robot_id = str(raw_rid).strip() if isinstance(raw_rid, str) and raw_rid.strip() else None
        pid = f"pinky-estop-{uuid.uuid4().hex[:6]}"
        pinky_estop = {
            "task_id": pid, "robot_id": target_robot_id, "action": "stop_now",
            "target_place": "VISION_HUMAN_ESTOP", "cable_guard_micro": True, "max_step_m": 0.0, "v_cmd_mps": 0.0, "duration_s": 0.0,
            "decision": dec, "spawned_cell_task_id": None, "status": "QUEUED", "created_at": round(time.time(), 3),
        }
        app.state.pinky_tasks[pid] = pinky_estop
        unconfirmed_stops = await _commit_and_halt_human_stop(
            pending_inflight, halt_targets, "vision_human_estop", target_robot_id=target_robot_id, pinky_estop=pinky_estop,
        )
        return {
            "ok": not unconfirmed_stops,
            "stop_confirmed": not unconfirmed_stops,
            "unconfirmed_pinky_stops": unconfirmed_stops,
            "vision_checked": True,
            "camera_snapshot_bytes": snap_bytes,
            "intrusion_score": intrusion_score,
            "human_detected": human_detected,
            "active_estop": _is_human_detected(),
            "detected_displaced_site": app.state.detected_displaced_site,
            "paused_tasks": paused_tasks,
            "resumed_tasks": resumed_tasks,
            "pinky_estop": pinky_estop,
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

    @app.post("/api/fleet/pipeline/decision-gate", dependencies=operator_guard)
    async def run_pipeline_decision_gate(request: Request):
        active = active_map()
        body = await request.json()
        subject_id = str(body.get("subject_id") or "cell_s")
        domain = body.get("domain")
        auto_execute = bool(body.get("auto_execute", True))
        dec = _evaluate_decision(subject_id, domain, body.get("facts") or body)
        spawned_cell_task = None
        pinky_task = None
        held = _is_human_detected() or any(state.get("phase") == "HUMAN_HOLD"
                                            for state in app.state.omx_cell_states.values())
        if auto_execute and held and (dec.get("auto_preset") or dec.get("auto_pinky_action") not in (None, "stop_now")):
            raise HTTPException(409, detail={"code": "HUMAN_HOLD_ACTIVE"})
        if auto_execute:
            if dec["domain"] == "arm_target" and dec.get("auto_preset"):
                preset_spec = CELL_TASK_PRESETS[dec["auto_preset"]]
                spawned_cell_task = _enqueue_one_task(active, {
                    **preset_spec,
                    **({"robot_id": body["robot_id"]} if "robot_id" in body else {}),
                    "cable_guard_micro": dec["cable_guard_micro"],
                })
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
                    if _aborted("cell_s"):
                        raise HTTPException(409, detail={"code": "CELL_ABORTED_HOLD"})
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
                    "status": "QUEUED",
                    "created_at": round(time.time(), 3),
                    **dispatch_fields(active, request, "S3" if target_place == "S3" else None),
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
        return {"tasks": tasks, "pinky_dispatch_enabled": pinky_dispatch_enabled()}
