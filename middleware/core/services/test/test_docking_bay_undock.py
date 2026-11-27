"""LiDAR-guarded charge-bay forward undock (`approach='line'`, Track 2A)."""

from __future__ import annotations

import pytest

from core_features.docking.manager import DockState
from test_docking_bay import DT, a_bay, done, run


def _dock_into_bay(*, record_mode_release: list[bool] | None = None):
    p = a_bay()
    if record_mode_release is not None:
        p.manager._release_mode = lambda: record_mode_release.append(True)
    p.manager.dock()
    run(p, done)
    assert p.manager.state is DockState.DOCKED
    p.world.commands.clear()
    return p


def _step_undock(p, *, scan_fn=None, ticks: int = 1):
    for _ in range(ticks):
        if scan_fn is not None:
            scan_fn(p)
        p.manager.tick()
        if p.manager.state in (DockState.UNDOCKED, DockState.DOCK_FAILED):
            break
        p.world.step()
        p.clock.now += DT


def test_bay_undock_waits_for_fresh_scan_then_drives_forward_to_undocked():
    p = _dock_into_bay()
    # A stale pre-undock scan is ignored once undock begins.
    p.manager.note_body_scan("rear", 0.80, 0.10, p.clock.now)
    p.clock.now += DT
    p.manager.undock()

    # Without a post-undock scan, the robot stays stopped in UNDOCKING.
    _step_undock(p, ticks=2)
    assert p.manager.state is DockState.UNDOCKING
    assert p.world.command == (0.0, 0.0)
    assert all(cmd == (0.0, 0.0) for _, cmd in p.world.commands)

    # Side rails blocking rotation ("rear") must still allow straight forward bay exit when front is clear.
    for _ in range(200):
        _step_undock(p, scan_fn=lambda q: q.manager.note_body_scan("rear", 0.80, 0.10 + q.world.odo, q.clock.now))
        if p.manager.state is DockState.UNDOCKED:
            break

    assert p.manager.state is DockState.UNDOCKED
    assert p.world.travelled_m() >= p.manager.database.type_of("bay1").undock_distance_m
    non_zero = [cmd for _, cmd in p.world.commands if cmd != (0.0, 0.0)]
    assert non_zero and all(v > 0.0 and w == 0.0 for v, w in non_zero)


@pytest.mark.parametrize(
    ("scan_args", "expected_fragment"),
    [
        (("rear", 0.05, 0.10), "something ahead"),
        (("empty", 0.0, None), "cannot vouch"),
        (None, "no fresh body scan"),
    ],
)
def test_bay_undock_fails_closed_on_front_obstacle_or_empty_or_missing_lidar(scan_args, expected_fragment):
    p = _dock_into_bay()
    p.manager.undock()
    for _ in range(60):  # > bay_scan_wait_s (2.0 s) at DT = 0.05 s
        if scan_args is None:
            _step_undock(p)
        else:
            kind, front, rear = scan_args
            _step_undock(p, scan_fn=lambda q: q.manager.note_body_scan(kind, front, rear, q.clock.now))
        if p.manager.state is DockState.DOCK_FAILED:
            break

    assert p.manager.state is DockState.DOCK_FAILED
    assert p.world.command == (0.0, 0.0)
    err = p.manager.status().error or ""
    assert "bay undock:" in err and expected_fragment in err


def test_bay_undock_fails_closed_on_rail_hangup_wheel_slip():
    p = _dock_into_bay()
    p.manager.undock()
    for _ in range(150):
        # Wheels turn (world.step advances odo) while rear LiDAR gap remains frozen at 0.10 m.
        _step_undock(p, scan_fn=lambda q: q.manager.note_body_scan("rear", 0.80, 0.10, q.clock.now))
        if p.manager.state is DockState.DOCK_FAILED:
            break

    assert p.manager.state is DockState.DOCK_FAILED
    assert p.world.command == (0.0, 0.0)
    assert "not following the wheels" in (p.manager.status().error or "")


def test_bay_undock_respects_estop_preemption():
    released: list[bool] = []
    p = _dock_into_bay(record_mode_release=released)
    released.clear()
    p.manager.undock()
    _step_undock(p, scan_fn=lambda q: q.manager.note_body_scan("rear", 0.80, 0.10 + q.world.odo, q.clock.now), ticks=3)
    assert p.manager.state is DockState.UNDOCKING and p.world.command[0] > 0.0

    p.safety.estop = True
    _step_undock(p, scan_fn=lambda q: q.manager.note_body_scan("rear", 0.80, 0.10 + q.world.odo, q.clock.now))
    assert p.manager.state is DockState.DOCK_FAILED
    assert p.world.command == (0.0, 0.0)
    assert released
