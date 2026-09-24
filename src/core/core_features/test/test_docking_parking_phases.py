"""The parking phases live in `docking/parking_phases.py`; the manager delegates.

Manager-level, on the kinematic parking bench of test_docking_parking_manager.
"""

from __future__ import annotations

import ast
from pathlib import Path

from core_common.protocol.schemas import DockState
from core_features.docking.manager import DockPhase
from core_features.docking.parking_phases import ParkingPhases

from test_docking_parking_manager import ENTRY_X, SPOT, a_parking, done, run

DOCKING = Path(__file__).resolve().parents[1] / "core_features" / "docking"
POSE_ENTRIES = ("begin_entry_turn", "begin_turn", "begin_undock_turn", "begin_acquiring",
                "tick_turning", "tick_acquiring", "tick_approaching", "tick_aligning",
                "tick_settling", "tick_backoff")


def spy(manager):
    """Wrap the manager's strategy so each entry point is recorded and still runs."""
    calls = []
    strategy = manager._parking_phases
    for name in POSE_ENTRIES:
        real = getattr(strategy, name)

        def wrapped(*args, _name=name, _real=real, **kwargs):
            calls.append(_name)
            return _real(*args, **kwargs)
        setattr(strategy, name, wrapped)
    return calls


def test_the_manager_delegates_every_pose_phase_to_the_strategy():
    p = a_parking((ENTRY_X, 0.0, 1.5708))
    calls = spy(p.manager)
    p.manager.dock()
    run(p, done)
    assert p.manager.state is DockState.DOCKED
    for name in ("begin_entry_turn", "begin_turn", "tick_turning", "begin_acquiring",
                 "tick_acquiring", "tick_approaching", "tick_aligning", "tick_settling"):
        assert name in calls, name

    p.manager.undock()
    run(p, done, max_s=60.0)
    assert p.manager.state is DockState.UNDOCKED
    assert "begin_undock_turn" in calls


def test_the_distance_backoff_is_delegated_too():
    p = a_parking(SPOT)
    calls = spy(p.manager)
    p.manager.dock()
    with p.manager._lock:
        p.manager._begin_backoff(DockPhase.ACQUIRING)
    assert p.manager.phase is DockPhase.BACKOFF
    p.manager.tick()
    assert "tick_backoff" in calls


def test_the_strategy_holds_no_state_or_lock_of_its_own():
    p = a_parking(SPOT)
    strategy = p.manager._parking_phases
    assert isinstance(strategy, ParkingPhases)
    assert set(vars(strategy)) == {"_h", "gains"}
    assert strategy._h is p.manager


def test_the_parking_modules_import_no_ros_no_cv2_and_no_threading():
    banned = ("rclpy", "cv2", "sensor_msgs", "geometry_msgs", "nav_msgs", "std_msgs",
              "tf2_ros", "builtin_interfaces", "threading")
    for name in ("parking_phases.py", "model.py", "parking.py"):
        tree = ast.parse((DOCKING / name).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & set(banned), (name, sorted(imported & set(banned)))
