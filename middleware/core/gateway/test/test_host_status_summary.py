"""D-260 5: GET /api/v1/host/status-summary — one robot state for the operate view.

CORE applies the same rule table (core_common.robot_state) the boot display
applies, to boot-status.json, hardware.json (with CORE's overlays), the
battery and the runtime mode. Files live under tmp_path.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from core_api_web.api.app import create_app
from core_api_web.api.v1 import host as host_api
from core_common import robot_state

VIEWER_TOKEN = "viewer-token"
ADMIN_TOKEN = "admin-token"


def _config(tmp_path: Path, mode: str = "core") -> dict:
    (tmp_path / "run/rosy-boot").mkdir(parents=True, exist_ok=True)
    return {
        "auth": {"tokens": [{"token": VIEWER_TOKEN, "role": "viewer"},
                            {"token": ADMIN_TOKEN, "role": "administrator"}]},
        "runtime": {"mode": mode},
        "host_agent": {"socket_path": "/nonexistent/host-agent.sock", "timeout_s": 0.1},
        "hardware_probe": {"result_path": str(tmp_path / "run/rosy-boot/hardware.json"),
                           "boot_status_path": str(tmp_path / "run/rosy-boot/boot-status.json"),
                           "test_result_path": str(tmp_path / "run/rosy-boot/hw-test.json"),
                           "confirm_path": str(tmp_path / "home/.rosy/hw-confirmations.json")},
    }


class FakeState:
    def __init__(self, percent=None, voltage=None, evidence="fresh", mode=None, nav=None):
        self.percent, self.voltage, self.evidence, self.mode = percent, voltage, evidence, mode
        self.navigation = nav

    def snapshot(self):
        evidence = {} if self.evidence is None else {"battery": SimpleNamespace(evidence=self.evidence)}
        return SimpleNamespace(battery=SimpleNamespace(percent=self.percent, voltage=self.voltage),
                               evidence=evidence, mode=self.mode, navigation=self.navigation)


class FakeProbe:
    def __init__(self, value):
        self.value = value

    def temperature(self):
        return self.value


def _get(tmp_path: Path, *, mode: str = "core", token: str = VIEWER_TOKEN, **services):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    config = _config(tmp_path, mode)
    svc = SimpleNamespace(config=config, state=services.pop("state", None), **services)
    return TestClient(create_app(config, svc)).get(
        "/api/v1/host/status-summary", headers={"Authorization": f"Bearer {token}"} if token else {})


def _boot(tmp_path: Path, stage: str, **extra) -> None:
    path = tmp_path / "run/rosy-boot/boot-status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": stage, "device_name": "rosy", **extra}), encoding="utf-8")


def _device(device_id: str, state: str = "ok", product: bool = True, label: str | None = None) -> dict:
    return {"id": device_id, "label": label or device_id, "bus": "bus", "state": state, "evidence": "e",
            "product": product}


def _hardware(tmp_path: Path, devices: list[dict]) -> None:
    path = tmp_path / "run/rosy-boot/hardware.json"
    path.write_text(json.dumps({"schema": 1, "boot_id": "b", "devices": devices,
                                "measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                               ensure_ascii=False), encoding="utf-8")


def test_it_needs_a_token(tmp_path):
    assert _get(tmp_path, token="").status_code == 401


def test_a_viewer_reads_the_whole_summary(tmp_path):
    _boot(tmp_path, "CORE_READY")
    _hardware(tmp_path, [_device("motor.1"), _device("camera", "no_response", label="카메라 (OV5647)"),
                         _device("imu", "bus_missing", product=False),
                         _device("buzzer", "needs_human", product=False)])

    body = _get(tmp_path, mode="core", state=FakeState(81.4, 7.93),
                safety=SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=20.0)),
                runtime_probe=FakeProbe(51.2)).json()

    assert body["state"] == robot_state.CAUTION and body["label"] == "주의"
    assert body["state_line"] == "주의: 카메라 (OV5647) 응답 없음"
    assert body["motion_reason"] == host_api.MOTION_REASON["core"]
    assert body["boot"] == {"available": True, "stage": "CORE_READY"}
    assert body["devices"]["ok"] == 1 and body["devices"]["total"] == 4
    assert [item["id"] for item in body["devices"]["problems"]] == ["camera", "imu", "buzzer"]
    assert body["battery"] == {"percent": 81.4, "voltage": 7.93, "warning_percent": 20.0, "low": False}
    assert body["temperature_c"] == 51.2
    assert body["todos"] == [
        {"id": "camera_cable", "text": "카메라 케이블 확인", "device": "camera"},
        {"id": "promote_motor", "text": "관리자가 모터 모드로 승격"},
        {"id": "human_test", "text": "부저: 시험 동작으로 확인", "device": "buzzer"},
    ]


def test_the_summary_is_the_rule_table_s_answer_for_the_same_inputs(tmp_path):
    # One table, two readers: what CORE says must equal what the boot display computes.
    devices = [_device("adc.battery", "no_response"), _device("lamp", "needs_human", product=False)]
    _boot(tmp_path, "FAILED:rosy-core", failed_unit="rosy-core.service")
    _hardware(tmp_path, devices)

    body = _get(tmp_path, mode="hardware", state=FakeState(12.0, 6.6)).json()
    expected = robot_state.evaluate("FAILED:rosy-core", devices, battery_percent=12.0, runtime_mode="hardware",
                                    failed_unit="rosy-core.service")

    assert body["state"] == expected["state"] == robot_state.FAILED
    assert body["reason"] == expected["reason"] == "rosy-core"
    assert [item["text"] for item in body["todos"]] == [item["text"] for item in expected["todos"]]
    assert body["battery"]["low"] is True


def test_the_live_warning_threshold_is_used(tmp_path):
    _boot(tmp_path, "CORE_READY")
    safety = SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=40.0))

    body = _get(tmp_path, mode="hardware", state=FakeState(35.0, 7.1), safety=safety).json()

    assert body["state"] == robot_state.CAUTION and body["reason"] == "배터리 35 %"


def test_hardware_mode_with_nothing_wrong_is_ready(tmp_path):
    _boot(tmp_path, "CORE_READY")
    _hardware(tmp_path, [_device("motor.1"), _device("lidar")])

    body = _get(tmp_path, mode="hardware", state=FakeState(90.0, 8.1)).json()

    assert (body["state"], body["state_line"], body["todos"]) == (robot_state.READY, "준비됨", [])


def test_nothing_measured_yet_is_said_not_invented(tmp_path):
    # No boot-status.json, no hardware.json, no state, no probe: CORE is answering,
    # so the stage is taken as ready, and every missing value stays null.
    body = _get(tmp_path, mode="core").json()

    assert body["state"] == robot_state.READY_HELD
    assert body["boot"] == {"available": False, "stage": None}
    assert body["devices"] == {"available": False, "stale": False, "ok": 0, "total": 0, "problems": []}
    assert body["battery"] == {"percent": None, "voltage": None, "warning_percent": 20.0, "low": False}
    assert body["temperature_c"] is None


def test_a_battery_reading_whose_channel_is_not_fresh_is_none(tmp_path):
    _boot(tmp_path, "CORE_READY")

    body = _get(tmp_path, mode="hardware", state=FakeState(5.0, 6.1, evidence="delayed")).json()

    assert body["battery"]["percent"] is None and body["state"] == robot_state.READY


@pytest.mark.parametrize("content", [
    "not json", json.dumps([1]), json.dumps({"stage": 5}), json.dumps({"stage": ""}),
    json.dumps({"stage": "CORE_READY", "failed_unit": 7}), json.dumps({"stage": "x" * 300}),
])
def test_a_malformed_boot_status_is_not_trusted(tmp_path, content):
    (tmp_path / "run/rosy-boot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "run/rosy-boot/boot-status.json").write_text(content, encoding="utf-8")

    assert host_api.read_boot_status(str(tmp_path / "run/rosy-boot/boot-status.json")) is None


def test_an_oversized_boot_status_is_not_read(tmp_path):
    path = tmp_path / "boot-status.json"
    path.write_text(json.dumps({"stage": "CORE_READY", "pad": "x" * 9000}), encoding="utf-8")

    assert host_api.read_boot_status(str(path)) is None


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
def test_a_symlinked_boot_status_is_never_followed(tmp_path):
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"stage": "CORE_READY"}), encoding="utf-8")
    link = tmp_path / "boot-status.json"
    link.symlink_to(real)

    assert host_api.read_boot_status(str(link)) is None


def test_human_answers_reach_the_summary_through_the_card_overlay(tmp_path):
    # The summary reads the device rows through GET /host/hardware's overlays.
    _boot(tmp_path, "CORE_READY")
    _hardware(tmp_path, [_device("buzzer", "needs_human", product=False)])
    confirm = tmp_path / "home/.rosy/hw-confirmations.json"
    confirm.parent.mkdir(parents=True)
    confirm.write_text(json.dumps({"schema": 1, "devices": {"buzzer": {
        "observed": True, "by": "t", "label": "관리자", "at": "2026-09-26T05:00:00+00:00"}}}), encoding="utf-8")

    body = _get(tmp_path, mode="hardware").json()

    assert body["devices"]["ok"] == 1 and body["todos"] == []


def test_the_runtime_probe_reads_only_the_temperature(tmp_path):
    from core.system.runtime import HostRuntimeProbe

    zone = tmp_path / "sys/class/thermal/thermal_zone0"
    zone.mkdir(parents=True)
    (zone / "temp").write_text("48750\n", encoding="utf-8")
    probe = HostRuntimeProbe(host_root=tmp_path)

    assert probe.temperature() == 48.75
    assert probe._last_cpu is None  # the runtime card's CPU delta is untouched
    assert HostRuntimeProbe(host_root=tmp_path / "none").temperature() is None


# --- D-260 M1: the boot display evaluates the inputs CORE evaluates ----------------

REPO = Path(__file__).resolve().parents[4]
NATIVE = REPO / "deploy/robot/pinky_pro/native"


def _native(name: str, filename: str):
    import importlib.util
    import sys

    sys.path.insert(0, str(NATIVE))
    spec = importlib.util.spec_from_file_location(name, NATIVE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


READY_UNITS = {unit: "active" for unit in ("rosy-release-recover.service", "rosy-first-boot.service",
                                           "rosy-sd-provision.service", "rosy-core.service",
                                           "rosy-runtime.target")}


def _root_side(tmp_path: Path, battery_percent):
    """rosy-boot-status (root) copies CORE's hand-over; the display evaluates boot-status.json."""
    status = _native("rosy_boot_status_m1", "rosy-boot-status.py")
    display = _native("rosy_boot_display_m1", "rosy-face.py")
    (tmp_path / "etc/rosy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "etc/rosy/runtime.env").write_text("ROSY_RUNTIME_MODE=hardware\n", encoding="utf-8")
    (tmp_path / "var/lib/rosy/provisioning").mkdir(parents=True, exist_ok=True)
    (tmp_path / "var/lib/rosy/provisioning/state.json").write_text('{"state":"PROVISIONED"}', encoding="utf-8")

    def run(command):
        return READY_UNITS.get(command[-1], "") if command[:2] == ["systemctl", "show"] else ""

    facts = status.gather(tmp_path, run)
    stage = status.classify(facts["units"], facts["provisioning"])
    record = status.status_record(facts, stage, datetime.now(timezone.utc))
    (tmp_path / "run/rosy-boot/boot-status.json").write_text(json.dumps(record), encoding="utf-8")
    battery = None if battery_percent is None else (battery_percent, 7.4)
    return record, display.read_view(tmp_path, battery)


def _m1_config(tmp_path: Path) -> dict:
    config = _config(tmp_path, "hardware")
    (tmp_path / "run/rosy").mkdir(parents=True, exist_ok=True)
    config["hardware_probe"]["status_inputs_path"] = str(tmp_path / "run/rosy/status-inputs.json")
    return config


@pytest.mark.parametrize("case", ["live_threshold", "topic_overlay", "human_answer"])
def test_the_boot_display_and_the_summary_say_the_same_state(tmp_path, case):
    config = _m1_config(tmp_path)
    devices = [_device("motor.1"), _device("buzzer", "needs_human", product=False)]
    battery, evidence, warning = 80.0, "fresh", 20.0
    if case == "live_threshold":
        battery, warning = 35.0, 40.0  # the display's default 20 % would call this ready
    elif case == "topic_overlay":
        devices.append({**_device("adc.battery", "not_measured"), "held_by": "rosy-io.service"})
        battery, evidence = None, "delayed"  # CORE judges the held ADC silent from its topic
    else:
        confirm = tmp_path / "home/.rosy/hw-confirmations.json"
        confirm.parent.mkdir(parents=True)
        confirm.write_text(json.dumps({"schema": 1, "devices": {"buzzer": {
            "observed": True, "by": "t", "label": "관리자", "at": "2026-09-26T05:00:00+00:00"}}}), encoding="utf-8")
    _boot(tmp_path, "CORE_READY")
    _hardware(tmp_path, devices)
    svc = SimpleNamespace(config=config, state=FakeState(battery, 7.4, evidence=evidence),
                          safety=SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=warning)))

    host_api.write_status_inputs(svc)
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    summary = TestClient(create_app(config, svc)).get(
        "/api/v1/host/status-summary", headers={"Authorization": f"Bearer {VIEWER_TOKEN}"}).json()
    record, view = _root_side(tmp_path, battery)

    assert record["battery_warning_percent"] == warning
    assert view["robot_state"] == summary["state"]
    assert (view["todo"] is None) == (not summary["todos"])
    expected = {"live_threshold": robot_state.CAUTION, "topic_overlay": robot_state.CAUTION,
                "human_answer": robot_state.READY}[case]
    assert summary["state"] == expected
    if case == "human_answer":
        assert view["todo"] is None  # the confirmed buzzer asks nothing on the LCD either


