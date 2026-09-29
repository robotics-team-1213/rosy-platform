"""D-352 S2: enrollment routes — named operators write, viewers read, no secrets leak."""

from __future__ import annotations

import base64
import logging
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from enrollment_fakes import AUTH, CODE, ISSUED, KEY, NAME, PINNED, FakeCore, build, scan_row
from fakes import FakeRobot
from fleet.server.app import create_app

OPERATOR = "op-" + "secret-1"
VIEWER = "view-" + "secret-1"
DISCOVERY = "disc-" + "secret-1"


def _headers(token: str) -> dict:
    return {AUTH: "Bearer " + token}


def _users() -> dict:
    return {sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "alice", "role": "operator"},
            sha256(VIEWER.encode()).hexdigest(): {"principal_id": "vic", "role": "viewer"}}


def _app(tmp_path, *, site_users=True, core=None, **kwargs):
    service, network, console, discovery, store, tasks = build(
        tmp_path, {PINNED: core or FakeCore()}, static=(FakeRobot("rosy_01"),))
    discovery.replace_scan([scan_row()])
    app = create_app(console, console_token=None if site_users else "console-" + "tok",
                     task_service=tasks, start_task_dispatcher=False,
                     site_users=_users() if site_users else None, enrollment=service,
                     discovery=discovery, discovery_token=DISCOVERY, **kwargs)
    return TestClient(app), service, network, store


def test_named_operator_enrolls_and_the_audit_names_the_principal(tmp_path, caplog):
    client, service, network, store = _app(tmp_path)
    with caplog.at_level(logging.DEBUG):
        created = client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                              json={"discovery_name": NAME, "code": CODE.lower()})
        listed = client.get("/api/fleet/enrollment/robots", headers=_headers(VIEWER))

    assert created.status_code == 201, created.text
    assert created.json()["robot_id"] == "rosy_09"
    assert listed.status_code == 200
    assert [row["robot_id"] for row in listed.json()["robots"]] == ["rosy_09"]
    assert listed.json()["static_robot_ids"] == ["rosy_01"]
    audit = store.audit_rows()[-1]
    assert (audit["principal_id"], audit["device_kind"], audit["outcome"]) == ("alice", "robot",
                                                                               "enrolled")
    for text in (created.text, listed.text, caplog.text, repr(store.audit_rows())):
        assert ISSUED not in text and CODE not in text


def test_viewer_reads_but_cannot_write(tmp_path):
    client, *_ = _app(tmp_path)
    for method, path in (("post", "/api/fleet/enrollment/robots"),
                         ("post", "/api/fleet/enrollment/robots/rosy_09/move-address"),
                         ("delete", "/api/fleet/enrollment/robots/rosy_09")):
        kwargs = {"json": {"address": PINNED, "code": CODE}} if path.endswith("robots") else {}
        response = getattr(client, method)(path, headers=_headers(VIEWER), **kwargs)
        assert response.status_code == 403


def test_single_console_token_cannot_write_and_each_route_says_what_it_needs(tmp_path):
    client, service, network, _ = _app(tmp_path, site_users=False)
    token = _headers("console-" + "tok")
    messages = []
    for method, path in (("post", "/api/fleet/enrollment/robots"),
                         ("post", "/api/fleet/enrollment/robots/rosy_09/move-address"),
                         ("delete", "/api/fleet/enrollment/robots/rosy_09")):
        kwargs = {"json": {"address": PINNED, "code": CODE}} if path.endswith("robots") else {}
        response = getattr(client, method)(path, headers=token, **kwargs)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "OPERATOR_IDENTITY_REQUIRED"
        messages.append(response.json()["detail"]["message"])
    assert len(set(messages)) == 3 and all("mission" not in m for m in messages)
    assert network.requests == []
    assert client.get("/api/fleet/enrollment/robots", headers=token).status_code == 200


def test_rate_limit_is_passed_through_with_retry_after(tmp_path):
    client, *_ = _app(tmp_path, core=FakeCore(pair_status=429, retry_after=30))
    response = client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                           json={"discovery_name": NAME, "code": CODE})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.json()["detail"]["code"] == "rate_limited"


def test_unenroll_with_active_task_is_409_with_task_list(tmp_path):
    client, service, network, store = _app(tmp_path)
    client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                json={"discovery_name": NAME, "code": CODE})
    task = client.post("/api/fleet/robots/rosy_09/goal", headers={
        **_headers(OPERATOR), "Idempotency-Key": "k-1"}, json={"x": 1.0, "y": 1.0})
    assert task.status_code in (200, 201, 202), task.text
    refused = client.delete("/api/fleet/enrollment/robots/rosy_09", headers=_headers(OPERATOR))
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "ACTIVE_TASKS"
    assert refused.json()["detail"]["task_ids"]


def test_discovery_readback_shows_enrolled_and_scan_updates_the_register(tmp_path):
    client, service, network, store = _app(tmp_path)
    before = client.get("/api/fleet/discovery", headers=_headers(VIEWER)).json()["devices"][0]
    assert before["status"] == "registration_pending" and before["enrollable"] is True
    client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                json={"discovery_name": NAME, "code": CODE})
    after = client.get("/api/fleet/discovery", headers=_headers(VIEWER)).json()["devices"][0]
    assert after["status"] == "enrolled" and after["enrollable"] is False
    assert after["robot_id"] == "rosy_09"

    moved = scan_row("192.168.1.203:8080")
    accepted = client.post("/api/fleet/discovery/scan", headers=_headers(DISCOVERY),
                           json={"devices": [moved]})
    assert accepted.status_code == 200
    assert store.get("rosy_09")["state"] == "address_changed"


def test_key_equal_to_another_site_secret_refuses_start(tmp_path):
    key_text = base64.b64encode(KEY).decode()
    service, network, console, discovery, store, tasks = build(tmp_path, {})
    with pytest.raises(ValueError, match="robot credential key"):
        create_app(console, console_token=key_text, task_service=tasks,
                   start_task_dispatcher=False, enrollment=service,
                   robot_credential_key=key_text)
    with pytest.raises(ValueError, match="robot credential key"):
        create_app(console, task_service=tasks, start_task_dispatcher=False,
                   site_users={sha256(key_text.encode()).hexdigest():
                               {"principal_id": "alice", "role": "operator"}},
                   enrollment=service, robot_credential_key=key_text)


def test_key_failure_keeps_the_app_up_and_enrollment_answers_503(tmp_path):
    service, network, console, discovery, store, tasks = build(tmp_path, {}, key=None)
    before = store.rows()
    client = TestClient(create_app(console, task_service=tasks, start_task_dispatcher=False,
                                   site_users=_users(), enrollment=service))
    assert client.get("/api/fleet/state", headers=_headers(VIEWER)).status_code == 200
    listed = client.get("/api/fleet/enrollment/robots", headers=_headers(VIEWER)).json()
    assert listed["available"] is False and listed["unavailable_reason"]
    response = client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                           json={"address": PINNED, "code": CODE})
    assert response.status_code == 503
    assert store.rows() == before and network.requests == []


def test_unenroll_with_an_active_console_goal_is_409(tmp_path):
    client, service, network, store = _app(tmp_path)
    client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                json={"discovery_name": NAME, "code": CODE})
    service._roster._console._goals["rosy_09"] = {"x": 1.0, "y": 1.0, "yaw": 0.0}
    refused = client.delete("/api/fleet/enrollment/robots/rosy_09", headers=_headers(OPERATOR))
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "ROBOT_BUSY"
    assert store.get("rosy_09")["state"] == "active"
    assert "/api/v1/auth/logout" not in network.paths()
