"""Heat mode: SoC, firmware throttle bits and wheel motors decide how fast the robot may drive."""
from types import SimpleNamespace

import pytest

from core.bridge import thermal_policy
from core.system.runtime import HostRuntimeProbe
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core_features.safety.thermal import HOT, OK, WARM, ThermalMonitor, ThermalPolicy
from core_features.state.manager import StateManager


def motors(temp, limit=72, error=0):
    return {"motors": [{"id": 1, "temperature_c": temp, "temperature_limit_c": limit,
                        "input_voltage_v": 12.0, "hardware_error": error}]}


def test_no_readings_is_ok_and_the_soc_raises_warm_then_hot():
    m = ThermalMonitor()
    assert m.update(None, None, 0.0) == OK                     # unknown is not hot
    assert m.update(60.0, 0, 1.0) == OK
    assert m.update(75.0, 0, 2.0) == WARM and m.reasons == ("soc_warm",)
    assert m.update(82.0, 0, 3.0) == HOT


def test_a_level_is_left_only_clear_c_below_its_threshold():
    m = ThermalMonitor()
    m.update(82.0, 0, 0.0)
    assert m.update(78.0, 0, 1.0) == HOT                       # 82 - 5 = 77 still holds hot
    assert m.update(76.0, 0, 2.0) == WARM
    assert m.update(71.0, 0, 3.0) == WARM                      # 75 - 5 = 70 still holds warm
    assert m.update(69.0, 0, 4.0) == OK


def test_a_motor_near_its_own_limit_or_reporting_overheating_is_judged_on_that_limit():
    m = ThermalMonitor()
    m.on_motor_health(motors(61), 0.0)
    assert m.update(50.0, 0, 0.0) == OK
    m.on_motor_health(motors(62), 1.0)
    assert m.update(50.0, 0, 1.0) == WARM and m.reasons == ("motor_1_warm",)
    m.on_motor_health(motors(68), 2.0)
    assert m.update(50.0, 0, 2.0) == HOT
    m = ThermalMonitor()
    m.on_motor_health(motors(40, error=0x04), 0.0)
    assert m.update(50.0, 0, 0.0) == HOT and "motor_1_overheating" in m.reasons


def test_a_stale_or_malformed_motor_sample_does_not_count():
    m = ThermalMonitor()
    m.on_motor_health(motors(70), 0.0)
    assert m.update(50.0, 0, 11.0) == OK                       # older than motor_stale_s
    m.on_motor_health({"motors": "x"}, 12.0)
    m.on_motor_health(motors(True, limit="72"), 12.0)          # bool and str are not numbers
    assert m.update(50.0, 0, 12.0) == OK


def test_firmware_throttling_or_under_voltage_now_is_warm_and_since_boot_is_not():
    m = ThermalMonitor()
    assert m.update(50.0, 0x1, 0.0) == WARM and m.reasons == ("under_voltage",)
    assert m.update(50.0, 0x50000, 1.0) == OK                  # 16-19: happened earlier, not now


def test_policy_comes_from_safety_config_and_rejects_inverted_thresholds():
    assert ThermalPolicy.from_config({"thermal": {"soc_warm_c": 70}}).soc_warm_c == 70.0
    with pytest.raises(ValueError):
        ThermalPolicy(soc_warm_c=85.0, soc_hot_c=80.0)


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


def test_a_hot_motor_that_stops_answering_holds_the_level_until_a_fresh_reading_is_cool():
    m = ThermalMonitor()
    m.on_motor_health(motors(69), 0.0)
    assert m.update(50.0, 0, 0.0) == HOT
    assert m.update(50.0, 0, 11.0) == HOT and "readings_lost" in m.reasons     # stale
    assert m.update(50.0, 0, 30.0) == HOT                                       # still no reading
    m.on_motor_health(motors(None), 31.0)                                       # bus answers nothing
    assert m.update(50.0, 0, 31.0) == HOT
    m.on_motor_health(motors(55), 32.0)
    assert m.update(50.0, 0, 32.0) == OK


def test_a_lost_soc_reading_holds_a_level_the_soc_raised():
    m = ThermalMonitor()
    m.update(83.0, 0, 0.0)
    assert m.update(None, None, 1.0) == HOT and "readings_lost" in m.reasons
    assert m.update(60.0, 0, 2.0) == OK


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
