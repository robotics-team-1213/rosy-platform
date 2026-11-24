"""Pinky task dispatch (D-1060, panel 5 slice 3): a QUEUED pinky task drives once, as an ordinary Fleet trip.

The pinky-task routes only record a row; this tick is their consumer. It never sends a goal itself: the row's place
goes through the trip plan path (``app.state.trip_plan``) and ``TripRunner.start``, which own the map pose
check (LOCALIZED, fresh), the CORE trip lease, the map version, the console motion guard and the E-stop/cancel stop
(``trip_guard``). Arrival and every other end come only from the trip's own state. Later precision stops live in the
trip steps, not here.

Exactly once: the row is SENDING on disk before the plan, the plan id (= trip id) is on disk before the start, and a
SENDING row found at the next tick (restart, lost response, exception) is never planned or started again: its trip
decides SENT, else it ends FAILED DISPATCH_INTERRUPTED. Every refusal is terminal with a reason and moves nothing; a
person sends a new task. Off unless ROSY_FLEET_PINKY_TASK_DISPATCH=1 (a person turns it on at the site).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from contextlib import closing

from fastapi import HTTPException, Request

_LOG = logging.getLogger(__name__)

FLAG = "ROSY_FLEET_PINKY_TASK_DISPATCH"
MAX_QUEUE_AGE_S = 120.0  # an older request is not this moment's intent (a cancel-all or E-stop may sit between)
IN_FLIGHT = ("SENDING", "SENT")
TERMINAL = ("ARRIVED", "FAILED", "CANCELLED", "REFUSED")
#: The cell whose AMR zone the place is (pinky-task routes: dock_s3 checks cell_s, dock_s5 cell_ab).
CELL_AT_PLACE = {"S3": "cell_s", "S5": "cell_ab"}
ARMS_OF_CELL = {"cell_s": ("arm_s",), "cell_ab": ("arm_a", "arm_b")}
TRIP_OPEN = ("started", "running", "link_wait")  # trip_ports.OPEN


def requester_named(app_state, principal) -> bool:
    """True when the trip routes' guards (require_operator, then require_named_operator from
    site_auth.build_role_guards, set by app.py) admit this principal; no guards or no principal is False."""
    guards = getattr(app_state, "trip_requester_guards", None)
    if principal is None or not guards:
        return False
    try:
        for guard in guards:
            guard(principal)
    except HTTPException:
        return False
    return True


def dispatch_fields(active, request, place_id) -> dict:
    """What a pinky-task row carries for this dispatcher: its place, the map it was asked on and who asked."""
    principal = getattr(request.state, "site_principal", None)
    return {"place_id": place_id, "map_version": active[0], "requested_by": getattr(principal, "principal_id", None),
            "requester_named": requester_named(request.app.state, principal)}


def enabled() -> bool:
    return os.environ.get(FLAG) == "1"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds")


def last_cancel_all_at(task_service) -> str | None:
    """The newest D-421 cancel-all window opening (ISO, UTC) in the Fleet journal, or None."""
    with closing(task_service.store._connect()) as connection:
        row = connection.execute("SELECT MAX(opened_at) FROM fleet_cancel_all").fetchone()
    # Compared as strings with _iso(created): both sides must stay UTC isoformat(timespec="milliseconds").
    return row[0] if row is not None else None


def _cell_refusal(state, place, robot_id) -> str | None:
    cell_id = CELL_AT_PLACE.get(place)
    if cell_id is None:
        return None
    cell = state.omx_cell_states.get(cell_id) or {}
    if "ABORTED" in (cell.get("phase"), cell.get("prev_phase")) or any(
            (state.arm_holds.get(arm) or {}).get("held") for arm in ARMS_OF_CELL[cell_id]):
        return "CELL_HOLD"
    docked = (cell.get("docked_robot") or {}).get("robot_id")
    if (cell.get("amr_motion_inhibited") or cell.get("phase") == "ARM_IN_BED_ZONE"
            or (docked is not None and docked != robot_id)
            or any(t.get("cell_id") == cell_id and t.get("status") in ("RUNNING", "PAUSED_HUMAN")
                   for t in state.omx_cell_tasks.values())):
        return "CELL_BUSY"
    return None


def _depart_refusal(state, task: dict, *, now: float, human_detected: bool) -> str | None:
    if task.get("action") != "depart_s3":
        return None
    from fleet.server.sitemap.pipeline_unload_release import unload_release

    batch_id = task.get("unload_batch_id")
    rec = (getattr(state, "unload_releases", None) or {}).get(batch_id) if batch_id else None
    if (rec is None or rec.get("state") != "OPERATOR" or rec.get("task_id") != task.get("task_id")
            or (rec.get("target") and task.get("place_id") != rec.get("target"))
            or (rec.get("robot_id") and task.get("robot_id") != rec.get("robot_id"))):
        return "DEPART_RESERVATION_MISMATCH"
    rel = unload_release(state, task.get("robot_id") or "", now=now, human_detected=human_detected, allow_used=True)
    if not rel["ready"] or rel.get("batch_id") != batch_id:
        return (rel.get("reasons") or ["DEPART_NOT_PERMITTED"])[0]
    return None


def refusal(state, task: dict, *, now: float, active, robot_row, human_detected: bool, dispatch_open: bool,
            cancel_all_at: str | None, trip_busy: bool) -> str | None:
    """Why this QUEUED task may not drive now, or None. Pure: every input is read by the caller."""
    robot_id, place = task.get("robot_id"), task.get("place_id")
    if not place:
        return "ACTION_NOT_DISPATCHABLE"  # micro steps, stop_now, depart_s3: not a place goal
    if not task.get("requested_by"):
        return "REQUESTER_UNKNOWN"
    if task.get("requester_named") is not True:  # parity with the trip routes' require_named_operator
        return "REQUESTER_NOT_NAMED"
    created = float(task.get("created_at") or 0.0)
    if now - created > MAX_QUEUE_AGE_S:
        return "REQUEST_STALE"
    if active is None:
        return "NO_ACTIVE_MAP"
    if task.get("map_version") != active[0]:
        return "MAP_VERSION_CHANGED"
    if place not in active[2].places:
        return "PLACE_NOT_ON_MAP"
    if robot_row is None:
        return "ROBOT_UNKNOWN"
    if not robot_row.get("online"):
        return "ROBOT_OFFLINE"
    if ((robot_row.get("state") or {}).get("safety") or {}).get("estop") is not False:
        return "ROBOT_ESTOP"
    if not dispatch_open:
        return "DISPATCH_CLOSED"  # the site E-stop latch (or startup) closed Fleet dispatch
    if cancel_all_at is not None and cancel_all_at >= _iso(created):
        return "CANCEL_ALL_AFTER_REQUEST"
    if human_detected or any(s.get("phase") == "HUMAN_HOLD" for s in state.omx_cell_states.values()):
        return "HUMAN_HOLD"
    if cell_why := _cell_refusal(state, place, robot_id):
        return cell_why
    if depart_why := _depart_refusal(state, task, now=now, human_detected=human_detected):
        return depart_why
    if trip_busy or any(t is not task and _ours(t) and t.get("robot_id") == robot_id and t.get("status") in IN_FLIGHT
                        for t in state.pinky_tasks.values()):
        return "ROBOT_DISPATCH_IN_FLIGHT"
    return None


def _ours(task: dict) -> bool:
    """A row this dispatcher sent (depart_tick's SENT rows carry no plan id and are not ours)."""
    return "plan_id" in task


def _cleanup_on_end(state, task: dict, status: str, now: float) -> None:
    if state is None or status not in ("REFUSED", "FAILED", "CANCELLED"):
        return
    if task.get("action") == "depart_s3" and not task.get("trip_id"):
        batch_id = task.get("unload_batch_id")
        releases = getattr(state, "unload_releases", None)
        if batch_id and isinstance(releases, dict):
            rec = releases.get(batch_id)
            if rec is not None and rec.get("state") == "OPERATOR" and rec.get("task_id") == task.get("task_id"):
                releases.pop(batch_id, None)
    if task.get("action") == "dock_and_unload_s3":
        cid = task.get("spawned_cell_task_id")
        ctask = (getattr(state, "omx_cell_tasks", None) or {}).get(cid) if cid else None
        if ctask is not None and ctask.get("status") == "QUEUED":
            from fleet.server.sitemap.pipeline_routes import _enrich_task_health

            ctask["status"] = "CANCELLED"
            ctask["completed_at"] = round(now, 3)
            ctask["cancel_reason"] = f"PINKY_TASK_{status}"
            _enrich_task_health(ctask)


def _end(task: dict, status: str, reason, now: float, state=None) -> None:
    task.update(status=status, reason=reason, ended_at=round(now, 3))
    _cleanup_on_end(state, task, status, now)


def settle(task: dict, runner, now: float, state=None) -> bool:
    """SENT/SENDING from the trip's own state; True when the row changed."""
    trip_id = task.get("trip_id") or task.get("plan_id")
    view = runner.view(trip_id) if (runner is not None and trip_id) else None
    if task["status"] == "SENDING":  # left over: never plan or start again
        if view is None:
            if task.get("cancel_requested"):
                _end(task, "CANCELLED", "OPERATOR_CANCEL", now, state=state)
            else:
                _end(task, "FAILED", "DISPATCH_INTERRUPTED", now, state=state)
            return True
        task.update(status="SENT", trip_id=trip_id, sent_at=round(now, 3), receipt={"trip_state": view.get("state")})
    if view is None:
        _end(task, "FAILED", "TRIP_UNKNOWN", now, state=state)
        return True
    state_str = view.get("state")
    if state_str in TRIP_OPEN:
        changed = (task.get("receipt") or {}).get("trip_state") != state_str
        task["receipt"] = {**(task.get("receipt") or {}), "trip_state": state_str}
        return changed
    if state_str == "arrived":
        _end(task, "ARRIVED", None, now, state=state)
    elif state_str in ("canceled", "stopped"):
        if _unconfirmed(view) or (task.get("cancel_requested") and _unconfirmed(task.get("cancel_receipt"))):
            return False
        if state_str == "canceled":
            _end(task, "CANCELLED", view.get("reason") or "TRIP_CANCELED", now, state=state)
        else:
            _end(task, "FAILED", view.get("reason") or state_str, now, state=state)
    else:
        _end(task, "FAILED", view.get("reason") or state_str, now, state=state)
    return True


async def _retry_halt_trip(runner, trip_id: str) -> dict:
    if runner is None or not hasattr(runner, "retry_halt"):
        return {"error": "HALT_RETRY_UNAVAILABLE"}
    try:
        return await runner.retry_halt(trip_id)
    except Exception as exc:
        return {"error": _code(exc)}


def _depart_submit_active(state, task: dict) -> bool:
    tid = task.get("task_id") or ""
    if not tid.startswith("depart-"):
        return False
    return tid[len("depart-"):] in (getattr(state, "_depart_submitting", None) or ())


async def retry_native_cancels(state, *, console, save, now: float) -> None:
    """Retry any pending cancel on native S3 departure rows even when trip dispatch is disabled."""
    dirty = False
    for task in list(state.pinky_tasks.values()):
        if task.get("status") == "SENT" and not _ours(task) and task.get("cancel_requested"):
            receipt = await _cancel_native_goal(console, task.get("robot_id"))
            if _depart_submit_active(state, task):
                task["cancel_receipt"] = receipt if _unconfirmed(receipt) else {"error": "DEPART_SUBMIT_IN_FLIGHT"}
            else:
                task["cancel_receipt"] = receipt
                if not _unconfirmed(receipt):
                    _end(task, "CANCELLED", "OPERATOR_CANCEL", now, state=state)
            dirty = True
    if dirty:
        save()


def _dispatch_open_for_trip(state, task_service) -> bool:
    if getattr(state, "_fleet_estop_latch_unresolved", False) or getattr(state, "_pipeline_ledger_fault", False):
        return False
    try:
        return task_service.store.dispatch_control().get("dispatch_enabled") is True
    except Exception:
        return False


async def dispatch_tick(state, *, console, runner, plan, task_service, active, human_detected, save,
                        now: float, trip_request) -> list[dict]:
    """One pass: retry native cancels, settle in-flight rows, then dispatch each QUEUED place task at most once."""
    await retry_native_cancels(state, console=console, save=save, now=now)
    if not enabled():
        return []
    human_now = (lambda: bool(human_detected())) if callable(human_detected) else (lambda: bool(human_detected))
    for task in list(state.pinky_tasks.values()):
        if not (_ours(task) and task.get("status") in IN_FLIGHT):
            continue
        dirty = False
        trip_id = task.get("trip_id") or task.get("plan_id")
        if task.get("cancel_requested") and runner is not None and trip_id:
            view = runner.view(trip_id) or {}
            if view.get("state") in TRIP_OPEN:
                task["cancel_receipt"] = await _cancel_trip(runner, trip_id, task.get("cancelled_by"))  # unconfirmed: ask again
                if not task.get("trip_id"):
                    task["trip_id"] = trip_id
                dirty = True
            elif view.get("state") in ("canceled", "stopped") and (_unconfirmed(view) or _unconfirmed(task.get("cancel_receipt"))):
                task["cancel_receipt"] = await _retry_halt_trip(runner, trip_id)
                dirty = True
        if settle(task, runner, now, state=state) or dirty:
            save()
    queued = sorted((t for t in state.pinky_tasks.values() if t.get("status") == "QUEUED"),
                    key=lambda t: t.get("created_at") or 0)
    if not queued:
        return []
    sent = []
    if runner is None or plan is None or task_service is None or not getattr(runner.lease, "required", False):
        why = "TRIP_PATH_UNAVAILABLE" if task_service is not None else "FLEET_JOURNAL_UNAVAILABLE"
        for task in queued:
            _end(task, "REFUSED", why if task.get("place_id") else "ACTION_NOT_DISPATCHABLE", now, state=state)
        save()
        return sent
    sending = getattr(state, "_pinky_dispatch_sending", None)
    if sending is None:
        sending = state._pinky_dispatch_sending = set()
    rows = {row["robot_id"]: row for row in (await console.snapshot())["robots"]}
    awaited = False
    for task in queued:
        if awaited:
            rows = {row["robot_id"]: row for row in (await console.snapshot())["robots"]}
            awaited = False
        if task.get("status") != "QUEUED":  # an operator cancel landed while this tick awaited: never claim it
            continue
        dispatch_open = _dispatch_open_for_trip(state, task_service)
        cancel_all_at = last_cancel_all_at(task_service)
        robot_id = task.get("robot_id")
        why = refusal(state, task, now=now, active=active, robot_row=rows.get(robot_id),
                      human_detected=human_now(), dispatch_open=dispatch_open, cancel_all_at=cancel_all_at,
                      trip_busy=bool(runner.robot_busy(robot_id)))
        if why is not None:
            _end(task, "REFUSED", why, now, state=state)
            save()
            continue
        task.update(status="SENDING", sending_at=round(now, 3), plan_id=None, trip_id=None)
        save()  # the claim is on disk before anything is planned or started
        token = runner._start_token(robot_id)  # no await since the claim: a cancel-all or E-stop during the plan refuses the start
        tid = task.get("task_id")

        async def _guard(t=task, rid=robot_id) -> None:
            from fleet.server.trip_ports import TripError
            if t.get("cancel_requested") or t.get("status") != "SENDING":
                raise TripError(409, "OPERATOR_CANCEL")
            if not _dispatch_open_for_trip(state, task_service):
                raise TripError(409, "DISPATCH_CLOSED")
            latest_cancel = last_cancel_all_at(task_service)
            if latest_cancel is not None and latest_cancel >= _iso(float(t.get("created_at") or 0.0)):
                raise TripError(409, "CANCEL_ALL_AFTER_REQUEST")
            human_active = human_now()
            if human_active or any(s.get("phase") == "HUMAN_HOLD" for s in state.omx_cell_states.values()):
                raise TripError(409, "HUMAN_HOLD")
            if cell_why := _cell_refusal(state, t.get("place_id"), rid):
                raise TripError(409, cell_why)
            if depart_why := _depart_refusal(state, t, now=time.time(), human_detected=human_active):
                raise TripError(409, depart_why)

        sending.add(tid)
        try:
            awaited = True
            planned = await plan(robot_id, trip_request(task["place_id"]), task["requested_by"])
            task["plan_id"] = planned["plan_id"]
            save()  # a restart finds the plan id and never starts a second trip
            if task.get("cancel_requested") or task["status"] != "SENDING":
                if task["status"] == "SENDING":
                    _end(task, "CANCELLED", "OPERATOR_CANCEL", now, state=state)
                save()
                continue  # cancelled while planning: the plan is never started
            trip = await runner.start(planned["plan_id"], task["requested_by"], start_token=token, start_guard=_guard)
            task["trip_id"] = trip["trip_id"]
        except Exception as exc:  # a refusal of the trip path (TripError, coded HTTPException) is data
            if task["status"] == "SENDING":
                if task.get("cancel_requested"):
                    _end(task, "CANCELLED", "OPERATOR_CANCEL", now, state=state)
                else:
                    _end(task, "FAILED", _code(exc), now, state=state)
            save()
            continue
        finally:
            sending.discard(tid)
        if task.get("cancel_requested") or task["status"] != "SENDING":  # cancelled while starting: stop the trip it just opened
            if task["status"] not in TERMINAL:
                receipt = await _cancel_trip(runner, trip["trip_id"], task.get("cancelled_by"))
                task["cancel_receipt"] = receipt
                if task["status"] in TERMINAL:
                    pass
                elif _unconfirmed(receipt):  # the stop did not land: the trip is live, so the row stays in flight and re-asks
                    task.update(status="SENT", reason=None, ended_at=None, sent_at=round(now, 3), cancel_requested=True,
                                receipt={"trip_state": trip.get("state")})
                elif receipt.get("error") == "TRIP_NOT_RUNNING":
                    settle(task, runner, now, state=state)
                else:
                    _end(task, "CANCELLED", "OPERATOR_CANCEL", now, state=state)
            save()
            continue
        task.update(status="SENT", trip_id=trip["trip_id"], sent_at=round(now, 3),
                    receipt={"trip_state": trip.get("state"), "lease": (trip.get("lease") or {}).get("lease_id")})
        save()
        sent.append(task)
    return sent


def _code(exc) -> str:
    detail = getattr(exc, "detail", None)
    return (getattr(exc, "code", None) or (detail.get("code") if isinstance(detail, dict) else None)
            or type(exc).__name__)


async def _cancel_trip(runner, trip_id, principal_id) -> dict:
    if runner is None:
        return {"error": "TRIP_PATH_UNAVAILABLE"}
    try:
        return await runner.cancel(trip_id, principal_id, "pinky_task_cancel")
    except Exception as exc:  # TRIP_NOT_RUNNING: it already ended; its state settles the row
        return {"error": _code(exc)}


async def _cancel_native_goal(console, robot_id: str | None) -> dict:
    """Withdraw queued native goal and cancel any live CORE Nav2 goal, requiring positive ack."""
    if console is None or not robot_id or not callable(getattr(console, "cancel", None)):
        return {"error": "CONSOLE_CANCEL_UNAVAILABLE"}
    discard_err = None
    discard = getattr(console, "discard_queued_goal", None)
    if callable(discard):
        try:
            discard(robot_id)
        except Exception as exc:
            discard_err = _code(exc)
    try:
        res = await console.cancel(robot_id)
    except Exception as exc:
        return {"error": _code(exc)}
    from fleet.server.console.goal_admission import cancel_confirmed as _native_cancel_confirmed

    confirmed = (
        isinstance(res, dict)
        and "error" not in res
        and res.get("ok") is not False
        and res.get("cancel_confirmed") is not False
        and res.get("stop_sent") is not False
        and (_native_cancel_confirmed(res) or res.get("cancel_confirmed") is True or res.get("stop_sent") is True)
    )
    if not confirmed:
        base = dict(res) if isinstance(res, dict) else {}
        return {**base, "error": (base.get("error") if isinstance(base.get("error"), str) and base.get("error") else "NATIVE_CANCEL_UNCONFIRMED")}
    if discard_err is not None:
        return {**res, "error": discard_err}
    return res


def _unconfirmed(receipt) -> bool:
    """A cancel the trip path did not confirm (including stop_sent=False or error under receipt detail)."""
    if not receipt:
        return False
    if "error" in receipt and receipt["error"] != "TRIP_NOT_RUNNING":
        return True
    detail = receipt.get("detail")
    return isinstance(detail, dict) and (detail.get("stop_sent") is False or ("error" in detail and detail["error"] != "TRIP_NOT_RUNNING"))


async def cancel_task(state, task: dict, *, runner, principal_id, now: float, console=None) -> dict:
    """Cancel never refuses a stop: a queued row ends; an in-flight one ends only when its trip confirms the cancel.
    A failed or lost cancel leaves the row in flight (cancel_requested) and every tick re-asks and re-reads the trip."""
    task.update(cancelled_by=principal_id, cancel_requested=True)
    if task["status"] in IN_FLIGHT:
        trip_id = task.get("trip_id") or task.get("plan_id")
        view = runner.view(trip_id) if (runner is not None and trip_id) else None
        if (task["status"] == "SENT" and trip_id) or (view is not None and view.get("state") in TRIP_OPEN):
            if view is not None and view.get("state") in ("canceled", "stopped"):
                receipt = task["cancel_receipt"] = await _retry_halt_trip(runner, trip_id)
            else:
                receipt = task["cancel_receipt"] = await _cancel_trip(runner, trip_id, principal_id)
            if trip_id and not task.get("trip_id"):
                task["trip_id"] = trip_id
            cur_view = runner.view(trip_id) if runner is not None else None
            if _unconfirmed(receipt) or _unconfirmed(cur_view):
                return task
            if receipt.get("error") == "TRIP_NOT_RUNNING":  # it ended by itself first: its own state is the truth
                settle(task, runner, now, state=state)
                return task
        elif task["status"] == "SENT":
            receipt = await _cancel_native_goal(console, task.get("robot_id"))
            if _depart_submit_active(state, task):
                task["cancel_receipt"] = receipt if _unconfirmed(receipt) else {"error": "DEPART_SUBMIT_IN_FLIGHT"}
                return task
            task["cancel_receipt"] = receipt
            if _unconfirmed(receipt):
                return task
        elif task["status"] == "SENDING":
            if view is not None:  # it already ended in runner (e.g. arrived) while sending
                task["trip_id"] = trip_id
                settle(task, runner, now, state=state)
                return task
            if task.get("task_id") in (getattr(state, "_pinky_dispatch_sending", None) or ()):
                return task  # plan/start is actively running: let start_guard/dispatch_tick abort and confirm
    _end(task, "CANCELLED", "OPERATOR_CANCEL", now, state=state)
    return task


def install_pinky_dispatch(app, ctx) -> None:
    """The cancel route and ``app.state.task_dispatch_tick`` (run by the pipeline's 1 s loop in pipeline_unload_release)."""
    import time

    def active_or_none():
        try:
            return ctx.active_map()
        except HTTPException:
            return None

    def trip_request(place_id):
        from fleet.server.trip_routes import TripRequest  # late: the routes module pulls in the whole trip stack

        return TripRequest(to=place_id)

    app.state.task_dispatch_tick = lambda: dispatch_tick(
        app.state, console=ctx.console, runner=getattr(app.state, "trip_runner", None),
        plan=getattr(app.state, "trip_plan", None), task_service=getattr(app.state, "task_service", None),
        active=active_or_none(), human_detected=ctx._is_human_detected, save=ctx._save_ledger,
        now=time.time(), trip_request=trip_request)

    @app.post("/api/fleet/pipeline/pinky-tasks/{task_id}/cancel", dependencies=ctx.operator_guard)
    async def cancel_pinky_task(task_id: str, request: Request):
        task = app.state.pinky_tasks.get(task_id)
        if task is None:
            raise HTTPException(404, detail={"code": "UNKNOWN_TASK"})
        if task.get("status") in TERMINAL:
            raise HTTPException(409, detail={"code": "PINKY_TASK_ENDED", "status": task["status"]})
        principal = getattr(request.state, "site_principal", None)
        await cancel_task(app.state, task, runner=getattr(app.state, "trip_runner", None),
                          principal_id=getattr(principal, "principal_id", None), now=time.time(),
                          console=ctx.console)
        ctx._save_ledger()
        return {"ok": True, "confirmed": task["status"] in TERMINAL, "pinky_task": task}
