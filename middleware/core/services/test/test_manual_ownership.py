"""D-442 U1: services own manual admission, expiry and commit races."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


@pytest.fixture
def command_rig():
    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety)
    return SimpleNamespace(command=command, modes=modes, safety=safety)


@pytest.mark.parametrize("release", ["clear", "expire"])
def test_mode_machine_refuses_navigation_until_manual_session_ends(command_rig, monkeypatch, release):
    svc = command_rig
    assert svc.modes.transition(Mode.MANUAL)[0]
    assert svc.command.teleop(0.1, 0.0)[0]
    assert not svc.modes.can_transition(Mode.NAVIGATION)
    assert not svc.modes.transition(Mode.NAVIGATION)[0]
    if release == "clear":
        svc.command.clear_manual()
    else:
        expired_at = svc.command.watchdog._last_refresh + 1.0
        monkeypatch.setattr("core_features.safety.manager.time.monotonic", lambda: expired_at)
    assert not svc.command.manual_active
    assert svc.modes.can_transition(Mode.NAVIGATION)
    assert svc.modes.transition(Mode.NAVIGATION)[0]


@pytest.mark.parametrize("target", [Mode.IDLE, Mode.EMERGENCY])
def test_stop_can_always_leave_live_manual(command_rig, target):
    svc = command_rig
    assert svc.modes.transition(Mode.MANUAL)[0]
    assert svc.command.teleop(0.1, 0.0)[0]
    assert svc.modes.transition(target)[0]


def test_teleop_cannot_commit_after_navigation_took_an_expired_session(command_rig, monkeypatch):
    svc = command_rig
    assert svc.modes.transition(Mode.MANUAL)[0]
    entered, proceed = Event(), Event()
    original_clip = svc.safety.clip

    def paused_clip(*args, **kwargs):
        entered.set()
        assert proceed.wait(5)
        return original_clip(*args, **kwargs)

    monkeypatch.setattr(svc.safety, "clip", paused_clip)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(svc.command.teleop, 0.1, 0.0)
        try:
            assert entered.wait(5)
            assert svc.modes.transition(Mode.NAVIGATION)[0]
        finally:
            proceed.set()
        assert pending.result(timeout=5) == (False, "MODE_CONFLICT")
    assert svc.modes.mode is Mode.NAVIGATION
    assert not svc.command.manual_active
