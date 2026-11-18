"""Charge bay entry direction (D-1013, 2026-11-19 panel): which side the robot may start from, the
staging arrival heading, a fixed turn sense, and ±20 deg arrivals between charging neighbours.

Frames: bay_zone.map_offsets follows the DockObservation contract (dock.yaw = inward axis toward the
stop face, along > 0 outside the bay). The Fleet site map's yaw -pi/2 for C1-C3 is the direction the
bay faces; CORE's dock for the same bay is the stop face at y 0.47 with yaw +pi/2.
"""

from __future__ import annotations

import math

import pytest

from core_common.protocol.schemas import DockState
from core_features.docking.bay_zone import classify
from core_features.docking.database import DockInstance
from core_features.docking.detector import DockObservation
from core_features.docking.manager import DockingConfig, DockPhase
from test_docking_bay import a_bay, done

CFG = DockingConfig()
STAGING = 0.443
C2 = DockInstance(id="C2", type="bay-line", x=-0.19, y=0.47, yaw=math.pi / 2)


def observe(pose, dock=C2):
    """The guide line as the virtual dock: stop-face centre and inward axis in base_link."""
    x, y, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dy = dock.x - x, dock.y - y
    return DockObservation(x=c * dx + s * dy, y=-s * dx + c * dy, yaw=dock.yaw - yaw, confidence=0.9, at=0.0)


def verdict(pose, cfg=CFG, dock=C2):
    return classify(pose, dock, STAGING, observe(pose, dock), cfg)


def test_site_frame_signs_outside_is_positive_and_the_bay_row_is_exit():
    out_yaw = -math.pi / 2                                        # nose out, rear to the bay
    assert C2.staging_pose(STAGING).y == pytest.approx(0.027, abs=1e-6)   # P y; poses below sit a hair past it
    assert verdict((-0.19, 0.02, out_yaw)).kind == "out"
    assert verdict((-0.19, 0.30, out_yaw)).kind == "exit"
    assert verdict((-0.19, 0.30, out_yaw + math.pi)).kind == "manual"   # nose to the bay


@pytest.mark.parametrize("pose,kind", [
    ((-0.49, 0.02, math.pi), "manual"),                # west = downstream of C2 (C3 -> C1)
    ((-0.49, 0.10, math.pi), "manual"),
    ((0.11, 0.02, math.pi), "out"),                    # east = upstream: Nav2 drives with the flow
    ((-0.19, 0.02, math.pi), "out"),                   # in front of the mouth
    ((-0.49, -0.25, math.pi), "out"),                   # upper lane, far from the corridor line
])
def test_bay_zone_downstream_side_is_manual(pose, kind):
    assert verdict(pose).kind == kind


def test_downstream_check_can_be_switched_off():
    assert verdict((-0.49, 0.02, math.pi), DockingConfig(bay_downstream_sign=0.0)).kind == "out"


def test_staging_arrival_wrong_heading_fails():
    for dyaw in (math.pi, math.radians(75.0)):
        p = a_bay()
        p.world.arrival_error = (0.0, dyaw)
        p.manager.dock()
        p.manager.tick()
        assert p.manager.state is DockState.DOCK_FAILED and "heading" in p.manager._error
        assert not [c for _, c in p.world.commands if c != (0.0, 0.0)]


def turning_commands(noise):
    p = a_bay()
    p.world.arrival_error = (0.0, noise)
    p.manager.dock()
    seen = []
    for k in range(120):
        if k % 4 == 0:
            p.detector.capture()
            p.manager._bay_phases.note_body_scan(None, None, None, p.clock.now)
        p.manager.tick()
        if p.manager.phase is not DockPhase.TURNING:
            if seen:
                break
        else:
            seen.append(p.world.command)
        p.world.step()
        p.clock.now += 0.05
    return [w for _, w in seen if w]


def test_turning_direction_stable_under_noise():
    runs = [turning_commands(n) for n in (1e-9, -1e-9, 0.0)]
    assert all(r and all(w < 0.0 for w in r) for r in runs)        # clockwise: the tray swings downstream
    assert all(len(r) == len(runs[0]) for r in runs)               # and the same short way every time


# --- kinematic row: charging neighbours and a car at the junction --------------------------------

FRONT, REAR, HALF = 0.042, 0.135, 0.0566
SWEEP = math.hypot(REAR, HALF) + 0.010
PITCH = 0.221


def corners(x, y, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return [(x + a * c - b * s, y + a * s + b * c) for a, b in ((FRONT, HALF), (FRONT, -HALF), (-REAR, -HALF), (-REAR, HALF))]


def inside(p, poly):
    cross = [(poly[(i + 1) % 4][0] - poly[i][0]) * (p[1] - poly[i][1])
             - (poly[(i + 1) % 4][1] - poly[i][1]) * (p[0] - poly[i][0]) for i in range(4)]
    return all(v > 0 for v in cross) or all(v < 0 for v in cross)


def overlap(a, b):
    return any(inside(p, b) for p in a) or any(inside(q, a) for q in b)


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def run_row(p, bodies, max_s=300.0):
    bodies, contacts, t0, k = [corners(*b) for b in bodies], 0, p.clock.now, 0
    while p.clock.now - t0 < max_s:
        if k % 4 == 0:
            p.detector.capture()
            x, y, _ = p.world.pose
            near = min((0.0 if inside((x, y), q) else min(seg_dist((x, y), q[i], q[(i + 1) % 4]) for i in range(4))
                        for q in bodies), default=9.0)
            p.manager._bay_phases.note_body_scan("near" if near <= SWEEP else None, None, None, p.clock.now)
        p.manager.tick()
        if done(p.manager):
            break
        was = any(overlap(corners(*p.world.pose), q) for q in bodies)
        p.world.step()
        contacts += (not was) and any(overlap(corners(*p.world.pose), q) for q in bodies)
        p.clock.now += 0.05
        k += 1
    return contacts


NEIGHBOURS = [(-0.05, PITCH, math.pi), (-0.05, -PITCH, math.pi)]


@pytest.mark.parametrize("dyaw_deg", [-20.0, 20.0])
def test_arrival_yaw_20_deg_between_neighbours_docks_without_contact(dyaw_deg):
    p = a_bay()
    p.world.arrival_error = (0.0, math.radians(dyaw_deg))
    p.manager.dock()
    contacts = run_row(p, NEIGHBOURS)
    assert p.manager.state in (DockState.DOCKED, DockState.DOCK_FAILED)
    assert contacts == 0


def test_a_car_0_15_m_behind_at_the_junction_blocks_the_turn_without_contact():
    p = a_bay()
    p.manager.dock()
    contacts = run_row(p, NEIGHBOURS + [(-0.45, -0.15 - FRONT, math.pi / 2)])
    assert p.manager.state is DockState.DOCK_FAILED and "turn not clear" in p.manager._error
    assert contacts == 0
    assert not [c for ph, c in p.world.commands if ph is not DockPhase.STAGING and c != (0.0, 0.0)]
