"""D-341 2, 5, 12: pairing routes on the real create_app, roles and credential separation."""

from __future__ import annotations

import logging
import re
from hashlib import sha256

import pytest
from core_common.protocol import pairing
from fakes import FakeRobot
from fastapi.testclient import TestClient
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.pairing import PairingService
from fleet.server.pairing_store import PairingStore
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from pairing_fixtures import LEAF_SHA256, SITE_CA_PEM, TLS_HOST, FakeClock, Phone

OPERATOR = "op-" + "secret-1"
VIEWER = "view-" + "secret-1"
POLICY = "policy-" + "secret-1"
SYNC = "sync-" + "secret-1"
BASE = "/api/fleet/pairing/v1"
SOURCES = {"ceiling_north": "paired", "bench_static": "static"}


def _users() -> dict:
    return {sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "alice", "role": "operator"},
            sha256(VIEWER.encode()).hexdigest(): {"principal_id": "vic", "role": "viewer"},
            sha256(POLICY.encode()).hexdigest(): {"principal_id": "pam", "role": "policy-admin"}}


def _console() -> FleetConsole:
    endpoints = [RobotEndpoint(robot_id="rosy_01", base_url="http://127.0.0.1:8080", token="t")]
    return FleetConsole(endpoints, [FakeRobot("rosy_01")])


def _app(tmp_path, *, site_users=True, sync_token=SYNC, clock=None, **kwargs):
    clock = clock or FakeClock()
    store = PairingStore(tmp_path / "fleet.sqlite3", clock=clock.wall)
    service = PairingService(store, leaf_cert_sha256=LEAF_SHA256, site_ca_pem=SITE_CA_PEM,
                             tls_host=TLS_HOST, site_name="Rosy Lab", sources=SOURCES,
                             monotonic=clock.monotonic, wall=clock.wall)
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=["rosy_01"])
    app = create_app(_console(), console_token=None if site_users else "console-" + "tok",
                     task_service=tasks, start_task_dispatcher=False,
                     site_users=_users() if site_users else None, pairing=service,
                     pairing_sync_token=sync_token, **kwargs)
    return TestClient(app), service, store, clock


