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
# Stationary odom-bridged poses match MapPoseTracker STILL_PATH_M (0.02 m) / STILL_TURN_RAD (2 deg) and max_anchor_age_s (10 s).
POSE_ANCHOR_SOURCES = frozenset({"sighting", "operator_pin", "track", "peer"})
STILL_BRIDGE_TURN_DEG = 2.0
PIN_ZONE_MAX_AGE_S = 10.0
# Stillness thresholds on CORE odom twist. The linear one equals the guard's 1e-4 m/s; the angular one is a D-1057 choice.
STILL_LINEAR_MPS = 1e-4
STILL_ANGULAR_RADPS = 1e-3
STILL_MIN_S = 1.0
STILL_MAX_GAP_S = 2.5
BED_CONFIRM_TTL_S = 120.0
# D-1057 2-9: cell S top-camera bed judgement. Its record waits at most 10 s for the claim (the worker claims right after it).
BED_CAMERA_TTL_S = 10.0
BED_CAMERA_VERDICT_S = 10.0  # a measured NOT_READY blocks the operator fallback this long
BED_CAMERA_SOURCE = "cell_top_camera"
OBS_MIN_FRAMES = 3
OBS_MIN_SPAN_S = STILL_MIN_S
OBS_FRAME_MAX_AGE_S = 2.0
OBS_FUTURE_S = 0.5
OBS_CLOCK_MARGIN_S = 0.5  # cell host vs Fleet clock
PRESENCE_TTL_S = 120.0   # a named operator's "I am at the power switch" for one task's supervised first run (D-911)
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


def _zone_pose_stamp(pose, now: float) -> float | None:
    """Live observation epoch of a trusted LOCALIZED map pose, or None (stationary odom-bridged allowed)."""
    if (pose is None or pose.state != "LOCALIZED"
            or not _finite(pose.x, pose.y, pose.yaw, pose.age_s) or not 0 <= pose.age_s <= POSE_MAX_AGE_S):
        return None
    if pose.source != "bridged":
        return now - pose.age_s if pose.source in POSE_ANCHOR_SOURCES else None
    src, a_age, dr, turn = (getattr(pose, k, None) for k in ("anchor_source", "anchor_age_s", "dead_reckon_m", "bridge_turn_deg"))
    max_anchor = PIN_ZONE_MAX_AGE_S if src == "operator_pin" else POSE_MAX_AGE_S
    if (src not in POSE_ANCHOR_SOURCES or not _finite(a_age, dr, turn)
            or not 0 <= a_age <= max_anchor or not 0 <= dr <= BED_MOVE_LIMIT_M or not 0 <= turn <= STILL_BRIDGE_TURN_DEG):
        return None
    return now - (pose.age_s if src == "operator_pin" else max(pose.age_s, a_age))


def zone_pose(app, task: dict):
    """(pose dict, observation epoch) from arbitrated map pose (direct or stationary bridged within 2 cm/2 deg), or None."""
    svc = getattr(app.state, "map_pose", None)
    maps = getattr(app.state, "site_maps", None)
    active = maps.active() if maps is not None else None
    if svc is None or active is None:
        return None
    pose = svc.arbitrated_pose(task["robot_id"])
    pose_at = _zone_pose_stamp(pose, time.time())
    if pose_at is None:
        return None
    active_id = svc.active_map_id()
    if active_id is None or pose.map_id != active_id:
        return None
    station = resolve_omx_cells(active[1], active[2]).get(task["cell_id"])
    # resolve_omx_cells falls back to built-in coordinates; only a stop place that the active map or graph really has counts.
    if (station is None or not any(_has_place(src, station.station_place) for src in (active[2], active[1]))
            or math.hypot(pose.x - station.station_xy[0], pose.y - station.station_xy[1]) > STOP_ZONE_RADIUS_M):
        return None
    return {"x": float(pose.x), "y": float(pose.y), "yaw": float(pose.yaw)}, pose_at


def _bed_valid(rec: dict, now: float | None = None) -> bool:
    """Not voided, and either bound to a claimed task's lease (the 120 s only bounds the wait for the claim) or inside the TTL."""
    now = time.time() if now is None else now
    return not rec.get("invalid") and (bool(rec.get("lease")) or 0 <= now - rec["confirmed_at"] <= rec.get("ttl_s", BED_CONFIRM_TTL_S))


