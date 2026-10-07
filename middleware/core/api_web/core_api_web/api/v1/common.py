"""core_api_web.api.v1.common — 라우터 모듈이 공유하는 역할 의존성과 모드 전이.

라우터를 파일로 나누면서 생기는 유일한 공유 지점이다. 여기에 엔드포인트를
두지 않는다 — 여기 있는 것은 여러 도메인이 같은 규칙을 쓰기 때문에 있는 것뿐이다.
"""

from __future__ import annotations

import contextlib
import logging
import math
from typing import Iterator

from core_api_web.api.deps import AuthContext, require_role, CoreServicesLike
from core_api_web.api.errors import ApiError
from core_api_web.api.deps import Mode, NavigationError
from core_common.domain.capabilities import runtime_truth
from core_common.domain.tasks import TaskKind
from core_common.protocol.schemas import RobotMode
from core_features.power.battery import STALE_AFTER_S

viewer = require_role("viewer")
operator = require_role("operator")
admin = require_role("administrator")


def battery_health(svc) -> dict:
    """`BatteryMonitor.health()`, or "missing" where no monitor is wired (D-502)."""
    health = getattr(getattr(svc, "battery", None), "health", None)
    if health is None:
        return {"evidence": "missing", "sample_age_s": None, "stale_after_s": STALE_AFTER_S,
                "level": None, "percent": None}
    return health()


# Stop evidence (D-411 addendum 17/18). A parked robot's velocity flips between 0 and one encoder
# tick per odometry period; "still" means at most two ticks per period. The geometry comes from the
# robot package's ``odometry`` config section (URDF nominal, refined per robot), never from here.
STILL_LINEAR_MPS = 0.005
#: Strict fallback when the robot package gives no odometry geometry: no tick-noise allowance.
STILL_ANGULAR_FALLBACK_RPS = 0.01
_log = logging.getLogger(__name__)
_warned_no_odometry = False


def still_angular_rps(config) -> float:
    """Two encoder ticks per odometry period, as angular speed; strict fallback if unconfigured."""
    global _warned_no_odometry
    odo = (config or {}).get("odometry") or {}
    try:
        tick_m = 2 * math.pi * float(odo["wheel_radius_m"]) / float(odo["encoder_ticks_per_rev"])
        limit = 2 * tick_m / float(odo["wheel_separation_m"]) * float(odo["publish_hz"])
        if math.isfinite(limit) and limit > 0:
            return limit
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    if not _warned_no_odometry:
        _warned_no_odometry = True
        _log.warning("config odometry section missing or invalid; stop evidence uses strict %s rad/s",
                     STILL_ANGULAR_FALLBACK_RPS)
    return STILL_ANGULAR_FALLBACK_RPS


def robot_still(svc: CoreServicesLike) -> bool:
    """E-Stop, or fresh velocity within the tick-noise floor. Shared by recordings and traffic."""
    if svc.safety.estop:
        return True
    snapshot = svc.state.snapshot()
    evidence = snapshot.evidence.get("velocity")
    return bool(evidence and evidence.evidence.value == "fresh"
                and abs(float(snapshot.velocity.linear)) <= STILL_LINEAR_MPS
                and abs(float(snapshot.velocity.angular)) <= still_angular_rps(svc.config))


def require_kept(svc: CoreServicesLike, flag: str) -> None:
    """Reject a write that the live CAP-001 readout currently withholds."""
    reason = runtime_truth(svc.config, svc.state, svc.readiness).reasons.get(flag)
    if reason:
        raise ApiError(
            "CAPABILITY_WITHHELD", 409, f"{flag} withheld: {reason}",
            detail={"capability": flag, "reason": reason},
        )


def require_localized(svc: CoreServicesLike) -> None:
    """D-395 §2: autonomous driving only from LOCALIZED.

    A robot that predates D-395 reports no localization state; it keeps today's
    behaviour (contract open question 2).
    """
    loc = getattr(svc, "localization", None)
    status = loc.status() if loc is not None else None
    if status is None or (status.state.value == "LOCALIZED" and status.pose_frame.value == "map"):
        return
    # An odom-frame pose is not one Fleet trusts either (D-395 10), even when LOCALIZED.
    raise ApiError(
        "NOT_LOCALIZED", 409,
        f"robot localization is {status.state.value} in the {status.pose_frame.value} frame",
        detail={"state": status.state.value, "pose_frame": status.pose_frame.value,
                "reason": status.reason},
    )


