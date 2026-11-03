"""Heat mode decisions: SoC, firmware throttle bits and wheel motors -> ok/warm/hot, with hysteresis."""
import pytest

from core_features.safety.thermal import HOT, OK, WARM, ThermalMonitor, ThermalPolicy


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


@pytest.mark.parametrize("missing", ["temperature_c", "temperature_limit_c", "motor"])
def test_a_cool_second_motor_cannot_clear_a_hot_motor_with_missing_evidence(missing):
    m = ThermalMonitor()
    hot, cool = motors(77, limit=80)["motors"][0], {**motors(40, limit=80)["motors"][0], "id": 2}
    m.on_motor_health({"motors": [hot, cool]}, 0.0)
    assert m.update(50.0, 0, 0.0) == HOT
    partial = {**hot, missing: None}
    for now in (1.0, 2.0):
        m.on_motor_health({"motors": [cool] if missing == "motor" else [partial, cool]}, now)
        assert m.update(50.0, 0, now) == HOT
        assert "motor_1_hot" in m.reasons and "readings_lost" in m.reasons
        assert m.caps(.2, .8, "nav") == (0.0, 0.0)
        if missing != "motor":
            assert m.status()["motors"][0][missing] is None
    m.on_motor_health({"motors": [{**hot, "temperature_c": 60}, cool]}, 3.0)
    assert m.update(50.0, 0, 3.0) == OK
    assert "readings_lost" not in m.reasons


def test_a_missing_warm_source_does_not_hold_another_sources_cleared_hot_level():
    m = ThermalMonitor()
    hot = motors(77, limit=80)["motors"][0]
    warm = {**motors(72, limit=80)["motors"][0], "id": 2}
    m.on_motor_health({"motors": [hot, warm]}, 0.0)
    assert m.update(50.0, 0, 0.0) == HOT
    m.on_motor_health({"motors": [{**hot, "temperature_c": 40}, {**warm, "temperature_c": None}]}, 1.0)
    assert m.update(50.0, 0, 1.0) == WARM
    assert "motor_2_warm" in m.reasons and "motor_1_hot" not in m.reasons
    assert m.caps(.2, .8, "nav") == pytest.approx((.1, .8))
    m.on_motor_health({"motors": [{**hot, "temperature_c": 40}, {**warm, "temperature_c": 40}]}, 2.0)
    assert m.update(50.0, 0, 2.0) == OK


@pytest.mark.parametrize("error,level,reason", [(0x04, HOT, "overheating"), (0x01, WARM, "input_voltage")])
def test_motor_fault_needs_its_own_fresh_error_register_to_clear(error, level, reason):
    m = ThermalMonitor()
    fault = motors(40, limit=80, error=error)["motors"][0]
    cool = {**motors(40, limit=80)["motors"][0], "id": 2}
    m.on_motor_health({"motors": [fault, cool]}, 0.0)
    assert m.update(50.0, 0, 0.0) == level
    m.on_motor_health({"motors": [{**fault, "hardware_error": None}, cool]}, 1.0)
    assert m.update(50.0, 0, 1.0) == level
    assert f"motor_1_{reason}" in m.reasons and "readings_lost" in m.reasons
    assert m.status()["motors"][0]["hardware_error"] is None
    m.on_motor_health({"motors": [{**fault, "hardware_error": 0}, cool]}, 2.0)
    assert m.update(50.0, 0, 2.0) == OK


def test_a_missing_warm_soc_does_not_hold_a_cleared_motor_hot_level():
    m = ThermalMonitor()
    m.on_motor_health(motors(77, limit=80), 0.0)
    assert m.update(76.0, 0, 0.0) == HOT
    m.on_motor_health(motors(40, limit=80), 1.0)
    assert m.update(None, 0, 1.0) == WARM
    assert "soc_warm" in m.reasons and "motor_1_hot" not in m.reasons
