"""Charge bay camera-heading align and line find (D-1013, real y8xs 2026-11-19): the map yaw and the camera line can
disagree by 17-30 deg, and the stop-face line can sit outside the camera's range at the staging point. Same kinematic
harness as test_docking_bay.py."""

from __future__ import annotations

import math

from core_features.docking.manager import DockingConfig, DockPhase, DockState
from test_docking_bay import DT, a_bay, done
from test_docking_bay_guards import drive, reasons

CFG = DockingConfig()


def _spins(p):
    """Commands in ACQUIRING that turn in place."""
    return [c for ph, c in p.world.commands if ph is DockPhase.ACQUIRING and c[0] == 0.0 and abs(c[1]) > 1e-6]


def test_camera_heading_align_after_turn():
    """The arrival yaw is 20 deg off the bay (the map and the camera line disagree): the robot turns in place to the
    camera line instead of backing off, then docks."""
    p = a_bay()
    p.world.arrival_error = (0.0, math.radians(20.0))
    p.manager.dock()
    order = drive(p, done)
    assert p.manager.state is DockState.DOCKED, order
    assert "backoff" not in order, order
    assert _spins(p) and not reasons(p, "docking.retry")


def test_staging_heading_uses_camera_line_not_map_yaw():
    """The map yaw is 70 deg off at staging (past the 60 deg map limit) while the camera sees the line square: it goes on and
    docks. With no line in view the map yaw still decides and refuses."""
    p = a_bay()
    p.manager._pose_provider = lambda: (p.world.pose[0], p.world.pose[1], p.world.pose[2] + math.radians(70.0))
    p.manager.dock()
    drive(p, done)
    assert p.manager.state is DockState.DOCKED
    q = a_bay()
    q.manager._pose_provider = lambda: (q.world.pose[0], q.world.pose[1], q.world.pose[2] + math.radians(70.0))
    q.detector.capture = lambda: setattr(q.detector, "latest", None)
    q.manager.dock()
    drive(q, done)
    assert any("arrival heading" in str((data or {}).get("reason", "")) for _, data in q.events)


def test_staging_arrival_with_the_map_25_deg_off_passes():
    p = a_bay()
    p.manager._pose_provider = lambda: (p.world.pose[0], p.world.pose[1], p.world.pose[2] + math.radians(25.0))
    p.manager.dock()
    drive(p, done)
    assert p.manager.state is DockState.DOCKED


def test_heading_align_refused_when_turn_blocked():
    """A blocked sweep (LiDAR rotation_block) stops the align: no spin command and a person is called."""
    p = a_bay()
    p.world.arrival_error = (0.0, math.radians(20.0))
    bay = p.manager._bay_phases

    def block(p):
        if bay._align is not None:
            bay.note_body_scan("near", None, None, p.clock.now)
    p.manager.dock()
    drive(p, done, hook=block)
    assert p.manager.state is DockState.DOCK_FAILED
    assert not _spins(p)
    assert any("heading align not clear" in str((data or {}).get("reason", "")) for _, data in p.events)


def test_lateral_too_large_still_retries():
    """The lateral is outside the window: the heading align does not apply and the old entry-window retry stands."""
    p = a_bay()
    p.world.arrival_error = (0.09, math.radians(20.0))
    p.manager.dock()
    drive(p, done)
    assert any("entry error" in r for r in reasons(p, "docking.retry"))
    assert not _spins(p)


def test_tray_tip_beside_a_neighbour_is_not_fixed_by_turning():
    """6.5 cm off at 30 deg puts the tray tip 13 cm from the line (lane half pitch 11 cm): refuse and retry."""
    p = a_bay()
    p.world.arrival_error = (0.065, math.radians(30.0))
    p.manager.dock()
    drive(p, done)
    assert any("entry error" in r for r in reasons(p, "docking.retry"))
    assert not _spins(p)


def test_heading_beyond_the_align_limit_retries():
    p = a_bay()
    p.world.arrival_error = (0.0, math.radians(50.0))
    p.manager.dock()
    drive(p, done)
    assert any("entry error" in r for r in reasons(p, "docking.retry"))
    assert not _spins(p)


def test_line_found_by_creep_from_staging_with_nav2_error():
    """The stop-face line is out of range at the staging point (nose 0.45 m out, line seen inside 0.38 m): it waits to
    be sure, creeps back until the line shows, goes a bit further, then docks. The creep stays inside its cap."""
    p = a_bay()
    capture = p.detector.capture

    def hidden_far():
        capture()
        if p.world.pose[0] < -0.38:
            p.detector.latest = None
    p.detector.capture = hidden_far
    low = {"x": p.world.pose[0]}

    def hook(p):
        if p.manager.phase is DockPhase.ACQUIRING:
            low["x"] = max(low["x"], p.world.pose[0])
    p.manager.dock()
    drive(p, done, hook=hook)
    assert p.manager.state is DockState.DOCKED
    assert not reasons(p, "docking.retry")
    creep = [c for ph, c in p.world.commands if ph is DockPhase.ACQUIRING and c[0] < 0.0]
    assert creep and all(abs(c[0]) <= CFG.bay_find_speed + 1e-9 for c in creep)
    assert len(creep) * DT * CFG.bay_find_speed <= CFG.bay_find_creep_max_m + CFG.bay_find_extra_m + 0.01


def test_find_creep_stops_when_the_line_never_shows():
    p = a_bay()
    capture = p.detector.capture

    def never():
        capture()
        p.detector.latest = None if p.manager.phase is DockPhase.ACQUIRING else p.detector.latest
    p.detector.capture = never
    start = {}

    def hook(p):
        if p.manager.phase is DockPhase.ACQUIRING:
            start.setdefault("x", p.world.pose[0])
    p.manager.dock()
    drive(p, lambda m: m.phase is DockPhase.BACKOFF, hook=hook)
    assert p.world.pose[0] - start["x"] <= CFG.bay_find_creep_max_m + 0.03
    assert any("find creep" in r for r in reasons(p, "docking.retry"))


def test_find_creep_stops_on_lidar_rear_gap():
    """Something stands 4 cm behind the tray tip: no reverse creep at all."""
    p = a_bay()
    capture = p.detector.capture

    def hidden():
        capture()
        if p.world.pose[0] < -0.38:
            p.detector.latest = None
    p.detector.capture = hidden
    p.manager.dock()
    drive(p, lambda m: m.phase is DockPhase.BACKOFF, rear_gap=lambda p: 0.04)
    assert not [c for ph, c in p.world.commands if ph is DockPhase.ACQUIRING and c[0] < 0.0]
    assert any("close behind" in r for r in reasons(p, "docking.retry"))
