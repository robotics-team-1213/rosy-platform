"""CORE-mediated policy I/O; execution stays on the installed OMX owner's port."""
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from core_api_web.api.deps import AuthContext, CoreServicesLike, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator

arm_router = APIRouter(prefix='/api/v1/arm', tags=['arm'])
Revision = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]
Target = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class ArmObservationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    policy_revision: Revision


class ArmActionRequest(ArmObservationRequest):
    observation_id: str = Field(min_length=1, max_length=128)
    positions: dict[str, Target] = Field(min_length=1, max_length=8)


Text = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^\S(?:.*\S)?$')]  # trimmed, not whitespace-only


class ArmLeaseGrant(BaseModel):
    """Fleet's lease push (D-1024 3). ``ttl_s`` is converted to the owner's monotonic clock on arrival."""
    model_config = ConfigDict(extra='forbid', strict=True)
    lease_id: Text
    episode_id: Text
    workcell_id: Text
    policy_digest: Revision
    rig_revision: Text
    calibration_revision: Text
    ttl_s: float = Field(ge=0.001, le=2.0, allow_inf_nan=False)
    seq: int = Field(ge=1, le=2**53)
    window_remaining_s: float = Field(gt=0, le=1800.0, allow_inf_nan=False)


class ArmHoldRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: Annotated[str, Field(min_length=1, max_length=96, pattern=r'^\S(?:.*\S)?$')]


def arm_caller(auth: AuthContext = Depends(operator)):
    """D-807 2: the arm policy routes are for machine operator tokens, never a human Account session or a dev token."""
    if getattr(auth, 'account', None) is not None or getattr(auth, 'shared_dev', False):
        raise ApiError('FORBIDDEN', 403, 'arm policy routes need a machine operator token')
    return auth


def _port(svc):
    port = getattr(svc, 'arm_policy', None)
    if port is None:
        raise ApiError('ARM_POLICY_UNAVAILABLE', 503, 'no authorized arm policy session installed')
    return port


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except PermissionError as exc:
        raise ApiError('ARM_POLICY_FORBIDDEN', 403, str(exc)) from exc
    except BlockingIOError as exc:
        raise ApiError('ARM_POLICY_BUSY', 409, str(exc)) from exc
    except ValueError as exc:
        raise ApiError('ARM_POLICY_CONFLICT', 409, str(exc)) from exc


@arm_router.get('/policy')
def policy(auth: AuthContext = Depends(arm_caller), svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).policy, auth.token_id)


@arm_router.post('/observations')
def observation(body: ArmObservationRequest, auth: AuthContext = Depends(arm_caller),
                svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).observation, auth.token_id, body.policy_revision)


@arm_router.post('/actions', status_code=202)
def action(body: ArmActionRequest, auth: AuthContext = Depends(arm_caller),
           svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).submit, auth.token_id, **body.model_dump())


@arm_router.post('/stop')
def stop(_: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).stop)


@arm_router.post('/lease')
def lease(body: ArmLeaseGrant, auth: AuthContext = Depends(arm_caller), svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).deliver_lease, auth.token_id, body.model_dump())


@arm_router.post('/hold')
def hold(body: ArmHoldRequest, auth: AuthContext = Depends(arm_caller), svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).hold, auth.token_id, body.reason)
