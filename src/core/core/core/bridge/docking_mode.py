"""ROS-free bridge seam: docking's hold on the DOCKING mode and its tick rate.

The docking API takes DOCKING when a dock or undock starts (the nav slot only
reaches the wheels in NAVIGATION or DOCKING). Once the manager leaves
DOCKING/UNDOCKING — docked, undocked, failed or cancelled — the mode goes back
to IDLE here, from the bridge's docking tick, so a finished dock never keeps
the robot in a mode nothing drives.
"""

from core_common.protocol.schemas import DockState, RobotMode
from core_features.command.arbitration import Mode

#: A parking run ticks at the bridge's fast rate; everything else at 1 in 4
#: of it (the original 5 Hz; a dock agent is polled at most that often).
SLOW_EVERY = 4


def release_docking_mode(svc) -> bool:
    """IDLE again once docking no longer moves the robot. True if released."""
    if svc.modes.mode is not Mode.DOCKING:
        return False
    if svc.docking.state in (DockState.DOCKING, DockState.UNDOCKING):
        return False
    ok, _ = svc.modes.transition(Mode.IDLE)
    if ok:
        svc.command.clear_navigation()
        svc.state.set_mode(RobotMode.IDLE)
    return ok


def due(count: int, fast: bool) -> bool:
    """Whether the `count`-th fast-rate call ticks the manager."""
    return fast or count % SLOW_EVERY == 0
