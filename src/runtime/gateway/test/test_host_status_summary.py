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
    def __init__(self, percent=None, voltage=None, evidence="fresh"):
        self.percent, self.voltage, self.evidence = percent, voltage, evidence

    def snapshot(self):
        evidence = {} if self.evidence is None else {"battery": SimpleNamespace(evidence=self.evidence)}
        return SimpleNamespace(battery=SimpleNamespace(percent=self.percent, voltage=self.voltage),
                               evidence=evidence)


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
