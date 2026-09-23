"""The DOCKING mode is released in the same critical section that ends a run.

Follow-up review N1/N6: the bridge used to read `docking.state` without the
manager's lock and then move DOCKING -> IDLE. An API undock arriving between the
read and the transition found the mode still DOCKING (so `take_mode` did
nothing), set UNDOCKING, and the bridge's transition then fired `leave_docking`,
which cancelled the undock and reported UNDOCKED for a robot sitting on its
dock. Now the manager releases the mode under its own lock, at the same moment
it leaves DOCKING/UNDOCKING: whoever sees the run over also sees the mode IDLE.
"""

from __future__ import annotations

import threading

from core_common.protocol.schemas import DockState
from core_features.command.arbitration import Mode
from core_features.command.manager import Twist
from core.bridge import docking_mode

from test_docking_mode_ownership import docking_robot, wheels


def just_docked(core_client):
    """A parking run whose last tick has just reached DOCKED."""
    client, services = docking_robot(core_client)
    services.docking._state = DockState.DOCKED
    services.docking._phase = None
    assert services.modes.mode is Mode.DOCKING
    return client, services


def test_an_undock_at_the_release_point_keeps_the_robot_docked(core_client):
    _, services = just_docked(core_client)
    real_transition = services.modes.transition
    worker = []

    def undock_arrives(new):
        # The API worker's undock lands exactly where the mode is released.
        if new is Mode.IDLE and not worker:
            thread = threading.Thread(target=services.docking.undock)
            worker.append(thread)
            thread.start()
            thread.join(0.3)       # blocked on the docking lock, if the release holds it
        return real_transition(new)

    services.modes.transition = undock_arrives
    docking_mode.tick(services, lambda msg: None)
    worker[0].join(5.0)
    assert not worker[0].is_alive()
    assert services.docking.state is DockState.UNDOCKING
    assert services.modes.mode is Mode.DOCKING


def test_the_tick_that_docks_releases_the_mode(core_client):
    _, services = just_docked(core_client)
    services.docking.tick()
    assert services.docking.state is DockState.DOCKED
    assert services.modes.mode is Mode.IDLE


def test_cancel_releases_the_mode_atomically(core_client):
    _, services = docking_robot(core_client)
    services.command.set_docking_twist(Twist(0.03, 0.1))
    services.docking.cancel()
    assert services.docking.state is DockState.UNDOCKED
    assert services.modes.mode is Mode.IDLE
    assert wheels(services) == (0.0, 0.0)


def test_abort_releases_the_mode_atomically(core_client):
    _, services = docking_robot(core_client)
    services.docking.abort("test")
    assert services.docking.state is DockState.DOCK_FAILED
    assert services.modes.mode is Mode.IDLE


def test_no_nav2_twist_reaches_the_docking_slot_after_a_cancel(core_client):
    """N6: route_nav_cmd_vel reads the mode; it is IDLE the moment cancel returns."""
    _, services = docking_robot(core_client)
    services.docking.cancel()
    assert not docking_mode.route_nav_cmd_vel(services, Twist(0.2, 0.0))
    assert wheels(services) == (0.0, 0.0)


def test_status_waits_for_a_terminal_change_in_progress(core_client):
    _, services = docking_robot(core_client)
    held, release = threading.Event(), threading.Event()

    def hold_the_lock():
        with services.docking._lock:
            held.set()
            release.wait(5.0)

    holder = threading.Thread(target=hold_the_lock)
    holder.start()
    held.wait(5.0)
    seen = []
    readers = [threading.Thread(target=lambda: seen.append(services.docking.status())),
               threading.Thread(target=lambda: seen.append(services.docking.state)),
               threading.Thread(target=lambda: seen.append(services.docking.phase))]
    for reader in readers:
        reader.start()
    for reader in readers:
        reader.join(0.2)
    assert seen == []              # all three wait for the critical section
    release.set()
    holder.join(5.0)
    for reader in readers:
        reader.join(5.0)
    assert len(seen) == 3


def test_a_mode_exit_from_the_api_still_cancels_and_stays_idle(core_client):
    client, services = docking_robot(core_client)
    services.modes.transition(Mode.IDLE)
    assert services.docking.state is DockState.UNDOCKED
    assert services.modes.mode is Mode.IDLE
