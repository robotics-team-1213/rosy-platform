"""D-1057: measured evidence providers and owner/bed evidence routes for cell task admission.

The guards in pipeline_routes._ready_amr and pipeline_camera_routes.complete_cell_task are not changed here.
Every provider returns None when a measurement is missing, stale or not trustworthy, so those guards refuse.
"""
from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
from datetime import datetime

from fastapi import HTTPException, Request

from fleet.pipeline import resolve_omx_cells

# Same value as fleet.server.console.charge_bay_routes.CELL_CLAIM_RADIUS_M (not imported: import cycle); a test pins it.
STOP_ZONE_RADIUS_M = 0.18
HEARTBEAT_MAX_AGE_S = 2.0
POSE_MAX_AGE_S = 2.0
# Stillness thresholds on CORE odom twist. The linear one equals the guard's 1e-4 m/s; the angular one is a D-1057 choice.
STILL_LINEAR_MPS = 1e-4
STILL_ANGULAR_RADPS = 1e-3
STILL_MIN_S = 1.0
STILL_MAX_GAP_S = 2.5
BED_CONFIRM_TTL_S = 120.0
BED_MOVE_LIMIT_M = 0.02
OWNER_EVIDENCE_MAX_AGE_S = 60.0
_IDLE_NAV = frozenset({"IDLE", "ARRIVED", "CANCELED", "FAILED"})  # anything else is a drive task in progress
VELOCITY_MAX_AGE_S = 2.0
MAX_BODY_BYTES = 64 * 1024
OWNER_MEASURED_SKEW_S = 2.0
_TERMINAL = frozenset({"COMPLETED", "CANCELLED", "ABORTED"})


class StillTracker:
    """Per robot: since when every heartbeat sample has been still, without a gap over STILL_MAX_GAP_S."""

    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def feed(self, robot_id: str, mark: float, arrival: float, still: bool) -> None:
        with self._lock:
            row = self._rows.get(robot_id)
            if row is not None and row["mark"] == mark:
                return
            keep = bool(still and row and row["since"] is not None and arrival - row["last"] <= STILL_MAX_GAP_S)
            self._rows[robot_id] = {"mark": mark, "last": arrival,
                                    "since": row["since"] if keep else (arrival if still else None)}

    def still_for_s(self, robot_id: str) -> float | None:
        with self._lock:
            row = self._rows.get(robot_id)
            return None if row is None or row["since"] is None else row["last"] - row["since"]


def _finite(*values) -> bool:
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _heartbeat(app, robot_id: str):
    """(StateSnapshot, wall arrival time, heartbeat mark) of an online robot's heartbeat at most HEARTBEAT_MAX_AGE_S old."""
    hub = getattr(getattr(app.state, "console", None), "hub", None)
    row = hub.registry.find(robot_id) if hub is not None else None
    if row is None or not row.online or row.snapshot is None or row.last_heartbeat_monotonic is None:
        return None
    age = time.monotonic() - row.last_heartbeat_monotonic
    if not 0 <= age <= HEARTBEAT_MAX_AGE_S:
        return None
    return row.snapshot, time.time() - age, row.last_heartbeat_monotonic


def _velocity_stamp(snapshot) -> float | None:
    """CORE's receipt time of the odom velocity channel, only while CORE judges that channel fresh."""
    ev = (snapshot.evidence or {}).get("velocity")
    if ev is None or getattr(ev.evidence, "value", ev.evidence) != "fresh" or not ev.received_at:
        return None
    try:
        return datetime.fromisoformat(ev.received_at).timestamp()
    except ValueError:
        return None