@contextlib.contextmanager
def localized_start(svc: CoreServicesLike) -> Iterator[None]:
    """Check LOCALIZED and dispatch the start under the localization gate.

    The leave-LOCALIZED halt takes the same gate, so it runs either before the
    check (which then refuses) or after the start (which it then stops) — never
    in between.
    """
    loc = getattr(svc, "localization", None)
    with (loc.gate if loc is not None else contextlib.nullcontext()):
        require_localized(svc)
        yield


def require_calibration_owner(svc: CoreServicesLike, auth: AuthContext, action: str) -> None:
    """D-321 addendum: while a calibration lease is alive only its owner drives.

    E-stop is never routed through here — anyone can always stop the robot.
    """
    if getattr(svc.modes, "motion_reserved", False):
        raise ApiError("MODE_CONFLICT", 409, "lane perception configuration is being applied")
    session = svc.calibration.blocking(auth.token_id)
    if session is not None:
        raise ApiError(
            "CALIBRATION_ACTIVE", 409,
            f"{action} refused: calibration '{session['label']}' is in progress",
            detail={"session": session},
        )


def apply_mode(svc: CoreServicesLike, auth: AuthContext, new_mode: Mode) -> None:
    """`POST /mode` semantics, shared with the D-407 MANUAL / ABORT stuck answers."""
    if new_mode is Mode.NAVIGATION:
        require_manual_released(svc)
    if new_mode is not Mode.IDLE:
        # IDLE only stops the robot, so like e-stop it stays open to everyone.
        require_calibration_owner(svc, auth, "mode change")
    if svc.line_follow.active:
        status = svc.line_follow.stop()
        svc.command.clear_navigation()
        svc.state.set_line_follow(status)
    if new_mode is Mode.NAVIGATION:
        TaskKind.NAVIGATE.require(svc.capability)
        if svc.modes.mode is not Mode.NAVIGATION:
            svc.command.clear_navigation()
    if new_mode is Mode.MANUAL:
        # 조건 없이 부른다. `cancel()` 은 거둘 것이 없으면 스스로 돌아서고,
        # nav_state 만 보면 아직 목표를 내지 않은 군집 세션을 놓친다 —
        # 그러면 수동으로 넘어간 뒤에도 대형이 무장된 채로 남는다.
        svc.nav.cancel(source=f"mode:{auth.role}")
    ok, reason = svc.modes.transition(new_mode)
    if not ok:
        raise ApiError("MODE_CONFLICT", 409, reason)
    svc.state.set_mode(RobotMode(new_mode.value))
    svc.events.publish("mode.changed", source="api",
                       data={"from": "api", "to": new_mode.value, "by": auth.role})


def require_manual_released(svc: CoreServicesLike) -> None:
    """D-442 U1: refuse autonomy before changing any live manual state."""
    if svc.modes.mode is Mode.MANUAL and svc.command.manual_active:
        raise ApiError("MODE_CONFLICT", 409, "manual control is active")


def enter_navigation_mode(svc: CoreServicesLike, auth: AuthContext) -> None:
    """D-2: Nav2 velocity only reaches the wheels in NAVIGATION."""
    # Nav goal, return-home, swarm follow and line-follow all drive through here.
    require_manual_released(svc)
    require_calibration_owner(svc, auth, "navigation")
    if svc.line_follow.active:
        status = svc.line_follow.stop()
        svc.command.clear_navigation()
        svc.state.set_line_follow(status)
    try:
        svc.nav.require_ready()
    except NavigationError as exc:
        raise ApiError(exc.code, 503, str(exc)) from exc
    if svc.modes.mode is Mode.NAVIGATION:
        return
    svc.command.clear_navigation()
    ok, reason = svc.modes.transition(Mode.NAVIGATION)
    if not ok:
        raise ApiError("MODE_CONFLICT", 409, reason)
    svc.state.set_mode(RobotMode.NAVIGATION)
    svc.events.publish(
        "mode.changed",
        source="api",
        data={"from": "api", "to": Mode.NAVIGATION.value, "by": auth.role},
    )
