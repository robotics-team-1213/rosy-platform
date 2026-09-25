"""D-247: the board device card API and the operate view's motion reason.

rosy-hw-probe (root) writes /run/rosy-boot/hardware.json; CORE reads it as
strictly as the login verifier and asks for a new run by writing a request
file into its own /run/rosy. Here both paths are under tmp_path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from core_api_web.api.app import create_app
from core_api_web.api.v1 import host as host_api

VIEWER_TOKEN = "viewer-token"
OPERATOR_TOKEN = "operator-token"
ADMIN_TOKEN = "admin-token"
PROBE = Path(__file__).resolve().parents[4] / "deploy/robot/native/rosy-hw-probe.py"
POSIX = pytest.mark.skipif(os.name != "posix", reason="symlinks and FIFOs")


def _config(tmp_path: Path, mode: str = "core") -> dict:
    (tmp_path / "run/rosy-boot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "run/rosy").mkdir(parents=True, exist_ok=True)
    return {
        "auth": {"tokens": [
            {"token": VIEWER_TOKEN, "role": "viewer"},
            {"token": OPERATOR_TOKEN, "role": "operator"},
            {"token": ADMIN_TOKEN, "role": "administrator"},
        ]},
        "runtime": {"mode": mode},
        "host_agent": {"socket_path": "/nonexistent/host-agent.sock", "timeout_s": 0.1},
        "hardware_probe": {"result_path": str(tmp_path / "run/rosy-boot/hardware.json"),
                           "request_path": str(tmp_path / "run/rosy/hw-probe.request")},
    }


def _client(config: dict, state=None):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    return TestClient(create_app(config, SimpleNamespace(config=config, state=state)))


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _device(device_id: str, state: str = "ok", **extra) -> dict:
    return {"id": device_id, "label": device_id, "bus": "bus", "state": state, "evidence": "e",
            "product": True, **extra}


def _write(tmp_path: Path, devices: list[dict], *, measured_at: str | None = None, **top) -> Path:
    path = tmp_path / "run/rosy-boot/hardware.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"schema": 1, "boot_id": "b", "devices": devices,
                "measured_at": measured_at or datetime.now(timezone.utc).isoformat(timespec="seconds"), **top}
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_refresh_memory():
    host_api._last_refresh.clear()
    yield
    host_api._last_refresh.clear()


# --- GET /api/v1/host/hardware ----------------------------------------------------


def test_no_result_yet_is_said_in_korean_not_blanked(tmp_path):
    body = _client(_config(tmp_path)).get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    assert body == {"available": False, "detail": "장치 점검 결과가 아직 없습니다", "devices": []}


def test_a_viewer_reads_every_row_with_its_age(tmp_path):
    measured = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(timespec="seconds")
    _write(tmp_path, [_device("camera", "no_response"), _device("imu", "bus_missing", product=False)],
           measured_at=measured)
    body = _client(_config(tmp_path)).get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()

    assert body["available"] is True and body["schema"] == 1 and body["detail"] == ""
    assert 89 <= body["age_s"] <= 120
    assert body["stale"] is False
    assert body["measured_at"] == measured
    assert [(row["id"], row["state"], row["product"]) for row in body["devices"]] == [
        ("camera", "no_response", True), ("imu", "bus_missing", False)]


def test_an_old_result_is_marked_stale_by_the_server(tmp_path):
    measured = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    _write(tmp_path, [_device("camera")], measured_at=measured)
    body = _client(_config(tmp_path)).get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    assert body["stale"] is True


def test_the_card_needs_a_token(tmp_path):
    response = _client(_config(tmp_path)).get("/api/v1/host/hardware")
    assert response.status_code == 401


@pytest.mark.parametrize("mutate", [
    lambda doc: doc.update(schema=2),
    lambda doc: doc.update(measured_at="2026-09-25T10:00:00"),  # no zone
    lambda doc: doc.update(measured_at="yesterday"),
    lambda doc: doc.update(devices=[]),
    lambda doc: doc["devices"][0].update(state="broken"),
    lambda doc: doc["devices"][0].update(product="yes"),
    lambda doc: doc["devices"][0].update(evidence="x" * 201),
    lambda doc: doc["devices"][0].update(label=None),
    lambda doc: doc["devices"][0].update(held_by=5),
    lambda doc: doc.update(devices=[_device(f"d{i}") for i in range(65)]),
])
def test_a_malformed_result_is_unreadable_not_trusted(tmp_path, mutate):
    document = {"schema": 1, "boot_id": "b", "measured_at": "2026-09-25T10:00:00+00:00",
                "devices": [_device("camera")]}
    mutate(document)
    (tmp_path / "run/rosy-boot").mkdir(parents=True)
    path = tmp_path / "run/rosy-boot/hardware.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert host_api.read_hardware(str(path)) is None


def test_an_oversized_or_non_json_result_is_unreadable(tmp_path):
    body = _client(_config(tmp_path))
    path = tmp_path / "run/rosy-boot/hardware.json"
    path.write_text(" " * (host_api.MAX_HARDWARE_BYTES + 1), encoding="utf-8")
    assert body.get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json() == {
        "available": False, "detail": "장치 점검 결과를 읽을 수 없습니다", "devices": []}
    path.write_text("not json", encoding="utf-8")
    assert host_api.read_hardware(str(path)) is None


@POSIX
def test_a_symlinked_or_fifo_result_is_never_followed(tmp_path):
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({"schema": 1}), encoding="utf-8")
    config = _config(tmp_path)
    path = tmp_path / "run/rosy-boot/hardware.json"
    path.symlink_to(elsewhere)
    body = _client(config).get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    assert body["available"] is False and body["detail"] == "장치 점검 결과를 읽을 수 없습니다"
    path.unlink()
    os.mkfifo(path)
    assert host_api.read_hardware(str(path)) is None


def test_the_probe_output_passes_cores_validation(tmp_path):
    spec = importlib.util.spec_from_file_location("rosy_hw_probe_for_core", PROBE)
    probe = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = probe
    spec.loader.exec_module(probe)
    rows = [probe.Row(device_id, state, "근거") for device_id, state in
            zip(probe.DEVICE_IDS, list(probe.STATES) * 3)]
    rows[0].held_by = "rosy-io.service"
    config = _config(tmp_path)
    (tmp_path / "run/rosy-boot/hardware.json").write_text(
        json.dumps(probe.document(rows, tmp_path), ensure_ascii=False), encoding="utf-8")

    body = _client(config).get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    assert body["available"] is True
    assert [row["id"] for row in body["devices"]] == list(probe.DEVICE_IDS)
    assert body["devices"][0]["held_by"] == "rosy-io.service"


# --- topic overlay while rosy-io holds the buses ------------------------------------


class FakeState:
    """The two StateManager reads the overlay uses: snapshot().evidence/battery and get_sensor.

    A fake, not StateManager, so this API test stays inside the gateway (D-184).
    """

    def __init__(self, *, velocity="unavailable", battery="unavailable", voltage=None, lidar_at=None):
        self.evidence = {"velocity": SimpleNamespace(evidence=velocity),
                         "battery": SimpleNamespace(evidence=battery)}
        self.voltage = voltage
        self.lidar_at = lidar_at

    def snapshot(self):
        return SimpleNamespace(evidence=self.evidence, battery=SimpleNamespace(voltage=self.voltage))

    def get_sensor(self, key):
        return {"received_at": self.lidar_at} if key == "lidar" and self.lidar_at is not None else None


def _held(device_id: str) -> dict:
    return _device(device_id, "not_measured", held_by="rosy-io.service")


def test_rows_rosy_io_holds_are_judged_from_fresh_topics(tmp_path):
    import time

    state = FakeState(velocity="fresh", battery="fresh", voltage=8.49, lidar_at=time.time())
    _write(tmp_path, [_held("motor.1"), _held("motor.2"), _held("lidar"), _held("adc.battery"),
                      _held("adc.ir0"), _device("camera", "no_response")])
    body = _client(_config(tmp_path, "hardware"), state).get(
        "/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    rows = {row["id"]: row for row in body["devices"]}

    assert rows["motor.1"]["state"] == rows["motor.2"]["state"] == "ok"
    assert rows["motor.1"]["evidence"] == "odom 수신 중 (토픽 판정)"
    assert rows["adc.battery"]["evidence"] == "8.49 V (토픽 판정)"
    assert rows["lidar"]["state"] == "ok" and rows["lidar"]["source"] == "topic"
    # No topic for the IR channels: the probe's word stands.
    assert rows["adc.ir0"]["state"] == "not_measured" and "source" not in rows["adc.ir0"]
    assert rows["camera"]["state"] == "no_response"


def test_stale_topics_turn_held_rows_into_no_response(tmp_path):
    import time

    state = FakeState(velocity="delayed", battery="disconnected", lidar_at=time.time() - 30.0)
    _write(tmp_path, [_held("motor.1"), _held("lidar"), _held("adc.battery")])
    body = _client(_config(tmp_path, "hardware"), state).get(
        "/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    rows = {row["id"]: row for row in body["devices"]}

    assert rows["motor.1"]["state"] == "no_response" and rows["motor.1"]["evidence"] == "odom delayed (토픽 판정)"
    assert rows["lidar"]["state"] == "no_response" and "끊김" in rows["lidar"]["evidence"]
    assert rows["adc.battery"]["state"] == "no_response"


def test_a_probe_measurement_is_never_overwritten_by_topics(tmp_path):
    state = FakeState(velocity="fresh")
    _write(tmp_path, [_device("motor.1", "no_response")])
    body = _client(_config(tmp_path, "hardware"), state).get(
        "/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    assert body["devices"][0]["state"] == "no_response"


# --- POST /api/v1/host/hardware/refresh ---------------------------------------------


def test_only_an_administrator_can_ask_for_a_new_probe(tmp_path):
    client = _client(_config(tmp_path))
    for token in (VIEWER_TOKEN, OPERATOR_TOKEN):
        assert client.post("/api/v1/host/hardware/refresh", headers=_auth(token)).status_code == 403
    assert not (tmp_path / "run/rosy/hw-probe.request").exists()


def test_refresh_writes_the_request_file_once_per_window(tmp_path):
    client = _client(_config(tmp_path))
    first = client.post("/api/v1/host/hardware/refresh", headers=_auth(ADMIN_TOKEN))
    assert first.status_code == 200 and first.json()["accepted"] is True
    request = json.loads((tmp_path / "run/rosy/hw-probe.request").read_text(encoding="utf-8"))
    assert set(request) == {"requested_at", "by"}
    assert not [path for path in (tmp_path / "run/rosy").iterdir() if path.name.startswith(".hw-probe")]

    again = client.post("/api/v1/host/hardware/refresh", headers=_auth(ADMIN_TOKEN)).json()
    assert again["accepted"] is False and "잠시 뒤" in again["detail"]


def test_refresh_without_cores_runtime_directory_is_a_503(tmp_path):
    config = _config(tmp_path)
    config["hardware_probe"]["request_path"] = str(tmp_path / "missing/hw-probe.request")
    response = _client(config).post("/api/v1/host/hardware/refresh", headers=_auth(ADMIN_TOKEN))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "HARDWARE_NOT_READY"


def test_the_api_runs_no_subprocess_for_hardware():
    source = Path(host_api.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source and "subprocess." not in source
    assert '"systemctl"' not in source


# --- the dashboard wiring (the Chromium checks are optional; these always run) -----

WEB = Path(__file__).resolve().parents[3] / "hmi" / "dashboard"


def test_the_inspect_view_has_the_device_card_after_commissioning():
    markup = (WEB / "index.html").read_text(encoding="utf-8")
    inspect = markup.split('id="view-inspect-panel"')[1]
    assert inspect.index('id="commissioning-card"') < inspect.index('id="hardware-card"') \
        < inspect.index('id="field-settings-panel"')
    card = inspect.split('id="hardware-card"')[1].split("</article>")[0]
    assert '<h3 id="hardware-heading">장치</h3>' in card
    assert 'id="hardware-refresh" data-role="administrator" disabled' in card


def test_the_script_renders_six_states_and_the_motion_reason():
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'api("/api/v1/host/hardware")' in script
    assert '"/api/v1/host/hardware/refresh", {method: "POST"}' in script
    for text in ("정상", "응답 없음", "버스 없음", "드라이버 없음", "사람 확인 필요", "측정 안 함", "벤치 전용"):
        assert f'"{text}"' in script, text
    assert "session.motionReason = payload.motion_reason" in script
    assert 'setEnabled("hardware-refresh", isAdmin())' in script
    # No raw colour for the chips: they reuse the shared [data-status] vocabulary.
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    device_rules = css.split("D-247 장치 카드")[1].split("\n\n")[0]
    assert "#" not in device_rules.split("*/", 1)[1] and "rgb" not in device_rules


# --- /commissioning: why the robot cannot move -------------------------------------


@pytest.mark.parametrize("mode,expected", [
    ("core", "모터가 꺼진 CORE 전용 모드입니다. 관리자가 모터 모드로 올려야 움직입니다."),
    ("motor", "LiDAR"),
    ("hardware", ""),
])
def test_commissioning_says_why_the_robot_cannot_move(tmp_path, mode, expected):
    body = _client(_config(tmp_path, mode)).get("/api/v1/host/commissioning", headers=_auth(VIEWER_TOKEN)).json()
    assert body["runtime_mode"] == mode
    if expected:
        assert expected in body["motion_reason"]
    else:
        assert body["motion_reason"] == ""
    # Not a permission sentence (D-247 7).
    assert "권한" not in body["motion_reason"]
    for key in ("motor_hold", "lidar_hold", "battery_hold", "imu_hold", "slam_hold", "fleet_hold", "detail"):
        assert key in body
