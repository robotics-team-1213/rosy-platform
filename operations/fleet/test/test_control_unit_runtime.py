import asyncio
import json

import httpx
import pytest
import yaml

from test_control_unit_service import MANIFEST


def config_file(tmp_path, **changes):
    (tmp_path / "parent.token").write_text("parent-service-token", encoding="utf-8")
    document = {"unit_id": "A1", "manifest": MANIFEST,
                "peers": {"A": {"url": "http://parent.invalid:8080", "token_file": "parent.token"}}}
    document.update(changes)
    path = tmp_path / "control.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_runtime_config_has_only_direct_neighbors_and_hides_secrets(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit
    config = load_control_unit(config_file(tmp_path))
    assert config.unit_id == "A1"
    assert set(config.peers) == {"A"}
    assert "parent-service-token" not in repr(config)


@pytest.mark.parametrize("peers", [
    {}, {"R": {"url": "http://root.invalid", "token_file": "parent.token"}},
    {"A": {"url": "http://user:password@parent.invalid", "token_file": "parent.token"}},
    {"A": {"url": "http://parent.invalid/path?token=secret", "token_file": "parent.token"}},
    {"A": {"url": "http://parent.invalid:invalid", "token_file": "parent.token"}},
    {"A": {"url": "http://parent.invalid:65536", "token_file": "parent.token"}},
])
def test_rejects_missing_foreign_or_credential_bearing_peer_config(tmp_path, peers):
    from fleet.server.control_unit_runtime import load_control_unit
    with pytest.raises(ValueError):
        load_control_unit(config_file(tmp_path, peers=peers))


def test_peer_transport_uses_scoped_paths_auth_and_bounded_reply(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    requests = []
    def serve(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True}, headers={"Content-Encoding": "identity"})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            peer = ControlUnitPeers(load_control_unit(config_file(tmp_path)), client)
            assert await peer("A", "GET", "R/job-1") == {"ok": True}
            await peer("A", "POST", "inbox", {"origin_id": "R"})
            await peer("A", "POST", "R/job-1", {})
            with pytest.raises(ValueError):
                await peer("R", "GET", "R/job-1")
            with pytest.raises(ValueError):
                await peer("A", "GET", "../secrets")
    asyncio.run(exercise())
    assert [r.url.path for r in requests] == ["/api/fleet/control-unit/delegations/R/job-1",
                                            "/api/fleet/control-unit/inbox",
                                            "/api/fleet/control-unit/delegations/R/job-1/cancel"]
    assert requests[0].headers["Authorization"] == "Bearer parent-service-token"
    assert requests[0].headers["Accept-Encoding"] == "identity"
    assert json.loads(requests[1].content) == {"origin_id": "R"}


@pytest.mark.parametrize("response,error,code", [
    (httpx.Response(302, headers={"Location": "http://other.invalid"}), httpx.HTTPStatusError, None),
    (httpx.Response(200, json={"data": "x" * 131073}), ValueError, "CONTROL_UNIT_PEER_RESPONSE_TOO_LARGE"),
])
def test_peer_transport_refuses_redirects_and_oversized_replies(tmp_path, response, error, code):
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response), follow_redirects=True) as client:
            peer = ControlUnitPeers(load_control_unit(config_file(tmp_path)), client)
            with pytest.raises(error, match=code):
                await peer("A", "GET", "R/job-1")
    asyncio.run(exercise())


@pytest.mark.parametrize("flag", ["share_information_with_parent", "accept_parent_stop"])
@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_information_and_stop_opt_ins_require_strict_booleans(tmp_path, flag, value):
    from fleet.server.control_unit_runtime import load_control_unit
    with pytest.raises(ValueError, match="INVALID_CONTROL_UNIT_OPT_IN"):
        load_control_unit(config_file(tmp_path, **{flag: value}))


