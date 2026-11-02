"""Heat mode: SoC, firmware throttle bits and wheel motors decide how fast the robot may drive."""
from types import SimpleNamespace

import pytest

from core.bridge import thermal_policy
from core.system.runtime import HostRuntimeProbe
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core_features.safety.thermal import HOT, OK, ThermalPolicy
from core_features.state.manager import StateManager


@pytest.fixture
def robot():
    events, soc = [], {"c": 50.0}
    bus = SimpleNamespace(publish=lambda t, severity=None, source=None, data=None: events.append((t, severity)))
    manager = SafetyManager(SpeedLimits(max_linear=0.20, max_angular=0.80, manual_linear=0.15,
                                        manual_angular=0.60), BatteryPolicy(), events=bus)
    probe = SimpleNamespace(temperature=lambda: soc["c"], throttled=lambda: 0)
    state = StateManager("rosy_45")
    return SimpleNamespace(safety=manager, runtime_probe=probe, events=bus, state=state), soc, events


def test_warm_halves_linear_and_hot_stops_autonomy_but_lets_an_operator_nudge(robot):
    services, soc, events = robot
    manager = services.safety
    assert manager.clip(0.2, 0.5, "nav") == pytest.approx((0.2, 0.5))
    soc["c"] = 76.0
    thermal_policy.tick(services, 0.0)
    assert manager.clip(0.2, 0.5, "nav")[0] == pytest.approx(0.1)
    soc["c"] = 83.0
    thermal_policy.tick(services, 1.0)
    assert manager.clip(0.2, 0.5, "nav") == (0.0, 0.0)
    assert manager.clip(0.2, 0.5, "fleet") == (0.0, 0.0)
    assert manager.clip(0.15, 0.3, "manual")[0] == pytest.approx(0.075)
    thermal_policy.tick(services, 2.0)                          # no change, no event
    soc["c"] = 60.0
    thermal_policy.tick(services, 3.0)
    assert manager.clip(0.2, 0.5, "nav") == pytest.approx((0.2, 0.5))
    assert [e for e in events if e[0].startswith("thermal.")] == [
        ("thermal.warm", "warning"), ("thermal.hot", "critical"), ("thermal.ok", "info")]
    assert not manager.estop                                    # heat never latches


def test_the_bridge_feeds_motor_health_into_the_level(robot):
    services, _, _ = robot
    thermal_policy.on_motor_health(services, "not json", 0.0)
    thermal_policy.on_motor_health(services, '{"motors": [{"id": 2, "temperature_c": 69, '
                                             '"temperature_limit_c": 72, "hardware_error": 0}]}', 0.0)
    assert thermal_policy.tick(services, 1.0) == HOT
    assert services.safety.thermal.status()["motors"][0]["id"] == 2


def test_core_services_take_the_thermal_policy_from_safety_config(core_client):
    _, svc = core_client()
    assert svc.safety.thermal.policy == ThermalPolicy.from_config(svc.config.get("safety") or {})


def test_the_probe_reads_firmware_throttle_bits(tmp_path):
    path = tmp_path / "sys/devices/platform/soc/soc:firmware"
    path.mkdir(parents=True)
    (path / "get_throttled").write_text("0x50005\n", encoding="utf-8")
    assert HostRuntimeProbe(host_root=tmp_path).throttled() == 0x50005
    assert HostRuntimeProbe(host_root=tmp_path / "none").throttled() is None


def test_a_failing_evaluation_is_logged_and_never_raises_into_the_diagnostics_tick(robot):
    services, _, _ = robot
    services.runtime_probe = SimpleNamespace(temperature=lambda: 1 / 0, throttled=lambda: 0)
    assert thermal_policy.tick(services, 0.0) is None
    assert services.safety.thermal.level == OK


def test_the_state_snapshot_carries_the_heat_level_and_an_estop_keeps_it(robot):
    services, soc, _ = robot
    soc["c"] = 83.0
    thermal_policy.tick(services, 0.0)
    assert services.state.snapshot().safety.thermal == HOT
    services.state.set_estop(True, "api:operator")
    safety = services.state.snapshot().safety
    assert (safety.estop, safety.source, safety.thermal) == (True, "api:operator", HOT)
    soc["c"] = 60.0
    thermal_policy.tick(services, 1.0)
    assert services.state.snapshot().safety.thermal == OK and services.state.snapshot().safety.estop