def _held_still(app, robot_id: str, snapshot, arrival: float) -> bool:
    """One sample of held-still: CORE mode IDLE, no drive task, no E-stop, odom 0, velocity channel fresh in this sample.

    No commanded velocity reaches Fleet (D-1057), so a command already sent but not yet moving is excluded by the
    mode and the absence of a navigation state or Fleet goal, not by measuring the command.
    """
    v, stamp = snapshot.velocity, _velocity_stamp(snapshot)
    goals = getattr(getattr(app.state, "console", None), "_goals", None) or {}
    return (stamp is not None and abs(arrival - stamp) <= VELOCITY_MAX_AGE_S
            and _finite(v.linear, v.angular) and abs(v.linear) <= STILL_LINEAR_MPS and abs(v.angular) <= STILL_ANGULAR_RADPS
            and snapshot.mode.value == "IDLE" and snapshot.navigation.value in _IDLE_NAV
            and robot_id not in goals and not snapshot.safety.estop)


def _tracker(app) -> StillTracker:
    if getattr(app.state, "amr_still_tracker", None) is None:
        app.state.amr_still_tracker = StillTracker()
    return app.state.amr_still_tracker


def feed_still_tracker(app, robot_id: str) -> None:
    beat = _heartbeat(app, robot_id)
    if beat is not None:
        _tracker(app).feed(robot_id, beat[2], beat[1], _held_still(app, robot_id, beat[0], beat[1]))


def _ensure_feeder(app) -> None:
    """Sample every online robot's heartbeat twice a second so stillness is judged over time, not at one request."""
    if getattr(app.state, "amr_still_feeder", None) is not None or not getattr(app.state, "amr_still_autostart", True):
        return
    hub = getattr(getattr(app.state, "console", None), "hub", None)
    if hub is None:
        return

    def run() -> None:
        while True:
            try:
                for robot_id in hub.registry.online_ids():
                    feed_still_tracker(app, robot_id)
                check_beds(app)
            except Exception:  # a sampling fault only leaves the run unproven, which the guard refuses
                pass
            time.sleep(0.5)

    app.state.amr_still_feeder = threading.Thread(target=run, daemon=True, name="amr-still-feeder")
    app.state.amr_still_feeder.start()


def _has_place(source, place_id: str) -> bool:
    places = getattr(source, "places", None)
    if isinstance(places, dict):
        return place_id in places
    return any(getattr(p, "id", None) == place_id or (isinstance(p, dict) and p.get("id") == place_id) for p in places or ())


def zone_pose(app, task: dict):
    """(pose dict, observation epoch) from the arbitrated map pose, or None.

    Only a LOCALIZED pose set by a sighting, pin or peer anchor (not odom-bridged), at most POSE_MAX_AGE_S old, on the
    active map and inside the cell's stop zone (station place within STOP_ZONE_RADIUS_M) counts.
    """
    svc = getattr(app.state, "map_pose", None)
    maps = getattr(app.state, "site_maps", None)
    active = maps.active() if maps is not None else None
    if svc is None or active is None:
        return None
    pose = svc.arbitrated_pose(task["robot_id"])
    if (pose is None or pose.state != "LOCALIZED" or pose.source in (None, "bridged")
            or not _finite(pose.x, pose.y, pose.yaw, pose.age_s) or not 0 <= pose.age_s <= POSE_MAX_AGE_S):
        return None
    active_id = svc.active_map_id()
    if active_id is None or pose.map_id != active_id:
        return None
    station = resolve_omx_cells(active[1], active[2]).get(task["cell_id"])
    # resolve_omx_cells falls back to built-in coordinates; only a stop place that the active map or graph really has counts.
    if (station is None or not any(_has_place(src, station.station_place) for src in (active[2], active[1]))
            or math.hypot(pose.x - station.station_xy[0], pose.y - station.station_xy[1]) > STOP_ZONE_RADIUS_M):
        return None
    return {"x": float(pose.x), "y": float(pose.y), "yaw": float(pose.yaw)}, time.time() - pose.age_s


def _bed_valid(rec: dict) -> bool:
    return not rec.get("invalid") and 0 <= time.time() - rec["confirmed_at"] <= BED_CONFIRM_TTL_S


