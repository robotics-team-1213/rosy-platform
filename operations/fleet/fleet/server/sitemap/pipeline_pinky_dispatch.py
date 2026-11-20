"""Pinky task dispatch (D-1059, panel 5 slice 3): a QUEUED pinky task drives once, as an ordinary Fleet trip.

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


def dispatch_fields(active, request, place_id) -> dict:
    """What a pinky-task row carries for this dispatcher: its place, the map it was asked on and who asked."""
    principal = getattr(request.state, "site_principal", None)
    return {"place_id": place_id, "map_version": active[0], "requested_by": getattr(principal, "principal_id", None)}


def enabled() -> bool:
    return os.environ.get(FLAG) == "1"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="milliseconds")


def last_cancel_all_at(task_service) -> str | None:
    """The newest D-421 cancel-all window opening (ISO, UTC) in the Fleet journal, or None."""
    with closing(task_service.store._connect()) as connection:
        row = connection.execute("SELECT MAX(opened_at) FROM fleet_cancel_all").fetchone()
    return row[0] if row is not None else None


def refusal(state, task: dict, *, now: float, active, robot_row, human_detected: bool, dispatch_open: bool,
            cancel_all_at: str | None, trip_busy: bool) -> str | None:
    """Why this QUEUED task may not drive now, or None. Pure: every input is read by the caller."""
    robot_id, place = task.get("robot_id"), task.get("place_id")
    if not place:
        return "ACTION_NOT_DISPATCHABLE"  # micro steps, stop_now, depart_s3: not a place goal
    if not task.get("requested_by"):
        return "REQUESTER_UNKNOWN"
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
    cell_id = CELL_AT_PLACE.get(place)
    if cell_id is not None:
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
    if trip_busy or any(t is not task and _ours(t) and t.get("robot_id") == robot_id and t.get("status") in IN_FLIGHT
                        for t in state.pinky_tasks.values()):
        return "ROBOT_DISPATCH_IN_FLIGHT"
    return None


def _ours(task: dict) -> bool:
    """A row this dispatcher sent (depart_tick's SENT rows carry no plan id and are not ours)."""
    return "plan_id" in task


def _end(task: dict, status: str, reason, now: float) -> None:
    task.update(status=status, reason=reason, ended_at=round(now, 3))


def settle(task: dict, runner, now: float) -> bool:
    """SENT/SENDING from the trip's own state; True when the row changed."""
    trip_id = task.get("trip_id") or task.get("plan_id")
    view = runner.view(trip_id) if (runner is not None and trip_id) else None
    if task["status"] == "SENDING":  # left over: never plan or start again
        if view is None:
            _end(task, "FAILED", "DISPATCH_INTERRUPTED", now)
            return True
        task.update(status="SENT", trip_id=trip_id, sent_at=round(now, 3), receipt={"trip_state": view.get("state")})
    if view is None:
        _end(task, "FAILED", "TRIP_UNKNOWN", now)
        return True
    state = view.get("state")
    if state in TRIP_OPEN:
        changed = (task.get("receipt") or {}).get("trip_state") != state
        task["receipt"] = {**(task.get("receipt") or {}), "trip_state": state}
        return changed
    if state == "arrived":
        _end(task, "ARRIVED", None, now)
    elif state == "canceled":
        _end(task, "CANCELLED", view.get("reason") or "TRIP_CANCELED", now)
    else:
        _end(task, "FAILED", view.get("reason") or state, now)
    return True


async def dispatch_tick(state, *, console, runner, plan, task_service, active, human_detected: bool, save,
                        now: float, trip_request) -> list[dict]:
    """One pass: settle in-flight rows, then dispatch each QUEUED place task at most once."""
    if not enabled():
        return []
    for task in list(state.pinky_tasks.values()):
        if _ours(task) and task.get("status") in IN_FLIGHT and settle(task, runner, now):
            save()
    queued = sorted((t for t in state.pinky_tasks.values() if t.get("status") == "QUEUED"),
                    key=lambda t: t.get("created_at") or 0)
    if not queued:
        return []
    sent = []
    if runner is None or plan is None or task_service is None or not getattr(runner.lease, "required", False):
        why = "TRIP_PATH_UNAVAILABLE" if task_service is not None else "FLEET_JOURNAL_UNAVAILABLE"
        for task in queued:
            _end(task, "REFUSED", why if task.get("place_id") else "ACTION_NOT_DISPATCHABLE", now)
        save()
        return sent
    rows = {row["robot_id"]: row for row in (await console.snapshot())["robots"]}
    dispatch_open = bool(task_service.store.dispatch_control().get("dispatch_enabled"))
    cancel_all_at = last_cancel_all_at(task_service)
    for task in queued:
        robot_id = task.get("robot_id")
        why = refusal(state, task, now=now, active=active, robot_row=rows.get(robot_id),
                      human_detected=human_detected, dispatch_open=dispatch_open, cancel_all_at=cancel_all_at,
                      trip_busy=bool(runner.robot_busy(robot_id)))
        if why is not None:
            _end(task, "REFUSED", why, now)
            save()
            continue
        task.update(status="SENDING", sending_at=round(now, 3), plan_id=None, trip_id=None)
        save()  # the claim is on disk before anything is planned or started
        try:
            planned = await plan(robot_id, trip_request(task["place_id"]), task["requested_by"])
            task["plan_id"] = planned["plan_id"]
            save()  # a restart finds the plan id and never starts a second trip
            if task["status"] != "SENDING":
                continue  # cancelled while planning: the plan is never started
            trip = await runner.start(planned["plan_id"], task["requested_by"])
        except Exception as exc:  # a refusal of the trip path (TripError, coded HTTPException) is data
            if task["status"] == "SENDING":
                _end(task, "FAILED", _code(exc), now)
            save()
            continue
        if task["status"] != "SENDING":  # cancelled while starting: stop the trip it just opened
            await _cancel_trip(runner, trip["trip_id"], task.get("cancelled_by"))
            task.update(trip_id=trip["trip_id"])
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
    try:
        return await runner.cancel(trip_id, principal_id, "pinky_task_cancel")
    except Exception as exc:  # TRIP_NOT_RUNNING: it already ended; its state settles the row
        return {"error": _code(exc)}


async def cancel_task(state, task: dict, *, runner, principal_id, now: float) -> dict:
    """Cancel never refuses a stop: a queued row ends, an in-flight one cancels its trip through the trip path."""
    receipt = None
    if task["status"] in IN_FLIGHT and task.get("trip_id"):
        receipt = await _cancel_trip(runner, task["trip_id"], principal_id)
    task.update(cancelled_by=principal_id, cancel_receipt=receipt)
    _end(task, "CANCELLED", "OPERATOR_CANCEL", now)
    return task


def install_pinky_dispatch(app, ctx) -> None:
    """The cancel route and ``app.state.pinky_dispatch_tick`` (run by the pipeline's 1 s loop in pipeline_unload_release)."""
    import time

    def active_or_none():
        try:
            return ctx.active_map()
        except HTTPException:
            return None

    def trip_request(place_id):
        from fleet.server.trip_routes import TripRequest  # late: the routes module pulls in the whole trip stack

        return TripRequest(to=place_id)

    app.state.pinky_dispatch_tick = lambda: dispatch_tick(
        app.state, console=ctx.console, runner=getattr(app.state, "trip_runner", None),
        plan=getattr(app.state, "trip_plan", None), task_service=getattr(app.state, "task_service", None),
        active=active_or_none(), human_detected=bool(ctx._is_human_detected()), save=ctx._save_ledger,
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
                          principal_id=getattr(principal, "principal_id", None), now=time.time())
        ctx._save_ledger()
        return {"ok": True, "pinky_task": task}