def bind_bed(app, task: dict, lease_id, now: float | None = None) -> bool:
    """At the claim, BEFORE the ledger changes: consume the task's bed confirmation into the lease (who, when, pose and map
    version at that moment). One `now` decides validity. False when a confirmation exists but is no longer valid at `now`
    (nothing is changed then and the claim is refused); no confirmation at all is nothing to bind."""
    rec = (getattr(app.state, "cell_bed_confirmations", None) or {}).get(task["task_id"])
    if rec is None:
        return True
    if not _bed_valid(rec, time.time() if now is None else now):
        return False
    rec["lease"] = lease_id
    camera = rec.get("source") == BED_CAMERA_SOURCE
    task["bed_confirmation"] = {"operator": None if camera else rec["principal_id"], "confirmed_at": rec["confirmed_at"],
                                "pose": dict(rec["pose"]), "map_id": rec["map_id"], "map_version": rec["map_version"],
                                **({"source": BED_CAMERA_SOURCE, "principal": rec["principal_id"], "camera": copy.deepcopy(rec["camera"])}
                                   if camera else {})}
    return True


def bed_confirmation_lost(app, task: dict) -> bool:
    """True for a claimed task that had a bed confirmation which is no longer valid under its lease (needs a named operator)."""
    rec = (getattr(app.state, "cell_bed_confirmations", None) or {}).get(task["task_id"])
    return task.get("bed_confirmation") is not None and (
        rec is None or not _bed_valid(rec) or rec.get("lease") != task.get("handoff_lease_id"))


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
    svc = getattr(app.state, "map_pose", None)
    if svc is not None and hasattr(svc, "add_update_listener") and getattr(app.state, "bed_pose_listener", None) is not svc:
        svc.add_update_listener(lambda robot_id: check_beds(app, robot_id))  # every pose feed, incl. direct state reads
        app.state.bed_pose_listener = svc
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
    if task.get("status") == "RUNNING" and rec.get("lease") != task.get("handoff_lease_id"):
        return False  # a RUNNING task releases only on a confirmation bound to its own lease
    check_beds(app, task["robot_id"])  # also at the time of asking, for a deployment whose sink could not be chained
    return not rec.get("invalid") and math.hypot(pose["x"] - rec["pose"]["x"], pose["y"] - rec["pose"]["y"]) <= BED_MOVE_LIMIT_M


def _presence_valid(rec: dict, now: float | None = None) -> bool:
    t = time.time() if now is None else now
    return 0 <= t - rec["confirmed_at"] <= PRESENCE_TTL_S


def _valid_presence_operator(rec: dict | None, now: float | None = None) -> str | None:
    if rec is None or not _presence_valid(rec, now=now):
        return None
    op = rec.get("principal_id")
    if not isinstance(op, str) or not op.strip() or op == "site-console" or op.startswith("development-"):
        return None
    return op.strip()


def has_valid_presence(app, task: dict, now: float | None = None) -> bool:
    """True when the task holds a non-expired named-operator presence confirmation (non-consuming)."""
    rec = (getattr(app.state, "cell_presence", None) or {}).get(task["task_id"])
    return _valid_presence_operator(rec, now=now) is not None


def take_presence(app, task: dict, now: float | None = None) -> dict | None:
    """The valid presence confirmation of this task as {"operator", "at"}, used up by the claim that reads it; else None."""
    rec = (getattr(app.state, "cell_presence", None) or {}).pop(task["task_id"], None)
    op = _valid_presence_operator(rec, now=now)
    return None if op is None else {"operator": op, "at": rec["confirmed_at"]}


