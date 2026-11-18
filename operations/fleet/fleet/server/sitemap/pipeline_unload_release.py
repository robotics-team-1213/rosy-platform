"""When an AMR docked at S3 may leave (2026-11-19 panel: Claude, opencode, agy partial; user: "다 가져가고 나면 판정해서
전달하고, 정지해 있던 AMR가 출발해야 해").

A dock_and_unload_s3 starts one unload batch with one s3_shuttle; after each verified carry the cell looks at the bed
(source_clearance) and, while it still sees objects, the next s3_shuttle joins the batch (continue_unload). Nobody types
a count (user 2026-11-19): a cargo_manifest from Harbor, when given, is the expected count. The vehicle is ready only
when every check holds at once:
- COUNT: no task aborted or cancelled, none open, and the manifest count (if any) completed;
- BED: the last completion's source_clearance saw 0 objects on the AMR site (the cell's camera); missing = not seen;
- ARM: arm_s folded by measurement and fresh; the cell RELEASED and not inhibited;
- HOLD: no arm hold, no person detected or HUMAN_HOLD.
Either source alone fails one way: the camera alone leaves with a box it missed, the ledger alone leaves after a box
fell back on the bed. The departure is automatic (user 2026-11-19, replacing 11-14's operator approval for this path):
depart_tick sends the vehicle to the site rules' return.exit_place once the check holds on two ticks, re-checks with a
tight fold age, records the release before it sends (persisted with the ledger), and holds after three failed sends.
A named operator may still send it early with depart_s3; a release is used once per batch."""
from __future__ import annotations

from fastapi import HTTPException

FOLD_MAX_AGE_S = 120.0  # an operator's depart may come a minute after the last park; older fold readings are not trusted
DEPART_FOLD_AGE_S = 15.0  # the automatic send trusts only a fold reading this fresh (cell-quality posts every few s)
BED_MAX_AGE_S = 300.0  # the bed look belongs to this stop, not to an earlier one
MAX_CONTAINERS = 6
MAX_SEND_ATTEMPTS = 3
OPEN_STATUSES = ("QUEUED", "RUNNING", "PAUSED_HUMAN")


def batch_tasks(tasks: dict, robot_id: str) -> list[dict]:
    """The robot's newest unload batch, in order."""
    rows = [t for t in tasks.values() if t.get("unload_batch_id") and t.get("robot_id") == robot_id]
    if not rows:
        return []
    newest = max(rows, key=lambda t: t.get("created_at") or 0)["unload_batch_id"]
    return sorted((t for t in rows if t["unload_batch_id"] == newest), key=lambda t: t.get("unload_index", 0))


def _objects(task: dict):
    stage = task.get("stage_result")
    clearance = stage.get("source_clearance") if isinstance(stage, dict) else None
    return clearance, (clearance.get("objects") if isinstance(clearance, dict) else None)


