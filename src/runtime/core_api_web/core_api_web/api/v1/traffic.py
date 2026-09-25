"""Semantic road policy supervision and simulation-only signal control."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from core_api_web.api.deps import (
    AuthContext,
    CoreServicesLike,
    Mode,
    get_services,
)
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, viewer


traffic_router = APIRouter(prefix="/api/v1/traffic", tags=["traffic"])


class TrafficPolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Optional[str] = None
    map_id: Optional[str] = None
    scene_revision: Optional[str] = None
    policy_revision: Optional[str] = None
    approach_distance_m: Optional[float] = None
    stop_distance_m: Optional[float] = None
    stop_dwell_s: Optional[float] = None
    stale_after_s: Optional[float] = None
    min_confidence: Optional[float] = None
    proceed_speed_scale: Optional[float] = None


class SimulationSignalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colour: str


def _actor(auth: AuthContext) -> str:
    return f"{auth.role}:{auth.token_id}"


def _readback(svc: CoreServicesLike) -> dict:
    return {
        "status": svc.traffic_policy.status().model_dump(),
        **svc.traffic_policy.configuration(),
    }


def _robot_stopped(svc: CoreServicesLike) -> bool:
    snapshot = svc.state.snapshot()
    velocity = snapshot.velocity
    velocity_evidence = snapshot.evidence.get("velocity")
    fresh_velocity = bool(
        velocity_evidence
        and velocity_evidence.evidence.value == "fresh"
    )
    stationary = (
        abs(float(velocity.linear)) <= 0.005
        and abs(float(velocity.angular)) <= 0.01
    )
    inert_mode = svc.modes.mode in (Mode.IDLE, Mode.EMERGENCY)
    stop_proven = bool(svc.safety.estop) or (fresh_velocity and stationary)
    return stop_proven and inert_mode and not svc.line_follow.active


@traffic_router.get("")
def get_traffic_policy(_: AuthContext = Depends(viewer),
                       svc: CoreServicesLike = Depends(get_services)):
    return _readback(svc)


@traffic_router.post("/policy/stage")
def stage_traffic_policy(body: TrafficPolicyPatch,
                         auth: AuthContext = Depends(operator),
                         svc: CoreServicesLike = Depends(get_services)):
    patch = body.model_dump(exclude_none=True, exclude_unset=True)
    try:
        svc.traffic_policy.stage(patch, actor=_actor(auth))
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, str(exc)) from exc
    return _readback(svc)


@traffic_router.post("/policy/apply")
def apply_traffic_policy(auth: AuthContext = Depends(operator),
                         svc: CoreServicesLike = Depends(get_services)):
    if not _robot_stopped(svc):
        raise ApiError(
            "ROBOT_MUST_BE_STOPPED", 409,
            "traffic policy can only be applied while the robot is stopped",
        )
    try:
        svc.command.clear_navigation()
        svc.traffic_policy.apply_staged(actor=_actor(auth))
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, str(exc)) from exc
    svc.state.set_traffic_policy(svc.traffic_policy.status())
    return _readback(svc)


@traffic_router.put("/simulation/signal")
def set_simulation_signal(body: SimulationSignalRequest,
                          auth: AuthContext = Depends(operator),
                          svc: CoreServicesLike = Depends(get_services)):
    try:
        return svc.traffic_policy.set_simulation_signal(
            body.colour, actor=_actor(auth))
    except RuntimeError as exc:
        raise ApiError("CAPABILITY_NOT_SUPPORTED", 501, str(exc)) from exc
    except ValueError as exc:
        raise ApiError("VALIDATION_ERROR", 400, str(exc)) from exc