def prune_evidence(app) -> None:
    """Drop stored confirmations and owner evidence of finished tasks and of expired records."""
    tasks = getattr(app.state, "omx_cell_tasks", None) or {}
    now = time.time()
    for store, dead in ((getattr(app.state, "cell_bed_confirmations", None) or {},
                         lambda r: not _bed_valid(r)),
                        (getattr(app.state, "cell_presence", None) or {}, lambda r: not _presence_valid(r)),
                        (getattr(app.state, "cell_bed_camera", None) or {}, lambda r: now - r["at"] > BED_CAMERA_VERDICT_S),
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


def bed_camera_enabled() -> bool:
    """Kill switch of the cell S camera bed judgement, read at each call: ROSY_FLEET_CELL_S_BED_CAMERA=off (default on)."""
    return os.environ.get("ROSY_FLEET_CELL_S_BED_CAMERA", "").strip().lower() not in ("0", "off", "false", "no")


def _camera_not_ready(app, task: dict) -> bool:
    """A cell S task whose top camera measured NOT_READY within BED_CAMERA_VERDICT_S: no person may overrule it."""
    last = (getattr(app.state, "cell_bed_camera", None) or {}).get(task["task_id"])
    return (task["cell_id"] == "cell_s" and bed_camera_enabled() and last is not None
            and last["verdict"] == "NOT_READY" and 0 <= time.time() - last["at"] <= BED_CAMERA_VERDICT_S)


def _observation_frames(body: dict, now: float) -> list | None:
    """The frame summaries of a bed observation, or None when they do not prove 3 advancing, fresh frames over 1 s."""
    frames = body.get("frames")
    if not isinstance(frames, list) or len(frames) < OBS_MIN_FRAMES:
        return None
    out = []
    for f in frames:
        if (not isinstance(f, dict) or type(f.get("source_seq")) is not int or not _finite(f.get("source_stamp"))
                or not isinstance(f.get("jpeg_sha256"), str)):
            return None
        out.append({k: f[k] for k in ("source_seq", "source_stamp", "jpeg_sha256")})
    if any(b["source_seq"] <= a["source_seq"] or b["source_stamp"] <= a["source_stamp"] for a, b in zip(out, out[1:])):
        return None
    age = now - out[-1]["source_stamp"]
    if out[-1]["source_stamp"] - out[0]["source_stamp"] < OBS_MIN_SPAN_S or not -OBS_FUTURE_S <= age <= OBS_FRAME_MAX_AGE_S:
        return None
    return out


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
    app.state.cell_presence = getattr(app.state, "cell_presence", None) or {}
    app.state.cell_bed_camera = getattr(app.state, "cell_bed_camera", None) or {}

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
        old = app.state.cell_bed_confirmations.get(task_id)
        lost = task.get("status") == "RUNNING" and bed_confirmation_lost(app, task)
        if task.get("status") != "QUEUED" and not lost:  # a RUNNING task may be confirmed again only after its confirmation lapsed
            raise _error(409, "CELL_TASK_NOT_QUEUED")
        if old is not None and _bed_valid(old):  # a repeated request never renews the expiry or the pose
            return {"ok": True, "renewed": False, "confirmation": old}
        if _camera_not_ready(app, task):  # D-1057 2-9: the person is the fallback for UNKNOWN only
            raise _error(409, "BED_CAMERA_NOT_READY")
        located = zone_pose(app, task)
        if located is None:
            raise _error(409, "BED_CONFIRM_POSE_UNAVAILABLE")
        if lost:  # the robot must stand still at the station right now, as the release will ask again
            ev = amr_evidence(app, task)
            if (ev is None or not ev["wheel_brake_locked"] or abs(ev["v_cmd_mps"]) > 1e-4 or time.time() - ev["observed_at"] > 2.0):
                raise _error(409, "BED_CONFIRM_ROBOT_NOT_STOPPED")
        rec = {"task_id": task_id, "robot_id": task["robot_id"], "principal_id": principal_id,
               "confirmed_at": time.time(), "pose": located[0], "map_id": _map_state(app)[0], "map_version": _map_state(app)[1]}
        watch_pose_updates(app)
        app.state.cell_bed_confirmations[task_id] = rec
        if lost:  # same lease, confirmed again under it
            rec["lease"] = task.get("handoff_lease_id")
            task["bed_confirmation"] = {"operator": principal_id, "confirmed_at": rec["confirmed_at"], "pose": dict(rec["pose"]),
                                        "map_id": rec["map_id"], "map_version": rec["map_version"], "renewed": True}
        return {"ok": True, "renewed": True, "confirmation": rec, "expires_in_s": BED_CONFIRM_TTL_S}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/bed-observation", dependencies=proposer_guard)
    async def record_bed_observation(task_id: str, request: Request):
        """D-1057 2-9: cell S's top-camera bed judgement. Only READY, re-bound to Fleet's own pose and stillness, makes the
        same record a named operator's bed-confirm makes (source cell_top_camera, 10 s to the claim); UNKNOWN never does."""
        task = task_of(task_id)
        if task["cell_id"] != "cell_s":
            raise _error(409, "BED_CAMERA_CELL_NOT_SUPPORTED")
        if not bed_camera_enabled():
            raise _error(409, "BED_CAMERA_DISABLED")
        refusal = owner_principal_refusal(request, task)
        if refusal is not None:
            raise refusal
        if task.get("status") != "QUEUED":  # a RUNNING task is confirmed again by a named operator only
            raise _error(409, "CELL_TASK_NOT_QUEUED")
        body = await read_body(request)
        if not isinstance(body, dict) or body.get("robot_id") != task["robot_id"]:
            raise _error(422, "BED_CONFIRM_ROBOT_MISMATCH")
        now = time.time()
        try:
            json.dumps(body, allow_nan=False)
        except (TypeError, ValueError):
            raise _error(422, "BED_OBSERVATION_INVALID") from None
        frames, verdict, reasons = _observation_frames(body, now), body.get("verdict"), body.get("reasons", [])
        if (frames is None or verdict not in ("READY", "NOT_READY", "UNKNOWN")
                or not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons)):
            raise _error(422, "BED_OBSERVATION_INVALID")
        app.state.cell_bed_camera[task_id] = {"verdict": verdict, "reasons": list(reasons), "at": now}
        if verdict != "READY":
            return {"ok": True, "recorded": False, "verdict": verdict}
        located = zone_pose(app, task)
        if located is None:
            raise _error(409, "BED_CONFIRM_POSE_UNAVAILABLE")
        amr = amr_evidence(app, task)
        still_s = _tracker(app).still_for_s(task["robot_id"])
        if (amr is None or not amr["wheel_brake_locked"] or abs(amr["v_cmd_mps"]) > STILL_LINEAR_MPS or still_s is None
                or now - still_s > frames[0]["source_stamp"] - OBS_CLOCK_MARGIN_S):  # Fleet's still run covers the camera window
            raise _error(409, "BED_OBSERVATION_ROBOT_NOT_STILL")
        old = app.state.cell_bed_confirmations.get(task_id)
        if old is not None and _bed_valid(old):  # never renews or replaces a valid confirmation (operator or camera)
            return {"ok": True, "recorded": False, "verdict": verdict}
        principal_id = getattr(getattr(request.state, "site_principal", None), "principal_id", None)
        rec = {"task_id": task_id, "robot_id": task["robot_id"], "principal_id": principal_id, "source": BED_CAMERA_SOURCE,
               "ttl_s": BED_CAMERA_TTL_S, "confirmed_at": time.time(), "pose": located[0],
               "map_id": _map_state(app)[0], "map_version": _map_state(app)[1],
               "camera": copy.deepcopy({"frames": frames, "bed": body.get("bed"), "objects": body.get("objects"),
                                        "config_sha256": body.get("config_sha256")})}
        watch_pose_updates(app)
        app.state.cell_bed_confirmations[task_id] = rec
        return {"ok": True, "recorded": True, "verdict": verdict, "expires_in_s": BED_CAMERA_TTL_S}

    @app.post("/api/fleet/pipeline/cell-tasks/{task_id}/presence-confirm", dependencies=operator_guard)
    async def confirm_presence(task_id: str, request: Request):
        """A named operator states that a person is at the power switch for this task's supervised (commissioning) run."""
        task = task_of(task_id)
        await read_body(request)
        principal_id = getattr(getattr(request.state, "site_principal", None), "principal_id", None)
        if not principal_id or principal_id == "site-console" or principal_id.startswith("development-"):
            raise _error(403, "NAMED_OPERATOR_REQUIRED")
        if task.get("status") != "QUEUED":
            raise _error(409, "CELL_TASK_NOT_QUEUED")
        old = app.state.cell_presence.get(task_id)
        if old is not None and _presence_valid(old):  # a repeated request never renews the expiry
            return {"ok": True, "renewed": False, "presence": {"operator": old["principal_id"], "at": old["confirmed_at"]}}
        rec = {"task_id": task_id, "principal_id": principal_id, "confirmed_at": time.time()}
        app.state.cell_presence[task_id] = rec
        return {"ok": True, "renewed": True, "presence": {"operator": principal_id, "at": rec["confirmed_at"]},
                "expires_in_s": PRESENCE_TTL_S}

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
