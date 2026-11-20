"""Charge bay row with neighbours: the pink-line pit-in (D-1013) must not touch a docked robot.

2026-11-18 a robot turned in place in front of its bay and pushed the charging neighbour. This
kinematic row keeps the robot of test_docking_bay and adds two docked neighbours at the site pitch,
a body with the tray (rear 0.126 m, assumed until D-397 measures it) and the body-scan verdicts CORE
feeds (rotation check with the tray, straight gaps). It covers the start from the corridor, a turn
the scan refuses, and docking switched on while the robot is already inside the bay row
(bay_zone.py): leave straight and skip the turn, or stay still and call a person.
"""

from __future__ import annotations

import math

import pytest

from core_common.protocol.schemas import DockState
from core_features.docking.database import DockType
from core_features.docking.manager import DockPhase
from test_docking_bay import BAY, a_bay, done

PITCH = 0.221                       # C2-C3 bay pitch (BAY_DOCK_SPECS), the tighter one
FRONT, REAR, HALF = 0.042, 0.126, 0.0566
SWEEP = math.hypot(REAR, HALF) + 0.010
DOCKED = (-0.05, 0.0, math.pi)      # base_link on the stop face, rear in


def corners(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return [(x + a * c - b * s, y + a * s + b * c) for a, b in ((FRONT, HALF), (FRONT, -HALF), (-REAR, -HALF), (-REAR, HALF))]


def _inside(p, poly):
    sign = None
    for i in range(4):
        a, b = poly[i], poly[(i + 1) % 4]
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        if sign is None:
            sign = cross > 0
        elif (cross > 0) != sign:
            return False
    return True


def _seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def overlap(P, Q):
    return any(_inside(p, Q) for p in P) or any(_inside(q, P) for q in Q)


def point_to_poly(p, Q):
    return 0.0 if _inside(p, Q) else min(_seg(p, Q[i], Q[(i + 1) % 4]) for i in range(4))


class Row:
    """Neighbour bodies, contact count and the body scan CORE would feed."""

    def __init__(self, p, others):
        self.p, self.others = p, [corners(*o) for o in others]
        self.contacts = 0
        self.override = None                 # callable(p) -> verdict tuple, or "skip" to feed nothing

    def scan(self):
        if self.override is not None:
            return self.override(self.p)
        x, y, yaw = self.p.world.pose
        near = min((point_to_poly((x, y), q) for q in self.others), default=9.0)
        block = "near" if near <= SWEEP else None
        return block, self._gap(x, y, yaw, 1.0), self._gap(x, y, yaw, -1.0)

    def _gap(self, x, y, yaw, sign):
        for k in range(101):
            d = 0.005 * k
            body = corners(x + sign * d * math.cos(yaw), y + sign * d * math.sin(yaw), yaw)
            if any(overlap(body, q) for q in self.others):
                return d
        return None

    def touching(self):
        return any(overlap(corners(*self.p.world.pose), q) for q in self.others)


def a_row(start=None, others=((DOCKED[0], PITCH, math.pi), (DOCKED[0], -PITCH, math.pi)), **kw):
    p = a_bay(**kw)
    if start is not None:
        p.world.pose = start
    return p, Row(p, others)


def run_row(p, row, until=done, max_s=300.0):
    phases, k, t0 = [], 0, p.clock.now
    while p.clock.now - t0 < max_s:
        if k % 4 == 0:
            p.detector.capture()
            verdict = row.scan()
            if verdict != "skip":
                p.manager.note_body_scan(*verdict, p.clock.now)
        p.manager.tick()
        phase = p.manager.phase.value if p.manager.phase else None
        if not phases or phases[-1] != phase:
            phases.append(phase)
        if until(p.manager):
            break
        was = row.touching()
        p.world.step()
        row.contacts += (not was) and row.touching()
        p.clock.now += 0.05
        k += 1
    return phases


def moved(p):
    return [cmd for _, cmd in p.world.commands if cmd != (0.0, 0.0)]


@pytest.mark.parametrize("dy", [-0.03, 0.0, 0.03])
@pytest.mark.parametrize("dyaw_deg", [-6.0, 0.0, 6.0])
def test_from_the_corridor_it_docks_between_neighbours_without_contact(dy, dyaw_deg):
    p, row = a_row()
    p.world.arrival_error = (dy, math.radians(dyaw_deg))
    p.manager.dock()
    phases = run_row(p, row)
    assert p.manager.state is DockState.DOCKED, (phases, p.manager._error)
    assert row.contacts == 0


@pytest.mark.parametrize("dy,dyaw_deg", [(0.10, 0.0), (-0.10, 14.0), (0.07, -14.0)])
def test_a_poor_staging_never_touches_a_neighbour(dy, dyaw_deg):
    p, row = a_row()
    p.world.arrival_error = (dy, math.radians(dyaw_deg))
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state in (DockState.DOCKED, DockState.DOCK_FAILED)
    assert row.contacts == 0


def test_the_turn_waits_for_the_tray_sweep_and_fails_when_a_robot_is_beside_staging():
    # A robot parked 0.20 m beside the staging point: inside the tray sweep, as on 2026-11-18.
    p, row = a_row(others=((-0.45, 0.20, math.pi / 2),))
    p.manager.dock()
    phases = run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED
    assert "bay turn not clear" in p.manager._error
    assert all(cmd[1] == 0.0 for _, cmd in p.world.commands if _ is DockPhase.TURNING)
    assert row.contacts == 0, phases


def test_a_line_bay_turning_closer_than_0_30_m_is_refused():
    with pytest.raises(ValueError):
        DockType(**dict(BAY, staging_offset_m=0.25))


def test_inside_the_bay_nose_out_it_leaves_straight_and_skips_nav2_and_the_turn():
    p, row = a_row(start=(-0.15, 0.004, math.pi + math.radians(1.0)))
    p.manager.dock()
    phases = run_row(p, row)
    assert p.manager.state is DockState.DOCKED, (phases, p.manager._error)
    assert p.world.goals == []                       # no Nav2 inside the bay row
    assert "turning" not in phases
    assert row.contacts == 0


@pytest.mark.parametrize("start,why", [
    ((-0.15, 0.0, 0.0), "nose toward the bay"),
    ((-0.15, 0.0, math.pi + math.radians(20.0)), "not straight enough"),
    ((-0.40, 0.0, 0.0), "nose toward the bay"),     # inside the staging distance: no Nav2 either
    ((-0.15, PITCH, math.pi), "not in this bay's lane"),
    ((-0.15, 0.07, math.pi), "not straight enough"),
])
def test_inside_the_bay_row_otherwise_it_stays_still_and_calls_a_person(start, why):
    p, row = a_row(start=start, others=((DOCKED[0], -PITCH, math.pi),))
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED
    assert why in p.manager._error
    assert moved(p) == [] and p.world.goals == []


def test_inside_the_bay_without_the_line_it_stays_still():
    p, row = a_row(start=(-0.15, 0.0, math.pi))
    p.detector.dead = True
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED
    assert "guide line not visible" in p.manager._error
    assert moved(p) == []


def test_without_a_map_pose_it_stays_still():
    p, row = a_row()
    p.manager._pose_provider = lambda: None
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED
    assert "map pose unavailable" in p.manager._error
    assert moved(p) == [] and p.world.goals == []


def test_near_staging_it_uses_the_normal_nav2_staging():
    p, row = a_row(start=(-0.50, 0.0, 0.0))          # 0.50 m out: beyond the 0.45 m staging
    p.manager.dock()
    run_row(p, row)
    assert len(p.world.goals) >= 1
    assert p.manager.state is DockState.DOCKED and row.contacts == 0


def test_a_retry_leaves_the_bay_row_straight_instead_of_nav2():
    p, row = a_row(charges=False)                     # contact without charge: retry, then fail
    p.manager.dock()
    phases = run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED
    assert len(p.world.goals) == 1                   # only the first staging used Nav2
    assert phases.count("turning") == 1
    assert row.contacts == 0


def test_a_line_bay_does_not_start_itself_on_low_battery_unless_asked():
    from core_common.protocol.schemas import BatteryLevel  # noqa: PLC0415
    p, _ = a_row()
    p.manager.on_battery_level(BatteryLevel.WARNING)
    assert p.manager.state is DockState.UNDOCKED and p.world.goals == []
    q, _ = a_row(auto_return=True)
    q.manager.on_battery_level(BatteryLevel.WARNING)
    assert q.manager.state is DockState.DOCKING


def test_leaving_the_row_steers_on_the_line_from_a_skewed_start():
    p, row = a_row(start=(-0.12, 0.04, math.pi - math.radians(10.0)))
    p.manager.dock()
    phases = run_row(p, row)
    assert p.manager.state is DockState.DOCKED, (phases, p.manager._error)
    assert p.world.goals == [] and "turning" not in phases and row.contacts == 0


def test_a_straight_start_acquires_where_it_stands_when_the_line_ends_short_of_the_exit():
    # y8xs 2026-11-20: the guide line ended before the staging distance, so leaving the row lost it and failed.
    p, row = a_row(start=(-0.13, 0.002, math.pi + math.radians(1.0)), others=())
    p.detector.reach = 0.30
    out = []
    p.manager.dock()
    run_row(p, row, until=lambda m: out.append(-p.world.pose[0]) or done(m))
    assert p.manager.state is DockState.DOCKED, p.manager._error
    assert max(out) < 0.20                            # a settle creep only: no exit toward the staging distance
    assert p.world.goals == []


def test_a_start_skewed_past_the_acquire_limit_still_leaves_and_never_drives_blind():
    p, row = a_row(start=(-0.12, 0.0, math.pi - math.radians(9.0)), others=())
    p.detector.reach = 0.20
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED and "lost the guide line" in p.manager._error


def test_a_stale_map_pose_stops_it_and_the_reason_carries_both_laterals():
    # Odom slip near the bay leaves the map pose off; the check stays blocked (wrong-bay protection) but says by how much.
    p, row = a_row(start=(-0.15, 0.0, math.pi))
    x, y, yaw = p.world.pose
    p.manager._pose_provider = lambda: (x, y + 0.08, yaw)
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED
    assert "map pose and guide line disagree (lateral map" in p.manager._error and "line" in p.manager._error
    assert moved(p) == []


def test_a_few_frames_off_the_map_are_waited_out_but_a_lasting_disagreement_still_refuses():
    p, row = a_row(start=(-0.15, 0.0, math.pi), others=())
    p.detector.glitch_frames = 3                     # the camera reads another line for the first captures
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCKED, p.manager._error
    q, qrow = a_row(start=(-0.15, 0.0, math.pi), others=())
    q.detector.glitch_frames = 10_000                # it never agrees: the look time ends and it stays still
    q.manager.dock()
    run_row(q, qrow)
    assert q.manager.state is DockState.DOCK_FAILED and "map pose and guide line disagree" in q.manager._error
    assert moved(q) == []


def _exit_then(p, row, harm):
    p.manager.dock()
    run_row(p, row, until=lambda m: m.phase is DockPhase.BACKOFF and m._bay_phases._zone == "exit")
    start = p.world.pose
    harm(p, row)
    run_row(p, row)
    return math.hypot(p.world.pose[0] - start[0], p.world.pose[1] - start[1])


def test_losing_the_line_while_leaving_stops_rather_than_driving_blind():
    p, row = a_row(start=(-0.12, 0.0, math.pi - math.radians(8.0)))
    moved_m = _exit_then(p, row, lambda p, row: setattr(p.detector, "dead", True))
    assert p.manager.state is DockState.DOCK_FAILED and "lost the guide line" in p.manager._error
    assert moved_m < 0.02


def test_an_empty_scan_is_not_a_clear_way_out():
    p, row = a_row(start=(-0.12, 0.0, math.pi - math.radians(8.0)))
    moved_m = _exit_then(p, row, lambda p, row: setattr(row, "override", lambda p: ("empty", 0.0, 0.0)))
    assert p.manager.state is DockState.DOCK_FAILED and "cannot vouch" in p.manager._error
    assert moved_m < 0.02


def test_no_scan_after_stopping_at_staging_means_no_turn():
    p, row = a_row(others=())
    p.manager.dock()
    run_row(p, row, until=lambda m: m.phase is DockPhase.TURNING)
    row.override = lambda p: "skip"
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED and "no fresh body scan" in p.manager._error
    assert all(cmd[1] == 0.0 for phase, cmd in p.world.commands if phase is DockPhase.TURNING)


def test_from_the_corridor_something_in_the_sweep_stops_it_before_nav2():
    p, row = a_row(start=(-0.60, 0.0, 0.0), others=((-0.60, 0.15, math.pi / 2),))
    p.manager.dock()
    run_row(p, row)
    assert p.manager.state is DockState.DOCK_FAILED and "tray sweep before Nav2" in p.manager._error
    assert p.world.goals == [] and moved(p) == []
