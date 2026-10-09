"""D-555: one hub credential per enrolled robot, digest only, delivered only over TLS."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from types import SimpleNamespace

import pytest

from enrollment_fakes import CODE, NAME, PINNED, FakeCore, build, scan_row
from core_common.protocol.schemas import Envelope, EnvelopeType, HelloPayload
from fleet.server.enrollment import EnrollmentError
from fleet.server.enrollment_store import EnrollmentStore
from fleet.swarm.transport import RobotApiError

HUB_LINK = {"expected_hostname": "rosy-site.local", "ca_pem": "-----BEGIN CERTIFICATE-----\nx\n"}


class LinkClient:
    """The enrolled robot's client as link_hub sees it (TLS transport is test_enrolled_tls's)."""

    def __init__(self, *, base="https://" + NAME + ".local:8443", provisioning=True,
                 put_error=None, delete_error=None) -> None:
        self._ep = SimpleNamespace(base_url=base)
        self.provisioning, self.put_error, self.delete_error = provisioning, put_error, delete_error
        self.puts: list[dict] = []
        self.deletes = 0

    async def capabilities(self) -> dict:
        return {"fleet_link_provisioning": True} if self.provisioning else {}

    async def fleet_link_put(self, body: dict) -> dict:
        self.puts.append(body)
        if self.put_error is not None:
            raise self.put_error
        return {"configured": True}

    async def fleet_link_delete(self) -> dict:
        self.deletes += 1
        if self.delete_error is not None:
            raise self.delete_error
        return {"removed": True}

    async def aclose(self) -> None:
        pass


def enrolled(tmp_path, *, tls=True, **client):
    service, network, console, discovery, store, tasks = build(tmp_path, {PINNED: FakeCore()})
    discovery.replace_scan([scan_row()])
    asyncio.run(service.enroll(code=CODE, principal_id="alice", discovery_name=NAME))
    service._hub_link = dict(HUB_LINK)
    if tls:
        service._tls_bound = lambda robot_id: True
        console._clients["rosy_09"] = LinkClient(**client)
    network.clear()
    return service, network, console, store


def hello(console, token: str) -> Envelope:
    envelope = Envelope(type=EnvelopeType.HELLO,
                        payload=HelloPayload(robot_id="rosy_09", pairing_token=token).model_dump())
    return console.hub.handle(envelope, session=console.hub.open_session())


def secret_free(tmp_path, secret: str) -> bool:
    blobs = [path.read_bytes() for path in tmp_path.glob("fleet.sqlite3*")]
    return all(secret.encode() not in blob for blob in blobs)


def test_link_stores_only_the_digest_and_the_hub_takes_the_token(tmp_path, caplog):
    service, _, console, store = enrolled(tmp_path)
    with caplog.at_level(logging.DEBUG):
        row = asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    client = console._clients["rosy_09"]
    sent = client.puts[0]
    token = sent["pairing_token"]
    assert len(token) >= 43 and sent["expected_hostname"] == "rosy-site.local"
    assert sent["ca_pem"] == HUB_LINK["ca_pem"]
    stored = store.get("rosy_09")
    assert stored["hub_digest"] == hashlib.sha256(token.encode()).hexdigest()
    assert row["hub_linked"] is True and row["hub_host"] == "rosy-site.local"
    assert "hub_digest" not in row
    # Never stored, logged, audited or listed in plaintext.
    for text in (caplog.text, repr(store.audit_rows()), repr(service.listing()), repr(stored)):
        assert token not in text
    assert secret_free(tmp_path, token)
    assert store.audit_rows()[-1]["outcome"] == "linked"
    # HELLO: right token welcomed, wrong token refused.
    assert hello(console, token).type is EnvelopeType.WELCOME
    refused = hello(console, token[:-1] + ("A" if token[-1] != "A" else "B"))
    assert refused.type is EnvelopeType.ERROR and refused.payload["code"] == "PAIRING_INVALID"


def test_plain_http_enrollment_is_refused_before_anything_is_sent(tmp_path):
    service, network, console, store = enrolled(tmp_path, tls=False)
    with pytest.raises(EnrollmentError) as refused:
        asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    assert refused.value.code == "tls_binding_required" and refused.value.status == 409
    assert network.requests == [] and store.get("rosy_09")["hub_digest"] is None
    assert store.audit_rows()[-1]["outcome"] == "tls_binding_required"
    # A TLS binding whose client is not on https still never sends the credential.
    service._tls_bound = lambda robot_id: True
    with pytest.raises(EnrollmentError, match="not on TLS"):
        asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    assert network.requests == []


def test_robot_without_the_capability_gets_nothing(tmp_path):
    service, _, console, store = enrolled(tmp_path, provisioning=False)
    with pytest.raises(EnrollmentError, match="fleet_link_provisioning"):
        asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    assert console._clients["rosy_09"].puts == [] and store.get("rosy_09")["hub_digest"] is None


def test_failed_delivery_rolls_back_and_rotation_kills_the_old_token(tmp_path, caplog):
    service, _, console, store = enrolled(tmp_path)
    first = asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    client = console._clients["rosy_09"]
    old = client.puts[-1]["pairing_token"]
    assert first["hub_linked"] is True

    client.put_error = RobotApiError("rosy_09", 500, "INTERNAL_ERROR", "echo " + "x")
    with caplog.at_level(logging.DEBUG), pytest.raises(EnrollmentError) as failed:
        asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    attempted = client.puts[-1]["pairing_token"]
    assert failed.value.code == "robot_refused" and attempted not in str(failed.value.body())
    assert attempted not in caplog.text
    # Rolled back: the old credential still works, the attempted one never did.
    assert store.get("rosy_09")["hub_digest"] == hashlib.sha256(old.encode()).hexdigest()
    assert hello(console, old).type is EnvelopeType.WELCOME
    assert hello(console, attempted).payload["code"] == "PAIRING_INVALID"

    client.put_error = None
    asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    new = client.puts[-1]["pairing_token"]
    assert store.audit_rows()[-1]["outcome"] == "rotated"
    assert hello(console, new).type is EnvelopeType.WELCOME
    assert hello(console, old).payload["code"] == "PAIRING_INVALID"


@pytest.mark.parametrize("reachable", [True, False])
def test_unlink_clears_both_sides_and_the_hub_refuses_the_token(tmp_path, reachable):
    error = None if reachable else RobotApiError("rosy_09", 502, "UNREACHABLE", "down")
    service, _, console, store = enrolled(tmp_path, delete_error=error)
    asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    client = console._clients["rosy_09"]
    token = client.puts[-1]["pairing_token"]
    assert hello(console, token).type is EnvelopeType.WELCOME

    result = asyncio.run(service.unlink_hub("rosy_09", principal_id="bob"))
    assert client.deletes == 1 and result["robot_cleared"] is reachable
    assert result["hub_linked"] is False and store.get("rosy_09")["hub_digest"] is None
    assert not console.hub.registry.find("rosy_09").online
    assert hello(console, token).payload["code"] == "PAIRING_INVALID"
    audit = store.audit_rows()[-1]
    assert (audit["action"], audit["principal_id"]) == ("hub_unlink", "bob")


def test_unenroll_asks_the_robot_to_drop_the_link(tmp_path):
    service, _, console, store = enrolled(tmp_path)
    asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    client = console._clients["rosy_09"]
    asyncio.run(service.unenroll("rosy_09", principal_id="alice"))
    assert client.deletes == 1


def test_a_restarted_fleet_loads_the_digest_into_its_hub(tmp_path):
    service, _, console, _ = enrolled(tmp_path)
    asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    token = console._clients["rosy_09"].puts[-1]["pairing_token"]
    again, _, console2, _, _, _ = build(tmp_path, {PINNED: FakeCore()})
    again.load()
    assert hello(console2, token).type is EnvelopeType.WELCOME


def test_hub_link_needs_configuration(tmp_path):
    service, _, _, _ = enrolled(tmp_path)
    service._hub_link = None
    with pytest.raises(EnrollmentError) as refused:
        asyncio.run(service.link_hub("rosy_09", principal_id="alice"))
    assert refused.value.code == "hub_link_unavailable"


def test_an_older_register_gains_the_hub_columns(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE robot_enrollments (robot_id TEXT PRIMARY KEY, hostname TEXT NOT NULL, "
                           "serial_number TEXT, device_uid TEXT, discovery_name TEXT, address TEXT NOT NULL, "
                           "token_id TEXT NOT NULL, role TEXT NOT NULL, source TEXT NOT NULL, expires_at TEXT, "
                           "fleet_expires_at REAL, warn_at REAL, ciphertext BLOB NOT NULL, principal_id TEXT NOT NULL, "
                           "state TEXT NOT NULL, logout_attempted INTEGER NOT NULL DEFAULT 0, "
                           "created_at REAL NOT NULL, updated_at REAL NOT NULL)")
    EnrollmentStore(path)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(robot_enrollments)")}
    assert {"hub_digest", "hub_host"} <= columns


def test_route_needs_a_named_operator_and_refuses_plain_http(tmp_path):
    from test_enrollment_api import OPERATOR, VIEWER, _app, _headers

    client, service, network, store = _app(tmp_path)
    assert client.post("/api/fleet/enrollment/robots", headers=_headers(OPERATOR),
                       json={"discovery_name": NAME, "code": CODE}).status_code == 201
    service._hub_link = dict(HUB_LINK)
    network.clear()
    assert client.post("/api/fleet/robots/rosy_09/hub-link", headers=_headers(VIEWER)).status_code == 403
    response = client.post("/api/fleet/robots/rosy_09/hub-link", headers=_headers(OPERATOR))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "tls_binding_required"
    assert network.requests == []
    listed = client.get("/api/fleet/enrollment/robots", headers=_headers(VIEWER)).json()["robots"][0]
    assert listed["hub_linkable"] is False and listed["hub_linked"] is False