SCHEMA_1_KEYS = {"schema", "written_at", "battery_warning_percent", "devices",
                 "robot_mode", "nav_state", "swarm_role"}
# D-412: what the device updater judges idleness from, without a token.
SCHEMA_2_KEYS = {"velocity_linear", "velocity_angular", "battery_percent", "battery_charging",
                 "docking_state", "line_follow_mode", "line_follow_state", "swarm_active", "estop",
                 "activity_kind"}


def test_the_status_inputs_carry_only_the_threshold_the_states_and_the_mode(tmp_path):
    config = _m1_config(tmp_path)
    _hardware(tmp_path, [_device("camera", "no_response", label="카메라")])
    svc = SimpleNamespace(config=config, state=FakeState(80.0, 8.0, mode="NAVIGATION", nav="BLOCKED"),
                          safety=SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=25.0)))

    host_api.write_status_inputs(svc)
    written = json.loads((tmp_path / "run/rosy/status-inputs.json").read_text(encoding="utf-8"))

    assert set(written) == SCHEMA_1_KEYS | SCHEMA_2_KEYS | {"calibration_active"}
    assert written["calibration_active"] is None  # missing service is unknown, not idle
    assert written["schema"] == 2
    assert written["battery_warning_percent"] == 25.0
    assert written["devices"] == [{"id": "camera", "state": "no_response", "product": True}]
    assert written["robot_mode"] == "NAVIGATION"
    assert written["nav_state"] == "BLOCKED"
    # D-383: additive like the modes — a state without a formation role is absent.
    assert written["swarm_role"] is None


