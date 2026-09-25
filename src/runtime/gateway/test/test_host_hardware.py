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
                           "request_path": str(tmp_path / "run/rosy/hw-probe.request"),
                           "test_request_path": str(tmp_path / "run/rosy/hw-test.request"),
                           "test_result_path": str(tmp_path / "run/rosy-boot/hw-test.json"),
                           "confirm_path": str(tmp_path / "home/.rosy/hw-confirmations.json")},
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
    host_api._last_test.clear()
    yield
    host_api._last_refresh.clear()
    host_api._last_test.clear()


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
    lambda doc: doc.update(devices=[_device("camera"), _device("camera", "no_response")]),
    lambda doc: doc.update(boot_id="b" * 65),
    lambda doc: doc.update(boot_id=7),
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

    def __init__(self, *, velocity="unavailable", battery="unavailable", voltage=None, lidar_at=None,
                 ultrasonic_at=None):
        self.evidence = {"velocity": SimpleNamespace(evidence=velocity),
                         "battery": SimpleNamespace(evidence=battery)}
        self.voltage = voltage
        self.samples = {"lidar": lidar_at, "ultrasonic": ultrasonic_at}
        self.snapshots = 0

    def snapshot(self):
        self.snapshots += 1
        return SimpleNamespace(evidence=self.evidence, battery=SimpleNamespace(voltage=self.voltage))

    def get_sensor(self, key):
        at = self.samples.get(key)
        return {"received_at": at} if at is not None else None


def _held(device_id: str) -> dict:
    return _device(device_id, "not_measured", held_by="rosy-io.service")


