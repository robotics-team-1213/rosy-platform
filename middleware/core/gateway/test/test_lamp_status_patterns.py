"""Persistent status lamp control at the CORE API boundary."""

from core_api_web.api.v1 import host_hardware


VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}
OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
PATH = "/api/v1/host/lamp/status-patterns"


def test_status_patterns_roles_persistence_and_strict_request(core_client, tmp_path, monkeypatch):
    client, svc = core_client()
    path = tmp_path / "lamp" / "status-patterns.json"
    path.parent.mkdir()
    monkeypatch.setattr("core.system.host_files.LAMP_STATUS_FILE", str(path))

    assert client.get(PATH, headers=VIEWER).json() == {"status_patterns": "on", "available": True}
    assert client.put(PATH, json={"status_patterns": "off"}, headers=VIEWER).status_code == 403
    assert client.put(PATH, json={"status_patterns": "off", "extra": 1}, headers=OPERATOR).status_code == 422
    svc.state.set_velocity(0.0, 0.0)
    response = client.put(PATH, json={"status_patterns": "off"}, headers=OPERATOR)
    assert response.status_code == 200
    assert response.json() == {"status_patterns": "off", "available": True}
    assert client.get(PATH, headers=VIEWER).json() == response.json()
    assert path.exists()


def test_off_refused_during_manual_and_on_remains_allowed(core_client, tmp_path, monkeypatch):
    client, svc = core_client()
    path = tmp_path / "lamp" / "status-patterns.json"
    path.parent.mkdir()
    monkeypatch.setattr("core.system.host_files.LAMP_STATUS_FILE", str(path))
    svc.state.set_velocity(0.0, 0.0)
    assert client.post("/api/v1/mode", json={"mode": "MANUAL"}, headers=OPERATOR).status_code == 200
    refused = client.put(PATH, json={"status_patterns": "off"}, headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LAMP_BUSY"
    assert client.put(PATH, json={"status_patterns": "on"}, headers=OPERATOR).status_code == 200
