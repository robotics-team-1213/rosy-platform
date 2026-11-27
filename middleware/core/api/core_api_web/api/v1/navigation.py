"""core_api_web.api.v1.navigation — NAV-001~005 주행·SLAM·로컬라이제이션(초기 위치추정)."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from uuid import UUID

from core_api_web.api.v1.common import (
    enter_navigation_mode,
    operator,
    owns_trip_lease,
    require_calibration_owner,
    require_manual_released,
    require_kept,
    localized_start,
    stop_ends_trip_lease,
    viewer,
)
from core_api_web.api.deps import (GOAL_LEASE_MAX_S, MAX_POINTS, AuthContext, Mode, NavigationError,
                                  RoutePoint, get_services, CoreServicesLike)
from core_api_web.api.errors import ApiError, navigation_error_status
from core_api_web.api.grants import NAVIGATE, check_grant
from core_api_web.api.v1.localization import send_decision
from core_common.domain.tasks import TaskKind
from core_common.protocol.schemas import ScopedNavigationCancelRequest
from core_common.protocol.trip_lease import TripLeaseError
from core_api_web.api.v1.navigation_handover import navigation_handover
from core_api_web.api.v1.navigation_plan import plan_scope, verify_plan_start


class MotionReceivedRoute(APIRoute):
    def get_route_handler(self):
        handle = super().get_route_handler()

        async def received(request):
            # Count body parsing, dependencies and the sync threadpool queue before the handler runs.
            request.state.motion_received_at = time.monotonic()
            return await handle(request)

        return received


navigation_router = APIRouter(prefix="/api/v1", tags=["navigation"], route_class=MotionReceivedRoute)
navigation_router.add_api_route('/navigation/handover', navigation_handover, methods=['POST'])


class MotionAdmitRequest(BaseModel):
    admit_within_s: float | None = Field(default=None, gt=0, le=10, allow_inf_nan=False)


class GoalRequest(MotionAdmitRequest):
    x: float | None = None
    y: float | None = None
    yaw: float | None = 0.0
    waypoint: str | None = None
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    #: D-550 10: optional goal lease; needs correlation_id. Checked before the mode changes.
    lease_ttl_s: float | None = Field(default=None, gt=0, le=GOAL_LEASE_MAX_S, allow_inf_nan=False)
    expected_boot_id: UUID | None = None
    expected_owner_generation: int | None = Field(default=None, ge=0, strict=True)


class BoundGoalRequest(GoalRequest):
    expected_map_grid_id: str = Field(min_length=1, max_length=128, strict=True)
    plan_id: UUID | None = None


class PlanLineStop(BaseModel):
    lease_id: str = Field(min_length=1, max_length=64, strict=True)
    trip_id: str = Field(min_length=1, max_length=128, strict=True)
    job_id: str | None = Field(default=None, max_length=128, strict=True)
    junction_seq: int = Field(gt=0, strict=True)
    stop_place_id: str = Field(min_length=1, max_length=128, strict=True)


class LineHandoffGoalRequest(BoundGoalRequest, PlanLineStop):
    correlation_id: str = Field(min_length=1, max_length=128, strict=True)
    expected_boot_id: UUID
    expected_owner_generation: int = Field(ge=0, strict=True)


class BoundPlanRequest(BoundGoalRequest):
    correlation_id: str = Field(min_length=1, max_length=128, strict=True)
    line_stop: PlanLineStop | None = None


class HomeRequest(MotionAdmitRequest):
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    lease_ttl_s: float | None = Field(default=None, gt=0, le=GOAL_LEASE_MAX_S, allow_inf_nan=False)
    expected_boot_id: UUID | None = None
    expected_owner_generation: int | None = Field(default=None, ge=0, strict=True)


class RoadSpeedGrant(BaseModel):
    issued_at: float = Field(allow_inf_nan=False)
    expires_at: float = Field(allow_inf_nan=False)
    limit_mps: float = Field(ge=0, allow_inf_nan=False)


class GoalLeaseRequest(BaseModel):
    speed_grant: RoadSpeedGrant | None = None
    correlation_id: str = Field(min_length=1, max_length=128)
    ttl_s: float = Field(gt=0, le=GOAL_LEASE_MAX_S, allow_inf_nan=False)


def _goal_gates(body, auth: AuthContext, svc: CoreServicesLike) -> None:
    """Everything a goal or a route must pass before the mode changes."""
    if body.lease_ttl_s is not None and body.correlation_id is None:  # D-550 10, before any mode change
        raise ApiError("VALIDATION_ERROR", 400, "lease_ttl_s needs a correlation_id")
    require_manual_released(svc)
    if svc.line_follow.active:
        # D-541 5: the trip lease owner switches lane -> free with the goal itself
        # (enter_navigation_mode turns line-follow off); a line-follow OFF first would go IDLE.
        require_calibration_owner(svc, auth, "navigation")
        if not owns_trip_lease(svc, auth):
            raise ApiError("LINE_FOLLOW_ACTIVE", 409,
                           "stop the selected line-follow mode before accepting a navigation goal")
    TaskKind.NAVIGATE.require(svc.capability)
    require_kept(svc, "navigation.goal_navigation")


@navigation_router.post("/navigation/goal")
def navigation_goal(body: GoalRequest, auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services), request: Request = None):
    return _navigation_goal(body, auth, svc, admit_before=_admit_before(body, request))


@navigation_router.post("/navigation/bound-goal")
def bound_navigation_goal(body: BoundGoalRequest, auth: AuthContext = Depends(operator),
                          svc: CoreServicesLike = Depends(get_services), request: Request = None):
    return _bound_execution(body, auth, svc, admit_before=_admit_before(body, request))


@navigation_router.post("/navigation/bound-plan")
def prepare_bound_path(body: BoundPlanRequest, auth: AuthContext = Depends(operator),
                       svc: CoreServicesLike = Depends(get_services)):
    require_calibration_owner(svc, auth, "navigation planning")
    _goal_gates(body, auth, svc)
    with svc.state.map_grid_gate, localized_start(svc):
        scope = plan_scope(svc, body, auth, body.line_stop)
        spec = svc.nav.resolve_goal(x=body.x, y=body.y, yaw=body.yaw, waypoint=body.waypoint)
    plan = svc.nav.prepare_path(spec, scope=scope, timeout_s=2.0)
    with svc.state.map_grid_gate, localized_start(svc):
        if plan_scope(svc, body, auth, body.line_stop) != scope:
            raise ApiError("NAVIGATION_PLAN_CHANGED", 409, "the navigation scope changed during planning")
        verify_plan_start(svc, plan)
    return {"plan_id": plan.plan_id, "map_grid_id": body.expected_map_grid_id,
            "frame": "map", "points": plan.points}


@navigation_router.post("/navigation/line-handoff-goal")
def line_handoff_navigation_goal(body: LineHandoffGoalRequest, auth: AuthContext = Depends(operator),
                                 svc: CoreServicesLike = Depends(get_services), request: Request = None):
    return _bound_execution(body, auth, svc, line_stop=body, admit_before=_admit_before(body, request))


def _admit_before(body, request):
    if body.admit_within_s is None:
        return None
    # Direct callers (POST /do) have no route receipt: the deadline still applies, measured from this call.
    state = getattr(request, "state", None)
    received = getattr(state, "motion_received_at", None)
    return (time.monotonic() if received is None else received) + body.admit_within_s


def _bound_execution(body, auth, svc, *, line_stop=None, admit_before=None):
    admitted = False

    def record_admission():
        nonlocal admitted
        admitted = True

    try:
        return _navigation_goal(body, auth, svc, expected_grid=body.expected_map_grid_id, line_stop=line_stop,
                                record_admission=record_admission, admit_before=admit_before)
    except (ApiError, NavigationError) as exc:
        if admitted or body.plan_id is None:
            raise
        detail = dict(exc.detail or {}) if isinstance(exc, ApiError) else {}
        detail.update(plan_id=str(body.plan_id), native_admitted=False)
        status = exc.http_status if isinstance(exc, ApiError) else navigation_error_status(exc.code)
        raise ApiError(exc.code, status, str(exc), detail=detail) from exc


def _navigation_goal(body, auth, svc, *, expected_grid=None, line_stop=None, record_admission=None,
                     admit_before=None):
    _goal_gates(body, auth, svc)
    gate = svc.state.map_grid_gate if expected_grid is not None else nullcontext()
    with gate, localized_start(svc):
        if expected_grid is not None and svc.state.map_grid_id != expected_grid:
            raise ApiError("NAVIGATION_MAP_GRID_CHANGED", 409, "the loaded grid differs from the approved goal grid")
        if expected_grid is not None and body.plan_id is None:
            raise ApiError("NAVIGATION_PLAN_REQUIRED", 409, "prepare and approve a bound path before execution")
        pin = nullcontext()
        extra = {}
        scope = None
        planned = None
        if line_stop is not None:
            svc.nav.require_ready()
            svc.nav._require_executor()
            trip = getattr(svc, "trip_lease", None)
            if trip is None:
                raise ApiError("NAVIGATION_HANDOFF_LEASE_CHANGED", 409, "trip lease is unavailable")
            scope = dict(lease_id=line_stop.lease_id, trip_id=line_stop.trip_id,
                         job_id=line_stop.job_id, owner_id=auth.token_id)
            mode_epoch = svc.modes.epoch
            if svc.modes.mode is not Mode.NAVIGATION:
                raise ApiError("NAVIGATION_HANDOFF_STOP_CHANGED", 409, "lane motion mode changed")

            def allows_handoff():
                return (svc.modes.mode is Mode.NAVIGATION and svc.modes.epoch == mode_epoch
                        and trip.commit_nav_handoff(**scope))

        spec = svc.nav.resolve_goal(x=body.x, y=body.y, yaw=body.yaw, waypoint=body.waypoint)
        owner = dict(expected_boot_id=body.expected_boot_id, expected_owner_generation=body.expected_owner_generation)
        if expected_grid is not None:
            if body.correlation_id is None:
                raise ApiError("VALIDATION_ERROR", 400, "a prepared path needs a correlation_id")
            require_calibration_owner(svc, auth, "navigation")
            planned = plan_scope(svc, body, auth, line_stop)
            grid_id, revision, mode, epoch, _ = planned.binding
            admitted_epoch = epoch + int(mode is Mode.IDLE)
            approved = []

            def verify(plan):
                verify_plan_start(svc, plan)
                approved.append(plan)

            def allows_plan():
                if (svc.state.map_grid_context() != (grid_id, revision)
                        or svc.modes.mode is not Mode.NAVIGATION or svc.modes.epoch != admitted_epoch):
                    raise ApiError("NAVIGATION_PLAN_CHANGED", 409, "the navigation scope changed before execution")
                verify_plan_start(svc, approved[0])
                if scope is not None:
                    if not allows_handoff():
                        return False
                    _consume_line_stop(svc, auth, line_stop)
                return True

            token = svc.nav.reserve_planned_goal(body.plan_id, spec, scope=planned, verify=verify, **owner)
            extra["handoff_admission"] = allows_plan
        else:
            token = svc.nav.reserve_goal(**owner)
        if scope is not None:
            pin = trip.pin_nav_handoff(**scope, reservation=token)
        receipt = []
        entered = False
        try:
            with pin as pinned_lease:
                if line_stop is None:
                    entered = enter_navigation_mode(svc, auth, expected=None if planned is None else (mode, epoch))

                def record(operation):
                    receipt.append(operation)
                    if record_admission is not None:
                        record_admission()
                    if pinned_lease is not None:
                        # Owner release is still pinned, before the executor sees this run.
                        pinned_lease.handoff_run_id = operation.run_id

                svc.nav.goal(spec, source=f"api:{auth.role}", correlation_id=body.correlation_id,
                             lease_ttl_s=body.lease_ttl_s, lease_owner=auth.token_id, reservation=token,
                             receipt_sink=record, admit_before=admit_before, **extra)
        except TripLeaseError as exc:
            raise ApiError("NAVIGATION_HANDOFF_LEASE_CHANGED", 409, str(exc)) from exc
        except (ApiError, NavigationError):
            if planned is not None and entered and not receipt:
                svc.modes.transition(Mode.IDLE, expect=Mode.NAVIGATION, expect_epoch=admitted_epoch)
            raise
        finally:
            svc.nav.release_goal_reservation(token)
    return {
        "accepted": True,
        "mode": svc.modes.mode.value,
        "goal": {"x": spec.x, "y": spec.y, "yaw": spec.yaw},
        "operation": receipt[0].model_dump(mode="json"),
    }


def _holds_handoff_lease(svc, auth, handoff) -> bool:
    trip = getattr(svc, "trip_lease", None)
    if trip is None or svc.safety.estop:
        return False
    return bool(trip.matches_nowait(lease_id=handoff.lease_id, trip_id=handoff.trip_id,
                                    job_id=handoff.job_id, owner_id=auth.token_id))


def _consume_line_stop(svc, auth, handoff) -> None:
    status = svc.line_follow.stop_held_junction(
        seq=handoff.junction_seq, place_id=handoff.stop_place_id,
        admitted=lambda: _holds_handoff_lease(svc, auth, handoff),
    )
    if status is None:
        raise ApiError("NAVIGATION_HANDOFF_STOP_CHANGED", 409, "the specified trip stop is no longer held")
    svc.command.clear_navigation()
    svc.state.set_line_follow(status)


class RoutePointRequest(BaseModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)
    yaw: float | None = Field(default=None, allow_inf_nan=False)
    #: "pass": drive through without stopping. "stop": halt here. Unspecified means stop.
    kind: Literal["pass", "stop"] = "stop"


class RouteRequest(MotionAdmitRequest):
    road_speed_controlled: bool = Field(default=False, strict=True)
    points: list[RoutePointRequest] = Field(min_length=1, max_length=MAX_POINTS)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    lease_ttl_s: float | None = Field(default=None, gt=0, le=GOAL_LEASE_MAX_S, allow_inf_nan=False)
    expected_boot_id: UUID | None = None
    expected_owner_generation: int | None = Field(default=None, ge=0, strict=True)


class BoundRouteRequest(RouteRequest):
    expected_map_grid_id: str = Field(min_length=1, max_length=128, strict=True)


@navigation_router.post("/navigation/route")
def navigation_route(body: RouteRequest, auth: AuthContext = Depends(operator),
                     svc: CoreServicesLike = Depends(get_services), request: Request = None):
    """NAV-008 (D-1009): an ordered route of pass/stop points as one navigation owner and one lease."""
    return _navigation_route(body, auth, svc, admit_before=_admit_before(body, request))


@navigation_router.post("/navigation/bound-route")
def bound_navigation_route(body: BoundRouteRequest, auth: AuthContext = Depends(operator),
                           svc: CoreServicesLike = Depends(get_services), request: Request = None):
    require_calibration_owner(svc, auth, "navigation")
    return _navigation_route(body, auth, svc, expected_grid=body.expected_map_grid_id,
                             admit_before=_admit_before(body, request))


def _navigation_route(body, auth, svc, *, expected_grid=None, admit_before=None):
    if body.road_speed_controlled and not (body.correlation_id and body.lease_ttl_s and auth.token_id):
        raise ApiError("VALIDATION_ERROR", 400, "road speed control requires an owned goal lease")
    _goal_gates(body, auth, svc)
    points = [RoutePoint(p.x, p.y, p.kind, p.yaw) for p in body.points]
    gate = svc.state.map_grid_gate if expected_grid is not None else nullcontext()
    with gate, localized_start(svc):
        if expected_grid is not None and svc.state.map_grid_id != expected_grid:
            raise ApiError("NAVIGATION_MAP_GRID_CHANGED", 409, "the loaded grid differs from the approved route grid")
        token = svc.nav.reserve_goal(expected_boot_id=body.expected_boot_id,
                                     expected_owner_generation=body.expected_owner_generation)
        receipt = []
        try:
            enter_navigation_mode(svc, auth)
            svc.nav.route(points, road_speed_controlled=body.road_speed_controlled, source=f"api:{auth.role}", correlation_id=body.correlation_id,
                          lease_ttl_s=body.lease_ttl_s, lease_owner=auth.token_id, reservation=token,
                          receipt_sink=receipt.append, admit_before=admit_before)
        finally:
            svc.nav.release_goal_reservation(token)
    return {
        "accepted": True,
        "mode": svc.modes.mode.value,
        "route": svc.nav.route_status(),
        "operation": receipt[0].model_dump(mode="json"),
        **({"map_grid_id": expected_grid} if expected_grid is not None else {}),
    }


@navigation_router.post("/navigation/goal/lease")
def navigation_goal_lease(body: GoalLeaseRequest, auth: AuthContext = Depends(operator),
                          svc: CoreServicesLike = Depends(get_services)):
    """D-550 10: renew a leased goal; 409 GOAL_LEASE_NOT_ACTIVE once it is not the active goal.
    D-760 9: 403 FORBIDDEN from a token other than the one that sent the goal."""
    svc.nav.renew_goal_lease(body.correlation_id, body.ttl_s, owner=auth.token_id,
                             **({"speed_grant": body.speed_grant.model_dump()} if body.speed_grant else {}))
    return {"renewed": True, "correlation_id": body.correlation_id, "ttl_s": body.ttl_s}


def _navigation_readback(svc, run_id=None):
    result = svc.nav.native_readback(run_id)
    idle = result.pop("idle_owner", None)
    if idle is None:
        return result
    mode_epoch = svc.modes.epoch
    dock = svc.docking.native_owner(wait=False)
    mission = getattr(svc, "loc_mission", None)
    station = getattr(svc, "station_docking", None)
    if (not dock or dock["owner_run_id"] is not None or svc.docking.active or svc.modes.mode is not Mode.IDLE
            or svc.command.manual_active or svc.line_follow.active or svc.swarm.active or svc.modes.motion_reserved
            or svc.calibration.current() is not None or (mission is not None and mission.owns_wheels)
            or (station is not None and station.session is not None) or mode_epoch != svc.modes.epoch
            or dock != svc.docking.native_owner(wait=False)):
        return result
    result["idle_owner"] = {**idle, "mode_epoch": mode_epoch, "dock_owner_generation": dock["owner_generation"]}
    return result


class NavigationCancelRequest(BaseModel):
    advance_generation: bool = Field(default=False, strict=True)


@navigation_router.post("/navigation/cancel")
def navigation_cancel(auth: AuthContext = Depends(operator),
                      svc: CoreServicesLike = Depends(get_services),
                      body: NavigationCancelRequest | None = None):
    receipt = []
    advance = body is not None and body.advance_generation
    svc.nav.cancel(source=f"api:{auth.role}", advance_generation=advance, receipt_sink=receipt.append)
    stop_ends_trip_lease(svc, auth)
    readback = _navigation_readback(svc)
    result = {"navigation": svc.nav.nav_state.value,
              "operation": receipt[0].model_dump(mode="json") if receipt else None}
    if advance:
        result["owner"] = readback["owner"]
    if not receipt and result["navigation"] == "IDLE":
        idle = readback.get("idle_owner")
        if idle:
            result["idle_owner"] = idle
            result["idle_observed_at"] = datetime.now(timezone.utc).isoformat()
    return result


@navigation_router.post("/navigation/cancel-scoped")
def navigation_cancel_scoped(body: ScopedNavigationCancelRequest,
                             auth: AuthContext = Depends(operator),
                             svc: CoreServicesLike = Depends(get_services)):
    receipt = []
    canceled = svc.nav.cancel(source=f"api:{auth.role}", expected_boot_id=body.expected_boot_id,
                              run_id=body.run_id, correlation_id=body.correlation_id,
                              receipt_sink=receipt.append)
    if not canceled:
        raise ApiError("NAVIGATION_SCOPE_CHANGED", 409, "the exact active navigation owner has changed")
    # Ending a current trip lease here could halt a replacement run admitted after this exact cancel.
    return {"navigation": svc.nav.nav_state.value,
            "operation": receipt[0].model_dump(mode="json") if receipt else None}


@navigation_router.post("/navigation/home")
def navigation_home(auth: AuthContext = Depends(operator),
                    svc: CoreServicesLike = Depends(get_services),
                    body: HomeRequest | None = None, request: Request = None):
    body = body or HomeRequest()
    admit_before = _admit_before(body, request)
    if body.lease_ttl_s is not None and body.correlation_id is None:
        raise ApiError("VALIDATION_ERROR", 400, "lease_ttl_s needs a correlation_id")
    require_manual_released(svc)
    if svc.line_follow.active:
        raise ApiError("LINE_FOLLOW_ACTIVE", 409,
                       "stop the selected line-follow mode before accepting a return-home request")
    TaskKind.RETURN_HOME.require(svc.capability)
    require_kept(svc, "navigation.return_home")
    with localized_start(svc):
        token = svc.nav.reserve_goal(expected_boot_id=body.expected_boot_id,
                                     expected_owner_generation=body.expected_owner_generation)
        receipt = []
        try:
            enter_navigation_mode(svc, auth)
            svc.nav.home(source=f"api:{auth.role}", correlation_id=body.correlation_id,
                         lease_ttl_s=body.lease_ttl_s, lease_owner=auth.token_id, reservation=token,
                         receipt_sink=receipt.append, admit_before=admit_before)
        finally:
            svc.nav.release_goal_reservation(token)
    return {"accepted": True, "mode": svc.modes.mode.value,
            "operation": receipt[0].model_dump(mode="json")}


@navigation_router.get("/navigation/state")
def navigation_state(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services),
                     run_id: UUID | None = None):
    readiness = svc.readiness.snapshot()
    return {
        **_navigation_readback(svc, run_id),
        "navigation": svc.nav.nav_state.value,
        "route": svc.nav.route_status(),
        "mapping_active": svc.nav.mapping_active,
        "map_id": svc.state.map_id,
        "map_generation": svc.state.map_generation.value,
        "readiness": {
            "required": readiness.required,
            "ready": readiness.ready,
            "missing": list(readiness.missing),
            "reason": readiness.reason,
        },
    }


@navigation_router.get("/navigation/path")
def navigation_path(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return svc.maps.get_path_snapshot()


class InitialPoseRequest(BaseModel):
    x: float
    y: float
    yaw: float = 0.0


@navigation_router.post("/localization/initialpose")
def initialpose(body: InitialPoseRequest, auth: AuthContext = Depends(operator),
                svc: CoreServicesLike = Depends(get_services)):
    TaskKind.NAVIGATE.require(svc.capability)
    check_grant(auth, NAVIGATE)
    # D-321 addendum: a pose reset mid-calibration corrupts the owner's odometry legs.
    require_calibration_owner(svc, auth, "initial pose")
    loc = getattr(svc, "localization", None)
    if loc is not None and loc.reporting:
        # D-395 P2-4: a D-395 robot gets the pose as `source: human` so its sensing
        # node runs the same 3 s check as every other injection (contract §1).
        send_decision(loc, loc.human_decision(body.x, body.y, body.yaw))
    elif svc.nav.executor is None:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, "localization executor unavailable")
    else:
        # A robot that predates D-395 has no node to receive a decision.
        svc.nav.executor.send_initial_pose(body.x, body.y, body.yaw)
    svc.events.publish(
        "localization.initialpose",
        source=f"api:{auth.role}",
        data={"x": body.x, "y": body.y, "yaw": body.yaw, "source": "human"},
    )
    return {"accepted": True}


slam_router = APIRouter(prefix="/api/v1/slam", tags=["slam"])


class SlamSaveRequest(BaseModel):
    name: str = Field(
        default="rosy_map",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )


@slam_router.post("/start")
def slam_start(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    require_calibration_owner(svc, auth, "slam start")
    svc.nav.start_mapping(source=f"api:{auth.role}")
    return {"mapping": True}


@slam_router.post("/stop")
def slam_stop(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    require_calibration_owner(svc, auth, "slam stop")
    svc.nav.stop_mapping(source=f"api:{auth.role}")
    return {"mapping": False}


@slam_router.post("/save")
def slam_save(body: SlamSaveRequest, auth: AuthContext = Depends(operator),
              svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    try:
        map_id = svc.nav.save_map(body.name, source=f"api:{auth.role}")
    except RuntimeError as exc:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, str(exc))
    return {"map_id": map_id}


@slam_router.post("/reset")
def slam_reset(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    svc.capability.require("slam")
    require_calibration_owner(svc, auth, "slam reset")
    svc.nav.reset_mapping(source=f"api:{auth.role}")
    return {"reset": True}
