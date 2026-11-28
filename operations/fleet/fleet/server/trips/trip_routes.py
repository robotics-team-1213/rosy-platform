"""D-488 2 / D-490 5: ``POST /api/fleet/robots/{id}/trip`` plans and returns; it never drives.

The trip map pose (D-494 3 MapPose, else a robot-reported LOCALIZED map pose) and the active
site map go into the pure planner (``fleet.routing``). Every plan, refused or not, is a row
in the site map store (D-490 8).
D-494 5: ``POST /api/fleet/trips/{plan_id}/start`` runs a stored plan through the trip loop
(``trip_runner``); ``/cancel`` and ``/confirm-replan`` act on it and ``GET`` reads it. The
plan request's ``execute: true`` stays 501: starting is always its own named-operator call.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
import uuid
from typing import Annotated, Literal, Optional, Union

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fleet.hub.hub import HubError
from fleet.localization import trust
from fleet.routing.brief import route_context
from fleet.routing.execute import arc_id, plan_body
from fleet.routing.snap import PlanError
from fleet.routing.trip import ARRIVED_M, PlanRequest, plan_trip
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.server.named_stop_map_pose import commissioned_stop, read_precision_pose
from fleet.server.trip_admission import start_check
from fleet.server.trip_runner import LOCALIZED, PLAN_TTL_S, TripError
from fleet.stop_front import body_front_m
from fleet.swarm.transport import RobotApiError

PlaceRef = Annotated[str, Field(min_length=1, max_length=64)]
_LOG = logging.getLogger(__name__)


class TripPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    yaw: Optional[float] = Field(default=None, ge=-math.pi, le=math.pi, allow_inf_nan=False)


class TripConvoy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    leader: str = Field(min_length=1, max_length=96)


class TripPauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reason: Optional[str] = Field(default=None, max_length=120)


class TripResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    blocked_edges: list[PlaceRef] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def _unique_edges(self) -> "TripResumeRequest":
        if len(set(self.blocked_edges)) != len(self.blocked_edges):
            raise ValueError("blocked_edges contains a duplicate")
        return self


class SignalCommand(BaseModel):
    """D-525 4: an operator verb for one virtual signal."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    verb: str = Field(min_length=1, max_length=16)
    approach: Optional[str] = Field(default=None, min_length=1, max_length=128)  # set_aspect only


