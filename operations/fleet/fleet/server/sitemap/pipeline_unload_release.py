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
Only a goal the robot accepted is SENT. A goal Fleet merely queued (robot not LOCALIZED, traffic) is withdrawn in the
same tick: the traffic loop would release it later without these checks. The record stays SENDING and the next tick
checks everything again, for at most DEPART_QUEUE_WAIT_S from the first queue (queued_since); then HELD
(DEPART_WAIT_EXPIRED) until an operator re-arms.
A named operator may still send it early with depart_s3; a release is used once per batch."""
from __future__ import annotations

import asyncio
import logging
import math

from fastapi import HTTPException

_LOG = logging.getLogger(__name__)

FOLD_MAX_AGE_S = 120.0  # an operator's depart may come a minute after the last park; older fold readings are not trusted
DEPART_FOLD_AGE_S = 15.0  # the automatic send trusts only a fold reading this fresh (cell-quality posts every few s)
BED_MAX_AGE_S = 300.0  # the bed look belongs to this stop, not to an earlier one
MAX_CONTAINERS = 6
MAX_SEND_ATTEMPTS = 3
DEPART_QUEUE_WAIT_S = 120.0  # D-1060 MAX_QUEUE_AGE_S: a later move is not this moment's intent
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
    if not isinstance(clearance, dict):
        return clearance, None
    if clearance.get("site") not in (None, "pinky"):
        return clearance, None  # D-1047: displaced-site clearance is not a Pinky cargo-bed check
    return clearance, clearance.get("objects")


def _fresh(ts, now: float, max_age_s: float) -> bool:
    return (isinstance(ts, (int, float)) and not isinstance(ts, bool)
            and math.isfinite(ts) and (-5.0 <= (now - ts) <= max_age_s))


def _effective_batch_rows(rows: list[dict]) -> list[dict]:
    """Exclude ABORTED rows that were explicitly superseded by a COMPLETED repark retry."""
    superseded = {
        (t.get("unload_batch_id"), t.get("robot_id"), t.get("unload_index"), t.get("repark_root"))
        for t in rows
        if t.get("status") == "COMPLETED" and t.get("repark_root")
    }
    return [
        t for t in rows
        if not (
            t.get("status") == "ABORTED"
            and (t.get("unload_batch_id"), t.get("robot_id"), t.get("unload_index"), t.get("repark_root") or t.get("task_id"))
            in superseded
        )
    ]


def unload_release(state, robot_id: str, *, now: float, human_detected: bool, fold_max_age_s: float = FOLD_MAX_AGE_S,
                   allow_used: bool = False) -> dict:
    """{ready, reasons, ...} for one robot; reasons empty exactly when ready."""
    rows = batch_tasks(state.omx_cell_tasks, robot_id)
    out = {"robot_id": robot_id, "ready": False, "batch_id": None, "expected": 0, "completed": 0, "reasons": []}
    if not rows:
        return {**out, "reasons": ["NO_UNLOAD_BATCH"]}
    eff = _effective_batch_rows(rows)
    batch, expected = rows[0]["unload_batch_id"], rows[0].get("unload_expected")
    done = [t for t in eff if t.get("status") == "COMPLETED"]
    reasons = []
    if any(t.get("status") in ("ABORTED", "CANCELLED") for t in eff):
        reasons.append("UNLOAD_ABORTED")
    if any(t.get("status") in OPEN_STATUSES for t in eff):
        reasons.append("UNLOAD_IN_PROGRESS")
    if type(expected) is int and len(done) != expected:
        reasons.append("COUNT_MISMATCH")
    last = max(done, key=lambda t: t.get("completed_at") or 0) if done else {}
    clearance, objects = _objects(last)
    if type(objects) is not int or not _fresh(last.get("completed_at"), now, BED_MAX_AGE_S):
        reasons.append("BED_NOT_OBSERVED")
    elif objects != 0:
        reasons.append("CARGO_NOT_EMPTY")
    cell = state.omx_cell_states.get("cell_s") or {}
    if cell.get("phase") != "RELEASED" or cell.get("amr_motion_inhibited"):
        reasons.append("CELL_NOT_RELEASED")
    elif done and (cell.get("robot_id") != robot_id or cell.get("unload_batch_id") != batch
                   or not last.get("task_id") or cell.get("stage_id") != last["task_id"]):
        reasons.append("CELL_RELEASE_IDENTITY_MISMATCH")
    arm = state.arm_live_states.get("arm_s") or {}
    updated = arm["folded_updated_at"] if "folded_updated_at" in arm else arm.get("updated_at")
    if arm.get("folded") is not True or not _fresh(updated, now, fold_max_age_s):
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
        eff = _effective_batch_rows(rows)
        if not eff:
            continue
        eff.sort(key=lambda t: (t.get("unload_index", 0), t.get("created_at") or 0))
        last = eff[-1]
        if (batch_id in state.unload_releases or len(eff) >= MAX_CONTAINERS
                or any(t.get("status") != "COMPLETED" for t in eff)):
            continue
        _clearance, objects = _objects(last)
        if type(objects) is int and objects > 0:
            next_idx = (last.get("unload_index") or 0) + 1
            spec = {
                "robot_id": last["robot_id"], "task_id": f"{batch_id}-{next_idx + 1}",
                "depends_on": last["task_id"], "unload_batch_id": batch_id,
                "unload_expected": last.get("unload_expected"), "unload_index": next_idx,
            }
            if last.get("emit_release_permit") is True:
                spec["emit_release_permit"] = True
            made.append(enqueue(spec)["task_id"])
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


def _fence_ambiguous_depart(state, *, batch: str, robot_id: str, target_place: str, record: dict, now: float,
                            reason: str, cancelled_by: str, err_code: str, cancel_receipt: dict | None = None,
                            last_error: str | None = None, task_log=None) -> None:
    if task_log is not None:
        task_log(robot_id, batch, target_place, now)
    tasks = getattr(state, "pinky_tasks", None)
    if isinstance(tasks, dict):
        depart_task = tasks.setdefault(f"depart-{batch}", {})
        for _k, _v in (
            ("task_id", f"depart-{batch}"), ("robot_id", robot_id), ("action", "depart_s3"),
            ("target_place", target_place), ("status", "SENT"), ("auto", True), ("created_at", round(now, 3)),
        ):
            depart_task.setdefault(_k, _v)
        depart_task.update(cancel_requested=True, cancelled_by=cancelled_by,
                           cancel_receipt=cancel_receipt or {"error": err_code})
    record.update(state="HELD", reason=reason, **({"last_error": last_error} if last_error is not None else {}))
    _event(state, robot_id, batch, "HELD", reason, now)


async def depart_tick(state, *, console, rules, site, enqueue, human_detected, save, now: float, task_log=None,
                      flush_port_events=None, dispatch_open=None, stage_trip=None) -> list[dict]:
    """One pass: continue camera-driven unloads, then send each vehicle whose check held on two ticks to the exit."""
    human_now = (lambda: bool(human_detected())) if callable(human_detected) else (lambda: bool(human_detected))

    def _live_stop_blocked() -> bool:
        try:
            if getattr(state, "_pipeline_ledger_fault", False) or getattr(state, "_fleet_estop_latch_unresolved", False):
                return True
            if human_now():
                return True
            if any((s or {}).get("phase") == "HUMAN_HOLD" for s in (getattr(state, "omx_cell_states", None) or {}).values()):
                return True
            if any(bool(v) for v in (getattr(state, "human_detected", None) or {}).values()):
                return True
            if callable(dispatch_open) and not bool(dispatch_open()):
                return True
            return False
        except Exception:
            return True

    def _save_settled(rec: dict, *, clear_marker: bool = True) -> None:
        had_marker = bool(rec.get("submit_in_flight"))
        if clear_marker:
            rec.pop("submit_in_flight", None)
        try:
            save()
        except Exception:
            if had_marker:
                rec["submit_in_flight"] = True
            raise

    for _bid, _rec in list((getattr(state, "unload_releases", None) or {}).items()):
        if isinstance(_rec, dict) and _rec.get("submit_in_flight") and _rec.get("state") in ("SENDING", "SENT"):
            _fence_ambiguous_depart(
                state, batch=_bid, robot_id=_rec.get("robot_id") or "", target_place=_rec.get("target") or "S1",
                record=_rec, now=now, reason="DEPART_SEND_AMBIGUOUS", cancelled_by="depart_ambiguous_recovery",
                err_code="DEPART_SUBMIT_AMBIGUOUS", task_log=task_log,
            )
            try:
                _save_settled(_rec, clear_marker=False)
            except Exception:
                _LOG.exception("depart recovery save failed batch=%s", _bid)

    if console is not None and any(
        t.get("status") == "SENT" and "plan_id" not in t and t.get("cancel_requested")
        for t in (getattr(state, "pinky_tasks", None) or {}).values()
    ):
        from fleet.server.pipeline_pinky_dispatch import retry_native_cancels

        await retry_native_cancels(state, console=console, save=save, now=now)
    if flush_port_events is not None and any(t.get("pending_port_events") for t in state.omx_cell_tasks.values()):
        try:
            if await flush_port_events():
                save()
        except Exception:
            _LOG.exception("pending port-event flush failed in depart_tick")
    continue_unload(state, enqueue)
    sent = []
    if getattr(state, "depart_ready", None) is None:
        state.depart_ready = {}
    seen = state.depart_ready
    robots = {t["robot_id"] for t in state.omx_cell_tasks.values() if t.get("unload_batch_id")}
    for robot_id in sorted(robots):
        release = unload_release(state, robot_id, now=now, human_detected=_live_stop_blocked(),
                                 fold_max_age_s=DEPART_FOLD_AGE_S, allow_used=True)
        batch = release.get("batch_id")
        record = state.unload_releases.get(batch) if batch else None
        if record is not None and record.get("state") != "SENDING":
            continue  # sent, held or taken by an operator's depart_s3
        depart_task = (getattr(state, "pinky_tasks", None) or {}).get(f"depart-{batch}") if batch else None
        if isinstance(depart_task, dict) and depart_task.get("status") == "SENT" and depart_task.get("cancel_requested"):
            continue  # fenced until native cancel confirmation clears depart-<batch>
        if record is not None and record.get("queued_since") is not None and now - record["queued_since"] > DEPART_QUEUE_WAIT_S:
            record.update(state="HELD", reason="DEPART_WAIT_EXPIRED")
            _event(state, robot_id, batch, "HELD", "DEPART_WAIT_EXPIRED", now)
            save()
            continue
        if not release["ready"]:
            seen.pop(batch, None)
            continue
        seen[batch] = seen.get(batch, 0) + 1
        if seen[batch] < 2:
            continue  # the same answer on two ticks, not one lucky sample
        if _live_stop_blocked():
            seen.pop(batch, None)
            continue
        target = exit_target(rules, site)
        if stage_trip is not None:
            from fleet.server.pipeline_station_stop import stop_reason
            if stop_reason(state, robot_id, state.pinky_tasks):
                continue
            if target is not None and record is None:
                stage_trip(robot_id, batch, target[0], release, now)
            elif record is not None:
                record.update(state="HELD", reason="DEPART_LEGACY_ATTEMPT_REQUIRES_REVIEW")
                save()
            else:
                state.unload_releases[batch] = {"robot_id": robot_id, "state": "HELD", "reason": "NO_EXIT_PLACE"}
                save()
            continue
        if record is None:
            candidate = {"robot_id": robot_id, "state": "SENDING", "attempts": 0,
                         "at": round(now, 3), "operator": None, "release": release}
            if target is None:
                candidate.update(state="HELD", reason="NO_EXIT_PLACE")
                _event(state, robot_id, batch, "HELD", "NO_EXIT_PLACE", now)
            else:
                candidate["target"] = target[0]
                candidate["submit_in_flight"] = True
            state.unload_releases[batch] = candidate
            try:
                save()  # the claim is on disk before anything moves
            except Exception:
                state.unload_releases.pop(batch, None)
                raise
            record = candidate
        elif target is not None:
            record["target"] = target[0]
            record["submit_in_flight"] = True
            try:
                save()
            except Exception:
                record.pop("submit_in_flight", None)
                raise
        if target is None:
            continue
        stop_gen = int(getattr(state, "safety_stop_generation", 0))
        submitting = getattr(state, "_depart_submitting", None)
        if submitting is None:
            submitting = state._depart_submitting = set()
        submitting.add(batch)
        try:
            result = await console.goal(robot_id, target[1], target[2], target[3])
        except asyncio.CancelledError:
            _fence_ambiguous_depart(
                state, batch=batch, robot_id=robot_id, target_place=target[0], record=record, now=now,
                reason="DEPART_SEND_AMBIGUOUS", cancelled_by="depart_submit_cancelled",
                err_code="DEPART_SUBMIT_CANCELLED", task_log=task_log,
            )
            try:
                save()
            except Exception:
                pass
            raise
        except Exception as exc:  # one failed send may still have landed in CORE; re-check stop_landed below
            result = {"error": f"{type(exc).__name__}: {exc}"[:200], "_ambiguous_send": True}
        finally:
            submitting.discard(batch)
        if result.get("queued") is True and not result.get("accepted"):
            # Queued is not sent: the traffic loop would release it later without the fold, person, hold and bed checks.
            console.discard_queued_goal(robot_id)
            if result.get("dispatch_attempted") is True and result.get("cancel_confirmed") is not True:
                from fleet.server.pipeline_pinky_dispatch import _cancel_native_goal, _unconfirmed

                cancel_receipt = await _cancel_native_goal(console, robot_id)
                if _unconfirmed(cancel_receipt):
                    _fence_ambiguous_depart(
                        state, batch=batch, robot_id=robot_id, target_place=target[0], record=record, now=now,
                        reason="DEPART_CANCEL_UNCONFIRMED", cancelled_by="depart_queue_cleanup",
                        err_code="DEPART_CANCEL_UNCONFIRMED", cancel_receipt=cancel_receipt, task_log=task_log,
                    )
                    record["queue_reason"] = result.get("reason")
                    _save_settled(record, clear_marker=False)
                    continue
            if record.get("reason") != "GOAL_QUEUED_NOT_ACCEPTED":
                _event(state, robot_id, batch, "WAITING", result.get("reason") or "GOAL_QUEUED", now)
            record.update(reason="GOAL_QUEUED_NOT_ACCEPTED", queue_reason=result.get("reason"))
            record.setdefault("queued_since", round(now, 3))
            _save_settled(record, clear_marker=True)
            continue  # still SENDING: the next tick checks every release condition again
        record["attempts"] += 1
        accepted = bool(result.get("accepted"))
        stop_landed = int(getattr(state, "safety_stop_generation", 0)) != stop_gen or _live_stop_blocked()
        if stop_landed and (accepted or result.get("_ambiguous_send")):
            from fleet.server.pipeline_pinky_dispatch import _cancel_native_goal, _unconfirmed

            cancel_receipt = await _cancel_native_goal(console, robot_id)
            if _unconfirmed(cancel_receipt):
                _fence_ambiguous_depart(
                    state, batch=batch, robot_id=robot_id, target_place=target[0], record=record, now=now,
                    reason="HUMAN_HOLD_AFTER_SEND", cancelled_by="human_estop",
                    err_code="HUMAN_HOLD_AFTER_SEND", cancel_receipt=cancel_receipt, task_log=task_log,
                )
                _save_settled(record, clear_marker=False)
            else:
                record.update(state="HELD", reason="HUMAN_HOLD_AFTER_SEND")
                _event(state, robot_id, batch, "HELD", "HUMAN_HOLD_AFTER_SEND", now)
                _save_settled(record, clear_marker=True)
            continue
        if result.get("_ambiguous_send"):
            from fleet.server.pipeline_pinky_dispatch import _cancel_native_goal, _unconfirmed

            cancel_receipt = await _cancel_native_goal(console, robot_id)
            if _unconfirmed(cancel_receipt):
                _fence_ambiguous_depart(
                    state, batch=batch, robot_id=robot_id, target_place=target[0], record=record, now=now,
                    reason="DEPART_SEND_AMBIGUOUS", cancelled_by="depart_ambiguous_send",
                    err_code="DEPART_SEND_AMBIGUOUS", cancel_receipt=cancel_receipt,
                    last_error=result.get("error"), task_log=task_log,
                )
                _save_settled(record, clear_marker=False)
                continue
        if accepted:
            for key in ("reason", "queue_reason", "queued_since"):  # an earlier tick's queue wait is over
                record.pop(key, None)
            record.update(state="SENT", sent_at=round(now, 3), receipt={k: result.get(k) for k in ("accepted", "queued")})
            _event(state, robot_id, batch, "SENT", target[0], now)
            if task_log is not None:  # the robot task ledger is the caller's (pipeline_cell_task_routes)
                task_log(robot_id, batch, target[0], now)
            _save_settled(record, clear_marker=True)
            sent.append(record)
        elif record["attempts"] >= MAX_SEND_ATTEMPTS:
            record.update(state="HELD", reason="DEPART_SEND_FAILED", last_error=result.get("error"))
            _event(state, robot_id, batch, "HELD", "DEPART_SEND_FAILED", now)
            _save_settled(record, clear_marker=True)
        else:
            _save_settled(record, clear_marker=True)
    return sent


def _stage_departure_trip(state, robot_id, batch, place, release, now, version, save):
    from fleet.server.pipeline_pinky_dispatch import enabled
    from fleet.server.pipeline_station_stop import stage_departure_trip
    return stage_departure_trip(state, robot_id, batch, place, release, now, version, save, state.pinky_tasks, enabled)


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

    def _dispatch_open() -> bool:
        if getattr(app.state, "_fleet_estop_latch_unresolved", False):
            return False
        tsvc = getattr(app.state, "task_service", None)
        if tsvc is None:
            return True
        try:
            return tsvc.store.dispatch_control().get("dispatch_enabled") is True
        except Exception:
            return False

    async def _depart_tick():
        if not any(t.get("unload_batch_id") for t in app.state.omx_cell_tasks.values()):
            return []
        try:
            active = ctx.active_map()
        except HTTPException as exc:
            if exc.status_code == 404:
                return []
            raise
        from fleet.server.pipeline_port_events import flush_pending_port_events_async

        return await depart_tick(
            app.state,
            console=ctx.console,
            rules=ctx.rules(),
            site=active[1],
            enqueue=lambda spec: ctx._enqueue_one_task(active, {**ctx.CELL_TASK_PRESETS["s3_shuttle"], **spec}),
            human_detected=ctx._is_human_detected,
            save=ctx._save_ledger,
            now=time.time(),
            task_log=getattr(ctx, "record_depart_task", None),
            flush_port_events=lambda: flush_pending_port_events_async(app),
            dispatch_open=_dispatch_open,
            stage_trip=lambda robot, batch, place, release, now: _stage_departure_trip(
                app.state, robot, batch, place, release, now, active[0], ctx._save_ledger),
        )

    app.state.depart_tick = _depart_tick
    from fleet.server.sitemap.pipeline_repark import install_repark_routes

    install_repark_routes(app, ctx)  # a vehicle re-park closes here; DONE re-queues the cell task
    from fleet.server.sitemap.pipeline_observer import install_observer_routes

    install_observer_routes(app, ctx)  # a second idle vehicle looks at the docked one's stack (tier_hint)
    if getattr(ctx, "console", None) is None:
        return  # no robots to send (bare test apps): the read route and depart_s3 still work
    inner = app.router.lifespan_context

    async def run():
        while True:
            try:
                await app.state.depart_tick()
            except Exception:  # one bad pass must not end automatic departure
                log.exception("unload departure tick failed")
            try:  # D-1060: QUEUED AMR tasks go out as Fleet trips (env gate in the dispatch module)
                await app.state.task_dispatch_tick()
            except Exception:
                log.exception("AMR task dispatch tick failed")
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
