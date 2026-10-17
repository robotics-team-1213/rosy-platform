"""D-772 Fleet-owned station evidence and local native operation handover."""
from fastapi import APIRouter, Depends

from core_api_web.api.deps import AuthContext, CoreServicesLike, DockError, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import viewer, operator, localized_start, require_calibration_owner
from core_common.domain.tasks import TaskKind
from core_common.protocol.station_charging import (
    StationTargetBinding, StationMotionCommand, StationObservation, StationTargetStatus, StationReturnPermit,
    StationDeparturePermit, StationDepartureReceipt,
)

station_docking_router = APIRouter(prefix='/api/v1/docking', tags=['station-docking'])


def fleet_owner(svc, auth):
    configured = ((svc.config.get('docking') or {}).get('station') or {}).get('fleet_principals')
    if (auth.shared_dev or not isinstance(configured, list)
            or auth.principal_ref not in configured):
        raise ApiError('FORBIDDEN', 403, 'station evidence requires a configured Fleet principal')
    owner = getattr(svc, 'station_docking', None)
    if owner is None:
        raise ApiError('CAPABILITY_NOT_SUPPORTED', 501, 'station control profile is disabled')
    try:
        owner.require_principal(auth.principal_ref)
    except ValueError as exc:
        raise ApiError('FORBIDDEN', 403, str(exc)) from exc
    return owner


def conflict(exc):
    code = exc.code if isinstance(exc, DockError) else str(exc)
    if code == 'STATION_PRINCIPAL_MISMATCH':
        return ApiError('FORBIDDEN', 403, code)
    if (not isinstance(exc, DockError) and code not in ('OWNER_GENERATION_CHANGED', 'BOOT_ID_CHANGED')
            and not code.startswith('STATION_')):
        code = 'STATION_BINDING_INVALID'
    return ApiError(code, 409, str(exc))


@station_docking_router.get('/station-target', response_model=StationTargetStatus)
def station_target(_: AuthContext = Depends(viewer), svc: CoreServicesLike = Depends(get_services)):
    owner = getattr(svc, 'station_docking', None)
    if owner is None:
        raise ApiError('CAPABILITY_NOT_SUPPORTED', 501, 'station control profile is disabled')
    return owner.readback()


@station_docking_router.put('/station-target')
def bind_target(body: StationTargetBinding, auth: AuthContext = Depends(operator),
                svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    require_calibration_owner(svc, auth, 'station binding')
    try:
        return owner.bind(body.session, body.target, body.observation_scope,
                          principal_id=auth.principal_ref, expected_boot_id=body.expected_boot_id,
                          expected_owner_generation=body.expected_owner_generation).model_dump()
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.post('/station-observation')
def station_observation(body: StationObservation, auth: AuthContext = Depends(operator),
                        svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    try:
        return {'accepted': owner.ingest(body, received_at=owner.clock(), principal_id=auth.principal_ref)}
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.post('/station-dock')
def station_dock(body: StationMotionCommand, auth: AuthContext = Depends(operator),
                 svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    TaskKind.DOCK.require(svc.capability)
    require_calibration_owner(svc, auth, 'station docking')
    try:
        with localized_start(svc):
            # Checked again under the owner lock by start_docking.
            operation = owner.start_docking(
                session_id=body.session_id, correlation_id=body.correlation_id,
                expected_boot_id=body.expected_boot_id, expected_owner_generation=body.expected_owner_generation,
                principal_id=auth.principal_ref)
        return {'operation': operation.model_dump(mode='json')}
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.put('/station-return', response_model=StationTargetStatus)
def station_return(body: StationReturnPermit, auth: AuthContext = Depends(operator),
                   svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    require_calibration_owner(svc, auth, 'station return')
    try:
        owner.grant_return(body, principal_id=auth.principal_ref, owner_id=auth.token_id)
        return owner.readback()
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.post('/station-stop')
def station_stop(body: StationMotionCommand, auth: AuthContext = Depends(operator),
                 svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    try:
        owner.stop_docking(body, principal_id=auth.principal_ref)
        return {'accepted': True}  # Permission closed, never physical standstill evidence.
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.post('/station-return/finish')
def station_return_finish(body: StationMotionCommand, auth: AuthContext = Depends(operator),
                          svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    require_calibration_owner(svc, auth, 'station return handover')
    try:
        return owner.finish_return(body, principal_id=auth.principal_ref).model_dump()
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.post('/station-undock')
def station_undock(body: StationDeparturePermit, auth: AuthContext = Depends(operator),
                   svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    TaskKind.DOCK.require(svc.capability)
    require_calibration_owner(svc, auth, 'station undocking')
    try:
        with localized_start(svc):
            operation = owner.start_departure(body, principal_id=auth.principal_ref)
        return {'operation': operation.model_dump(mode='json')}
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.put('/station-departure')
def station_departure(body: StationDeparturePermit, auth: AuthContext = Depends(operator),
                      svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    require_calibration_owner(svc, auth, 'station departure permission')
    try:
        owner.renew_departure(body, principal_id=auth.principal_ref)
        return {'accepted': True}  # Permission only; never measured release.
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc


@station_docking_router.post('/station-departure/finish', response_model=StationDepartureReceipt)
def station_departure_finish(body: StationMotionCommand, auth: AuthContext = Depends(operator),
                             svc: CoreServicesLike = Depends(get_services)):
    owner = fleet_owner(svc, auth)
    require_calibration_owner(svc, auth, 'station departure handover')
    try:
        return owner.finish_departure(body, principal_id=auth.principal_ref)
    except (ValueError, DockError) as exc:
        raise conflict(exc) from exc
