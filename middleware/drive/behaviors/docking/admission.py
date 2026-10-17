"""Dock target admission before mode take and native receipt creation."""
from core_common.protocol.schemas import DockState
from .database import DockError


def dock_target(database, safety, state, dock_id, *, supported, line_active, localized, map_id):
    """Provider calls keep their original refusal order; callers hold the manager lock."""
    if not supported():
        raise DockError('CAPABILITY_NOT_SUPPORTED', 'docking is not supported on this robot')
    if getattr(safety, 'estop', False):
        raise DockError('EMERGENCY_ACTIVE', 'e-stop is active')
    if state in (DockState.DOCKING, DockState.UNDOCKING):
        raise DockError('DOCKING_ACTIVE', f'docking already in progress ({state.value})')
    if line_active():
        raise DockError('LINE_FOLLOW_ACTIVE', 'stop line following first')
    if not localized():
        raise DockError('NOT_LOCALIZED', 'robot localization is not LOCALIZED')
    if dock_id is None:
        dock = database.only()
        if dock is None:
            raise DockError('DOCK_REQUIRED', 'dock id required — zero or several docks configured')
    else:
        dock = database.get(dock_id)
    dock.require_map(map_id())
    return dock, database.type_of(dock.id)


def undock_ready(state, safety, line_active, executor):
    """Keep the legacy refusal order before the scoped motion admission hook."""
    if state not in (DockState.DOCKED, DockState.CHARGING):
        raise DockError('NOT_DOCKED', f'not docked ({state.value})')
    if getattr(safety, 'estop', False):
        raise DockError('EMERGENCY_ACTIVE', 'e-stop is active')
    if line_active():
        raise DockError('LINE_FOLLOW_ACTIVE', 'stop line following first')
    available = getattr(executor, 'odometry_available', None)
    if callable(available) and not available():
        raise DockError('NO_ODOMETRY', 'no odometry to measure the reverse')
