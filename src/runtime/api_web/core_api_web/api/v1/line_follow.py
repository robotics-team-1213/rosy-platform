"""D-143 line-follow mode selection and status API."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from typing import Optional

from pydantic import BaseModel, Field

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import (
    apply_mode,
    enter_navigation_mode,
    operator,
    require_calibration_owner,
    localized_start,
    viewer,
)
from core_common.domain.tasks import TaskKind
from core_common.protocol.schemas import DockState, RobotMode
from core_api_web.api.deps import Mode
from core_api_web.api.deps import LineFollowMode, LineStuckRefused


line_follow_router = APIRouter(prefix="/api/v1/line-follow", tags=["line-follow"])


class LineFollowModeRequest(BaseModel):
    mode: str
    # D-344 §8: 있으면 POST /hold 로 이 시간 안에 계속 갱신해야 한다(운전자 확인).
    hold_s: Optional[float] = Field(default=None, gt=0, le=2.0)


class LineStuckDecisionRequest(BaseModel):
    """D-407 §2: the console's answer to one open stuck, bound to its id."""

    stuck_id: str = Field(min_length=1, max_length=64)
    decision: str = Field(pattern="^(WAIT|RESUME|BACK_AND_RETRY|MANUAL|ABORT)$")


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


@line_follow_router.post("/stuck/decision")
def decide_line_stuck(body: LineStuckDecisionRequest,
                      auth: AuthContext = Depends(operator),
                      svc: CoreServicesLike = Depends(get_services)):
    """D-407 §2: WAIT | RESUME | BACK_AND_RETRY | MANUAL | ABORT for the open stuck id."""
    if body.decision in ("RESUME", "BACK_AND_RETRY", "MANUAL"):
        # Answers that move the wheels (or hand them to a driver, MANUAL) respect the
        # calibration lease like POST /mode does; checked before the stuck is consumed.
        # WAIT holds and ABORT goes to IDLE, so they stay open like e-stop.
        require_calibration_owner(svc, auth, "line-follow stuck decision")
    if body.decision in ("RESUME", "BACK_AND_RETRY") and (
            svc.safety.estop or svc.modes.is_emergency):
        raise ApiError("EMERGENCY_ACTIVE", 409, "release emergency stop first")
    try:
        outcome = svc.line_follow.stuck_decision(
            body.stuck_id, body.decision, by=auth.role, token_id=auth.token_id)
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
