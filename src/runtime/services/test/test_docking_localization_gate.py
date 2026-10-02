"""D-395 review item 1: the battery auto-dock obeys the LOCALIZED gate.

`on_battery_level` -> `_try_pending_return` -> `dock()` -> `navigate_to(staging)`
is a motion start no HTTP route sees. While the robot is not LOCALIZED the
return stays pending and resumes on the next tick once it is LOCALIZED again.
A robot without D-395 keeps the default provider (always allowed).
"""

from __future__ import annotations

import pytest

from core_common.protocol.schemas import BatteryLevel, DockState
from core_features.docking.database import DockError
from test_docking import a_manager, clock  # noqa: F401  (fixture re-export)


class _Loc:
    def __init__(self, ok: bool) -> None:
        self.ok = ok

    def __call__(self) -> bool:
        return self.ok


def test_not_localized_and_warning_battery_does_not_dock(clock):  # noqa: F811
    manager = a_manager(clock)
    manager.localization_ok = _Loc(False)
    manager.on_battery_level(BatteryLevel.WARNING)
    assert manager.state is DockState.UNDOCKED
    assert manager.return_pending is True
    assert manager.executor.goals == []


def test_the_pending_return_proceeds_once_localized_again(clock):  # noqa: F811
    manager = a_manager(clock)
    loc = manager.localization_ok = _Loc(False)
    manager.on_battery_level(BatteryLevel.WARNING)
    clock.advance(0.5)
    manager.tick()
    assert manager.state is DockState.UNDOCKED
    loc.ok = True
    clock.advance(0.5)
    manager.tick()
    assert manager.state is DockState.DOCKING
    assert manager.return_pending is False


def test_a_halt_during_the_dock_does_not_redock_until_localized(clock):  # noqa: F811
    manager = a_manager(clock)
    loc = manager.localization_ok = _Loc(True)
    manager.on_battery_level(BatteryLevel.WARNING)
    assert manager.state is DockState.DOCKING
    loc.ok = False
    manager.cancel()                                  # the localization halt
    manager.on_battery_level(BatteryLevel.WARNING)    # the next battery sample
    for _ in range(4):
        clock.advance(0.5)
        manager.tick()
    assert manager.state is DockState.UNDOCKED
    assert manager.return_pending is True
    loc.ok = True
    clock.advance(0.5)
    manager.tick()
    assert manager.state is DockState.DOCKING


def test_an_explicit_dock_is_refused_when_not_localized(clock):  # noqa: F811
    manager = a_manager(clock)
    manager.localization_ok = _Loc(False)
    with pytest.raises(DockError) as excinfo:
        manager.dock("dock_1")
    assert excinfo.value.code == "NOT_LOCALIZED"


def test_the_default_provider_keeps_todays_behaviour(clock):  # noqa: F811
    manager = a_manager(clock)
    manager.on_battery_level(BatteryLevel.WARNING)
    assert manager.state is DockState.DOCKING