def test_new_permissions_are_opt_in_without_changing_delegation_config(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit
    config = load_control_unit(config_file(tmp_path))
    assert config.share_information_with_parent is False
    assert config.accept_parent_stop is False
    assert config.tls_context is None
    config = load_control_unit(config_file(tmp_path, share_information_with_parent=True, accept_parent_stop=True))
    assert config.share_information_with_parent is True
    assert config.accept_parent_stop is True


@pytest.mark.parametrize("url", ["http://parent.invalid?", "http://parent.invalid#", "http://parent.invalid/#"])
def test_empty_query_and_fragment_delimiters_are_rejected(tmp_path, url):
    from fleet.server.control_unit_runtime import load_control_unit
    with pytest.raises(ValueError, match="INVALID_CONTROL_UNIT_PEER_URL"):
        load_control_unit(config_file(tmp_path, peers={"A": {"url": url, "token_file": "parent.token"}}))


@pytest.mark.parametrize("left,right", [
    ("HTTP://PARENT.invalid", "http://parent.invalid:80/"),
    ("https://PARENT.invalid/", "https://parent.invalid:443"),
    ("http://[::1]", "http://[::1]:80/"),
])
def test_endpoint_collision_uses_normalized_host_scheme_and_default_port(tmp_path, left, right):
    from fleet.server.control_unit_runtime import load_control_unit
    (tmp_path / "child.token").write_text("distinct-child-token", encoding="ascii")
    with pytest.raises(ValueError, match="CONTROL_UNIT_PEER_ENDPOINT_COLLISION"):
        load_control_unit(config_file(tmp_path, unit_id="R", peers={
            "A": {"url": left, "token_file": "parent.token"},
            "B": {"url": right, "token_file": "child.token"}}))


def test_outgoing_credentials_cannot_be_shared_by_neighbors(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit
    with pytest.raises(ValueError, match="CONTROL_UNIT_SERVICE_CREDENTIAL_NOT_ISOLATED"):
        load_control_unit(config_file(tmp_path, unit_id="R", peers={
            "A": {"url": "http://a.invalid", "token_file": "parent.token"},
            "B": {"url": "http://b.invalid", "token_file": "parent.token"}}))


@pytest.mark.parametrize("role", ["service", "operator", "viewer", "policy-admin"])
def test_outgoing_token_must_differ_from_every_incoming_principal(tmp_path, role):
    from hashlib import sha256
    from types import SimpleNamespace
    from fleet.server.control_unit_runtime import install_control_unit
    principals = {
        sha256(b"unrelated-incoming-token").hexdigest():
            SimpleNamespace(principal_id="control-unit:A", role="service"),
        sha256(b"parent-service-token").hexdigest():
            SimpleNamespace(principal_id="other-incoming", role=role),
    }
    with pytest.raises(ValueError, match="CONTROL_UNIT_SERVICE_CREDENTIAL_NOT_ISOLATED"):
        install_control_unit(SimpleNamespace(state=SimpleNamespace()), config_file(tmp_path),
                             tasks=object(), console=SimpleNamespace(uses_rest_token=lambda _: False,
                                                                          uses_agent_pairing_token=lambda _: False),
                             principals=principals, named_logins={}, console_token=None,
                             authorize=None, require_viewer=None, require_named_operator=None)


def test_information_and_stop_transport_are_scoped_to_child_subtrees(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    requests = []
    async def exercise():
        path = config_file(tmp_path, unit_id="R", peers={
            "A": {"url": "http://a.invalid", "token_file": "parent.token"},
            "B": {"url": "http://b.invalid", "token_file": "child.token"}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: requests.append(request) or httpx.Response(200, json={"ok": True}))) as client:
            peer = ControlUnitPeers(load_control_unit(path), client)
            for method, target in [("GET", "overview"), ("GET", "units/A"), ("GET", "units/A1/map"),
                                   ("POST", "stop-inbox"), ("GET", "stops/R/stop-1")]:
                assert await peer("A", method, target) == {"ok": True}
            for method, target in [("GET", "units/B"), ("GET", "units/A1/map/extra"),
                                   ("GET", "stops/B/stop-1"), ("GET", "stops"),
                                   ("POST", "stops/R/stop-1/reconcile"), ("POST", "stops")]:
                with pytest.raises(ValueError):
                    await peer("A", method, target)
            parent = ControlUnitPeers(load_control_unit(config_file(tmp_path)), client)
            for method, target in [("GET", "overview"), ("GET", "units/R"),
                                   ("POST", "stop-inbox"), ("GET", "stops/R/stop-1")]:
                with pytest.raises(ValueError):
                    await parent("A", method, target)
    (tmp_path / "child.token").write_text("distinct-child-token", encoding="ascii")
    asyncio.run(exercise())
    assert [request.url.path for request in requests] == [
        "/api/fleet/control-unit/overview", "/api/fleet/control-unit/units/A",
        "/api/fleet/control-unit/units/A1/map", "/api/fleet/control-unit/stop-inbox",
        "/api/fleet/control-unit/stops/R/stop-1"]


def test_transport_enforces_request_and_per_path_response_limits(tmp_path):
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    seen = []
    def serve(request):
        seen.append(request)
        return httpx.Response(200, json={"data": "x" * 140_000})
    async def exercise():
        config = load_control_unit(config_file(tmp_path, unit_id="A", peers={
            "R": {"url": "http://r.invalid", "token_file": "parent.token"},
            "A1": {"url": "http://a1.invalid", "token_file": "child.token"}}))
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            peer = ControlUnitPeers(config, client)
            with pytest.raises(ValueError, match="REQUEST_TOO_LARGE"):
                await peer("A1", "POST", "stop-inbox", {"data": "x" * 131_072})
            assert seen == []
            with pytest.raises(ValueError, match="RESPONSE_TOO_LARGE"):
                await peer("A1", "GET", "overview")
            assert len((await peer("A1", "GET", "units/A1/map"))["data"]) == 140_000
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"data": "x" * 2_097_152}))) as client:
            with pytest.raises(ValueError, match="RESPONSE_TOO_LARGE"):
                await ControlUnitPeers(config, client)("A1", "GET", "units/A1/map")
    (tmp_path / "child.token").write_text("distinct-child-token", encoding="ascii")
    asyncio.run(exercise())


