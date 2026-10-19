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
def policy(auth: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).policy, auth.token_id)


@arm_router.post('/observations')
def observation(body: ArmObservationRequest, auth: AuthContext = Depends(operator),
                svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).observation, auth.token_id, body.policy_revision)


@arm_router.post('/actions', status_code=202)
def action(body: ArmActionRequest, auth: AuthContext = Depends(operator),
           svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).submit, auth.token_id, **body.model_dump())


@arm_router.post('/stop')
def stop(_: AuthContext = Depends(operator), svc: CoreServicesLike = Depends(get_services)):
    return _call(_port(svc).stop)
