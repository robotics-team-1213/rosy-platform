"""Passively yield an exact completed navigation owner; no motion or cancellation."""
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel, ConfigDict, Field

from core_api_web.api.deps import AuthContext, CoreServicesLike, Mode, get_services
from core_api_web.api.errors import ApiError
from core_api_web.api.v1.common import operator, require_calibration_owner, require_manual_released

class NavigationHandoverRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_boot_id: UUID
    run_id: UUID
    expected_owner_generation: int = Field(ge=0, strict=True)
    correlation_id: str = Field(min_length=1, max_length=128)


def navigation_handover(body: NavigationHandoverRequest, auth: AuthContext = Depends(operator),
                        svc: CoreServicesLike = Depends(get_services)):
    require_calibration_owner(svc, auth, 'navigation handover')
    require_manual_released(svc)
    changed = admitted = False
    def admit():
        nonlocal admitted
        # The native lock may have waited. Lease owners are checked again only
        # after acquiring it. Never wait for the shared admission lock under Nav.
        admitted = svc.modes.idle_admission.acquire(blocking=False)
        if not admitted:
            return False
        require_calibration_owner(svc, auth, 'navigation handover')
        require_manual_released(svc)
        return (not svc.line_follow.active and not svc.safety.estop
            and svc.modes.mode in (Mode.NAVIGATION, Mode.IDLE))
    def transfer():
        nonlocal changed
        if svc.modes.mode is Mode.IDLE:
            return True  # Duplicate still requires the same live terminal/transport proof.
        svc.command.clear_navigation()
        changed, _ = svc.modes.transition(Mode.IDLE, expect=Mode.NAVIGATION)
        return changed
    try:
        accepted = svc.nav.with_terminal_navigation(str(body.expected_boot_id), transfer,
            expected_run_id=body.run_id, expected_owner_generation=body.expected_owner_generation,
            expected_correlation_id=body.correlation_id, admission=admit)
    finally:
        if admitted:
            svc.modes.idle_admission.release()
    if not accepted:
        raise ApiError('NAVIGATION_HANDOVER_UNAVAILABLE', 409, 'exact completed navigation owner is not quiescent')
    if changed:
        svc.events.publish('mode.changed', source='navigation_handover', data={
            'from': Mode.NAVIGATION.value, 'to': Mode.IDLE.value, 'by': 'navigation_handover',
            'run_id': str(body.run_id), 'boot_id': str(body.expected_boot_id)})
    return dict(accepted=True, mode='IDLE', run_id=str(body.run_id), boot_id=str(body.expected_boot_id),
        owner_generation=body.expected_owner_generation)