class SignalDemand(BaseModel):
    """D-525 rev 4: the AI PC controller asks for a green; ``approach`` None says it is alive, nobody waits."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    approach: Optional[str] = Field(default=None, min_length=1, max_length=128)
    ttl_s: float = Field(gt=0.0, le=5.0, allow_inf_nan=False)
    reason: str = Field(default="", max_length=200)


class TripRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    to: Union[PlaceRef, TripPoint]
    via: list[PlaceRef] = Field(default_factory=list, max_length=8)
    arrive_yaw: Optional[float] = Field(default=None, ge=-math.pi, le=math.pi, allow_inf_nan=False)
    speed_cap: Optional[float] = Field(default=None, gt=0.0, le=5.0, allow_inf_nan=False)
    #: Edge ids the caller keeps out of this plan. Empty leaves today's route.
    blocked_edges: list[PlaceRef] = Field(default_factory=list, max_length=32)
    #: Extra seconds on an edge id. Empty leaves today's route.
    extra_cost: dict[str, float] = Field(default_factory=dict)
    execute: bool = False
    #: D-517 2: lap ``via`` then ``to`` again and again; the cycle is place ids.
    repeat: bool = False
    # A finite lap starts and ends at the operator's chosen place.
    start_at: Optional[PlaceRef] = None
    #: D-517 9 M3: follow this robot's open repeat trip in a lane convoy (the same cycle).
    convoy: Optional[TripConvoy] = None
    camera_lane_fallback: bool = Field(default=False, strict=True)
    #: Optional Nav2 road-following execution mode over site-map edges.
    drive_mode: Optional[Literal["nav2"]] = None
    approved_slam_required: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def _cycle(self) -> "TripRequest":
        if self.approved_slam_required and (self.drive_mode != "nav2" or not isinstance(self.to, str)):
            raise ValueError("approved_slam_required needs Nav2 and a named destination")
        if self.camera_lane_fallback and (not self.approved_slam_required or self.repeat):
            raise ValueError("camera_lane_fallback needs a finite approved SLAM Nav2 trip")
        if self.repeat and (not isinstance(self.to, str) or not self.via):
            raise ValueError("repeat needs a place id in to and at least one via place")
        if self.convoy is not None and not self.repeat:
            raise ValueError("convoy needs repeat")
        if self.convoy is not None and self.drive_mode == "nav2":
            raise ValueError("convoy is only supported for lane trips")
        if self.start_at is not None and (self.repeat or self.to != self.start_at or not self.via
                                          or self.start_at in self.via):
            raise ValueError("start_at needs a finite trip via another place back to start_at")
        if len(set(self.blocked_edges)) != len(self.blocked_edges):
            raise ValueError("blocked_edges contains a duplicate")
        if len(self.extra_cost) > 32:
            raise ValueError("extra_cost has more than 32 edges")
        for edge, cost in self.extra_cost.items():
            if not 1 <= len(edge) <= 64:
                raise ValueError("extra_cost edge id must be 1 to 64 characters")
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0.0:
                raise ValueError("extra_cost must be finite and nonnegative")
        return self


def _refuse(code: str, detail: Optional[dict] = None, status: int = 422) -> HTTPException:
    """D-490 부록: every trip error is ``{"detail": {"code", "detail"}}``."""
    return HTTPException(status_code=status, detail={"code": code, "detail": detail or {}})


def install_trip_routes(app, *, console, site_maps, routing_config, require_operator, require_named_operator,
                        caps_for, runner, read_guard) -> None:
    app.state.trip_runner = runner
    if getattr(runner, "human_hold_fn", None) is None:
        runner.human_hold_fn = lambda: bool(
            callable(getattr(app.state, "pipeline_human_hold_fn", None)) and app.state.pipeline_human_hold_fn()
        )
        # the reason must follow the hold: without it a closed dispatch latch reads as HUMAN_HOLD
        runner.hold_state_fn = lambda: (getattr(app.state, "pipeline_hold_state_fn", None) or (lambda: None))()
    not_open = _refuse("TRIP_EXECUTION_NOT_AVAILABLE",
                       {"message": "start the plan with POST /api/fleet/trips/{plan_id}/start"}, 501)
    failed_versions: set = set()  # an unexpected planner failure is logged once per map version

    @app.post("/api/fleet/robots/{robot_id}/trip", tags=["fleet"])
    async def fleet_trip(robot_id: str, body: TripRequest,
                         principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        if body.execute:
            raise not_open
        return await plan(robot_id, body, principal.principal_id)

    async def plan(robot_id: str, body: TripRequest, principal_id: str) -> dict:
        """The one trip plan path (D-763 6): robot card, site map and a job's 운행 step (``job_trip_steps``)."""
        plan_id = uuid.uuid4().hex
        active = site_maps.active()
        summary = body.model_dump(mode="json", exclude={"execute"})

        def record(result: dict) -> None:
            site_maps.record_plan(plan_id=plan_id, robot_id=robot_id[:96], principal_id=principal_id,
                                  map_version=active[0] if active else None, request=summary, result=result)

        if robot_id not in console.robot_ids:
            record({"error": "UNKNOWN_ROBOT"})
            raise _refuse("UNKNOWN_ROBOT", status=404)

        if active is None:
            record({"error": "TRIP_NO_ACTIVE_MAP"})
            raise _refuse("TRIP_NO_ACTIVE_MAP")
        from fleet.server.rear_bay_return import rear_bay
        try:
            parking = rear_bay(active[2], body.to) if not body.repeat else None
        except TripError as exc:
            record({"error": exc.code, "detail": exc.detail})
            raise _refuse(exc.code, exc.detail, exc.status) from exc
        if parking and (body.via or body.blocked_edges or body.extra_cost or body.speed_cap is not None
                        or body.arrive_yaw is not None or body.convoy):
            record({"error": "CHARGE_RETURN_CUSTOM_ROUTE_UNSUPPORTED"})
            raise _refuse("CHARGE_RETURN_CUSTOM_ROUTE_UNSUPPORTED")
        known_edges = {arc.edge_id for arc in active[2].arcs.values()}
        for edge in (*body.blocked_edges, *body.extra_cost):
            if edge not in known_edges:
                record({"error": "TRIP_UNKNOWN_EDGE", "detail": {"edge": edge}})
                raise _refuse("TRIP_UNKNOWN_EDGE", {"edge": edge})
        refused = body.convoy and runner.convoy_refusal(robot_id, body.convoy.leader,
                                                        cycle=frozenset([body.to, *body.via]))
        if refused:
            record({"error": refused[0], "detail": refused[1]})
            raise _refuse(*refused)
        # The trip loop's own map pose first (D-494 3, D-593 1): a motor-mode robot reports no
        # localization, so its Rosy Cam MapPose is its only map pose. A robot-reported LOCALIZED
        # map pose stays accepted (D-488 3); the start still requires MapPose LOCALIZED (D-494 5).
        nav2 = body.drive_mode == "nav2" or parking is not None
        if parking:
            summary.update(drive_mode="nav2")
        precision = commissioned_stop(active[2], body.to)
        if nav2 and precision is not None:
            record({"error": "PRECISION_STOP_REQUIRES_NAV2_TERMINAL"})
            raise _refuse("PRECISION_STOP_REQUIRES_NAV2_TERMINAL")
        binding_id = None
        bound_nav2 = nav2 and isinstance(body.to, str) and (body.approved_slam_required
                                                            or runner.config.map_binding_required)
        caps = None
        if precision is not None or bound_nav2:
            bound = await read_precision_pose(runner, robot_id, active[0])
            if bound is None:
                detail = {"reason": "APPROVED_SLAM_POSE_REQUIRED"}
                record({"error": "TRIP_POSE_UNTRUSTED", "detail": detail})
                raise _refuse("TRIP_POSE_UNTRUSTED", detail, 409)
            map_pose, binding_id = bound
        else:
            bound = await read_precision_pose(runner, robot_id, active[0]) if nav2 else None
            if bound is not None:
                caps = await caps_for(robot_id)
            if bound is not None and caps is not None and caps.bound_route:
                map_pose, binding_id = bound
            else:
                try:
                    map_pose = await runner.map_pose(robot_id)
                except (HubError, RobotApiError, OSError) as exc:
                    record({"error": "ROBOT_POSE_UNAVAILABLE", "detail": {"kind": type(exc).__name__}})
                    raise http_error(exc) from exc
        pose_state = map_pose.state if map_pose is not None else None
        if pose_state == LOCALIZED and map_pose.yaw is not None:
            pose = (map_pose.x, map_pose.y, map_pose.yaw)
        elif bound_nav2:
            pose = None
        else:
            try:
                pose = await console.trusted_map_pose(robot_id)
            except (HubError, RobotApiError, OSError) as exc:
                record({"error": "ROBOT_POSE_UNAVAILABLE", "detail": {"kind": type(exc).__name__}})
                raise http_error(exc) from exc
        if pose is None or pose[2] is None:
            record({"error": "TRIP_POSE_UNTRUSTED", "detail": {"pose_state": pose_state}})
            raise _refuse("TRIP_POSE_UNTRUSTED", {"pose_state": pose_state})
        if body.start_at is not None:
            if body.start_at not in active[2].places:
                record({"error": "TRIP_UNKNOWN_PLACE", "detail": {"place": body.start_at}})
                raise _refuse("TRIP_UNKNOWN_PLACE", {"place": body.start_at})
            distance = math.dist(pose[:2], active[2].place_xy(body.start_at))
            if distance > ARRIVED_M:
                detail = {"place": body.start_at, "distance_m": round(distance, 3), "limit_m": ARRIVED_M}
                record({"error": "TRIP_START_PLACE_MISMATCH", "detail": detail})
                raise _refuse("TRIP_START_PLACE_MISMATCH", detail)
        goal = body.to if isinstance(body.to, str) else (body.to.x, body.to.y, body.to.yaw)
        if parking:
            goal = parking["staging_place_id"]

        # D-494 1: the robot's trip caps bound the plan. An older image has none; its preview
        # keeps kind-restricted edges out and allows every drive mode (execution refuses it).
        # A robot held at 0 m/s may use no lane, so the planner answers TRIP_NO_ROUTE.
        if caps is None:
            caps = await caps_for(robot_id)
        if bound_nav2 and (caps is None or not caps.bound_route):
            detail = {"reason": "NAV2_BOUND_ROUTE_UNSUPPORTED"}
            record({"error": "NAV2_BOUND_ROUTE_UNSUPPORTED", "detail": detail})
            raise _refuse("NAV2_BOUND_ROUTE_UNSUPPORTED", status=409)
        if nav2 and caps is not None and (caps.max_speed <= 0 or "free" not in caps.modes):
            detail = {"drive_mode": "free"}
            record({"error": "TRIP_MODE_UNSUPPORTED", "detail": detail})
            raise _refuse("TRIP_MODE_UNSUPPORTED", detail)
        bounds = {} if caps is None else {
            "robot_kind": caps.kind,
            "drive_modes": (frozenset(("lane", "free")) if nav2 else caps.modes) if caps.max_speed > 0 else frozenset(),
            "max_speed_mps": caps.max_speed or None}
        request = PlanRequest(map_version=active[0], start_pose=(pose[0], pose[1], pose[2]), goal=goal,
                              via=tuple(body.via), arrive_yaw=body.arrive_yaw, speed_cap=body.speed_cap,
                              blocked_edges=frozenset(body.blocked_edges), extra_cost=dict(body.extra_cost),
                              body_front_m=body_front_m(bounds.get("robot_kind")),
                              stop_offset=not (nav2 and body.repeat), ignore_start_heading=nav2,
                              ignore_arrive_heading=nav2,
                              nav2_off_lane_margin_m=runner.config.nav2_off_lane_margin_m if nav2 else 0.0,
                              # Rear-bay staging within the trip's arrive radius is reached: CORE docks from there.
                              # A shorter Nav2 goal ends before its first lease renewal, and snapping onto the exit
                              # lane plans a whole loop back to the same staging place.
                              arrived_m=max(ARRIVED_M, runner.config.arrive_free_m) if parking and not body.via
                              else None, **bounds)
        try:
            plan = plan_trip(active[2], request, routing_config)
        except PlanError as exc:
            record({"error": exc.code, "detail": exc.detail})
            raise _refuse(exc.code, exc.detail) from exc
        except Exception as exc:  # a planner bug is a coded 500, logged once, never a bare traceback
            if active[0] not in failed_versions:
                failed_versions.add(active[0])
                _LOG.exception("trip planner failed on site map v%s", active[0])
            record({"error": "TRIP_PLAN_FAILED", "detail": {"kind": type(exc).__name__}})
            raise _refuse("TRIP_PLAN_FAILED", {"map_version": active[0]}, 500) from exc
        plan_data = plan_body(plan)
        if parking:
            plan_data["parking_handoff"] = parking
            staging_distance = math.dist(pose[:2], active[2].place_xy(goal))
            plan_data["staging_distance_m"] = round(staging_distance, 4)
            if staging_distance <= runner.config.arrive_free_m:
                parking["plan_prerequisites"] = await runner.rear_bay_port.prerequisites(robot_id, parking)
        if bound_nav2 or (nav2 and binding_id is not None):
            plan_data["nav2_binding_id"] = binding_id
        elif binding_id is not None:
            if not runner._precision_terminal_matches(active[2], plan_data["segments"], precision):
                record({"error": "PRECISION_STOP_REQUIRES_NAV2_TERMINAL"})
                raise _refuse("PRECISION_STOP_REQUIRES_NAV2_TERMINAL")
            plan_data["precision_binding_id"] = binding_id
        if not nav2 and any(active[2].arcs[arc_id(seg)].drive_mode == "lane" for seg in plan_data["segments"]):
            try:  # D-601 B: no lane trip for a robot whose line camera is not live
                await runner.camera_check(robot_id, caps)
            except TripError as exc:
                record({"error": exc.code, "detail": exc.detail})
                raise _refuse(exc.code, exc.detail, status=exc.status) from exc
        # D-601 D: the start's alignment check on this pose, shown before 출발 (the start checks again)
        plan_data["start_check"] = start_check(
            active[2], plan_data["segments"], *pose, runner.config.start_heading_tol_deg, nav2=nav2,
            off_lane_margin_m=runner.config.nav2_off_lane_margin_m)
        if (precision is None and runner.config.auto_align
                and plan_data["start_check"]["code"] == "TRIP_START_HEADING_MISMATCH"
                and plan_data["start_check"]["heading_err_deg"] is not None):
            plan_data["start_check"]["auto_align"] = True  # D-603: the start turns the robot first
        # D-494 5: the whole body is kept so /trips/{plan_id}/start runs exactly this plan.
        # The fact bundle sits beside that plan. The trip loop does not execute it.
        context = route_context(planner="lane_graph", supplied={
            "to": summary["to"], "via": list(summary.get("via") or []),
            "arrive_yaw": summary.get("arrive_yaw"), "speed_cap": summary.get("speed_cap"),
            "blocked_edges": list(summary.get("blocked_edges") or []),
            "extra_cost": dict(summary.get("extra_cost") or {}),
        }, holds={
            "map_version": plan_data["map_version"],
            "segments": [seg["edge_id"] for seg in plan_data["segments"]],
            "places": list(plan_data["places"]),
            "length_m": plan_data["length_m"], "eta_s": plan_data["eta_s"],
        })
        record({"segments": len(plan.segments), "length_m": plan.length_m, "eta_s": plan.eta_s,
                "plan": plan_data, "context": context})
        response = {"plan_id": plan_id, **plan_data, "context": context, "expires_at": time.time() + PLAN_TTL_S}
        if bound_nav2:
            response["nav2_preflight"] = {"code": None, "binding_required": True, "binding_status": "MATCHED"}
        elif nav2:
            state = None
            if runner._robot_state is not None:
                try:
                    state = await runner._call(runner._robot_state(robot_id), "ROBOT_POSE_UNTRUSTED")
                except TripError:
                    pass
            fit, binding_status = site_maps.map_bindings.matching_fit(robot_id, state or {}, (active[1].map_id, active[0]))
            required = runner.config.map_binding_required
            code = None
            if trust.classify(state) != trust.TRUSTED:
                code = "ROBOT_POSE_UNTRUSTED"
            elif caps is None:
                code = "TRIP_ROBOT_CAPS_UNKNOWN"
            elif required and fit is None:
                code = binding_status
            response["nav2_preflight"] = {"code": code, "binding_required": required,
                                          "binding_status": "MATCHED" if fit is not None else binding_status}
        return response

    from fleet.server.rear_bay_return import RearBayPort
    runner.rear_bay_port = RearBayPort(console, (*runner.halts.restarted, *runner.halts.gave_up))
    runner.halts.dock_stop = runner.rear_bay_port.halt
    app.state.trip_plan = plan
    from fleet.server.trip_reissue import TripReissue
    app.state.trip_reissue = TripReissue(runner, plan)   # D-1086: a non-hazard end is planned and started again

    @app.get("/api/fleet/robots/{robot_id}/bays/{bay_id}/dock-prerequisites", dependencies=read_guard, tags=["fleet"])
    async def dock_prerequisites(robot_id: str, bay_id: str) -> dict:
        from fleet.server.rear_bay_return import rear_bay
        if robot_id not in console.robot_ids:
            raise _refuse("UNKNOWN_ROBOT", status=404)
        active = site_maps.active()
        if active is None:
            raise _refuse("TRIP_NO_ACTIVE_MAP")
        try:
            info = rear_bay(active[2], bay_id)
        except TripError as exc:
            raise trip_error(exc) from exc
        if info is None:
            raise _refuse("CHARGE_BAY_APPROACH_UNAVAILABLE", status=404)
        return await runner.rear_bay_port.prerequisites(robot_id, info)

    def trip_error(exc: TripError) -> HTTPException:
        return _refuse(exc.code, exc.detail, exc.status)

    @app.post("/api/fleet/trips/{plan_id}/start", tags=["fleet"])
    async def fleet_trip_start(plan_id: str, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        def receipt(stage, code=None, detail=None):
            try:
                row = site_maps.plan(plan_id)
                if row is not None:
                    site_maps.record_event("trip_start_receipt", principal.principal_id, {
                        "plan_id": plan_id, "robot_id": row["robot_id"], "to": row["request"].get("to"),
                        "stage": stage, "code": code, "detail": detail or {}})
            except sqlite3.Error:
                _LOG.exception("trip receipt write failed plan_id=%s stage=%s code=%s", plan_id, stage, code)
        try:
            trip = await runner.start(plan_id, principal.principal_id)
        except TripError as exc:
            receipt("start_refused", exc.code, exc.detail)
            raise trip_error(exc) from exc
        receipt("start_accepted")
        return runner.execution_view(trip)

    @app.get("/api/fleet/trip-requests", dependencies=read_guard, tags=["fleet"])
    def trip_request_history() -> dict:
        rows = site_maps.trip_request_history()
        for row in rows:
            if row["stage"] == "start_accepted":
                trip = runner.view(row["plan_id"])
                if trip and trip["robot_id"] == row["robot_id"]:
                    detail = trip.get("detail") or {}
                    row["outcome"] = {"robot_id": trip["robot_id"], "state": trip["state"],
                                      "reason": trip.get("reason"), "detail": {k: detail[k] for k in
                                      ("goal_reason", "goal_admission", "peer_wait", "last_peer_wait",
                                       "wait_prefix", "traffic_hold", "last_peer_observation_retry", "held_lidar_observation",
                                       "stop_sent") if k in detail}}
        return {"requests": rows}

    @app.post("/api/fleet/trips/{trip_id}/cancel", tags=["fleet"])
    async def fleet_trip_cancel(trip_id: str,  # D-540 9: a stop stays open
                                principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return await runner.cancel(trip_id, principal.principal_id)
        except TripError as exc:
            raise trip_error(exc) from exc

    @app.post("/api/fleet/trips/{trip_id}/confirm-replan", tags=["fleet"])
    async def fleet_trip_confirm_replan(trip_id: str,
                                        principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return await runner.confirm_replan(trip_id, principal.principal_id)
        except TripError as exc:
            raise trip_error(exc) from exc

    @app.post("/api/fleet/trips/{trip_id}/pause", tags=["fleet"])
    async def fleet_trip_pause(trip_id: str, body: Optional[TripPauseRequest] = None,
                               principal: SitePrincipal = Depends(require_operator)) -> dict:
        try:
            return await runner.pause(trip_id, principal.principal_id, reason=body.reason if body else None)
        except TripError as exc:
            raise trip_error(exc) from exc

    @app.post("/api/fleet/trips/{trip_id}/resume", tags=["fleet"])
    async def fleet_trip_resume(trip_id: str, body: Optional[TripResumeRequest] = None,
                                principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            edges = tuple(body.blocked_edges) if body else ()
            return await runner.resume(trip_id, principal.principal_id, blocked_edges=edges)
        except TripError as exc:
            raise trip_error(exc) from exc

    @app.get("/api/fleet/trips", dependencies=read_guard, tags=["fleet"])
    def fleet_trips() -> dict:
        active = [runner.execution_view(row) for row in runner.open_trips()]
        return {"running": max(active, key=lambda t: t["created_at"], default=None), "open": active,
                "trips": [runner.execution_view(row) for row in runner.recent()]}

    @app.get("/api/fleet/traffic", dependencies=read_guard, tags=["fleet"])
    def fleet_traffic() -> dict:
        """D-517 3 (M1): the block table of the last trip period; nothing of it is sent to robots."""
        return runner.traffic.view()

    @app.get("/api/fleet/traffic/signals/ahead/{robot_id}", dependencies=read_guard, tags=["fleet"])
    def fleet_traffic_signal_ahead(robot_id: str) -> dict:
        """D-525 rev 3: the next virtual signal on this robot's trip and its countdown (advisory: only
        the D-517 authority lets a robot in). 404 SIGNAL_NONE_AHEAD when its route crosses none."""
        ahead = runner.traffic.signal_ahead(robot_id)
        if ahead is None:
            raise _refuse("SIGNAL_NONE_AHEAD", status=404)
        return ahead

    @app.post("/api/fleet/traffic/signals/presence", tags=["fleet"])
    def fleet_traffic_signal_presence(principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        """D-525 4: the operator's console is open; a manual green lasts while this keeps coming."""
        return runner.traffic.signal_presence()

    @app.post("/api/fleet/traffic/signals/{signal_id}/demand", tags=["fleet"])
    def fleet_traffic_signal_demand(signal_id: str, body: SignalDemand, request: Request,
                                    principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        """D-525 rev 4: a controller (AI PC) asks for a green for one approach for ``ttl_s`` (≤ 5 s). Fleet
        still decides: the zone must be free and every change goes through yellow and all red. Robots
        never get permission from it. 409 SIGNAL_NOT_DEMAND unless an operator enabled ``demand``."""
        try:
            row, fresh = runner.traffic.signal_demand(signal_id, body.approach, body.ttl_s, body.reason)
        except KeyError:
            raise _refuse("SIGNAL_UNKNOWN", status=404)
        except PermissionError:
            raise _refuse("SIGNAL_NOT_DEMAND", status=409)
        except ValueError:
            raise _refuse("SIGNAL_APPROACH", status=422)
        if fresh:  # audited at low rate: a new demand, not every 0.5 s repeat (site_auth skips this path)
            _LOG.info("signal %s demand %s by %s: %s", signal_id, body.approach, principal.principal_id, body.reason)
            store = getattr(getattr(request.app.state, "task_service", None), "store", None)
            if store is not None:
                try:
                    audit = store.begin_api_audit(principal_id=principal.principal_id, role=principal.role,
                                                  method="POST", path=request.url.path)
                    store.finish_api_audit(audit, status_code=200)
                except (OSError, sqlite3.Error, ValueError, KeyError):
                    _LOG.exception("signal demand audit failed; the demand stands (Fleet still decides)")
        return row

    @app.post("/api/fleet/traffic/signals/{signal_id}", tags=["fleet"])
    def fleet_traffic_signal(signal_id: str, body: SignalCommand,
                             principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        """D-525 4: operator verb for a virtual signal: ``occupancy`` (rev 6, the default: lamps follow the
        zone's live D-517 state), ``cycle``, ``hold``, ``all_red``, ``demand`` (rev 4: the next green
        follows controller demands), or ``set_aspect`` with ``approach`` (green for that
        approach while the operator's console sends presence)."""
        try:
            return runner.traffic.signal_command(signal_id, body.verb, body.approach)
        except KeyError:
            raise _refuse("SIGNAL_UNKNOWN", status=404)
        except ValueError:
            raise _refuse("SIGNAL_VERB", status=422)
        except PermissionError:
            raise _refuse("SIGNAL_NO_PRESENCE", status=409)

    @app.get("/api/fleet/trips/{trip_id}", dependencies=read_guard, tags=["fleet"])
    def fleet_trip_view(trip_id: str) -> dict:
        view = runner.view(trip_id)
        if view is None:
            raise _refuse("TRIP_UNKNOWN", status=404)
        return runner.execution_view(view)