def unload_release(state, robot_id: str, *, now: float, human_detected: bool, fold_max_age_s: float = FOLD_MAX_AGE_S,
                   allow_used: bool = False) -> dict:
    """{ready, reasons, ...} for one robot; reasons empty exactly when ready."""
    rows = batch_tasks(state.omx_cell_tasks, robot_id)
    out = {"robot_id": robot_id, "ready": False, "batch_id": None, "expected": 0, "completed": 0, "reasons": []}
    if not rows:
        return {**out, "reasons": ["NO_UNLOAD_BATCH"]}
    batch, expected = rows[0]["unload_batch_id"], rows[0].get("unload_expected")
    done = [t for t in rows if t.get("status") == "COMPLETED"]
    reasons = []
    if any(t.get("status") in ("ABORTED", "CANCELLED") for t in rows):
        reasons.append("UNLOAD_ABORTED")
    if any(t.get("status") in OPEN_STATUSES for t in rows):
        reasons.append("UNLOAD_IN_PROGRESS")
    if type(expected) is int and len(done) != expected:
        reasons.append("COUNT_MISMATCH")
    last = max(done, key=lambda t: t.get("completed_at") or 0) if done else {}
    clearance, objects = _objects(last)
    if type(objects) is not int or now - float(last.get("completed_at") or 0) > BED_MAX_AGE_S:
        reasons.append("BED_NOT_OBSERVED")
    elif objects != 0:
        reasons.append("CARGO_NOT_EMPTY")
    cell = state.omx_cell_states.get("cell_s") or {}
    if cell.get("phase") != "RELEASED" or cell.get("amr_motion_inhibited"):
        reasons.append("CELL_NOT_RELEASED")
    arm = state.arm_live_states.get("arm_s") or {}
    updated = arm.get("updated_at")
    if arm.get("folded") is not True or not isinstance(updated, (int, float)) or now - updated > fold_max_age_s:
        reasons.append("ARM_NOT_HOME")
    if (state.arm_holds.get("arm_s") or {}).get("held"):
        reasons.append("ARM_HELD")
    if human_detected or cell.get("phase") == "HUMAN_HOLD":
        reasons.append("HUMAN_HOLD")
    if batch in state.unload_releases and not allow_used:
        reasons.append("RELEASE_ALREADY_USED")
    return {**out, "ready": not reasons, "batch_id": batch, "expected": expected, "completed": len(done),
            "reasons": reasons, "clearance": clearance, "arm_folded": arm.get("folded"), "arm_updated_at": updated}


def manifest_count(body: dict):
    """The expected count from a system-provided cargo_manifest (Harbor), else None (the camera decides the end)."""
    manifest = body.get("cargo_manifest")
    if manifest is None:
        return None
    if (not isinstance(manifest, list) or not 1 <= len(manifest) <= MAX_CONTAINERS
            or not all(isinstance(ref, str) and ref for ref in manifest)):
        raise HTTPException(422, detail={"code": "INVALID_CARGO_MANIFEST"})
    return len(manifest)


def continue_unload(state, enqueue) -> list[str]:
    """After a verified carry that still sees objects on the bed, the next s3_shuttle joins the batch (camera-driven)."""
    batches: dict = {}
    for task in state.omx_cell_tasks.values():
        if task.get("unload_batch_id"):
            batches.setdefault(task["unload_batch_id"], []).append(task)
    made = []
    for batch_id, rows in batches.items():
        rows.sort(key=lambda t: t.get("unload_index", 0))
        last = rows[-1]
        if (batch_id in state.unload_releases or len(rows) >= MAX_CONTAINERS
                or any(t.get("status") != "COMPLETED" for t in rows)):
            continue
        _clearance, objects = _objects(last)
        if type(objects) is int and objects > 0:
            made.append(enqueue({"robot_id": last["robot_id"], "task_id": f"{batch_id}-{len(rows) + 1}",
                                 "depends_on": last["task_id"], "unload_batch_id": batch_id,
                                 "unload_expected": last.get("unload_expected"), "unload_index": len(rows)})["task_id"])
    return made


def _event(state, robot_id, batch, result, why, now) -> None:
    from fleet.server.sitemap import pipeline_auto_events

    pipeline_auto_events.add(state, [{"kind": "auto_depart", "robot_id": robot_id, "batch_id": batch, "result": result,
                                      "why": why, "t": now}], "fleet")


def exit_target(rules, site) -> tuple[str, float, float, float] | None:
    """(place_id, x, y, yaw) of the site rules' return.exit_place on the active map, else None (never a guess)."""
    place_id = getattr(getattr(rules, "return_", None), "exit_place", None) if rules is not None else None
    place = next((p for p in getattr(site, "places", ()) if p.id == place_id), None) if place_id else None
    if place is None:
        return None
    return place_id, float(place.x), float(place.y), float(getattr(place, "yaw", 0.0) or 0.0)


