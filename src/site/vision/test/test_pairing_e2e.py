"""D-341 synthetic end-to-end: Fleet (HTTPS) + Vision (WSS) + a synthetic Rosy Cam on 127.0.0.1.

request -> reveal -> operator approves with the phone's code -> one-time pickup -> mutual
confirm -> WSS pinned to the received site CA sends hello + frames -> Fleet stops (4503,
retry) -> Fleet restarts (reconnect) -> revoke -> 4401 within 5 s.

Runs in the normal suite: about 10 s on the 2026-10-01 Windows bench PC (opt-in gating was
not needed; the bound is < 20 s). A throwaway CA and leaf are generated in the test's tmp
dir; no key is ever committed. Fleet
runs in its own thread and event loop (uvicorn, real TLS); Vision's ingest runs on the test
loop with the real 2 s ``PairingSync`` thread. Only Vision's staleness limit is shortened
(3 s instead of 10 min) so the Fleet-down path finishes in seconds.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import http.client
import ipaddress
import json
import socket
import ssl
import threading
import time
from hashlib import sha256
from pathlib import Path

import pytest
import uvicorn
import websockets
import yaml
from core_common.protocol import pairing
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.pairing import PairingService
from fleet.server.pairing_store import PairingStore
from fleet.server.sightings_config import load_sighting_sources
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from fleet.swarm.transport import HttpRobotClient
from rosy_vision import protocol
from rosy_vision.cli import _vision_ingest, parse_args
from rosy_vision.pairing_sync import PairingSync
from rosy_vision.vision_config import load_vision_sources
from websockets.exceptions import ConnectionClosed, InvalidStatus

TLS_HOST = "rosy-e2e.local"
SOURCE = "ceiling_e2e"
OPERATOR = "op-" + "secret-e2e"
SYNC_ENV = "ROSY_E2E_PAIRING_SYNC"
BASE = "/api/fleet/pairing/v1"


# -- throwaway PKI ---------------------------------------------------------------------------

def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _write_pki(directory: Path) -> dict[str, Path]:
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (x509.CertificateBuilder().subject_name(_name("Rosy e2e site CA"))
          .issuer_name(_name("Rosy e2e site CA")).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=2))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                         critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                       content_commitment=False, key_encipherment=False,
                                       data_encipherment=False, key_agreement=False,
                                       encipher_only=False, decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder().subject_name(_name(TLS_HOST)).issuer_name(ca.subject)
            .public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                           critical=False)
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName(TLS_HOST), x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
                           critical=False)
            .sign(ca_key, hashes.SHA256()))
    pem = serialization.Encoding.PEM
    paths = {"ca": directory / "site-ca.crt", "chain": directory / "site.crt",
             "key": directory / "site.key"}
    paths["ca"].write_bytes(ca.public_bytes(pem))
    paths["chain"].write_bytes(leaf.public_bytes(pem) + ca.public_bytes(pem))
    paths["key"].write_bytes(leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption()))
    return paths


# -- Fleet in its own thread --------------------------------------------------------------

class FleetThread:
    def __init__(self, app, port: int, pki: dict[str, Path]) -> None:
        self.server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="critical",
            ssl_certfile=str(pki["chain"]), ssl_keyfile=str(pki["key"])))
        self.thread = threading.Thread(target=self.server.run, name="e2e-fleet", daemon=True)

    def start(self) -> FleetThread:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            assert time.monotonic() < deadline, "Fleet did not start"
            time.sleep(0.02)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(10)


def _fleet_app(db: Path, pki: dict[str, Path], sources: dict[str, str], sync_token: str):
    endpoint = RobotEndpoint("rosy_01", "http://127.0.0.1:9", "robot-rest")
    console = FleetConsole([endpoint], [HttpRobotClient(endpoint)])
    service = PairingService(
        PairingStore(db), leaf_cert_sha256=pairing.der_sha256(pki["chain"].read_text("utf-8")),
        site_ca_pem=pki["ca"].read_text("utf-8"), tls_host=TLS_HOST, site_name="Rosy e2e",
        sources=sources)
    tasks = FleetTaskService(FleetTaskStore(db), robot_ids=["rosy_01"])
    users = {sha256(OPERATOR.encode()).hexdigest(): {"principal_id": "alice", "role": "operator"}}
    return create_app(console, task_service=tasks, start_task_dispatcher=False, site_users=users,
                      pairing=service, pairing_sync_token=sync_token)


# -- the synthetic phone (blocking; called through asyncio.to_thread) -----------------------

class SyntheticPhone:
    """Records the first leaf it sees, trusts only that leaf until it holds the site CA."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.client_nonce = pairing.new_secret()
        self.poll = pairing.new_secret()
        self.leaf_der: bytes | None = None
        self.result: dict | None = None

    def _context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # first contact: record, do not verify (D-341 3)
        return context

    def record_leaf(self) -> str:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw, \
                self._context().wrap_socket(raw, server_hostname=TLS_HOST) as tls:
            self.leaf_der = tls.getpeercert(binary_form=True)
        leaf = x509.load_der_x509_certificate(self.leaf_der)
        names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert TLS_HOST in names.get_values_for_type(x509.DNSName), "SAN lacks the advertised tls_host"
        return sha256(self.leaf_der).hexdigest()

    def call(self, method: str, path: str, body: dict | None = None, *, bearer: str | None = None):
        connection = http.client.HTTPSConnection("127.0.0.1", self.port, timeout=5,
                                                 context=self._context())
        try:
            connection.connect()
            assert connection.sock.getpeercert(binary_form=True) == self.leaf_der, "leaf changed"
            headers = {"Content-Type": "application/json"}
            if bearer:
                headers["Authorization"] = "Bearer " + bearer
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    def accept_result(self, result: dict, console_fingerprint: str) -> None:
        assert pairing.validate_result(result) is None
        ca = x509.load_pem_x509_certificate(result["site_ca_pem"].encode())
        x509.load_der_x509_certificate(self.leaf_der).verify_directly_issued_by(ca)
        # Mutual confirm (D-341 4): the installer compares phone and console values.
        assert pairing.site_fingerprint(result["site_ca_pem"]) == console_fingerprint
        self.result = result

    def wss_context(self) -> ssl.SSLContext:
        # cadata only: no system or user trust store, exactly one CA (D-341 9).
        return ssl.create_default_context(cadata=self.result["site_ca_pem"])