@pytest.mark.parametrize("mode,nav", [(None, None), ("DRIVE", "LOST"), (3, 4), (True, False)])
def test_an_unknown_or_missing_mode_is_written_as_absent(tmp_path, mode, nav):
    # D-380/D-381: both are additive — a value outside the enums is absent, never guessed.
    config = _m1_config(tmp_path)
    svc = SimpleNamespace(config=config, state=FakeState(80.0, 8.0, mode=mode, nav=nav),
                          safety=SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=20.0)))

    host_api.write_status_inputs(svc)
    written = json.loads((tmp_path / "run/rosy/status-inputs.json").read_text(encoding="utf-8"))

    assert written["robot_mode"] is None and written["nav_state"] is None


def test_a_core_without_a_state_manager_writes_no_mode(tmp_path):
    config = _m1_config(tmp_path)
    svc = SimpleNamespace(config=config, state=None,
                          safety=SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=20.0)))

    host_api.write_status_inputs(svc)
    written = json.loads((tmp_path / "run/rosy/status-inputs.json").read_text(encoding="utf-8"))

    assert written["robot_mode"] is None
    # D-412: no snapshot means every idleness input is unknown, never a guessed "idle".
    assert {key: written[key] for key in SCHEMA_2_KEYS} == dict.fromkeys(SCHEMA_2_KEYS)


