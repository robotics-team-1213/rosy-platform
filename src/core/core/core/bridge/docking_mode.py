"""ROS-free bridge seam: docking's hold on the DOCKING mode and its tick rate.

The docking API takes DOCKING when a dock or undock starts (the docking slot
only reaches the wheels in DOCKING). Once the manager leaves
DOCKING/UNDOCKING — docked, undocked, failed or cancelled — the mode goes back
to IDLE here, from the bridge's docking tick, so a finished dock never keeps
the robot in a mode nothing drives.
"""

from core_common.protocol.schemas import DockState, RobotMode
from core_features.command.arbitration import Mode
from core_features.docking.manager import DockPhase

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
        svc.command.clear_docking()
        svc.state.set_mode(RobotMode.IDLE)
    return ok


def tick(svc, warn) -> None:
    """One docking tick from the bridge timer.

    An exception here would propagate out of the rclpy timer and stop CORE's
    executor — the 50 Hz cmd_vel timer with it — while the mode stayed
    DOCKING. Like the swarm tick, it is caught: docking fails and the mode is
    released, so the robot is left stopped in IDLE.
    """
    docking = svc.docking
    docking.on_navigation_state(svc.nav.nav_state)
    docking.set_manual_active(svc.command.manual_active)
    try:
        docking.tick()
    except Exception as exc:  # a failed tick must not stop the bridge
        warn(f"docking tick failed: {exc}")
        try:
            docking.abort(f"docking tick failed: {exc}")
        except Exception as cleanup:  # the state is DOCK_FAILED already
            warn(f"docking cleanup failed: {cleanup}")
    release_docking_mode(svc)
    svc.state.set_docking(docking.status())


def due(count: int, fast: bool) -> bool:
    """Whether the `count`-th fast-rate call ticks the manager."""
    return fast or count % SLOW_EVERY == 0


def route_nav_cmd_vel(svc, twist) -> bool:
    """Where Nav2's nav_cmd_vel goes. True if it was written to a slot.

    NAVIGATION: the nav slot. DOCKING: the docking slot, but only while a
    staging dock drives to its staging pose through Nav2 — any other Nav2
    output during docking (a stale goal, a swarm goal) must not move the
    robot. Line following owns the nav slot while it is active.
    """
    if svc.line_follow.active:
        return False
    mode = svc.modes.mode
    if mode is Mode.NAVIGATION:
        svc.command.set_nav_twist(twist)
        return True
    if (mode is Mode.DOCKING and svc.docking.state is DockState.DOCKING
            and svc.docking.phase is DockPhase.STAGING):
        svc.command.set_docking_twist(twist)
        return True
    return False