def _map_state(app) -> tuple:
    """(active map id, active map version): a new version of the same map id is a change too."""
    svc, maps = getattr(app.state, "map_pose", None), getattr(app.state, "site_maps", None)
    active = maps.active() if maps is not None else None
    return (svc.active_map_id() if svc is not None else None, active[0] if active else None)


def check_beds(app, robot_id: str | None = None) -> None:
    """Void, for good, every bed confirmation whose robot moved over BED_MOVE_LIMIT_M since it was given, or whose map
    (id or version) changed. Runs on every state update the console receives (see watch_pose_updates), not only when
    the evidence is asked for, so a move out and back between two requests is seen."""
    svc = getattr(app.state, "map_pose", None)
    for rec in (getattr(app.state, "cell_bed_confirmations", None) or {}).values():
        if rec.get("invalid") or (robot_id is not None and rec["robot_id"] != robot_id) or svc is None:
            continue
        pose = svc.arbitrated_pose(rec["robot_id"])  # any state: an odom-bridged or degraded pose still shows motion
        moved = (pose is not None and _finite(pose.x, pose.y)
                 and math.hypot(pose.x - rec["pose"]["x"], pose.y - rec["pose"]["y"]) > BED_MOVE_LIMIT_M)
        if moved or _map_state(app) != (rec["map_id"], rec["map_version"]):
            rec["invalid"] = True


def watch_pose_updates(app) -> None:
    """Chain check_beds behind the console's state sink (the one that feeds MapPoseService), once."""
    console = getattr(app.state, "console", None)
    if getattr(app.state, "bed_pose_watch", False) or console is None or not hasattr(console, "set_state_sink"):
        return
    previous = getattr(console, "_state_sink", None)

    def sink(robot_id, state):
        try:
            if previous is not None:
                previous(robot_id, state)
        finally:
            check_beds(app, robot_id)

    console.set_state_sink(sink)
    app.state.bed_pose_watch = True


def _bed_ready(app, task: dict, pose: dict) -> bool:
    rec = (getattr(app.state, "cell_bed_confirmations", None) or {}).get(task["task_id"])
    if rec is None or rec["robot_id"] != task["robot_id"] or not _bed_valid(rec):
        return False
    check_beds(app, task["robot_id"])  # also at the time of asking, for a deployment whose sink could not be chained
    return not rec.get("invalid") and math.hypot(pose["x"] - rec["pose"]["x"], pose["y"] - rec["pose"]["y"]) <= BED_MOVE_LIMIT_M


def prune_evidence(app) -> None:
    """Drop stored confirmations and owner evidence of finished tasks and of expired records."""
    tasks = getattr(app.state, "omx_cell_tasks", None) or {}
    now = time.time()
    for store, dead in ((getattr(app.state, "cell_bed_confirmations", None) or {},
                         lambda r: not _bed_valid(r)),
                        (getattr(app.state, "cell_owner_evidence", None) or {},
                         lambda r: now - r["measured_at"] > OWNER_EVIDENCE_MAX_AGE_S)):
        for task_id in [k for k, r in store.items()
                        if (tasks.get(k) or {}).get("status") in _TERMINAL or k not in tasks or dead(r)]:
            store.pop(task_id, None)


def cell_owner_principals(cell_id: str) -> frozenset:
    """Service principals registered as owners of a cell: ROSY_FLEET_CELL_OWNERS=cell_s=id1,id2;cell_ab=id3 (empty: none)."""
    for entry in os.environ.get("ROSY_FLEET_CELL_OWNERS", "").split(";"):
        cell, _, ids = entry.partition("=")
        if cell.strip() == cell_id:
            return frozenset(i.strip() for i in ids.split(",") if i.strip())
    return frozenset()