def test_rows_rosy_io_holds_are_judged_from_fresh_topics(tmp_path):
    import time

    state = FakeState(velocity="fresh", battery="fresh", voltage=8.49, lidar_at=time.time(),
                      ultrasonic_at=time.time())
    _write(tmp_path, [_held("motor.1"), _held("motor.2"), _held("lidar"), _held("adc.battery"),
                      _held("adc.ir0"), _held("adc.ultrasonic"), _device("camera", "no_response")])
    body = _client(_config(tmp_path, "hardware"), state).get(
        "/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    rows = {row["id"]: row for row in body["devices"]}

    assert rows["motor.1"]["state"] == rows["motor.2"]["state"] == "ok"
    assert rows["motor.1"]["evidence"] == "odom 수신 중 (토픽 판정)"
    assert rows["adc.battery"]["evidence"] == "8.49 V (토픽 판정)"
    assert rows["lidar"]["state"] == "ok" and rows["lidar"]["source"] == "topic"
    assert rows["adc.ultrasonic"]["state"] == "ok" and rows["adc.ultrasonic"]["evidence"].startswith("us_range")
    # CORE has no IR topic: the row stays not_measured and says who holds the bus.
    assert rows["adc.ir0"]["state"] == "not_measured" and "source" not in rows["adc.ir0"]
    assert rows["adc.ir0"]["evidence"] == "측정 안 함 — rosy-io 사용 중"
    assert state.snapshots == 1, "one snapshot per request"
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
    assert response.json()["error"]["code"] == "HW_PROBE_UNAVAILABLE"


def test_the_api_runs_no_subprocess_for_hardware():
    source = Path(host_api.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in source and "subprocess." not in source
    assert '"systemctl"' not in source


# --- D-247 6: buzzer / lamp test and the person's answer ----------------------------

HW_TEST = Path(__file__).resolve().parents[4] / "deploy/robot/native/rosy-hw-test.py"


def _human_rows(tmp_path: Path, buzzer="needs_human", lamp="needs_human") -> None:
    _write(tmp_path, [_device("buzzer", buzzer, product=False), _device("lamp", lamp, product=False),
                      _device("camera", "no_response")])


def _tested(tmp_path: Path, device: str, state: str = "done", age_s: float = 5.0,
            request_id: str = "fedcba9876543210") -> None:
    """What rosy-hw-test leaves after testing `device`, `age_s` seconds ago."""
    finished = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    (tmp_path / "run/rosy-boot").mkdir(parents=True, exist_ok=True)
    (tmp_path / "run/rosy-boot/hw-test.json").write_text(json.dumps({
        "schema": 1, "request_id": request_id, "action": device, "state": state, "detail": "d",
        "finished_at": finished.isoformat(timespec="seconds")}), encoding="utf-8")


def test_only_an_administrator_can_start_a_test(tmp_path):
    client = _client(_config(tmp_path))
    for token in (VIEWER_TOKEN, OPERATOR_TOKEN):
        response = client.post("/api/v1/host/hardware/test", json={"device": "buzzer"}, headers=_auth(token))
        assert response.status_code == 403
    assert not (tmp_path / "run/rosy/hw-test.request").exists()


def test_a_test_writes_the_request_rosy_hw_test_accepts(tmp_path):
    spec = importlib.util.spec_from_file_location("rosy_hw_test_for_core", HW_TEST)
    program = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(program)

    response = _client(_config(tmp_path)).post("/api/v1/host/hardware/test", json={"device": "lamp"},
                                               headers=_auth(ADMIN_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True and body["device"] == "lamp" and "보였는지" in body["detail"]
    path = tmp_path / "run/rosy/hw-test.request"
    request = program.read_request(path)
    assert request is not None, path.read_text(encoding="utf-8")
    assert request["action"] == "lamp" and request["request_id"] == body["request_id"]
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".hw-test")]


def test_rosy_hw_tests_outcome_passes_cores_validation(tmp_path):
    spec = importlib.util.spec_from_file_location("rosy_hw_test_outcome", HW_TEST)
    program = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(program)

    class Quiet(program.System):
        def unit_state(self, unit):
            return "inactive"

        def beep(self, pin):
            return None

    config = _config(tmp_path)
    _client(config).post("/api/v1/host/hardware/test", json={"device": "buzzer"}, headers=_auth(ADMIN_TOKEN))
    root = tmp_path / "root"
    (root / "run/rosy").mkdir(parents=True)
    (root / "run/rosy/hw-test.request").write_bytes((tmp_path / "run/rosy/hw-test.request").read_bytes())
    assert program.main(["--root", str(root)], system=Quiet(root), group=lambda _name: None) == 0
    outcome = host_api.read_test_result(str(root / "run/rosy-boot/hw-test.json"))
    assert outcome is not None and outcome["state"] == "done" and outcome["action"] == "buzzer"


def test_a_second_test_inside_the_cool_down_is_its_own_error(tmp_path):
    client = _client(_config(tmp_path))
    assert client.post("/api/v1/host/hardware/test", json={"device": "buzzer"},
                       headers=_auth(ADMIN_TOKEN)).status_code == 200
    again = client.post("/api/v1/host/hardware/test", json={"device": "lamp"}, headers=_auth(ADMIN_TOKEN))
    assert again.status_code == 429
    assert again.json()["error"]["code"] == "HW_TEST_COOLDOWN"
    request = json.loads((tmp_path / "run/rosy/hw-test.request").read_text(encoding="utf-8"))
    assert request["action"] == "buzzer"


@pytest.mark.parametrize("body", [{"device": "motor.1"}, {"device": "lamp", "extra": 1}, {}])
def test_a_test_only_names_the_buzzer_or_the_lamp(tmp_path, body):
    response = _client(_config(tmp_path)).post("/api/v1/host/hardware/test", json=body,
                                               headers=_auth(ADMIN_TOKEN))
    assert response.status_code in (400, 422)
    assert not (tmp_path / "run/rosy/hw-test.request").exists()


def test_a_test_without_cores_runtime_directory_is_a_503(tmp_path):
    config = _config(tmp_path)
    config["hardware_probe"]["test_request_path"] = str(tmp_path / "missing/hw-test.request")
    response = _client(config).post("/api/v1/host/hardware/test", json={"device": "buzzer"},
                                    headers=_auth(ADMIN_TOKEN))
    assert response.status_code == 503 and response.json()["error"]["code"] == "HW_TEST_UNAVAILABLE"
    # A failed write does not start the cool-down.
    config["hardware_probe"]["test_request_path"] = str(tmp_path / "run/rosy/hw-test.request")
    assert _client(config).post("/api/v1/host/hardware/test", json={"device": "buzzer"},
                                headers=_auth(ADMIN_TOKEN)).status_code == 200


def test_the_card_shows_the_last_test_outcome(tmp_path):
    _human_rows(tmp_path)
    (tmp_path / "run/rosy-boot/hw-test.json").write_text(json.dumps({
        "schema": 1, "request_id": "0123456789abcdef", "action": "buzzer", "state": "busy",
        "detail": "부팅 표시가 BCM 4 부저를 쓰는 중", "started_at": "2026-09-26T05:00:00+00:00",
        "finished_at": "2026-09-26T05:00:01+00:00"}, ensure_ascii=False), encoding="utf-8")
    body = _client(_config(tmp_path)).get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    assert body["test"] == {"request_id": "0123456789abcdef", "action": "buzzer", "state": "busy",
                            "detail": "부팅 표시가 BCM 4 부저를 쓰는 중",
                            "finished_at": "2026-09-26T05:00:01+00:00"}


@pytest.mark.parametrize("mutate", [
    lambda doc: doc.update(schema=2),
    lambda doc: doc.update(action="motor"),
    lambda doc: doc.update(state="ok"),
    lambda doc: doc.update(detail="x" * 201),
    lambda doc: doc.update(finished_at="2026-09-26T05:00:01"),
])
def test_a_malformed_test_outcome_is_not_shown(tmp_path, mutate):
    document = {"schema": 1, "request_id": "0123456789abcdef", "action": "lamp", "state": "done",
                "detail": "d", "finished_at": "2026-09-26T05:00:01+00:00"}
    mutate(document)
    path = tmp_path / "hw-test.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    assert host_api.read_test_result(str(path)) is None


def test_only_an_administrator_can_record_an_answer(tmp_path):
    client = _client(_config(tmp_path))
    _tested(tmp_path, "buzzer")
    for token in (VIEWER_TOKEN, OPERATOR_TOKEN):
        response = client.post("/api/v1/host/hardware/confirm", json={"device": "buzzer", "observed": True},
                               headers=_auth(token))
        assert response.status_code == 403
    assert not (tmp_path / "home/.rosy/hw-confirmations.json").exists()


def test_heard_and_not_seen_turn_the_rows_into_ok_and_no_response(tmp_path):
    _human_rows(tmp_path)
    client = _client(_config(tmp_path))
    _tested(tmp_path, "buzzer")
    heard = client.post("/api/v1/host/hardware/confirm", json={"device": "buzzer", "observed": True},
                        headers=_auth(ADMIN_TOKEN))
    assert heard.status_code == 200
    record = heard.json()
    assert record["recorded"] is True and record["observed"] is True and record["device"] == "buzzer"
    assert record["by"] and record["at"].endswith("+00:00")
    assert "request_id" not in record
    _tested(tmp_path, "lamp", request_id="0011223344556677")
    assert client.post("/api/v1/host/hardware/confirm", json={"device": "lamp", "observed": False},
                       headers=_auth(ADMIN_TOKEN)).status_code == 200

    stored = json.loads((tmp_path / "home/.rosy/hw-confirmations.json").read_text(encoding="utf-8"))
    assert stored["schema"] == 1 and set(stored["devices"]) == {"buzzer", "lamp"}
    assert set(stored["devices"]["buzzer"]) == {"observed", "by", "label", "at", "request_id"}
    assert stored["devices"]["buzzer"]["request_id"] == "fedcba9876543210"
    assert stored["devices"]["lamp"]["request_id"] == "0011223344556677"
    assert not [p for p in (tmp_path / "home/.rosy").iterdir() if p.name.startswith(".")]

    rows = {row["id"]: row for row in client.get("/api/v1/host/hardware",
                                                  headers=_auth(VIEWER_TOKEN)).json()["devices"]}
    assert rows["buzzer"]["state"] == "ok" and rows["buzzer"]["source"] == "human"
    assert rows["buzzer"]["evidence"].startswith("사람 확인: ") and rows["buzzer"]["evidence"].endswith(" UTC")
    assert rows["lamp"]["state"] == "no_response"
    assert rows["lamp"]["evidence"].startswith("사람 확인: 보이지 않음")
    assert rows["camera"]["state"] == "no_response" and "source" not in rows["camera"]
    assert not any("fedcba9876543210" in row["evidence"] for row in rows.values())


def test_a_later_answer_replaces_the_earlier_one(tmp_path):
    _human_rows(tmp_path)
    client = _client(_config(tmp_path))
    _tested(tmp_path, "buzzer")
    for observed in (False, True):
        client.post("/api/v1/host/hardware/confirm", json={"device": "buzzer", "observed": observed},
                    headers=_auth(ADMIN_TOKEN))
    rows = {row["id"]: row for row in client.get("/api/v1/host/hardware",
                                                  headers=_auth(VIEWER_TOKEN)).json()["devices"]}
    assert rows["buzzer"]["state"] == "ok"
    assert rows["lamp"]["state"] == "needs_human"


def test_an_answer_never_hides_a_missing_driver(tmp_path):
    _human_rows(tmp_path, lamp="driver_missing")
    client = _client(_config(tmp_path))
    _tested(tmp_path, "lamp")
    client.post("/api/v1/host/hardware/confirm", json={"device": "lamp", "observed": True},
                headers=_auth(ADMIN_TOKEN))
    rows = {row["id"]: row for row in client.get("/api/v1/host/hardware",
                                                  headers=_auth(VIEWER_TOKEN)).json()["devices"]}
    assert rows["lamp"]["state"] == "driver_missing"


@pytest.mark.parametrize("body", [{"device": "buzzer", "observed": "yes"}, {"device": "buzzer"},
                                  {"device": "camera", "observed": True},
                                  {"device": "lamp", "observed": True, "by": "someone"}])
def test_an_answer_is_strictly_typed(tmp_path, body):
    response = _client(_config(tmp_path)).post("/api/v1/host/hardware/confirm", json=body,
                                               headers=_auth(ADMIN_TOKEN))
    assert response.status_code in (400, 422)


def test_an_unwritable_state_directory_is_its_own_error(tmp_path):
    config = _config(tmp_path)
    _tested(tmp_path, "lamp")
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory", encoding="utf-8")
    config["hardware_probe"]["confirm_path"] = str(blocker / "hw-confirmations.json")
    response = _client(config).post("/api/v1/host/hardware/confirm", json={"device": "lamp", "observed": True},
                                    headers=_auth(ADMIN_TOKEN))
    assert response.status_code == 503 and response.json()["error"]["code"] == "HW_CONFIRM_UNAVAILABLE"


def test_an_answer_without_a_test_is_a_409(tmp_path):
    _human_rows(tmp_path)
    response = _client(_config(tmp_path)).post("/api/v1/host/hardware/confirm",
                                               json={"device": "buzzer", "observed": True},
                                               headers=_auth(ADMIN_TOKEN))
    assert response.status_code == 409 and response.json()["error"]["code"] == "HW_CONFIRM_NO_TEST"
    assert not (tmp_path / "home/.rosy/hw-confirmations.json").exists()


@pytest.mark.parametrize("device,state,age_s", [
    ("buzzer", "busy", 5.0),
    ("buzzer", "unavailable", 5.0),
    ("buzzer", "failed", 5.0),
    ("lamp", "done", 5.0),       # the last test was the other device
    ("buzzer", "done", 301.0),   # stale
    ("buzzer", "done", -60.0),   # finished in the future
])
def test_an_answer_needs_a_recent_finished_test_of_that_device(tmp_path, device, state, age_s):
    _human_rows(tmp_path)
    _tested(tmp_path, device, state=state, age_s=age_s)
    client = _client(_config(tmp_path))
    response = client.post("/api/v1/host/hardware/confirm", json={"device": "buzzer", "observed": True},
                           headers=_auth(ADMIN_TOKEN))
    assert response.status_code == 409 and response.json()["error"]["code"] == "HW_CONFIRM_NO_TEST"
    assert not (tmp_path / "home/.rosy/hw-confirmations.json").exists()
    rows = {row["id"]: row for row in client.get("/api/v1/host/hardware",
                                                  headers=_auth(VIEWER_TOKEN)).json()["devices"]}
    assert rows["buzzer"]["state"] == "needs_human"


def test_concurrent_tests_accept_only_one(tmp_path):
    import threading

    from core_api_web.api.errors import ApiError

    svc = SimpleNamespace(config=_config(tmp_path), state=None)
    auth = SimpleNamespace(token_id="t", label="")
    barrier = threading.Barrier(8)
    outcomes: list[str] = []

    def press():
        barrier.wait()
        try:
            host_api.host_hardware_test(host_api.HardwareTestRequest(device="buzzer"), auth, svc)
            outcomes.append("accepted")
        except ApiError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=press) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["HW_TEST_COOLDOWN"] * 7 + ["accepted"]


def test_concurrent_answers_keep_both_devices(tmp_path):
    import threading

    config = _config(tmp_path)
    svc = SimpleNamespace(config=config, state=None)
    auth = SimpleNamespace(token_id="t", label="")
    confirm_path = config["hardware_probe"]["confirm_path"]
    real_read = host_api.read_test_result
    barrier = threading.Barrier(2)

    def fresh(device):
        return {"request_id": f"{device}-run", "action": device, "state": "done", "detail": "d",
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def answer(device):
        barrier.wait()
        host_api.host_hardware_confirm(host_api.HardwareConfirmRequest(device=device, observed=True), auth, svc)

    lookups = {}
    host_api.read_test_result = lambda _path: fresh(lookups[threading.current_thread().name])
    try:
        threads = []
        for device in ("buzzer", "lamp"):
            thread = threading.Thread(target=answer, args=(device,), name=f"answer-{device}")
            lookups[thread.name] = device
            threads.append(thread)
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    finally:
        host_api.read_test_result = real_read
    stored = host_api.read_confirmations(confirm_path)
    assert set(stored) == {"buzzer", "lamp"}
    assert stored["lamp"]["request_id"] == "lamp-run"


def test_a_corrupt_answer_file_is_ignored_not_trusted(tmp_path):
    _human_rows(tmp_path)
    path = tmp_path / "home/.rosy/hw-confirmations.json"
    path.parent.mkdir(parents=True)
    for text in ("not json", json.dumps({"schema": 1, "devices": {"buzzer": {"observed": "yes", "by": "a",
                                                                               "label": "", "at": "x"}}})):
        path.write_text(text, encoding="utf-8")
        assert host_api.read_confirmations(str(path)) == {}
    body = _client(_config(tmp_path)).get("/api/v1/host/hardware", headers=_auth(VIEWER_TOKEN)).json()
    assert {row["id"]: row["state"] for row in body["devices"]}["buzzer"] == "needs_human"


def test_the_default_answer_file_is_beside_cores_other_state():
    svc = SimpleNamespace(config={})
    request, result, confirm = host_api._test_paths(svc)
    assert request == "/run/rosy/hw-test.request" and result == "/run/rosy-boot/hw-test.json"
    assert Path(confirm) == Path.home() / ".rosy" / "hw-confirmations.json"


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
    # The shell split (D-262) moved the card rendering into host-cards.js.
    script = "\n".join((WEB / name).read_text(encoding="utf-8") for name in ("app.js", "host-cards.js"))
    assert 'api("/api/v1/host/hardware")' in script
    assert '"/api/v1/host/hardware/refresh", {method: "POST"}' in script
    for text in ("정상", "응답 없음", "버스 없음", "드라이버 없음", "사람 확인 필요", "측정 안 함", "벤치 전용"):
        assert f'"{text}"' in script, text
    # host-cards.js hands the reason to the shell through onCommissioningRendered.
    assert 'onCommissioningRendered(payload.motion_reason || "")' in script
    assert "session.motionReason = reason" in script
    assert 'setEnabled("hardware-refresh", isAdmin())' in script
    # No raw colour for the chips: they reuse the shared [data-status] vocabulary.
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    device_rules = css.split("D-247 장치 카드")[1].split("\n\n")[0]
    assert "#" not in device_rules.split("*/", 1)[1] and "rgb" not in device_rules


def test_the_script_wires_the_buzzer_and_lamp_test_for_administrators_only():
    # The shell split (D-262) moved the card rendering into host-cards.js.
    script = "\n".join((WEB / name).read_text(encoding="utf-8") for name in ("app.js", "host-cards.js"))
    assert '"/api/v1/host/hardware/test", {method: "POST", body: JSON.stringify({device})}' in script
    assert '"/api/v1/host/hardware/confirm", {method: "POST", body: JSON.stringify({device, observed})}' in script
    for text in ("울려 보기", "켜 보기", "들림", "안 들림", "보임", "안 보임"):
        assert f'"{text}"' in script, text
    actions = script.split("function humanTestActions")[1].split("\nfunction ")[0]
    assert "!isAdmin()" in actions
    assert "innerHTML" not in actions and "outerHTML" not in actions
    assert "textContent = test.detail" in actions
    # The card is read until it shows this request's outcome, bounded, not after a fixed pause.
    assert "const HW_TEST_WAIT_MS = 12000;" in script
    wait = script.split("async function waitForHardwareTest")[1].split("\n}\n")[0]
    assert "payload?.test?.request_id !== requestId && Date.now() < deadline" in wait
    assert "waitForHardwareTest(reply.request_id)" in script
    assert "setTimeout(resolve, 4000)" not in script


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