def _auth(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def _pair(client, clock, *, source="ceiling_north"):
    phone = Phone()
    created = client.post(f"{BASE}/requests", content=phone.request_bytes())
    assert created.status_code == 201, created.text
    request_id = created.json()["request_id"]
    revealed = client.post(f"{BASE}/requests/{request_id}/reveal", content=phone.reveal_bytes(),
                           headers={"Authorization": phone.bearer})
    assert revealed.status_code == 200, revealed.text
    code = phone.code(request_id, created.json()["server_nonce"])
    approved = client.post(f"{BASE}/requests/{request_id}/approve", headers=_auth(OPERATOR),
                           json={"code": code, "source_id": source})
    return phone, request_id, code, approved


def test_full_http_flow_and_vision_list(tmp_path, caplog):
    client, _service, store, clock = _app(tmp_path)
    with caplog.at_level(logging.DEBUG):
        phone, request_id, _code, approved = _pair(client, clock)
        assert approved.status_code == 200, approved.text
        credential_id = approved.json()["credential_id"]
        assert approved.json()["site_ca_fingerprint"] == pairing.site_fingerprint(SITE_CA_PEM)

        listed = client.get(f"{BASE}/credentials", params={"role": "overhead-camera"},
                            headers=_auth(SYNC))
        assert listed.status_code == 200 and listed.json()["credentials"] == []

        polled = client.get(f"{BASE}/requests/{request_id}", headers={"Authorization": phone.bearer})
        assert polled.status_code == 200
        result = polled.json()["result"]
        assert pairing.validate_result(result) is None
        clock.advance(2)
        again = client.get(f"{BASE}/requests/{request_id}", headers={"Authorization": phone.bearer})
        assert again.status_code == 410

        confirmed = client.post(f"{BASE}/requests/{request_id}/confirm",
                                json={"credential_id": credential_id},
                                headers={"Authorization": phone.bearer})
        assert confirmed.status_code == 200, confirmed.text
        listed = client.get(f"{BASE}/credentials", params={"role": "overhead-camera"},
                            headers=_auth(SYNC))
        assert listed.json() == {"role": "overhead-camera", "credentials": [{
            "credential_id": credential_id, "source_id": "ceiling_north",
            "token_sha256": pairing.sha256_text(result["token"]),
            "expires_at": result["expires_at"]}]}

        summary = client.get(f"{BASE}/credentials/summary", headers=_auth(VIEWER))
        assert summary.status_code == 200
        assert "token_sha256" not in summary.text
        revoked = client.post(f"{BASE}/credentials/{credential_id}/revoke", headers=_auth(OPERATOR))
        assert revoked.status_code == 200
        listed = client.get(f"{BASE}/credentials", params={"role": "overhead-camera"},
                            headers=_auth(SYNC))
        assert listed.json()["credentials"] == []
    for secret in (result["token"], phone.poll, phone.client_nonce):
        assert secret not in caplog.text
    actions = [(row["action"], row["principal_id"]) for row in store.audit_rows()]
    assert ("approve", "alice") in actions and ("revoke", "alice") in actions


def test_viewer_and_policy_admin_cannot_approve_reject_or_revoke(tmp_path):
    client, *_ = _app(tmp_path)
    for token in (VIEWER, POLICY):
        for path, body in ((f"{BASE}/requests/pr-x/approve", {"code": "123456", "source_id": "a"}),
                           (f"{BASE}/requests/pr-x/reject", None),
                           (f"{BASE}/credentials/cred-x/revoke", None)):
            response = client.post(path, headers=_auth(token), json=body)
            assert response.status_code == 403, (token, path)
    assert client.get(f"{BASE}/pending", headers=_auth(VIEWER)).status_code == 200
    assert client.get(f"{BASE}/pending").status_code == 401


def test_single_console_token_gets_the_route_specific_403(tmp_path):
    client, *_ = _app(tmp_path, site_users=False)
    token = _auth("console-" + "tok")
    for path, body in ((f"{BASE}/requests/pr-x/approve", {"code": "123456", "source_id": "a"}),
                       (f"{BASE}/requests/pr-x/reject", None),
                       (f"{BASE}/credentials/cred-x/revoke", None)):
        response = client.post(path, headers=token, json=body)
        assert response.status_code == 403
        assert response.json()["detail"] == {
            "code": "OPERATOR_IDENTITY_REQUIRED",
            "message": "named operator required (site-users.yaml)"}


def test_vision_list_needs_its_own_token_and_the_camera_role(tmp_path):
    client, *_ = _app(tmp_path)
    path = f"{BASE}/credentials"
    assert client.get(path, params={"role": "overhead-camera"}).status_code == 401
    assert client.get(path, params={"role": "overhead-camera"},
                      headers=_auth(OPERATOR)).status_code == 401
    assert client.get(path, params={"role": "robot"}, headers=_auth(SYNC)).status_code == 400
    # The sync token is not a site user credential.
    assert client.get(f"{BASE}/pending", headers=_auth(SYNC)).status_code == 401


def test_vision_list_is_503_without_a_sync_token(tmp_path):
    client, *_ = _app(tmp_path, sync_token=None)
    response = client.get(f"{BASE}/credentials", params={"role": "overhead-camera"},
                          headers=_auth(SYNC))
    assert response.status_code == 503


def test_phone_bodies_are_capped_and_strict(tmp_path):
    client, *_ = _app(tmp_path)
    phone = Phone()
    big = client.post(f"{BASE}/requests", content=phone.request_bytes(device_label="z" * 4100))
    assert big.status_code == 400 and big.json()["detail"]["reason"] == "too_large"
    extra = client.post(f"{BASE}/requests", content=phone.request_bytes(tls_host="x.local"))
    assert extra.json()["detail"]["reason"] == "unknown_field"
    robot = client.post(f"{BASE}/requests", content=phone.request_bytes(role="robot"))
    assert robot.json()["detail"]["reason"] == "role"
    created = client.post(f"{BASE}/requests", content=phone.request_bytes()).json()
    confirm = client.post(f"{BASE}/requests/{created['request_id']}/confirm",
                          json={"credential_id": "cred-x", "extra": 1},
                          headers={"Authorization": phone.bearer})
    assert confirm.status_code == 400


def test_limits_answer_429_with_retry_after(tmp_path):
    client, *_ = _app(tmp_path)
    for _ in range(16):
        assert client.post(f"{BASE}/requests", content=Phone().request_bytes()).status_code == 201
    full = client.post(f"{BASE}/requests", content=Phone().request_bytes())
    assert full.status_code == 429 and full.headers["Retry-After"]


def test_code_mismatch_is_409_and_active_source_is_409(tmp_path):
    client, _service, _store, _clock = _app(tmp_path)
    phone = Phone()
    created = client.post(f"{BASE}/requests", content=phone.request_bytes()).json()
    client.post(f"{BASE}/requests/{created['request_id']}/reveal", content=phone.reveal_bytes(),
                headers={"Authorization": phone.bearer})
    wrong = client.post(f"{BASE}/requests/{created['request_id']}/approve", headers=_auth(OPERATOR),
                        json={"code": "000000" if phone.code(created["request_id"], created["server_nonce"]) != "000000" else "000001",
                              "source_id": "ceiling_north"})
    assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "CODE_MISMATCH"
    bad = client.post(f"{BASE}/requests/{created['request_id']}/approve", headers=_auth(OPERATOR),
                      json={"code": "12345", "source_id": "ceiling_north"})
    assert bad.status_code == 422


def test_pairing_routes_absent_without_pairing(tmp_path):
    app = create_app(_console())
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not any(path.startswith(BASE) for path in paths)


def test_pairing_routes_do_not_look_like_video_relay(tmp_path):
    client, *_ = _app(tmp_path)
    forbidden = re.compile(r"video|stream|camera|preview|proxy|relay|mjpeg|jpeg|image", re.IGNORECASE)
    paths = [route.path for route in client.app.routes if getattr(route, "path", "").startswith(BASE)]
    assert len(paths) >= 9
    assert not [path for path in paths if forbidden.search(path)]


def test_sync_token_requires_pairing(tmp_path):
    with pytest.raises(ValueError, match="pairing"):
        create_app(_console(), pairing_sync_token=SYNC)


@pytest.mark.parametrize("clash", ["console", "discovery", "preview", "robot", "user"])
def test_sync_token_must_differ_from_every_other_site_secret(tmp_path, clash):
    clock = FakeClock()
    store = PairingStore(tmp_path / "fleet.sqlite3", clock=clock.wall)
    service = PairingService(store, leaf_cert_sha256=LEAF_SHA256, site_ca_pem=SITE_CA_PEM,
                             tls_host=TLS_HOST, site_name="Rosy Lab", sources=SOURCES)
    kwargs = {"pairing": service, "pairing_sync_token": SYNC}
    console = _console()
    if clash == "console":
        kwargs["console_token"] = SYNC
    elif clash == "discovery":
        from fleet.server.discovery import DiscoveryStore
        kwargs.update(discovery=DiscoveryStore(), discovery_token=SYNC, console_token="c-" + "tok")
    elif clash == "preview":
        shared_secret = SYNC * 4  # the preview signer needs at least 32 bytes
        kwargs.update(vision_lease_secret=shared_secret, pairing_sync_token=shared_secret)
    elif clash == "robot":
        endpoints = [RobotEndpoint(robot_id="rosy_01", base_url="http://127.0.0.1:8080", token=SYNC)]
        console = FleetConsole(endpoints, [FakeRobot("rosy_01")])
    elif clash == "user":
        tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=["rosy_01"])
        kwargs.update(task_service=tasks, start_task_dispatcher=False,
                      site_users={sha256(SYNC.encode()).hexdigest(): {"principal_id": "a",
                                                                      "role": "operator"}})
    with pytest.raises(ValueError, match="pairing sync"):
        create_app(console, **kwargs)


def test_confirm_with_a_non_ascii_credential_id_is_a_400_not_a_500(tmp_path):
    # Security review finding 3: compare_digest on non-ASCII str raised TypeError (500).
    client, *_ = _app(tmp_path)
    phone = Phone()
    created = client.post(f"{BASE}/requests", content=phone.request_bytes()).json()
    confirm = client.post(f"{BASE}/requests/{created['request_id']}/confirm",
                          json={"credential_id": "céd-한"},
                          headers={"Authorization": phone.bearer})
    assert confirm.status_code == 400