def _hello() -> dict:
    return {"type": "hello", "proto": protocol.PROTO, "source": SOURCE, "app_version": "e2e",
            "device": "synthetic-phone", "sensor": {"width": 640, "height": 480, "rotation_deg": 0}}


def _frame(seq: int) -> bytes:
    return protocol.pack_header(protocol.FrameHeader(seq, 0, 640, 480, 0)) + b"\xff\xd8\xff\xd9"


async def _wait_for(predicate, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


async def _closed_code(ws, timeout: float) -> int:
    with pytest.raises(ConnectionClosed):
        while True:
            await asyncio.wait_for(ws.recv(), timeout)
    return ws.close_code


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _site_cameras(path: Path) -> Path:
    path.write_text(yaml.safe_dump({"sources": [{
        "source_id": SOURCE, "credential": "paired", "token_env": "ROSY_E2E_SIGHTING",
        "fleet_base_url": "https://127.0.0.1:9", "robot_ids": ["rosy_01"], "map_id": "site-v1",
        "calibration_revision": "cal-v1", "processor_revision": "aruco-v1",
        "corner_marker_ids": [30, 31, 32, 33], "corner_world_m": [[0, 0], [4, 0], [4, 2], [0, 2]],
        "robot_markers": {"rosy_01": 7},
    }]}), encoding="utf-8")
    return path


def test_console_approved_pairing_end_to_end(tmp_path, monkeypatch):
    asyncio.run(_scenario(tmp_path, monkeypatch))


async def _scenario(tmp_path: Path, monkeypatch) -> None:
    pki = _write_pki(tmp_path)
    sync_token = pairing.new_secret()
    environ = {"ROSY_E2E_SIGHTING": "sighting-" + "e2e", SYNC_ENV: sync_token}
    cameras = _site_cameras(tmp_path / "site-cameras.yaml")
    fleet_sources = {source.source_id: source.credential
                     for source in load_sighting_sources(cameras, environ=environ)}
    db = tmp_path / "fleet.sqlite3"
    fleet_port = _free_port()
    fleet = FleetThread(_fleet_app(db, pki, fleet_sources, sync_token), fleet_port, pki).start()

    vision_args = parse_args(["vision", "--config", str(cameras),
                              "--pairing-sync-url", f"https://127.0.0.1:{fleet_port}",
                              "--pairing-sync-token-env", SYNC_ENV,
                              "--pairing-sync-ca", str(pki["ca"])])
    ingest, sync_settings = _vision_ingest(vision_args, load_vision_sources(cameras, environ=environ),
                                           environ=environ)
    ingest.paired.max_age_s = 3.0  # 600 s in production; shortened for the Fleet-down path
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.load_cert_chain(str(pki["chain"]), str(pki["key"]))
    ws_server = await ingest.start("127.0.0.1", 0, ssl_context=server_tls)
    ws_url = f"wss://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}{protocol.WS_PATH}"
    loop = asyncio.get_running_loop()
    sync = PairingSync(ingest.paired, **sync_settings,
                       on_cycle=lambda: loop.call_soon_threadsafe(ingest.enforce_paired_credentials))
    sync.start()
    operator_tls = ssl.create_default_context(cafile=str(pki["ca"]))

    def operator(method: str, path: str, body: dict | None = None):
        connection = http.client.HTTPSConnection("127.0.0.1", fleet_port, timeout=5,
                                                 context=operator_tls)
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers={"Authorization": "Bearer " + OPERATOR,
                                        "Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            connection.close()

    async def connect():
        return await websockets.connect(
            ws_url, ssl=phone.wss_context(), server_hostname=TLS_HOST,
            additional_headers={"Authorization": "Bearer " + phone.result["token"]})

    async def stream(first_seq: int):
        ws = await connect()
        await ws.send(json.dumps(_hello()))
        assert json.loads(await ws.recv())["type"] == "config"
        await ws.send(_frame(first_seq))
        await _wait_for(lambda: (ingest.latest_frame(SOURCE) is not None
                                 and ingest.latest_frame(SOURCE).header.seq == first_seq),
                        3.0, f"frame {first_seq} at Vision")
        return ws

    phone = SyntheticPhone(fleet_port)
    try:
        # 1-2: discover -> record the leaf -> request (commit) -> reveal.
        leaf_sha256 = await asyncio.to_thread(phone.record_leaf)
        assert leaf_sha256 == pairing.der_sha256(pki["chain"].read_text("utf-8"))
        status, created = await asyncio.to_thread(phone.call, "POST", f"{BASE}/requests", {
            "proto": pairing.PROTO, "role": pairing.ROLE, "device_label": "synthetic S21",
            "app_version": "e2e", "client_commit": pairing.commit(phone.client_nonce),
            "poll_secret_sha256": pairing.sha256_text(phone.poll)})
        assert status == 201, created
        request_id = created["request_id"]
        status, _ = await asyncio.to_thread(phone.call, "POST", f"{BASE}/requests/{request_id}/reveal",
                                            {"client_nonce": phone.client_nonce}, bearer=phone.poll)
        assert status == 200
        code = pairing.confirmation_code(role=pairing.ROLE, request_id=request_id,
                                         leaf_cert_sha256=leaf_sha256,
                                         client_nonce=phone.client_nonce,
                                         server_nonce=created["server_nonce"])

        # 3: the operator types the phone's code and picks the paired source.
        status, pending = await asyncio.to_thread(operator, "GET", f"{BASE}/pending")
        assert status == 200 and pending["requests"][0]["state"] == "revealed"
        assert code not in json.dumps(pending)
        status, approval = await asyncio.to_thread(
            operator, "POST", f"{BASE}/requests/{request_id}/approve",
            {"code": code, "source_id": SOURCE})
        assert status == 200, approval

        # 4: one-time pickup, CA chain + fingerprint check, then confirm.
        status, polled = await asyncio.to_thread(phone.call, "GET", f"{BASE}/requests/{request_id}",
                                                 bearer=phone.poll)
        assert status == 200 and polled["state"] == "approved"
        phone.accept_result(polled["result"], approval["site_ca_fingerprint"])
        assert polled["result"]["credential_id"] == approval["credential_id"]
        status, confirmed = await asyncio.to_thread(
            phone.call, "POST", f"{BASE}/requests/{request_id}/confirm",
            {"credential_id": approval["credential_id"]}, bearer=phone.poll)
        assert status == 200, confirmed

        # 5: WSS pinned to the received CA; Vision picks the credential up on its next sync.
        await _wait_for(lambda: ingest.paired.check(
            SOURCE, sha256(phone.result["token"].encode()).digest())[0] == "ok", 5.0, "Vision sync")
        ws = await stream(1)
        await ws.send(_frame(2))
        await _wait_for(lambda: ingest.latest_frame(SOURCE).header.seq == 2, 3.0, "frame 2")

        # 6: Fleet stops -> the list goes stale -> 4503 (retry), and the upgrade answers 503.
        await asyncio.to_thread(fleet.stop)
        assert await _closed_code(ws, 10.0) == protocol.CLOSE_CREDENTIAL_UNKNOWN
        with pytest.raises(InvalidStatus) as refused:
            await connect()
        assert refused.value.response.status_code == 503

        # 7: Fleet restarts on the same database; the phone's retry gets through.
        fleet = FleetThread(_fleet_app(db, pki, fleet_sources, sync_token), fleet_port, pki).start()
        reconnect_deadline = time.monotonic() + 10
        while True:
            try:
                ws = await stream(3)
                break
            except InvalidStatus as exc:
                assert exc.response.status_code == 503
                assert time.monotonic() < reconnect_deadline, "phone never reconnected"
                await asyncio.sleep(0.5)

        # 8: revoke at the console -> the live socket closes 4401 within 5 s.
        status, _ = await asyncio.to_thread(
            operator, "POST", f"{BASE}/credentials/{approval['credential_id']}/revoke")
        assert status == 200
        revoked_at = time.monotonic()
        assert await _closed_code(ws, 6.0) == protocol.CLOSE_UNAUTHORIZED
        assert time.monotonic() - revoked_at < 5.0
        with pytest.raises(InvalidStatus) as refused:
            await connect()
        assert refused.value.response.status_code == 401
    finally:
        sync.stop()
        ws_server.close()
        await ws_server.wait_closed()
        await asyncio.to_thread(fleet.stop)
