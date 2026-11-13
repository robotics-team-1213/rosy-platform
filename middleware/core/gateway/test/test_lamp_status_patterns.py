"""Persistent status lamp control at the CORE API boundary."""

import pytest


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
    assert client.put(PATH, json={"status_patterns": "off", "extra": 1}, headers=OPERATOR).status_code == 400
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


@pytest.mark.parametrize("condition", ["driving", "no_odometry", "motion_reserved", "trip_lease", "manual_active"])
def test_off_refused_for_each_busy_condition(core_client, tmp_path, monkeypatch, condition):
    client, svc = core_client()
    path = tmp_path / "lamp" / "status-patterns.json"
    path.parent.mkdir()
    monkeypatch.setattr("core.system.host_files.LAMP_STATUS_FILE", str(path))
    if condition != "no_odometry":
        svc.state.set_velocity(0.0, 0.0)
    if condition == "driving":
        svc.state.set_velocity(0.2, 0.0)
    elif condition == "motion_reserved":
        assert svc.modes.reserve_idle_motion()
    elif condition == "trip_lease":
        opened = client.put("/api/v1/trip-lease", json={"lease_id": "lease-1", "trip_id": "trip-1",
                                                        "holder": "site-a", "operator_name": "kim", "ttl_s": 5},
                            headers=OPERATOR)
        assert opened.status_code == 200, opened.text
    elif condition == "manual_active":
        monkeypatch.setattr(type(svc.command), "manual_active", property(lambda _self: True))

    refused = client.put(PATH, json={"status_patterns": "off"}, headers=OPERATOR)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LAMP_BUSY"
    assert not path.exists()
    assert client.put(PATH, json={"status_patterns": "on"}, headers=OPERATOR).status_code == 200


def test_unwritable_lamp_setting_returns_503(core_client, tmp_path, monkeypatch):
    client, svc = core_client()
    svc.state.set_velocity(0.0, 0.0)

    def refuse(*_args):
        raise PermissionError("unwritable")

    monkeypatch.setattr("core.system.host_files._write_private", refuse)
    response = client.put(PATH, json={"status_patterns": "off"}, headers=OPERATOR)
    assert response.status_code == 503 and response.json()["error"]["code"] == "LAMP_UNAVAILABLE"
