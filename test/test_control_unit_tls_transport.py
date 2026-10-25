"""Actual loopback TLS peer transport; synthetic certificates, no device or external network access."""
import asyncio

import httpx
import pytest
import yaml


def config_file(tmp_path, *, peers, tls_ca_file=None):
    (tmp_path / "parent.token").write_text("parent-service-token", encoding="ascii")
    document = {"unit_id": "A1", "manifest": {"revision": "v1", "units": [
        {"id": "A"}, {"id": "A1", "parent": "A"}]}, "peers": peers}
    if tls_ca_file is not None:
        document["tls_ca_file"] = tls_ca_file
    path = tmp_path / "control.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


@pytest.fixture
def control_unit_tls(tmp_path):
    from datetime import datetime, timedelta, timezone
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    ca_key = ec.generate_private_key(ec.SECP256R1())
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "control-unit fixture")])
    now = datetime.now(timezone.utc)
    root = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (x509.CertificateBuilder().subject_name(leaf_name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    ca, leaf, private = tmp_path / "ca.pem", tmp_path / "leaf.pem", tmp_path / "key.pem"
    ca.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    leaf.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(leaf, private)
    return server, ca


@pytest.mark.parametrize("trust,host,success,encoding", [
    (True, "localhost", True, "identity"), (False, "localhost", False, "identity"),
    (True, "127.0.0.1", False, "identity"), (True, "localhost", False, "gzip"),
])
def test_actual_tls_requires_explicit_ca_and_matching_hostname(
        tmp_path, monkeypatch, control_unit_tls, trust, host, success, encoding):
    import gzip
    import ssl
    from fleet.server.control_unit_runtime import load_control_unit, ControlUnitPeers
    server_context, ca = control_unit_tls
    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    received = []
    async def handle(reader, writer):
        try:
            received.append(await reader.readuntil(b"\r\n\r\n"))
            payload = b'{"ok":true}'
            if encoding == "gzip":
                payload = gzip.compress(payload)
            headers = (f"HTTP/1.1 200 OK\r\nContent-Length: {len(payload)}\r\n"
                       f"Content-Encoding: {encoding}\r\nConnection: close\r\n\r\n").encode("ascii")
            writer.write(headers + payload)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    async def exercise():
        server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
        async with server:
            port = server.sockets[0].getsockname()[1]
            options = {"tls_ca_file": ca.name} if trust else {}
            config = load_control_unit(config_file(tmp_path, peers={
                "A": {"url": f"https://{host}:{port}", "token_file": "parent.token"}}, **options))
            if trust:
                assert config.tls_context.check_hostname
                assert config.tls_context.verify_mode == ssl.CERT_REQUIRED
            async with httpx.AsyncClient(verify=config.tls_context or True, trust_env=False) as client:
                peer = ControlUnitPeers(config, client)
                if success:
                    assert await peer("A", "GET", "R/job-1") == {"ok": True}
                elif encoding == "gzip":
                    with pytest.raises(ValueError, match="CONTROL_UNIT_PEER_ENCODING_NOT_ALLOWED"):
                        await peer("A", "GET", "R/job-1")
                else:
                    with pytest.raises(httpx.ConnectError):
                        await peer("A", "GET", "R/job-1")
    asyncio.run(exercise())
    assert bool(received) is (trust and host == "localhost")
    assert all(b"accept-encoding: identity" in request.lower() for request in received)
