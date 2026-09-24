"""Real-value assertions on the `display/info` decisions (PWR-003).

These lived inline in `ros_bridge.py`, which host pytest cannot import, so a
wrong rounding or a wrong fallback address reached the screen with CI green.
Duck-typed inputs, no rclpy — the same shape as `test_bridge_translate.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.bridge import display


def _snapshot(percent=87.6543, voltage=7.8912, estop=False):
    return SimpleNamespace(
        battery=SimpleNamespace(percent=percent, voltage=voltage),
        robot_id="rosy_01",
        mode=SimpleNamespace(value="IDLE"),
        navigation=SimpleNamespace(value="ARRIVED"),
        safety=SimpleNamespace(estop=estop),
        hitl_requested=False,
    )


def _status(reason="proximity", presence="NEAR"):
    return SimpleNamespace(last_wake_reason=reason,
                           presence=SimpleNamespace(value=presence))


def test_payload_rounds_to_the_widths_the_screen_has():
    payload = display.info_payload(
        _snapshot(), _status(), health="OK",
        address="http://10.0.0.4:8080", hold_s=12.3456)

    assert payload["battery_percent"] == 87.7
    assert payload["battery_voltage"] == 7.89
    assert payload["hold_s"] == 12.3


def test_missing_voltage_stays_none_and_never_becomes_zero():
    """0.00 V on the screen reads as a dead battery. Absent must look absent."""
    payload = display.info_payload(
        _snapshot(voltage=None), _status(), health="OK", address="x", hold_s=0.0)

    assert payload["battery_voltage"] is None


def test_payload_carries_every_field_the_screen_renders():
    payload = display.info_payload(
        _snapshot(estop=True), _status(reason="cmd_vel", presence="CONTACT"),
        health="DEGRADED", address="http://rosy-01:8080", hold_s=3.0)

    assert payload == {
        "battery_percent": 87.7,
        "battery_voltage": 7.89,
        "robot_id": "rosy_01",
        "mode": "IDLE",
        "navigation": "ARRIVED",
        "health": "DEGRADED",
        "estop": True,
        "address": "http://rosy-01:8080",
        "reason": "cmd_vel",
        "presence": "CONTACT",
        "hold_s": 3.0,
        "hitl_requested": False,
    }


def test_payload_carries_hitl_request_to_the_robot_face():
    snapshot = _snapshot()
    snapshot.hitl_requested = True

    payload = display.info_payload(
        snapshot, _status(), health="DEGRADED", address="x", hold_s=1.0)

    assert payload["hitl_requested"] is True


def test_address_prefers_the_routed_interface():
    assert display.api_address(8080, "10.0.0.4", "rosy-01") == "http://10.0.0.4:8080"


def test_address_falls_back_to_the_hostname_when_there_is_no_route():
    """Offline, the operator is standing at the robot — a name they can type
    beats a blank line."""
    assert display.api_address(8080, None, "rosy-01") == "http://rosy-01:8080"


def test_port_from_yaml_may_be_a_string():
    assert display.api_address("8080", "10.0.0.4", "rosy-01") == "http://10.0.0.4:8080"


def test_resolve_wires_the_two_lookups_without_touching_the_network():
    resolved = display.resolve_api_address(
        8080, hostname=lambda: "rosy-01", probe=lambda: "192.168.1.7")
    assert resolved == "http://192.168.1.7:8080"

    offline = display.resolve_api_address(
        8080, hostname=lambda: "rosy-01", probe=lambda: None)
    assert offline == "http://rosy-01:8080"


# --- republish (the decision `_INFO_REPUBLISH_S` used to guard inline) -------

def test_the_info_window_republishes_on_the_rising_edge():
    """The screen holds no state: opening the window must paint it at once."""
    assert display.republish_due(True, was_visible=False,
                                 now=100.0, last_pub=0.0) is True


def test_an_open_window_republishes_only_at_the_interval():
    assert display.republish_due(True, was_visible=True,
                                 now=100.9, last_pub=100.0) is False
    assert display.republish_due(True, was_visible=True,
                                 now=101.0, last_pub=100.0) is True


def test_a_closed_window_never_republishes():
    assert display.republish_due(False, was_visible=True,
                                 now=1e9, last_pub=0.0) is False


def test_the_republish_interval_is_one_second():
    assert display.REPUBLISH_S == 1.0
