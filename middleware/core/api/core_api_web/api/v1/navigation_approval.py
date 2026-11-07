"""D-986: navigation re-approval over REST, the one path for tools, agents and the console card."""
from fastapi import APIRouter, Depends

from core_api_web.api.deps import AuthContext, CoreServicesLike, Mode, TrialRefused, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import apply_mode, operator, require_calibration_owner, robot_still, viewer
from core_api_web.api.v1.control import TeleopRequest, apply_teleop
from core_common.protocol.schemas import NavigationApprovalSealRequest, NavigationApprovalTrialRequest

navigation_approval_router = APIRouter(prefix="/api/v1/navigation/approval", tags=["navigation"])


def _host(svc: CoreServicesLike, command: str, auth=None, params=None) -> dict:
    from core_api_web.api.v1.host import _agent
    agent = _agent(svc)
    agent.timeout_s = 20.0
    # Each route has already proved the caller's role; the agent only needs its level.
    reply = agent.request(command, role="operator" if auth else "viewer",
                          user_id=auth.token_id if auth else "", params=params)
    if not reply.ok:
        raise ApiError(reply.code, 409 if reply.reachable else 503,
                       reply.detail or "navigation approval is unavailable")
    if not isinstance(reply.data, dict):
        raise ApiError("HOST_AGENT_UNREADABLE_RESPONSE", 503, "invalid navigation approval response")
    return reply.data


def _approver(auth: AuthContext) -> str:
    """An approval names who stands behind it; the public development tokens name nobody."""
    if auth.shared_dev:
        raise ApiError("FORBIDDEN", 403, "navigation approval requires a personal login")
    return auth.principal_ref


def _require_unplugged(svc: CoreServicesLike) -> None:
    """Trials run unplugged and watched. No battery reading means nobody knows, and that refuses too."""
    battery = svc.state.snapshot().battery_status
    if battery.charging is True:
        raise ApiError("CHARGING", 409, "unplug the charger before measuring")
    if battery.charging is not False or battery.filtered_voltage is None:
        raise ApiError("CHARGING_UNKNOWN", 409, "the battery state is unknown: cannot confirm the robot is unplugged")


def _refused(exc: TrialRefused) -> ApiError:
    return ApiError(exc.code, 409, exc.detail)


def _view(svc: CoreServicesLike, data: dict) -> dict:
    return {**data, "trial": svc.approval_trials.status()}


@navigation_approval_router.get("")
def read(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    return _view(svc, _host(svc, "navigation_approval.status"))


@navigation_approval_router.post("/begin")
def begin(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    _approver(auth)
    require_calibration_owner(svc, auth, "navigation approval")
    _require_unplugged(svc)
    if svc.modes.mode not in (Mode.IDLE, Mode.MANUAL) or not robot_still(svc):
        raise ApiError("MODE_CONFLICT", 409, "the robot must be stopped and out of navigation")
    return _view(svc, _host(svc, "navigation_approval.begin", auth))


@navigation_approval_router.post("/cancel")
def cancel(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    _approver(auth)
    svc.approval_trials.abort("cancelled")
    return _view(svc, _host(svc, "navigation_approval.cancel", auth))


@navigation_approval_router.post("/seal")
def seal(body: NavigationApprovalSealRequest, auth: AuthContext = Depends(operator),
         svc: CoreServicesLike = Depends(get_services)):
    approver = _approver(auth)
    if svc.approval_trials.active:
        raise ApiError("TRIAL_ACTIVE", 409, "a trial is still running")
    return _view(svc, _host(svc, "navigation_approval.seal", auth,
                            {"operator": approver, "test_surface": body.test_surface}))


@navigation_approval_router.post("/navigation-start")
def navigation_start(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    _approver(auth)
    return _view(svc, _host(svc, "navigation_approval.start_navigation", auth))


@navigation_approval_router.post("/trial/start")
def trial_start(body: NavigationApprovalTrialRequest, auth: AuthContext = Depends(operator),
                svc: CoreServicesLike = Depends(get_services)):
    owner = _approver(auth)
    require_calibration_owner(svc, auth, "navigation approval trial")
    _require_unplugged(svc)
    state = _host(svc, "navigation_approval.status")
    if state["phase"] != "MEASURING" or state["runtime_mode"] != "motor":
        raise ApiError("APPROVAL_NOT_MEASURING", 409, "begin the approval before running a trial")
    if svc.safety.estop:
        raise ApiError("EMERGENCY_ACTIVE", 409, "release the E-Stop on purpose before a trial")
    if svc.modes.mode is not Mode.MANUAL:
        apply_mode(svc, auth, Mode.MANUAL)
    try:
        clearance = svc.approval_trials.start(body.direction, body.stop_cause, owner, body.rear_confirmed)
    except TrialRefused as exc:
        raise _refused(exc) from exc
    return {"clearance": clearance, **svc.approval_trials.status()}


@navigation_approval_router.post("/trial/hold")
def trial_hold(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    owner = _approver(auth)
    try:
        svc.approval_trials.hold(owner, lambda linear, angular: apply_teleop(
            TeleopRequest(linear=linear, angular=angular), auth, svc))
    except TrialRefused as exc:
        raise _refused(exc) from exc
    return {"accepted": True}


@navigation_approval_router.post("/trial/stop")
def trial_stop(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    try:
        svc.approval_trials.stop(_approver(auth))
    except TrialRefused as exc:
        raise _refused(exc) from exc
    return svc.approval_trials.status()
