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


# --- M5: an observation pairs only with odometry recorded near its capture ------


def test_the_tracker_rejects_a_pairing_far_from_the_capture_time():
    from core_features.docking.detector import DockObservation
    from core_features.docking.parking import DockPoseTracker
    tracker = DockPoseTracker(0.25)
    tracker.record_odometry(10.0, (0.0, 0.0, 0.0))
    far = DockObservation(x=0.3, y=0.0, yaw=0.0, confidence=0.9, at=10.5)
    assert not tracker.observe(far)
    assert tracker.anchored_at is None
    near = DockObservation(x=0.3, y=0.0, yaw=0.0, confidence=0.9, at=10.05)
    assert tracker.observe(near)
    assert tracker.anchored_at == 10.05


def test_the_entry_turn_records_odometry_for_the_first_pairing():
    from test_docking_parking_manager import DockPhase
    p = a_parking((ENTRY_X, 0.0, 1.5708))
    p.manager.dock()
    assert p.manager.phase is DockPhase.TURNING
    run(p, lambda m: m.phase is not DockPhase.TURNING)
    turn_end = p.manager._phase_since
    samples = list(p.manager._tracker._odometry)
    assert samples and samples[0][0] < turn_end



# --- M6: only a new anchor counts as seeing the dock ---------------------------


def test_a_repeated_frame_does_not_keep_the_approach_alive():
    from test_docking_parking_manager import DockPhase
    p = a_parking((ENTRY_X, 0.0, 1.5708))
    p.manager.dock()
    run(p, lambda m: m.phase is DockPhase.APPROACHING)
    assert p.manager.phase is DockPhase.APPROACHING
    frozen = p.camera.relative_pose()
    assert frozen is not None
    p.camera.relative_pose = lambda: frozen          # the feed repeats one frame
    p.camera.capture = lambda: None
    grace = p.manager._cfg.detector_lost_grace_s
    run(p, lambda m: m.phase is not DockPhase.APPROACHING, max_s=grace + 1.0)
    assert p.manager.phase is not DockPhase.APPROACHING
    assert p.manager.retries == 1