def owner_principal_refusal(request, task: dict) -> HTTPException | None:
    principal = getattr(request.state, "site_principal", None)
    pid = getattr(principal, "principal_id", None)
    if getattr(principal, "role", None) != "service" or not pid or pid not in cell_owner_principals(task["cell_id"]):
        return _error(403, "OWNER_PRINCIPAL_NOT_REGISTERED")
    return None


def amr_evidence(app, task: dict) -> dict | None:
    """Measured AMR evidence for pipeline_routes._ready_amr, or None when any live measurement is missing or stale.

    wheel_brake_locked is CORE's held-still state (no drive task, no E-stop, odom speed at or under threshold for
    STILL_MIN_S of heartbeats), NOT a mechanical brake: no brake sensor exists (D-1057).
    v_cmd_mps carries the measured odom linear speed: CORE exposes no commanded velocity to Fleet (D-1057, open judgment).
    bed_ready is a named operator's per-task confirmation, valid BED_CONFIRM_TTL_S and while the pose stays put.
    observed_at is the oldest live observation used (heartbeat arrival, velocity receipt, map pose); the operator
    confirmation has its own expiry and is not a live observation.
    """
    robot_id = task["robot_id"]
    prune_evidence(app)
    beat = _heartbeat(app, robot_id)
    located = zone_pose(app, task)
    if beat is None or located is None:
        return None
    snapshot, arrival, _ = beat
    stamp = _velocity_stamp(snapshot)
    if stamp is None or not _finite(snapshot.velocity.linear):
        return None
    _ensure_feeder(app)
    feed_still_tracker(app, robot_id)
    still_s = _tracker(app).still_for_s(robot_id)
    pose, pose_at = located
    return {
        "robot_id": robot_id, "cell_id": task["cell_id"],
        "observed_at": min(arrival, stamp, pose_at),
        "wheel_brake_locked": bool(still_s is not None and still_s >= STILL_MIN_S and _held_still(app, robot_id, snapshot, arrival)),
        "v_cmd_mps": float(snapshot.velocity.linear),
        "pose": pose,
        "bed_ready": _bed_ready(app, task, pose),
    }


def omx_owner_evidence(app, task: dict) -> dict | None:
    """The stored owner evidence of this RUNNING task's current lease (never the /complete body), or None."""
    prune_evidence(app)
    rec = (getattr(app.state, "cell_owner_evidence", None) or {}).get(task["task_id"])
    claimed_at = task.get("claimed_at")
    if (rec is None or task.get("status") != "RUNNING" or not task.get("handoff_lease_id")
            or rec["lease"] != task["handoff_lease_id"] or not _finite(claimed_at)
            or not claimed_at <= rec["measured_at"] <= time.time() + 2.0
            or time.time() - rec["measured_at"] > OWNER_EVIDENCE_MAX_AGE_S):
        return None
    return copy.deepcopy({k: rec[k] for k in ("receipt", "stage_result", "hardware_telemetry")})


def _error(status: int, code: str) -> HTTPException:
    return HTTPException(status, detail={"code": code})


