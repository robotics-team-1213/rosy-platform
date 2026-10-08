"""D-143 line-follow mode selection and status API."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.grants import STUCK_DECIDE, require_grant
from core_api_web.api.v1.common import (
    apply_mode,
    admin,
    enter_navigation_mode,
    operator,
    require_calibration_owner,
    require_manual_released,
    localized_start,
    viewer,
)
from core_common.domain.tasks import TaskKind
from core_common.protocol.schemas import DockState, LanePerceptionRequest, LanePerceptionStatus, RobotMode
from core_api_web.api.deps import Mode
from core_api_web.api.deps import JunctionRefused, LineFollowMode, LineStuckRefused


line_follow_router = APIRouter(prefix="/api/v1/line-follow", tags=["line-follow"])


def _perception_reply(svc, command: str, auth=None, params=None) -> dict:
    from core_api_web.api.v1.host import _agent
    agent = _agent(svc)
    # A camera restart may await its bounded systemd startup; status stays short.
    if command == "lane_perception.set":
        agent.timeout_s = 75.0
    reply = agent.request(command, role="administrator" if auth else "viewer",
                          user_id=auth.token_id if auth else "", params=params)
    if not reply.ok:
        raise ApiError(reply.code, 409 if reply.reachable else 503,
                       reply.detail or "lane perception configuration unavailable")
    if not isinstance(reply.data, dict):
        raise ApiError("HOST_AGENT_UNREADABLE_RESPONSE", 503, "invalid lane perception response")
    try:
        result = LanePerceptionStatus.model_validate(reply.data).model_dump()
        cache = svc.vision.lane_perception
        if command == "lane_perception.set":
            cache.clear()  # discard every sample received before camera restart completed
        actual = cache.snapshot(paint_source=result["paint_source"],
                                model_revision=result["model_revision"], now=time.monotonic())
        result.update(actual)
        if actual["applied_paint_source"] is not None:
            result["reason"] = ("recent keeper receipt reports " + actual["applied_paint_source"]
                                + "; lane validity and permission to move are separate")
        return result
    except ValidationError as exc:
        raise ApiError("HOST_AGENT_UNREADABLE_RESPONSE", 503, "invalid lane perception response") from exc


@line_follow_router.get("/perception")
def get_lane_perception(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _perception_reply(svc, "lane_perception.status")


@line_follow_router.put("/perception")
def set_lane_perception(body: LanePerceptionRequest, auth: AuthContext = Depends(admin),
                        svc: CoreServicesLike = Depends(get_services)):
    # Caller checks prevent a knowingly unsafe request; Host Agent independently
    # rechecks the fresh, sensor-gated status file immediately before writing.
    with svc.modes.idle_admission:
        if svc.modes.mode is not Mode.IDLE or svc.line_follow.active:
            raise ApiError("ROBOT_MUST_BE_STOPPED", 409, "select IDLE and line-follow OFF first")
        if svc.calibration.current() is not None:
            raise ApiError("CALIBRATION_ACTIVE", 409, "finish calibration before changing perception")
        if not svc.modes.reserve_idle_motion():
            raise ApiError("MODE_CONFLICT", 409, "motion or another configuration update is active")
    try:
        return _perception_reply(svc, "lane_perception.set", auth, {"paint_source": body.paint_source})
    finally:
        svc.modes.release_idle_motion()


class LineFollowModeRequest(BaseModel):
    mode: str
    # D-344 §8: 있으면 POST /hold 로 이 시간 안에 계속 갱신해야 한다(운전자 확인).
    hold_s: Optional[float] = Field(default=None, gt=0, le=2.0)


class LineStuckDecisionRequest(BaseModel):
    """D-407 §2: the console's answer to one open stuck, bound to its id.

    YIELD (D-453) is one checked segment: turn `yield_turn_rad`, then creep `yield_m`.
    """

    stuck_id: str = Field(min_length=1, max_length=64)
    decision: str = Field(pattern="^(WAIT|RESUME|BACK_AND_RETRY|MANUAL|ABORT|YIELD)$")
    yield_m: Optional[float] = None
    yield_turn_rad: Optional[float] = None


def _status(svc: CoreServicesLike) -> dict:
    return svc.line_follow.status().model_dump()


@line_follow_router.get("")
def get_line_follow(_: AuthContext = Depends(viewer),
                    svc: CoreServicesLike = Depends(get_services)):
    return _status(svc)


@line_follow_router.put("/mode")
def set_line_follow_mode(body: LineFollowModeRequest,
                         auth: AuthContext = Depends(operator),
                         svc: CoreServicesLike = Depends(get_services)):
    try:
        selected = LineFollowMode(body.mode)
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, "unknown line-follow mode") from exc

    if selected is LineFollowMode.OFF:
        was_active = svc.line_follow.active
        status = svc.line_follow.stop()
        svc.command.clear_navigation()
        svc.state.set_line_follow(status)
        if was_active and svc.modes.mode is Mode.NAVIGATION:
            ok, reason = svc.modes.transition(Mode.IDLE)
            if not ok:
                raise ApiError("MODE_CONFLICT", 409, reason)
            svc.state.set_mode(RobotMode.IDLE)
        return _status(svc)

    # Turning line-follow OFF above only stops motion, so it stays open to all.
    require_manual_released(svc)
    require_calibration_owner(svc, auth, "line-follow mode change")
    if svc.safety.estop or svc.modes.is_emergency:
        raise ApiError("EMERGENCY_ACTIVE", 409, "release emergency stop first")
    if svc.modes.mode is Mode.DOCKING or svc.docking.state in (
            DockState.DOCKING, DockState.UNDOCKING):
        # 도킹이 바퀴를 쥐고 있다. 조용히 빼앗지 않는다 — 먼저 취소하게 한다.
        raise ApiError("DOCKING_ACTIVE", 409, "cancel docking first")
    if svc.nav.mapping_active:
        raise ApiError("MAPPING_ACTIVE", 409, "mapping session owns navigation")

    if selected is LineFollowMode.IR_LINE and svc.line_follow.mode is LineFollowMode.CAMERA_LINE:
        # D-313: IR is an explicit recovery selection after a latched camera
        # failure. The normal CORE safety policy must also be bound to the
        # calibrated sensor-only worker; its command-time checks remain the
        # final authority for fresh IR/LiDAR evidence.
        camera_status = svc.line_follow.status()
        adapter = svc.control_adapter
        if (camera_status.state != "LOST"
                or camera_status.reason != "camera_reselection_required"
                or adapter is None
                or not getattr(adapter, "enabled", False)
                or not getattr(adapter, "calibration_revision", None)
                or not svc.safety.policy_required):
            raise ApiError(
                "IR_FALLBACK_NOT_READY", 409,
                "camera failure must be latched and calibrated IR/LiDAR safety policy must be active",
            )
        ir_ready, ir_reasons = svc.line_follow.ir_fallback_readiness()
        if not ir_ready:
            raise ApiError(
                "IR_FALLBACK_NOT_READY", 409,
                "fresh IR line evidence must match the CORE-configured calibration revision",
                detail={"reasons": list(ir_reasons)},
            )

    # D-344 §7: 차선 추종은 Nav2 가 아니라 구동을 요구한다. 증거 검사는 LineFollowManager 가 한다.
    TaskKind.MOVE.require(svc.capability)
    with localized_start(svc):
        svc.nav.cancel(source=f"line_follow:{auth.role}")
        svc.command.clear_navigation()
        enter_navigation_mode(svc, auth)
        status = svc.line_follow.set_mode(selected, hold_s=body.hold_s)
    svc.state.set_line_follow(status)
    return _status(svc)


@line_follow_router.post("/hold")
def hold_line_follow(auth: AuthContext = Depends(operator),
                     svc: CoreServicesLike = Depends(get_services)):
    """운전자가 "진행"을 누르고 있다(D-344 §8). hold 세션이 아니면 409."""
    require_calibration_owner(svc, auth, "line-follow hold")
    if not svc.line_follow.hold():
        raise ApiError("LINE_FOLLOW_NOT_HELD", 409, "no active hold-to-run line-follow session")
    return _status(svc)


class LineJunctionRequest(BaseModel):
    """D-494 decision 4: what to do at the next junction (Fleet trip loop)."""

    action: str = Field(pattern="^(straight|left|right|stop|bend)$")
    place_id: str = Field(min_length=1, max_length=128)
    stop_after_m: Optional[float] = Field(default=None, ge=0, le=2.0)
    expires_s: float = Field(gt=0, le=30)
    # D-495: bounded turn for left (+) / right (-); without it left/right stay unresolved.
    turn_deg: Optional[float] = Field(default=None, ge=-150, le=150)
    advance_m: Optional[float] = Field(default=None, ge=0, le=0.30)
    # D-507 2: the map's expectation, sent only to a robot announcing junction_pivot.
    map_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    expect_in_m: Optional[float] = Field(default=None, gt=0, le=2.0)
    expect_tol_m: Optional[float] = Field(default=None, gt=0, le=0.30)
    # signed (2026-10-08): negative when the measured cross line is past the place point.
    pivot_past_line_m: Optional[float] = Field(default=None, ge=-0.30, le=0.30)
    # D-507 addendum (2026-10-08): a site-map bend, sent only to a robot announcing lane_bend.
    bend_in_m: Optional[float] = Field(default=None, gt=0, le=2.0)
    bend_tol_m: Optional[float] = Field(default=None, gt=0, le=0.30)
    bend_radius_m: Optional[float] = Field(default=None, gt=0, le=0.5)


def _expect(body: LineJunctionRequest):
    """D-507 2: the optional fields as one dict, or None for an old client (behaviour unchanged)."""
    fields = dict(map_id=body.map_id, expect_in_m=body.expect_in_m, expect_tol_m=body.expect_tol_m,
                  pivot_past_line_m=body.pivot_past_line_m, bend_in_m=body.bend_in_m,
                  bend_tol_m=body.bend_tol_m, bend_radius_m=body.bend_radius_m)
    return fields if any(v is not None for v in fields.values()) else None


@line_follow_router.post("/junction")
def set_line_junction(body: LineJunctionRequest, auth: AuthContext = Depends(operator),
                      svc: CoreServicesLike = Depends(get_services)):
    """D-494 decision 4 / D-495. Never changes mode; the turn maneuver runs in CORE's own tick.
    "Seat" is the existing vocabulary (D-460): operator token, manual control released and the
    calibration lease, as the other motion endpoints. CAMERA_LINE only (IR has no junctions)."""
    if body.stop_after_m is not None and body.action != "stop":
        raise ApiError("VALIDATION_ERROR", 400, "stop_after_m belongs to stop")
    if body.turn_deg is not None and body.action != "bend" and (
            body.action not in ("left", "right") or body.turn_deg == 0
            or (body.turn_deg > 0) != (body.action == "left")):
        raise ApiError("VALIDATION_ERROR", 400, "turn_deg is left (+) or right (-) and not 0")
    bend = (body.bend_in_m, body.bend_tol_m, body.bend_radius_m)
    if body.action == "bend" and (
            None in bend or body.map_id is None or body.turn_deg is None or body.turn_deg == 0
            or abs(body.turn_deg) > 90 or body.expect_in_m is not None or body.expect_tol_m is not None
            or body.pivot_past_line_m is not None or body.advance_m is not None):
        raise ApiError("VALIDATION_ERROR", 400, "bend needs turn_deg (0 < |turn_deg| <= 90), map_id, "
                       "bend_in_m, bend_tol_m and bend_radius_m, and no window, pivot or advance")
    if body.action != "bend" and any(v is not None for v in bend):
        raise ApiError("VALIDATION_ERROR", 400, "bend_in_m, bend_tol_m and bend_radius_m belong to bend")
    if body.advance_m is not None and body.turn_deg is None:
        raise ApiError("VALIDATION_ERROR", 400, "advance_m belongs to a turn")
    if (body.expect_in_m is None) != (body.expect_tol_m is None):
        raise ApiError("VALIDATION_ERROR", 400, "expect_in_m and expect_tol_m come together")
    if body.pivot_past_line_m is not None and (body.action == "stop" or (
            body.action != "straight" and body.turn_deg is None)):
        raise ApiError("VALIDATION_ERROR", 400, "pivot_past_line_m belongs to straight or a turn")
    require_manual_released(svc)
    require_calibration_owner(svc, auth, "line-follow junction")
    try:
        result = svc.line_follow.set_junction(body.action, body.place_id, body.expires_s,
                                              body.stop_after_m, body.turn_deg, body.advance_m,
                                              expect=_expect(body))
    except JunctionRefused as exc:
        raise ApiError(exc.code, 409, str(exc)) from exc
    svc.state.set_line_follow(svc.line_follow.status())
    return {"accepted": result[0], "junction_seq": result[1], "state": result[2]}


@line_follow_router.post("/stuck/decision")
def decide_line_stuck(body: LineStuckDecisionRequest,
                      auth: AuthContext = Depends(require_grant(STUCK_DECIDE)),
                      svc: CoreServicesLike = Depends(get_services)):
    """D-407 §2 / D-453: WAIT | RESUME | BACK_AND_RETRY | MANUAL | ABORT | YIELD."""
    if body.decision == "MANUAL" and auth.role == "stuck_resolver":
        raise ApiError("FORBIDDEN", 403, "MANUAL is a human decision (D-438)")
    if body.decision == "YIELD" and (body.yield_m is None or body.yield_turn_rad is None):
        raise ApiError("VALIDATION_ERROR", 400, "YIELD needs yield_m and yield_turn_rad")
    if body.decision != "YIELD" and (body.yield_m is not None or body.yield_turn_rad is not None):
        raise ApiError("VALIDATION_ERROR", 400, "yield_m and yield_turn_rad belong to YIELD")
    if body.decision in ("RESUME", "BACK_AND_RETRY", "MANUAL", "YIELD"):
        # Answers that move the wheels (or hand them to a driver, MANUAL) respect the
        # calibration lease like POST /mode does; checked before the stuck is consumed.
        # WAIT holds and ABORT goes to IDLE, so they stay open like e-stop.
        require_calibration_owner(svc, auth, "line-follow stuck decision")
    if body.decision in ("RESUME", "BACK_AND_RETRY", "YIELD") and (
            svc.safety.estop or svc.modes.is_emergency):
        raise ApiError("EMERGENCY_ACTIVE", 409, "release emergency stop first")
    try:
        outcome = svc.line_follow.stuck_decision(
            body.stuck_id, body.decision, by=auth.role, principal_ref=auth.principal_ref,
            yield_m=body.yield_m, yield_turn_rad=body.yield_turn_rad)
    except LineStuckRefused as exc:
        raise ApiError(exc.code, 409, str(exc)) from exc
    if outcome in ("manual", "idle"):
        # Line-follow already stopped under its lock; the rest is POST /mode (nav and swarm
        # cancel on MANUAL, mode.changed, state).
        svc.command.clear_navigation()
        apply_mode(svc, auth, Mode.MANUAL if outcome == "manual" else Mode.IDLE)
        svc.state.set_line_follow(svc.line_follow.status())
    else:
        svc.state.set_line_follow(svc.line_follow.status())
    return {**_status(svc), "outcome": outcome}
