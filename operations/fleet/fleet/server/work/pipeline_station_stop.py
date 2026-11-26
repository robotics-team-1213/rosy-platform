"""Release an assigned station operation using its persisted trip, role and external evidence."""

from __future__ import annotations

import time

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field


class Release(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: str = Field(min_length=1, max_length=128)
    trip_id: str = Field(min_length=1, max_length=192)
    place_id: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=16)


def assigned_rule(rules, place, role):
    entry = next((s for s in getattr(rules, "stops", ()) if s.place == place), None)
    if entry is None or entry.role != role or entry.release != "external":
        raise HTTPException(409, detail={"code": "STATION_RULE_MISMATCH", "place_id": place, "role": role})
    return {"role": role, "place_id": place, "timeout_s": entry.timeout_s, "state": "ASSIGNED"}


def stop_reason(state, robot, tasks):
    for task in tasks.values():
        station = task.get("station_operation") or {}
        if task.get("robot_id") != robot or not station:
            continue
        if station["state"] in {"WAITING", "TIMEOUT_HOLD"}:
            return "STATION_" + station["state"]
        if station["state"] == "ASSIGNED" and task.get("status") == "SENT" and task.get("trip_id"):
            runner = getattr(state, "trip_runner", None)
            if runner and (runner.view(task["trip_id"]) or {}).get("state") == "arrived":
                return "STATION_WAITING"
    return None


def arrived(task, now):
    station = task.get("station_operation")
    if station and station["state"] == "ASSIGNED":
        station.update(state="WAITING", trip_id=task["trip_id"], arrived_at=now, deadline=now + station["timeout_s"])


def supervise(state, now, human, save, tasks):
    for task in tasks.values():
        op = task.get("station_operation") or {}
        if op.get("state") != "WAITING":
            continue
        if now >= op["deadline"]:
            op.update(state="TIMEOUT_HOLD", reason="STATION_RELEASE_TIMEOUT")
            try:
                save()
            except Exception:
                op.update(state="WAITING")
                op.pop("reason", None)
                raise
        elif op["role"] == "unload" and not human:
            proof = unload_proof(state, task, now, human)
            if proof:
                record_release(op, "cell_s", now, save, proof)


def unload_proof(state, task, now, human):
    from fleet.server.pipeline_unload_release import DEPART_FOLD_AGE_S, unload_release
    initial = state.omx_cell_tasks.get(task.get("spawned_cell_task_id")) or {}
    batch = initial.get("unload_batch_id")
    evidence = unload_release(state, task["robot_id"], now=now, human_detected=human, fold_max_age_s=DEPART_FOLD_AGE_S)
    if batch and evidence["ready"] and evidence["batch_id"] == batch:
        return {"batch_id": batch, "stage_id": state.omx_cell_states["cell_s"]["stage_id"]}
    return None


def record_release(op, actor, now, save, proof=None):
    before = dict(op)
    op.update(state="RELEASED", released_by=actor, released_at=now, evidence=proof)
    try:
        save()
    except Exception:
        op.clear()
        op.update(before)
        raise


def install(app, ctx, tasks_of, release_path, requester_named):
    def held(robot):
        return stop_reason(app.state, robot, tasks_of())
    if ctx.console is not None:
        ctx.console.station_stop_reason = held
        leases = getattr(ctx.console, "goal_leases", None)
        if leases is not None:
            leases.station_stop_reason = held
    if runner := getattr(app.state, "trip_runner", None):
        runner.station_stop_reason = held

    @app.post(release_path, dependencies=ctx.operator_guard)
    async def release(task_id: str, body: Release, request: Request):
        task = tasks_of().get(task_id) or {}
        op = task.get("station_operation") or {}
        principal = getattr(request.state, "site_principal", None)
        if not requester_named(app.state, principal):
            raise HTTPException(403, detail={"code": "NAMED_OPERATOR_REQUIRED"})
        if not op or (task.get("robot_id"), op.get("trip_id"), op["place_id"], op["role"]) != (
                body.robot_id, body.trip_id, body.place_id, body.role):
            raise HTTPException(409, detail={"code": "STATION_RELEASE_IDENTITY_MISMATCH"})
        if op["state"] == "RELEASED":
            return {"station_operation": op}
        if op["state"] not in {"WAITING", "TIMEOUT_HOLD"} or ctx._is_human_detected():
            raise HTTPException(409, detail={"code": "STATION_RELEASE_UNAVAILABLE"})
        now = time.time()
        proof = None
        if op["role"] == "unload":
            proof = unload_proof(app.state, task, now, False)
            if proof is None:
                raise HTTPException(409, detail={"code": "CELL_RELEASE_UNVERIFIED"})
        record_release(op, principal.principal_id, now, ctx._save_ledger, proof)
        return {"station_operation": op}


def stage_departure_trip(state, robot_id, batch, place_id, release, now, map_version, save, tasks, enabled):
    """Persist the release and the corresponding named-place task in the same ledger snapshot."""
    tid = f"depart-{batch}"
    if batch in state.unload_releases:
        return
    record = {"robot_id": robot_id, "task_id": tid, "at": now, "target": place_id, "release": release}
    inserted = False
    if tid in tasks or not enabled():
        record.update(state="HELD", reason="DEPART_TASK_ID_IN_USE" if tid in tasks else "TRIP_DISPATCH_DISABLED")
    else:
        record["state"] = "TRIP_QUEUED"
        tasks[tid] = {
            "task_id": tid, "robot_id": robot_id, "action": "depart_s3", "place_id": place_id, "target_place": place_id,
            "unload_batch_id": batch, "map_version": map_version, "auto": True, "requested_by": "fleet:auto-depart",
            "requester_named": False, "status": "QUEUED", "created_at": now,
        }
        inserted = True
    state.unload_releases[batch] = record
    try:
        save()
    except Exception:
        state.unload_releases.pop(batch, None)
        if inserted:
            tasks.pop(tid, None)
        raise



def plan_station(body, graph, rules):
    role, place_id = body.get("role"), body.get("place_id")
    if role not in ("load", "wait") or not isinstance(place_id, str) or place_id not in graph.places:
        raise HTTPException(422, detail={"code": "INVALID_ASSIGNED_STATION"})
    return assigned_rule(rules, place_id, role)


def record_depart_task(tasks, robot_id, batch, place, now):
    tasks[f"depart-{batch}"] = {"task_id": f"depart-{batch}", "robot_id": robot_id, "action": "depart_s3",
                                            "target_place": place, "status": "SENT", "auto": True, "created_at": round(now, 3)}


def operator_departure(state, request, robot_id, task_id, rules, site, human, tasks):
    from fleet.server.pipeline_unload_release import unload_release, exit_target
    if reason := stop_reason(state, robot_id, tasks):
        raise HTTPException(409, detail={"code": reason})
    release = unload_release(state, robot_id, now=time.time(), human_detected=bool(human))
    if not release["ready"]:
        raise HTTPException(409, detail={"code": "DEPART_NOT_PERMITTED", "reasons": release["reasons"]})
    target = exit_target(rules, site)
    if target is None:
        raise HTTPException(409, detail={"code": "NO_EXIT_PLACE"})
    principal = getattr(request.state, "site_principal", None)
    unload_batch_id = release["batch_id"]
    state.unload_releases[unload_batch_id] = {
        "robot_id": robot_id, "task_id": task_id, "at": round(time.time(), 3), "state": "OPERATOR",
        "operator": getattr(principal, "principal_id", None), "target": target[0], "release": release}
    place_id = target[0]
    return place_id, unload_batch_id