def install_evidence_routes(app, ctx) -> None:
    operator_guard, proposer_guard = ctx.operator_guard, ctx.proposer_guard
    app.state.cell_bed_confirmations = getattr(app.state, "cell_bed_confirmations", None) or {}
    app.state.cell_owner_evidence = getattr(app.state, "cell_owner_evidence", None) or {}

    async def read_body(request: Request):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise _error(413, "EVIDENCE_BODY_TOO_LARGE")
        try:
            return json.loads(raw)
        except ValueError:
            raise _error(422, "INVALID_OWNER_EVIDENCE") from None

    def task_of(task_id: str) -> dict:
        prune_evidence(app)
        task = app.state.omx_cell_tasks.get(task_id)
        if task is None:
            raise _error(404, "UNKNOWN_TASK")
        return task

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/bed-confirm", dependencies=operator_guard)
    async def confirm_bed(task_id: str, request: Request):
        task = task_of(task_id)
        body = await read_body(request)
        principal_id = getattr(getattr(request.state, "site_principal", None), "principal_id", None)
        # A shared console or development identity names nobody (same rule as the assistant routes).
        if not principal_id or principal_id == "site-console" or principal_id.startswith("development-"):
            raise _error(403, "NAMED_OPERATOR_REQUIRED")
        if not isinstance(body, dict) or body.get("robot_id") != task["robot_id"]:
            raise _error(422, "BED_CONFIRM_ROBOT_MISMATCH")
        if task.get("status") != "QUEUED":
            raise _error(409, "CELL_TASK_NOT_QUEUED")
        old = app.state.cell_bed_confirmations.get(task_id)
        if old is not None and _bed_valid(old):  # a repeated request never renews the expiry or the pose
            return {"ok": True, "renewed": False, "confirmation": old}
        located = zone_pose(app, task)
        if located is None:
            raise _error(409, "BED_CONFIRM_POSE_UNAVAILABLE")
        rec = {"task_id": task_id, "robot_id": task["robot_id"], "principal_id": principal_id,
               "confirmed_at": time.time(), "pose": located[0], "map_id": _map_state(app)[0], "map_version": _map_state(app)[1]}
        watch_pose_updates(app)
        app.state.cell_bed_confirmations[task_id] = rec
        return {"ok": True, "renewed": True, "confirmation": rec, "expires_in_s": BED_CONFIRM_TTL_S}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/owner-evidence", dependencies=proposer_guard)
    async def record_owner_evidence(task_id: str, request: Request):
        task = task_of(task_id)
        refusal = owner_principal_refusal(request, task)
        if refusal is not None:
            raise refusal
        body = await read_body(request)
        try:
            json.dumps(body, allow_nan=False)
        except (TypeError, ValueError):
            raise _error(422, "INVALID_OWNER_EVIDENCE") from None
        parts = {k: body.get(k) for k in ("receipt", "stage_result", "hardware_telemetry")} if isinstance(body, dict) else {}
        if not parts or not all(isinstance(v, dict) for v in parts.values()):
            raise _error(422, "INVALID_OWNER_EVIDENCE")
        if task.get("status") != "RUNNING":
            raise _error(409, "CELL_TASK_NOT_RUNNING")
        lease, measured_at = task.get("handoff_lease_id"), body.get("measured_at")
        if (not lease or body.get("handoff_lease_id") != lease or parts["receipt"].get("handoff_lease_id") != lease
                or parts["receipt"].get("stage_id") != task_id):
            raise _error(422, "OWNER_EVIDENCE_LEASE_MISMATCH")
        device_at = parts["hardware_telemetry"].get("measured_at")
        if (not _finite(measured_at, device_at) or not task["claimed_at"] <= measured_at <= time.time() + 2.0
                or time.time() - measured_at > OWNER_EVIDENCE_MAX_AGE_S
                or abs(measured_at - device_at) > OWNER_MEASURED_SKEW_S):
            raise _error(422, "OWNER_EVIDENCE_MEASURED_AT_INVALID")
        principal_id = getattr(getattr(request.state, "site_principal", None), "principal_id", None)
        rec = {"task_id": task_id, "lease": lease, "measured_at": measured_at, "recorded_at": round(time.time(), 3),
               "principal_id": principal_id, **copy.deepcopy(parts)}
        old = app.state.cell_owner_evidence.get(task_id)
        if old is not None and old["lease"] == lease:
            if old["principal_id"] != principal_id:
                raise _error(403, "OWNER_PRINCIPAL_NOT_REGISTERED")
            if all(old[k] == rec[k] for k in ("measured_at", *parts)):
                return {"ok": True, "recorded": False}
            raise _error(409, "OWNER_EVIDENCE_ALREADY_RECORDED")
        app.state.cell_owner_evidence[task_id] = rec
        return {"ok": True, "recorded": True}
