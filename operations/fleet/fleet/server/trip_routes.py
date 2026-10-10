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
from typing import Annotated, Optional, Union

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fleet.hub.hub import HubError
from fleet.routing.snap import PlanError
from fleet.routing.trip import PlanRequest, plan_trip
from fleet.server.http_errors import http_error
from fleet.server.site_auth import SitePrincipal
from fleet.routing.execute import arc_id, plan_body
from fleet.server.trip_admission import start_check
from fleet.server.trip_runner import LOCALIZED, PLAN_TTL_S, TripError
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
    execute: bool = False
    #: D-517 2: lap ``via`` then ``to`` again and again; the cycle is place ids.
    repeat: bool = False
    #: D-517 9 M3: follow this robot's open repeat trip in a lane convoy (the same cycle).
    convoy: Optional[TripConvoy] = None

    @model_validator(mode="after")
    def _cycle(self) -> "TripRequest":
        if self.repeat and (not isinstance(self.to, str) or not self.via):
            raise ValueError("repeat needs a place id in to and at least one via place")
        if self.convoy is not None and not self.repeat:
            raise ValueError("convoy needs repeat")
        return self


def _refuse(code: str, detail: Optional[dict] = None, status: int = 422) -> HTTPException:
    """D-490 부록: every trip error is ``{"detail": {"code", "detail"}}``."""
    return HTTPException(status_code=status, detail={"code": code, "detail": detail or {}})


def install_trip_routes(app, *, console, site_maps, routing_config, require_operator, require_named_operator,
                        caps_for, runner, read_guard) -> None:
    app.state.trip_runner = runner
    not_open = _refuse("TRIP_EXECUTION_NOT_AVAILABLE",
                       {"message": "start the plan with POST /api/fleet/trips/{plan_id}/start"}, 501)
    failed_versions: set = set()  # an unexpected planner failure is logged once per map version

    @app.post("/api/fleet/robots/{robot_id}/trip", tags=["fleet"])
    async def fleet_trip(robot_id: str, body: TripRequest,
                         principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        if body.execute:
            raise not_open
        plan_id = uuid.uuid4().hex
        active = site_maps.active()
        summary = body.model_dump(mode="json", exclude={"execute"})

        def record(result: dict) -> None:
            site_maps.record_plan(plan_id=plan_id, robot_id=robot_id[:96], principal_id=principal.principal_id,
                                  map_version=active[0] if active else None, request=summary, result=result)

        if robot_id not in console.robot_ids:
            record({"error": "UNKNOWN_ROBOT"})
            raise _refuse("UNKNOWN_ROBOT", status=404)

        if active is None:
            record({"error": "TRIP_NO_ACTIVE_MAP"})
            raise _refuse("TRIP_NO_ACTIVE_MAP")
        refused = body.convoy and runner.convoy_refusal(robot_id, body.convoy.leader,
                                                        cycle=frozenset([body.to, *body.via]))
        if refused:
            record({"error": refused[0], "detail": refused[1]})
            raise _refuse(*refused)
        # The trip loop's own map pose first (D-494 3, D-593 1): a motor-mode robot reports no
        # localization, so its Rosy Cam MapPose is its only map pose. A robot-reported LOCALIZED
        # map pose stays accepted (D-488 3); the start still requires MapPose LOCALIZED (D-494 5).
        map_pose = await runner.map_pose(robot_id)
        pose_state = map_pose.state if map_pose is not None else None
        if pose_state == LOCALIZED and map_pose.yaw is not None:
            pose = (map_pose.x, map_pose.y, map_pose.yaw)
        else:
            try:
                pose = await console.trusted_map_pose(robot_id)
            except (HubError, RobotApiError, OSError) as exc:
                record({"error": "ROBOT_POSE_UNAVAILABLE", "detail": {"kind": type(exc).__name__}})
                raise http_error(exc) from exc
        if pose is None or pose[2] is None:
            record({"error": "TRIP_POSE_UNTRUSTED", "detail": {"pose_state": pose_state}})
            raise _refuse("TRIP_POSE_UNTRUSTED", {"pose_state": pose_state})
        goal = body.to if isinstance(body.to, str) else (body.to.x, body.to.y, body.to.yaw)
        # D-494 1: the robot's trip caps bound the plan. An older image has none; its preview
        # keeps kind-restricted edges out and allows every drive mode (execution refuses it).
        # A robot held at 0 m/s may use no lane, so the planner answers TRIP_NO_ROUTE.
        caps = await caps_for(robot_id)
        bounds = {} if caps is None else {
            "robot_kind": caps.kind, "drive_modes": caps.modes if caps.max_speed > 0 else frozenset(),
            "max_speed_mps": caps.max_speed or None}
        request = PlanRequest(map_version=active[0], start_pose=(pose[0], pose[1], pose[2]), goal=goal,
                              via=tuple(body.via), arrive_yaw=body.arrive_yaw, speed_cap=body.speed_cap,
                              **bounds)
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
        body = plan_body(plan)
        if any(active[2].arcs[arc_id(seg)].drive_mode == "lane" for seg in body["segments"]):
            try:  # D-601 B: no lane trip for a robot whose line camera is not live
                await runner.camera_check(robot_id, caps)
            except TripError as exc:
                record({"error": exc.code, "detail": exc.detail})
                raise _refuse(exc.code, exc.detail) from exc
        # D-601 D: the start's alignment check on this pose, shown before 출발 (the start checks again)
        body["start_check"] = start_check(active[2], body["segments"], *pose, runner.config.start_heading_tol_deg)
        if (runner.config.auto_align and body["start_check"]["code"] == "TRIP_START_HEADING_MISMATCH"
                and body["start_check"]["heading_err_deg"] is not None):
            body["start_check"]["auto_align"] = True  # D-603: the start turns the robot first
        # D-494 5: the whole body is kept so /trips/{plan_id}/start runs exactly this plan.
        record({"segments": len(plan.segments), "length_m": plan.length_m, "eta_s": plan.eta_s, "plan": body})
        return {"plan_id": plan_id, **body, "expires_at": time.time() + PLAN_TTL_S}

    def trip_error(exc: TripError) -> HTTPException:
        return _refuse(exc.code, exc.detail, exc.status)

    @app.post("/api/fleet/trips/{plan_id}/start", tags=["fleet"])
    async def fleet_trip_start(plan_id: str, principal: SitePrincipal = Depends(require_named_operator)) -> dict:
        try:
            return await runner.start(plan_id, principal.principal_id)
        except TripError as exc:
            raise trip_error(exc) from exc

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

    @app.get("/api/fleet/trips", dependencies=read_guard, tags=["fleet"])
    def fleet_trips() -> dict:
        return {"running": runner.running(), "open": runner.open_trips(), "trips": runner.recent()}

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
        return view