def test_whole_request_deadline_cancels_a_continuously_trickling_body(tmp_path, monkeypatch):
    from fleet.server import control_unit_runtime as runtime
    timeout = asyncio.timeout
    deadlines, closed = [], []
    def fast_deadline(seconds):
        deadlines.append(seconds)
        return timeout(0.03)
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b" "
        async def aclose(self):
            closed.append(True)
    monkeypatch.setattr(runtime.asyncio, "timeout", fast_deadline)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, stream=Trickle()))) as client:
            peer = runtime.ControlUnitPeers(runtime.load_control_unit(config_file(tmp_path)), client)
            with pytest.raises(TimeoutError):
                await peer("A", "GET", "R/job-1")
    asyncio.run(exercise())
    assert deadlines == [3.0] and closed


@pytest.fixture
def control_unit_ca(tmp_path):
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "control-unit fixture")])
    now = datetime.now(timezone.utc)
    root = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    ca = tmp_path / "ca.pem"
    ca.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    return ca


@pytest.mark.parametrize("ca", [None, "", False, 123])
def test_explicit_ca_path_must_be_a_nonempty_string(tmp_path, ca):
    from fleet.server.control_unit_runtime import load_control_unit
    with pytest.raises(ValueError, match="CONTROL_UNIT_TLS_CA_FILE_REQUIRED"):
        load_control_unit(config_file(tmp_path, tls_ca_file=ca))


def test_explicit_ca_file_must_exist_and_contain_a_certificate(tmp_path):
    import ssl
    from fleet.server.control_unit_runtime import load_control_unit
    with pytest.raises(FileNotFoundError):
        load_control_unit(config_file(tmp_path, tls_ca_file="missing.pem"))
    (tmp_path / "invalid.pem").write_text("not a CA certificate", encoding="ascii")
    with pytest.raises(ssl.SSLError):
        load_control_unit(config_file(tmp_path, tls_ca_file="invalid.pem"))

@pytest.mark.parametrize("source", ["console", "device", "agent"])
def test_outgoing_token_remains_disjoint_from_console_and_device_tokens(tmp_path, source):
    from hashlib import sha256
    from types import SimpleNamespace
    from fleet.server.control_unit_runtime import install_control_unit
    principals = {sha256(b"incoming-parent-token").hexdigest():
                  SimpleNamespace(principal_id="control-unit:A", role="service")}
    with pytest.raises(ValueError, match="CONTROL_UNIT_SERVICE_CREDENTIAL_NOT_ISOLATED"):
        install_control_unit(SimpleNamespace(state=SimpleNamespace()), config_file(tmp_path),
                             tasks=object(), console=SimpleNamespace(uses_rest_token=lambda _: source == "device",
                                                                          uses_agent_pairing_token=lambda _: source == "agent"),
                             principals=principals, named_logins={},
                             console_token="parent-service-token" if source == "console" else None,
                             authorize=None, require_viewer=None, require_named_operator=None)


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "identity, gzip"])
def test_encoded_peer_response_is_rejected_before_any_body_read(tmp_path, encoding):
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    closed = []
    class NeverRead(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("encoded body must not reach the decoder")
            yield b""
        async def aclose(self):
            closed.append(True)
    def serve(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, headers={"Content-Encoding": encoding}, stream=NeverRead())
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            peer = ControlUnitPeers(load_control_unit(config_file(tmp_path)), client)
            with pytest.raises(ValueError, match="CONTROL_UNIT_PEER_ENCODING_NOT_ALLOWED"):
                await peer("A", "GET", "R/job-1")
    asyncio.run(exercise())
    assert closed