# --- D-412: schema 2 carries the idleness inputs from the robot/state snapshot ------


class SnapshotState:
    """A state manager double that hands out a real StateSnapshot (what GET /robot/state serves)."""

    def __init__(self, snapshot):
        self.value = snapshot

    def snapshot(self):
        return self.value


def _evidence(**channels) -> dict:
    """StateSnapshot.evidence with the given channel judgements (e.g. velocity="fresh")."""
    from core_common.protocol.evidence import ValueEvidence

    return {channel: ValueEvidence(evidence=judged) for channel, judged in channels.items()}


def _schema_2_written(tmp_path: Path, snapshot, devices=()) -> dict:
    config = _m1_config(tmp_path)
    _hardware(tmp_path, list(devices))
    svc = SimpleNamespace(config=config, state=SnapshotState(snapshot),
                          safety=SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=20.0)))
    host_api.write_status_inputs(svc)
    return json.loads((tmp_path / "run/rosy/status-inputs.json").read_text(encoding="utf-8"))


def test_schema_2_copies_the_idleness_inputs_from_the_state_snapshot(tmp_path):
    from core_common.protocol import schemas as s

    snapshot = s.StateSnapshot(
        robot_id="rosy_01", mode=s.RobotMode.MANUAL, navigation=s.NavigationState.NAVIGATING,
        velocity=s.Velocity(linear=0.12, angular=-0.5),
        battery=s.Battery(percent=63.5, voltage=7.6),
        battery_status=s.BatteryStatus(charging=True),
        docking=s.DockingStatus(state=s.DockState.DOCKED),
        safety=s.SafetySummary(estop=True),
        swarm=s.SwarmStatus(role=s.SwarmRole.LEADER, active=True),
        line_follow=s.LineFollowStatus(mode="FOLLOW", state="TRACKING"),
        activity=s.RobotActivity(session_id="c1", calibration_kind="camera", label="교정",
                                 owner=s.ActivityOwner(id="t"), started_at="2026-10-01T00:00:00+00:00",
                                 remaining_s=30.0),
        evidence=_evidence(velocity="fresh", battery="fresh"))

    written = _schema_2_written(tmp_path, snapshot)

    assert written["schema"] == 2
    assert {key: written[key] for key in SCHEMA_2_KEYS} == {
        "velocity_linear": 0.12, "velocity_angular": -0.5,
        "battery_percent": 63.5, "battery_charging": True,
        "docking_state": "DOCKED", "line_follow_mode": "FOLLOW", "line_follow_state": "TRACKING",
        "swarm_active": True, "estop": True, "activity_kind": "CALIBRATING"}
    # The schema-1 keys come from the same snapshot.
    assert written["robot_mode"] == "MANUAL" and written["nav_state"] == "NAVIGATING"
    assert written["swarm_role"] == "leader"


