"""Wheel progress during a commanded reverse, through the bay docking manager."""

import math

import pytest

from core_features.docking.manager import DockPhase
from test_docking_bay import DOCKED_ALONG, DT, a_bay, run


@pytest.mark.parametrize("free_reverse_m", [0.0, 0.04])
def test_stopped_wheels_end_the_reverse_and_wait_for_charge(free_reverse_m):
    p = a_bay(charges=False)
    p.manager.dock()
    run(p, lambda m: m.phase is DockPhase.ALIGNING and p.world.odo >= free_reverse_m)
    assert p.manager.phase is DockPhase.ALIGNING
    assert p.world.odo >= free_reverse_m

    p.world.step = lambda: None  # Both the axle and the body are held.
    stopped_at = p.clock.now
    stall_s = p.manager._cfg.contact_stall_s
    run(p, lambda m: m.phase is DockPhase.SETTLING, max_s=stall_s + 3 * DT)

    assert p.manager.phase is DockPhase.SETTLING
    assert p.clock.now - stopped_at == pytest.approx(stall_s, abs=2 * DT)
    assert p.world.command == (0.0, 0.0)
    assert not any(p.battery.charging_flags)


def test_rear_scan_motion_keeps_the_reverse_alive_with_frozen_wheel_feedback():
    p = a_bay()
    p.manager.dock()
    run(p, lambda m: m.phase is DockPhase.ALIGNING)
    assert p.manager.phase is DockPhase.ALIGNING
    p.world.travelled_m = lambda: 0.0
    start_x = p.world.pose[0]

    for tick in range(math.ceil(2 * p.manager._cfg.contact_stall_s / DT)):
        if tick % 2 == 0:
            p.detector.capture()
            gap = -p.world.pose[0] - DOCKED_ALONG + 0.01
            p.manager.note_body_scan(None, None, gap, p.clock.now)
        p.manager.tick()
        assert p.manager.phase is DockPhase.ALIGNING
        p.world.step()
        p.clock.now += DT

    assert p.world.pose[0] > start_x + 0.02
    assert p.world.command[0] < 0.0


def test_time_stopped_for_a_line_scan_does_not_count_against_resumed_reverse():
    p = a_bay()
    p.manager.dock()
    run(p, lambda m: m.phase is DockPhase.ALIGNING and p.world.odo >= 0.02)
    assert p.manager.phase is DockPhase.ALIGNING
    p.detector.dead = True
    run(p, lambda m: m.phase is DockPhase.ALIGNING and p.world.command[0] == 0.0,
        max_s=3.0)
    assert p.world.command[0] == 0.0
    p.world.step = lambda: None
    stall_s = p.manager._cfg.contact_stall_s
    run(p, lambda m: False, max_s=stall_s + DT)
    p.detector.dead = False

    run(p, lambda m: p.world.command[0] < 0.0, max_s=4 * DT)
    assert p.manager.phase is DockPhase.ALIGNING
    assert p.world.command[0] < 0.0
    run(p, lambda m: m.phase is DockPhase.SETTLING, max_s=stall_s + 3 * DT)
    assert p.manager.phase is DockPhase.SETTLING
