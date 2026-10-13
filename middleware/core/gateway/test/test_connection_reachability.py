"""D-535: GET /api/v1/auth/connection is the LAN reachability read — public facts only, rate-limited."""

from fastapi.testclient import TestClient

from core_common.protocol.connect_reason import REASONS


def _reason(response, status):
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] in REASONS and error["message"] and error["detail"]["action"]
    return error["code"]


def test_connection_reports_reachability_without_secrets(core_client, tmp_path, monkeypatch):
    status = tmp_path / "boot-status.json"
    status.write_text('{"stage": "CORE_READY", "release_id": "2026.10.08-055", "failed_unit": null}')
    original, _ = core_client(config_overrides={"hardware_probe": {"boot_status_path": str(status)}})
    client = TestClient(original.app, base_url="http://192.168.1.10", client=("192.168.1.20", 1234))
    body = client.get("/api/v1/auth/connection").json()
    assert set(body) == {"mode", "robot_id", "transport", "connect_contract", "api", "core_ready", "stage",
                         "release", "tls_hostname", "pairing"}
    assert body["connect_contract"] == 1 and body["api"] == "v1"
    assert (body["core_ready"], body["stage"], body["release"]) == (True, "CORE_READY", "2026.10.08-055")
    assert (body["transport"], body["tls_hostname"], body["pairing"]) == ("http", None, "unavailable")
    status.write_text('{"stage": "WAITING_CORE", "failed_unit": null}')
    later = client.get("/api/v1/auth/connection").json()
    assert (later["core_ready"], later["stage"], later["release"]) == (False, "WAITING_CORE", None)


def test_connection_is_lan_only_and_rate_limited(core_client):
    original, _ = core_client()
    outside = TestClient(original.app, client=("8.8.8.8", 1234))
    assert _reason(outside.get("/api/v1/auth/connection"), 403) == "LAN_REQUIRED"
    client = TestClient(original.app, base_url="http://192.168.1.10", client=("192.168.1.21", 1234))
    for _ in range(30):
        assert client.get("/api/v1/auth/connection").status_code == 200
    limited = client.get("/api/v1/auth/connection")
    assert _reason(limited, 429) == "RATE_LIMITED"
    assert int(limited.headers["retry-after"]) >= 1
    other = TestClient(original.app, base_url="http://192.168.1.10", client=("192.168.1.22", 1234))
    assert other.get("/api/v1/auth/connection").status_code == 200