def test_schema_2_of_a_resting_robot_is_idle_and_unknown_battery_is_null(tmp_path):
    from core_common.protocol import schemas as s

    snapshot = s.StateSnapshot(robot_id="rosy_01", evidence=_evidence(velocity="fresh"))
    written = _schema_2_written(tmp_path, snapshot)

    assert {key: written[key] for key in SCHEMA_2_KEYS} == {
        "velocity_linear": 0.0, "velocity_angular": 0.0,
        "battery_percent": None, "battery_charging": None,
        "docking_state": "UNDOCKED", "line_follow_mode": "OFF", "line_follow_state": "OFF",
        "swarm_active": False, "estop": False, "activity_kind": None}


def test_one_write_reads_one_snapshot(tmp_path):
    # The updater pairs mode with velocity: both must describe the same instant.
    from core_common.protocol import schemas as s

    class CountingState(SnapshotState):
        calls = 0

        def snapshot(self):
            CountingState.calls += 1
            return self.value

    config = _m1_config(tmp_path)
    svc = SimpleNamespace(config=config, state=CountingState(s.StateSnapshot(robot_id="rosy_01")),
                          safety=SimpleNamespace(battery_policy=SimpleNamespace(warning_percent=20.0)))
    host_api.status_inputs(svc)

    assert CountingState.calls == 1


