"""ROS-free bridge seam: docking's hold on the DOCKING mode and its tick rate.

The docking API takes DOCKING when a dock or undock starts (the docking slot
only reaches the wheels in DOCKING). Once the manager leaves
DOCKING/UNDOCKING — docked, undocked, failed or cancelled — it gives the mode
back to IDLE itself, under its lock (`CoreServices.release_docking_mode`), so a
finished dock never keeps the robot in a mode nothing drives. The bridge used to
do that here, outside the lock, and an undock arriving in between was cancelled
by the mode-exit listener (N1).
"""

from core_common.protocol.schemas import DockState
from core_features.command.arbitration import Mode
from core_features.docking.manager import DockPhase
from core_features.safety.manager import finite_velocity

#: A parking run ticks at the bridge's fast rate; everything else at 1 in 4
#: of it (the original 5 Hz; a dock agent is polled at most that often).
SLOW_EVERY = 4


def tick(svc, warn, *, station=None) -> None:
    """One docking tick from the bridge timer.

    An exception here would propagate out of the rclpy timer and stop CORE's
    executor — the 50 Hz cmd_vel timer with it — while the mode stayed
    DOCKING. Like the swarm tick, it is caught: docking fails, and the abort
    releases the mode, so the robot is left stopped in IDLE.
    """
    docking = svc.docking
    docking.on_navigation_state(svc.nav.nav_state)
    docking.set_manual_active(svc.command.manual_active)
    try:
        if station is not None and station.session is not None:
            station.tick()
        else:
            docking.tick()
    except Exception as exc:  # a failed tick must not stop the bridge
        warn(f"docking tick failed: {exc}")
        try:
            docking.abort(f"docking tick failed: {exc}")
        except Exception as cleanup:  # the state is DOCK_FAILED already
            warn(f"docking cleanup failed: {cleanup}")
    svc.state.set_docking(docking.status())


def motion_ready(svc) -> bool:
    """Keep original power/safety arbitration, plus the local automatic station lease."""
    if svc.power.motion_ready() is not True:
        return False
    # Explicit operator control retains existing arbitration. The mode listener
    # invalidates the automatic session outside this final output path.
    if svc.modes.mode is Mode.MANUAL:
        return True
    station = svc.station_docking
    return station is None or station.session is None or station.motion_ready(svc.modes.mode.value) is True


def due(count: int, fast: bool) -> bool:
    """Whether the `count`-th fast-rate call ticks the manager."""
    return fast or count % SLOW_EVERY == 0


def route_nav_cmd_vel(svc, twist) -> bool:
    """Where Nav2's nav_cmd_vel goes. True if it was written to a slot.

    NAVIGATION: the nav slot. DOCKING: the docking slot, but only while a
    staging dock drives to its staging pose through Nav2 — any other Nav2
    output during docking (a stale goal, a swarm goal) must not move the
    robot. Line following owns the nav slot while it is active, and so does a
    D-395 P2-7 rotate/nudge mission.
    """
    epoch = svc.modes.epoch
    mode = svc.modes.mode
    if svc.line_follow.active or svc.swarm.trail_active:  # D-559: trail owns the slot too
        return False
    mission = svc.loc_mission
    if mission is not None and mission.owns_wheels:
        return False
    if mode is Mode.NAVIGATION:
        setter = svc.command.set_nav_twist
    elif (mode is Mode.DOCKING and svc.docking.state is DockState.DOCKING
          and svc.docking.phase is DockPhase.STAGING):
        setter = svc.command.set_docking_twist
    else:
        return False

    if not finite_velocity(twist.linear, twist.angular):
        # The setter clears invalid input and publishes the rejection outside the locks.
        setter(twist)
        return False

    def commit():
        # observe_twist holds the navigation owner lock until the input is bound.
        route = getattr(svc.nav, "_route", None)
        authority = getattr(route, "speed_authority", None) if mode is Mode.NAVIGATION else None
        options = {"speed_authority": authority} if authority is not None else {}
        return svc.modes.commit_input(mode, lambda: setter(twist, **options), epoch=epoch)

    return svc.nav.observe_twist(commit)
