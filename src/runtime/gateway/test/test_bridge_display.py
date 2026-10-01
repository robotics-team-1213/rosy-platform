"""Real-value assertions on the `display/info` decisions (PWR-003).

These lived inline in `ros_bridge.py`, which host pytest cannot import, so a
wrong rounding or a wrong fallback address reached the screen with CI green.
Duck-typed inputs, no rclpy — the same shape as `test_bridge_translate.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.bridge import display


def _snapshot(percent=87.6543, voltage=7.8912, estop=False, charging=False,
              mode="IDLE", navigation="ARRIVED", speed=0.2367, docking_state=None):
    return SimpleNamespace(
        battery=SimpleNamespace(percent=percent, voltage=voltage),
        battery_status=SimpleNamespace(charging=charging),
        robot_id="rosy_01",
        mode=SimpleNamespace(value=mode),
        navigation=SimpleNamespace(value=navigation),
        velocity=SimpleNamespace(linear=speed, angular=0.0),
        docking=SimpleNamespace(state=docking_state),
        safety=SimpleNamespace(estop=estop),
        hitl_requested=False,
        activity=None,
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
        "charging": False,
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
        "activity": None,
    }


def test_payload_carries_hitl_request_to_the_robot_face():
    snapshot = _snapshot()
    snapshot.hitl_requested = True

    payload = display.info_payload(
        snapshot, _status(), health="DEGRADED", address="x", hold_s=1.0)

    assert payload["hitl_requested"] is True


def test_payload_carries_the_calibration_activity_to_the_robot_face():
    snapshot = _snapshot()
    snapshot.activity = SimpleNamespace(kind="CALIBRATING", label="drive")

    payload = display.info_payload(
        snapshot, _status(), health="OK", address="x", hold_s=1.0)

    assert payload["activity"] == "CALIBRATING"


def test_charging_reads_the_confirmed_status_not_the_raw_reading():
    """D-351: the screen shows the D-27 confirmed-charging judgment
    (`battery_status.charging`), not a probe of the raw `Battery` reading —
    that model carries only percent/voltage, so the old getattr default
    answered False forever and the screen could never say charging."""
    payload = display.info_payload(
        _snapshot(charging=True), _status(), health="OK", address="x", hold_s=0.0)

    assert payload["charging"] is True


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


# --- D-394: the drive card ---------------------------------------------------


def test_the_drive_card_is_due_only_while_operating_and_slowly():
    # IDLE(및 모름)에서는 얼굴이 주인이다 — 카드는 아무 때도 아니다.
    assert display.drive_due("IDLE", now=100.0, last_pub=None) is False
    assert display.drive_due(None, now=100.0, last_pub=None) is False
    # 운용 중: 처음엔 곧, 그 뒤로는 20 s 마다.
    assert display.drive_due("MANUAL", now=100.0, last_pub=None) is True
    assert display.drive_due("MANUAL", now=100.0, last_pub=95.0) is False
    assert display.drive_due("MANUAL", now=121.0, last_pub=100.0) is True
    # EMERGENCY 도 운용이다: 무엇에 멈춰 있는지가 읽혀야 한다.
    assert display.drive_due("EMERGENCY", now=100.0, last_pub=None) is True


def test_the_drive_payload_names_its_kind_and_rounds_like_the_wake_card():
    payload = display.drive_payload(_snapshot(mode="NAVIGATION", navigation="NAVIGATING"))

    assert payload["kind"] == "drive"
    assert payload["mode"] == "NAVIGATION"
    assert payload["navigation"] == "NAVIGATING"
    assert payload["speed"] == 0.24          # 0.01 m/s — 웨이크 카드와 같은 계약
    assert payload["battery_percent"] == 87.7
    assert payload["battery_voltage"] == 7.89
    assert payload["estop"] is False
    assert payload["hold_s"] == 5.0


def test_a_missing_speed_stays_none_because_zero_reads_as_stopped():
    payload = display.drive_payload(_snapshot(speed=None, mode="MANUAL"))

    assert payload["speed"] is None


def test_the_drive_card_carries_the_charging_flag():
    charging = display.drive_payload(_snapshot(mode="DOCKING", charging=True))
    discharging = display.drive_payload(_snapshot(mode="MANUAL", charging=False))

    assert charging["charging"] is True
    assert discharging["charging"] is False


def test_the_drive_card_carries_the_goal_only_while_navigating():
    payload = display.drive_payload(_snapshot(mode="NAVIGATION"), goal_x=1.234, goal_y=4.567)
    assert payload["goal_x"] == 1.23
    assert payload["goal_y"] == 4.57

    # NAVIGATION 이 아니면 목표는 실리지 않는다 — 모드가 곧 맥락이다.
    manual = display.drive_payload(_snapshot(mode="MANUAL"), goal_x=1.234, goal_y=4.567)
    assert manual["goal_x"] is None and manual["goal_y"] is None


def test_the_drive_card_carries_the_docking_state():
    payload = display.drive_payload(_snapshot(mode="DOCKING", docking_state="CHARGING"))
    assert payload["docking_state"] == "CHARGING"

    # 도킹이 아니면 None — 모드가 곧 맥락이다
    manual = display.drive_payload(_snapshot(mode="MANUAL"))
    assert manual["docking_state"] is None