def test_a_battery_reading_that_is_not_fresh_is_written_as_unknown(tmp_path):
    # Same rule as the status summary: a delayed channel's last number is not a reading,
    # and the updater must never apply on a battery figure CORE itself distrusts.
    from core_common.protocol import schemas as s

    snapshot = s.StateSnapshot(robot_id="rosy_01", battery=s.Battery(percent=90.0, voltage=8.0))
    snapshot.evidence = {"battery": SimpleNamespace(evidence="delayed")}

    written = _schema_2_written(tmp_path, snapshot)

    assert written["battery_percent"] is None


@pytest.mark.parametrize("judged", ["delayed", "disconnected", "unavailable", None])
def test_a_velocity_that_is_not_fresh_is_written_as_unknown(tmp_path, judged):
    # A silent odometry keeps its last 0.0: that is not a measured stop, and an
    # updater reading it as one would restart a moving robot (false idle).
    from core_common.protocol import schemas as s

    evidence = {} if judged is None else _evidence(velocity=judged)
    snapshot = s.StateSnapshot(robot_id="rosy_01", evidence=evidence)

    written = _schema_2_written(tmp_path, snapshot)

    assert written["velocity_linear"] is None and written["velocity_angular"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_number_is_written_as_unknown(tmp_path, value):
    # json.dumps would write NaN/Infinity, which is not JSON and compares false to every bound.
    from core_common.protocol import schemas as s

    snapshot = s.StateSnapshot(robot_id="rosy_01", velocity=s.Velocity(linear=value, angular=value),
                               battery=s.Battery(percent=value),
                               evidence=_evidence(velocity="fresh", battery="fresh"))

    written = _schema_2_written(tmp_path, snapshot)

    assert written["velocity_linear"] is None and written["velocity_angular"] is None
    assert written["battery_percent"] is None


@pytest.mark.parametrize("percent,judged", [(None, "fresh"), (80.0, "delayed")])
def test_charging_is_unknown_whenever_the_battery_is(tmp_path, percent, judged):
    # The charging flag is a dock latch: without a battery reading it proves nothing.
    from core_common.protocol import schemas as s

    snapshot = s.StateSnapshot(robot_id="rosy_01", battery=s.Battery(percent=percent),
                               battery_status=s.BatteryStatus(charging=True),
                               evidence=_evidence(battery=judged))

    written = _schema_2_written(tmp_path, snapshot)

    assert written["battery_percent"] is None and written["battery_charging"] is None


@pytest.mark.parametrize("length,kept", [(64, True), (65, False)])
def test_a_free_string_longer_than_64_is_written_as_unknown(tmp_path, length, kept):
    from core_common.protocol import schemas as s

    text = "X" * length
    snapshot = s.StateSnapshot(robot_id="rosy_01", line_follow=s.LineFollowStatus(mode=text, state=text))
    snapshot.docking.state = text  # a duck-typed manager could hand any string over

    written = _schema_2_written(tmp_path, snapshot)
    expected = text if kept else None

    assert (written["line_follow_mode"], written["line_follow_state"], written["docking_state"]) == (
        expected, expected, expected)


@pytest.mark.parametrize("bad", [
    {"velocity": SimpleNamespace(linear="fast", angular=True)},
    {"battery_status": SimpleNamespace(charging="yes")},
    {"docking": SimpleNamespace(state=7), "line_follow": SimpleNamespace(mode=None, state=3)},
    {"swarm": SimpleNamespace(active=1), "safety": SimpleNamespace(estop="on")},
    {"activity": SimpleNamespace(kind=5)},
])
def test_a_malformed_snapshot_field_is_written_as_unknown_not_coerced(tmp_path, bad):
    # Fresh evidence and a battery reading, so each bad field meets its own type guard.
    snapshot = SimpleNamespace(mode=None, navigation=None, swarm=None,
                               battery=SimpleNamespace(percent=50.0, voltage=None),
                               evidence=_evidence(velocity="fresh", battery="fresh"), **{
        key: None for key in ("velocity", "battery_status", "docking", "line_follow", "safety", "activity")})
    for key, value in bad.items():
        setattr(snapshot, key, value)

    written = _schema_2_written(tmp_path, snapshot)

    assert {key: written[key] for key in SCHEMA_2_KEYS} == {**dict.fromkeys(SCHEMA_2_KEYS), "battery_percent": 50.0}


def test_schema_2_stays_well_under_the_reader_cap_and_the_reader_takes_it(tmp_path):
    # Worst case the root reader accepts: 64 devices with 64-character ids.
    from core_common.protocol import schemas as s

    status = _native("rosy_boot_status_d406a", "rosy-boot-status.py")
    devices = [_device(f"{index:02d}" + "d" * 62, "no_response", label="장치" * 8) for index in range(64)]
    snapshot = s.StateSnapshot(robot_id="rosy_01", mode=s.RobotMode.IDLE,
                               swarm=s.SwarmStatus(role=s.SwarmRole.FOLLOWER))

    _schema_2_written(tmp_path, snapshot, devices)
    path = tmp_path / "run/rosy/status-inputs.json"

    assert path.stat().st_size < status.MAX_STATUS_INPUTS_BYTES // 2
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o644
    assert status._core_inputs(tmp_path, datetime.now(timezone.utc)) == {
        "battery_warning_percent": 20.0,
        "devices": [{"id": device["id"], "state": "no_response", "product": True} for device in devices],
        "robot_mode": "IDLE", "nav_state": "IDLE", "swarm_role": "follower"}


@pytest.mark.parametrize("mutate", [
    lambda doc: doc.update(schema=3),
    lambda doc: doc.update(schema=0),
    lambda doc: doc.update(schema="2"),
    lambda doc: doc.update(schema=True),
    lambda doc: doc.update(written_at="2020-01-01T00:00:00+00:00"),  # CORE stopped writing
    lambda doc: doc.update(written_at="now"),
    lambda doc: doc.update(battery_warning_percent=0),
    lambda doc: doc.update(battery_warning_percent=True),
    lambda doc: doc.update(devices=[{"id": "camera", "state": "broken", "product": True}]),
])
def test_a_stale_or_malformed_hand_over_falls_back_to_the_probe_and_the_default(tmp_path, mutate):
    status = _native("rosy_boot_status_m1b", "rosy-boot-status.py")
    document = {"schema": 1, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "battery_warning_percent": 30.0, "devices": [{"id": "camera", "state": "ok", "product": True}]}
    mutate(document)
    (tmp_path / "run/rosy").mkdir(parents=True)
    (tmp_path / "run/rosy/status-inputs.json").write_text(json.dumps(document), encoding="utf-8")

    assert status._core_inputs(tmp_path, datetime.now(timezone.utc)) is None


def test_an_oversized_hand_over_is_not_read(tmp_path):
    status = _native("rosy_boot_status_m1c", "rosy-boot-status.py")
    (tmp_path / "run/rosy").mkdir(parents=True)
    (tmp_path / "run/rosy/status-inputs.json").write_text("x" * (17 * 1024), encoding="utf-8")

    assert status._core_inputs(tmp_path, datetime.now(timezone.utc)) is None


# --- D-380: CORE's robot mode rides the same hand-over ---------------------------


def _hand_over(tmp_path: Path, **extra) -> dict:
    document = {"schema": 1, "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "battery_warning_percent": 30.0, "devices": [{"id": "camera", "state": "ok", "product": True}],
                **extra}
    (tmp_path / "run/rosy").mkdir(parents=True)
    (tmp_path / "run/rosy/status-inputs.json").write_text(json.dumps(document), encoding="utf-8")
    return document


def test_the_hand_over_carries_the_robot_mode_to_the_record(tmp_path):
    status = _native("rosy_boot_status_m1d", "rosy-boot-status.py")
    _hand_over(tmp_path, robot_mode="NAVIGATION", nav_state="BLOCKED")

    inputs = status._core_inputs(tmp_path, datetime.now(timezone.utc))
    assert inputs["robot_mode"] == "NAVIGATION"
    assert inputs["nav_state"] == "BLOCKED"


def test_a_schema_2_hand_over_reads_exactly_like_schema_1(tmp_path):
    # D-412: the root reader accepts both; the added keys are the updater's, not the display's.
    status = _native("rosy_boot_status_d406b", "rosy-boot-status.py")
    shared = {"robot_mode": "IDLE", "nav_state": "IDLE", "swarm_role": "follower"}
    _hand_over(tmp_path, **shared)
    one = status._core_inputs(tmp_path, datetime.now(timezone.utc))
    (tmp_path / "run/rosy/status-inputs.json").unlink()
    (tmp_path / "run/rosy").rmdir()
    _hand_over(tmp_path, schema=2, velocity_linear=0.0, velocity_angular=0.0, battery_percent=70.0,
               battery_charging=False, docking_state="UNDOCKED", line_follow_mode="OFF",
               line_follow_state="OFF", swarm_active=False, estop=False, activity_kind=None, **shared)
    two = status._core_inputs(tmp_path, datetime.now(timezone.utc))

    assert one is not None
    assert two == one


@pytest.mark.parametrize("mode", [None, "DRIVE", "manual", 7, True])
def test_an_unknown_mode_is_copied_as_absent_but_keeps_the_rest(tmp_path, mode):
    # D-380: the mode is additive — unlike a bad warning or device row it drops only
    # itself, because a wrong-but-plausible mode is undetectable anyway and the
    # warning and devices are independently useful. D-381: the nav state too.
    status = _native("rosy_boot_status_m1e", "rosy-boot-status.py")
    _hand_over(tmp_path, robot_mode=mode, nav_state="LOST")

    inputs = status._core_inputs(tmp_path, datetime.now(timezone.utc))

    assert inputs["robot_mode"] is None and inputs["nav_state"] is None
    assert inputs["battery_warning_percent"] == 30.0
    assert inputs["devices"] == [{"id": "camera", "state": "ok", "product": True}]


def test_without_a_hand_over_the_record_carries_no_mode(tmp_path):
    status = _native("rosy_boot_status_m1f", "rosy-boot-status.py")
    # No run/rosy at all: CORE never wrote a hand-over, so the record has no mode.
    facts = status.gather(tmp_path, lambda command: "active\n" if command[:2] == ["systemctl", "show"] else "")

    assert facts["robot_mode"] is None and facts["nav_state"] is None
