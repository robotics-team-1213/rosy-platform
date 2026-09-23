"""Independent review of stage 3 (parking), M3-M6 and the cheap LOWs.

Manager-level, on the kinematic parking bench of test_docking_parking_manager.
"""

from __future__ import annotations

import pytest

from core_common.protocol.schemas import DockState
from core_features.docking.database import DockError

from test_docking_parking_manager import ENTRY_X, SPOT, a_parking, done, run


# --- M3: a deleted dock or type must not kill the run ------------------------


def test_the_active_dock_cannot_be_removed():
    p = a_parking((ENTRY_X, 0.0, 1.5708))
    p.manager.dock()
    with pytest.raises(DockError) as excinfo:
        p.manager.remove_dock("parking")
    assert excinfo.value.code == "DOCKING_ACTIVE"
    assert [d.id for d in p.manager.database.list()] == ["parking"]


def test_an_idle_dock_can_be_removed():
    p = a_parking(SPOT)
    p.manager.remove_dock("parking")
    assert p.manager.database.list() == []


def test_the_dock_type_is_cached_when_docking_starts():
    p = a_parking((ENTRY_X, 0.0, 1.5708))
    p.manager.dock()
    # Behind the manager's back (another API worker, a hand-edited docks.json).
    p.manager.database._docks.clear()
    p.manager.database._types.clear()
    phases = run(p, done)
    assert p.manager.state is DockState.DOCKED, phases


# --- M4: undocking reverses blind, so it needs odometry and a deadline ---------


def docked(p):
    p.manager._state = DockState.DOCKED
    p.manager._dock = p.manager.database.get("parking")
    return p


def test_undock_without_odometry_is_refused_and_changes_nothing():
    p = docked(a_parking(SPOT))
    p.world.odometry_available = lambda: False
    with pytest.raises(DockError) as excinfo:
        p.manager.undock()
    assert excinfo.value.code == "NO_ODOMETRY"
    assert p.manager.state is DockState.DOCKED
    assert p.world.command == (0.0, 0.0)


def test_a_reverse_that_never_gets_there_times_out():
    p = docked(a_parking(SPOT))
    p.world.drive = lambda linear, angular: None      # wheels slip, odometry still
    p.manager.undock()
    distance = p.manager.database.type_of("parking").undock_distance_m
    deadline = 2 * distance / p.manager._cfg.undock_speed + 2.0
    run(p, lambda m: m.state is not DockState.UNDOCKING, max_s=deadline - 0.5)
    assert p.manager.state is DockState.UNDOCKING
    run(p, lambda m: m.state is not DockState.UNDOCKING, max_s=1.0)
    assert p.manager.state is DockState.DOCK_FAILED
    assert "undock timed out" in p.manager.status().error


def test_an_ordinary_undock_still_finishes():
    p = docked(a_parking(SPOT))
    p.manager.undock()
    run(p, done)
    assert p.manager.state is DockState.UNDOCKED