async def depart_tick(state, *, console, rules, site, enqueue, human_detected, save, now: float, task_log=None) -> list[dict]:
    """One pass: continue camera-driven unloads, then send each vehicle whose check held on two ticks to the exit."""
    continue_unload(state, enqueue)
    sent = []
    if getattr(state, "depart_ready", None) is None:
        state.depart_ready = {}
    seen = state.depart_ready
    robots = {t["robot_id"] for t in state.omx_cell_tasks.values() if t.get("unload_batch_id")}
    for robot_id in sorted(robots):
        release = unload_release(state, robot_id, now=now, human_detected=human_detected,
                                 fold_max_age_s=DEPART_FOLD_AGE_S, allow_used=True)
        batch = release.get("batch_id")
        record = state.unload_releases.get(batch) if batch else None
        if record is not None and record.get("state") != "SENDING":
            continue  # sent, held or taken by an operator's depart_s3
        if not release["ready"]:
            seen.pop(batch, None)
            continue
        seen[batch] = seen.get(batch, 0) + 1
        if seen[batch] < 2:
            continue  # the same answer on two ticks, not one lucky sample
        target = exit_target(rules, site)
        if record is None:
            record = state.unload_releases[batch] = {"robot_id": robot_id, "state": "SENDING", "attempts": 0,
                                                     "at": round(now, 3), "operator": None, "release": release}
            if target is None:
                record.update(state="HELD", reason="NO_EXIT_PLACE")
                _event(state, robot_id, batch, "HELD", "NO_EXIT_PLACE", now)
            save()  # the claim is on disk before anything moves
        if target is None:
            continue
        record["attempts"] += 1
        record["target"] = target[0]
        try:
            result = await console.goal(robot_id, target[1], target[2], target[3])
            accepted = bool(result.get("accepted")) or bool(result.get("queued"))
        except Exception as exc:  # one failed send is data; the next tick retries up to MAX_SEND_ATTEMPTS
            accepted, result = False, {"error": f"{type(exc).__name__}: {exc}"[:200]}
        if accepted:
            record.update(state="SENT", sent_at=round(now, 3), receipt={k: result.get(k) for k in ("accepted", "queued")})
            _event(state, robot_id, batch, "SENT", target[0], now)
            if task_log is not None:  # the robot task ledger is the caller's (pipeline_cell_task_routes)
                task_log(robot_id, batch, target[0], now)
            sent.append(record)
        elif record["attempts"] >= MAX_SEND_ATTEMPTS:
            record.update(state="HELD", reason="DEPART_SEND_FAILED", last_error=result.get("error"))
            _event(state, robot_id, batch, "HELD", "DEPART_SEND_FAILED", now)
        save()
    return sent


def install_unload_release_routes(app, ctx) -> None:
    import asyncio
    import logging
    import time

    log = logging.getLogger(__name__)
    app.state.unload_releases = getattr(app.state, "unload_releases", None) or {}

    @app.get("/api/fleet/pipeline/unload-release", dependencies=ctx.read_guard)
    async def read_unload_release(robot_id: str):
        out = unload_release(app.state, robot_id, now=time.time(), human_detected=bool(ctx._is_human_detected()))
        return {**out, "departure": app.state.unload_releases.get(out.get("batch_id"))}

    def tick_args():
        active = ctx.active_map()
        return dict(console=ctx.console, rules=ctx.rules(), site=active[1],
                    enqueue=lambda spec: ctx._enqueue_one_task(active, {**ctx.CELL_TASK_PRESETS["s3_shuttle"], **spec}),
                    human_detected=bool(ctx._is_human_detected()), save=ctx._save_ledger, now=time.time(),
                    task_log=getattr(ctx, "record_depart_task", None))

    app.state.depart_tick = lambda: depart_tick(app.state, **tick_args())
    if getattr(ctx, "console", None) is None:
        return  # no robots to send (bare test apps): the read route and depart_s3 still work
    inner = app.router.lifespan_context

    async def run():
        while True:
            try:
                await app.state.depart_tick()
            except Exception:  # one bad pass must not end automatic departure
                log.exception("unload departure tick failed")
            await asyncio.sleep(1.0)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(application):
        async with inner(application) as value:
            task = asyncio.create_task(run())
            try:
                yield value
            finally:
                task.cancel()

    app.router.lifespan_context = lifespan
