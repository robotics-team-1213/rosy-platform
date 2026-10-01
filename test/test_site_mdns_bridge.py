"""The host adapter accepts resolved ROSY services only."""

import importlib.util
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "deploy/site/mdns-bridge.py"


def _module():
    spec = importlib.util.spec_from_file_location("rosy_site_mdns_bridge", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolved_avahi_rows_become_a_deduplicated_station_scan():
    output = "\n".join((
        '=;eth0;IPv4;ROSY rosy-a;_rosy._tcp;local;rosy-a.local;192.168.1.10;8080;'
        '"stage=CORE_READY" "release=018" "name=rosy-a" "network=sta"',
        '=;wlan0;IPv4;ROSY rosy-a;_rosy._tcp;local;rosy-a.local;192.168.1.10;8080;'
        '"stage=CORE_READY" "name=rosy-a" "network=sta"',
        '=;eth0;IPv4;ROSY rosy-b;_rosy._tcp;local;rosy-b.local;192.168.1.11;8080;'
        '"stage=BOOTING" "name=rosy-b" "network=sta"',
        '=;eth0;IPv4;ROSY ap;_rosy._tcp;local;ap.local;10.42.0.1;8080;'
        '"network=ap"',
        '+;eth0;IPv4;ROSY not resolved;_rosy._tcp;local',
    ))
    rows = _module().parse_avahi(output)
    assert len(rows) == 2
    assert rows[0] == {"name": "rosy-a", "hostname": "rosy-a.local",
                       "address": "192.168.1.10", "port": 8080,
                       "stage": "CORE_READY", "release": "018", "network": "sta"}


def test_non_rosy_and_non_local_records_are_ignored():
    output = ('=;eth0;IPv4;imposter;_http._tcp;local;x.local;192.168.1.3;80;'
              '"name=imposter"\n'
              '=;eth0;IPv4;far;_rosy._tcp;example.com;far.example.com;192.168.1.4;8080;'
              '"name=far"')
    assert _module().parse_avahi(output) == []


# D-370 5.1: this standalone copy is held to the shared TXT vectors.
import json  # noqa: E402

import pytest  # noqa: E402

VECTORS = json.loads((Path(__file__).resolve().parent / "fixtures/protocol/discovery-txt.v1.json")
                     .read_text(encoding="utf-8"))


def avahi_line(case: dict) -> str:
    """One resolved avahi-browse -p row for a vector case."""
    family = "IPv6" if ":" in (case["address"] or "") else "IPv4"
    txt = " ".join(f'"{item}"' for item in case["txt"])
    return (f'=;eth0;{family};ROSY {case["id"]};{case["service_type"]};local;'
            f'{case["host"]};{case["address"]};{case["port"]};{txt}')


@pytest.mark.parametrize("case", VECTORS["cases"], ids=lambda case: case["id"])
def test_bridge_accepts_exactly_the_robot_vectors(case):
    accepted = case["expect"]["accepted"] and case["service_type"] == "_rosy._tcp"
    assert bool(_module().parse_avahi(avahi_line(case))) is accepted


# 2026-10-01 audit #4: the scan goes to the local proxy over loopback and proves the site by
# tls_host + site CA, so a renumbered LAN or a stale FQDN cannot take the scanner offline.
import datetime  # noqa: E402
import socket  # noqa: E402
import ssl  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _site_pki(tmp_path, tls_host, *, strict=True):
    """A site CA and a leaf whose only SAN is tls_host (no IP SAN), as PEM files.

    strict=True follows README "Site certificate profile"; False drops key usage and key
    identifiers, which OpenSSL's X509_STRICT rejects.
    """
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)

    def cert(subject, issuer, key, signer, *, ca, san=None):
        builder = (x509.CertificateBuilder()
                   .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
                   .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)]))
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - datetime.timedelta(minutes=5))
                   .not_valid_after(now + datetime.timedelta(days=1))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None),
                                  critical=True))
        if strict:
            builder = (builder
                       .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                                      critical=False)
                       .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                           signer.public_key()), critical=False)
                       .add_extension(x509.KeyUsage(
                           digital_signature=not ca, key_cert_sign=ca, crl_sign=ca,
                           content_commitment=False, key_encipherment=False,
                           data_encipherment=False, key_agreement=False, encipher_only=False,
                           decipher_only=False), critical=True))
            if not ca:
                builder = builder.add_extension(
                    x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        if san:
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]),
                                            critical=False)
        return builder.sign(signer, hashes.SHA256())

    ca_key, leaf_key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    ca = cert("rosy test site CA", "rosy test site CA", ca_key, ca_key, ca=True)
    leaf = cert(tls_host, "rosy test site CA", leaf_key, ca_key, ca=False, san=tls_host)
    pem = serialization.Encoding.PEM
    (tmp_path / "site-ca.crt").write_bytes(ca.public_bytes(pem))
    (tmp_path / "site.crt").write_bytes(leaf.public_bytes(pem))
    (tmp_path / "site.key").write_bytes(leaf_key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return tmp_path / "site-ca.crt"


def _proxy(tmp_path):
    """One-shot TLS server on 127.0.0.1 that records SNI and the request, answers 200."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "site.crt", tmp_path / "site.key")
    seen = {}
    context.sni_callback = lambda sock, name, ctx: seen.update(sni=name)
    listener = socket.create_server(("127.0.0.1", 0))

    def serve():
        conn, _ = listener.accept()
        try:
            with context.wrap_socket(conn, server_side=True) as tls:
                data = b""
                while b"\r\n\r\n" not in data:
                    data += tls.recv(4096)
                head, body = data.split(b"\r\n\r\n", 1)
                length = int([line for line in head.split(b"\r\n")
                              if line.lower().startswith(b"content-length:")][0].split(b":")[1])
                while len(body) < length:
                    body += tls.recv(4096)
                seen.update(head=head.decode("ascii"), body=body)
                tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
        except (ssl.SSLError, OSError) as error:
            seen.update(error=error)
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return listener.getsockname()[1], seen, thread


def test_scan_posts_over_loopback_with_tls_host_as_sni_and_host(tmp_path):
    ca_file = _site_pki(tmp_path, "site-pc.local")
    port, seen, thread = _proxy(tmp_path)
    status = _module().post_scan([{"name": "rosy-a"}], tls_host="site-pc.local", port=port,
                                 ca_file=ca_file, token="scanner-secret")
    thread.join(5)
    assert status == 200
    assert seen["sni"] == "site-pc.local"
    assert seen["head"].startswith("POST /api/fleet/discovery/scan HTTP/1.1\r\n")
    assert f"Host: site-pc.local:{port}" in seen["head"]
    assert "Authorization: Bearer scanner-secret" in seen["head"]
    assert json.loads(seen["body"]) == {"devices": [{"name": "rosy-a"}]}


def test_scan_refuses_a_proxy_whose_certificate_is_not_the_site(tmp_path):
    ca_file = _site_pki(tmp_path, "other-pc.local")
    port, seen, thread = _proxy(tmp_path)
    with pytest.raises(ssl.SSLCertVerificationError):
        _module().post_scan([], tls_host="site-pc.local", port=port, ca_file=ca_file,
                            token="scanner-secret")
    thread.join(5)
    assert "head" not in seen


def test_avahi_failure_posts_nothing_so_fleet_keeps_the_last_good_scan(tmp_path, monkeypatch):
    module = _module()
    token = tmp_path / "discovery_token"
    token.write_text("scanner-secret", encoding="utf-8")
    posted = []

    def avahi_down(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(module.subprocess, "run", avahi_down)
    monkeypatch.setattr(module, "post_scan", lambda *args, **kwargs: posted.append(args) or 200)
    monkeypatch.setattr("sys.argv", ["mdns-bridge.py", "--tls-host", "site-pc.local",
                                     "--port", "8443", "--ca-file", str(tmp_path / "ca.crt"),
                                     "--token-file", str(token)])
    with pytest.raises(subprocess.CalledProcessError):
        module.main()
    assert posted == []


@pytest.mark.parametrize("name, ok", [("site-pc.local", True), ("fleet.example.org", True),
                                      ("10.16.36.5", False), ("::1", False), ("proxy", False),
                                      ("https://site-pc.local", False)])
def test_tls_host_is_a_certificate_name_not_an_address(name, ok):
    assert _module().valid_tls_host(name) is ok


def test_bridge_unit_targets_tls_host_and_loopback_only():
    unit = (ROOT / "deploy/site/rosy-mdns-bridge.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=/run/rosy-site/site-public.env" in unit
    assert "/etc/rosy/site/site.env" not in unit and "${" not in unit  # only the two public values
    assert "ROSY_SITE_DISCOVERY_URL" not in unit and "--url" not in unit
    assert "IPAddressDeny=any" in unit and "IPAddressAllow=localhost" in unit
    for name in ("rosy-fleet-advertise.service", "rosy-overhead-advertise.service"):
        advertise = (ROOT / "deploy/site" / name).read_text(encoding="utf-8")
        assert "EnvironmentFile=-/run/rosy-site/site-public.env" in advertise
        assert "/etc/rosy/site/.env" not in advertise


def _run_main(module, monkeypatch, tmp_path, token, *args, env=None):
    token_file = tmp_path / "discovery_token"
    token_file.write_bytes(token)
    posted = []
    monkeypatch.setattr(module.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""))
    monkeypatch.setattr(module, "post_scan", lambda devices, **kwargs: posted.append(kwargs) or 200)
    for key in ("ROSY_SITE_TLS_HOST", "ROSY_SITE_HTTPS_PORT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in (env or {}).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", ["mdns-bridge.py", "--ca-file", str(tmp_path / "ca.crt"),
                                     "--token-file", str(token_file), *args])
    module.main()
    return posted


def test_tls_host_and_port_come_from_the_environment_with_the_compose_default(tmp_path, monkeypatch):
    module = _module()
    posted = _run_main(module, monkeypatch, tmp_path, b"scanner-secret\n",
                       env={"ROSY_SITE_TLS_HOST": "Site-PC.local."})
    assert (posted[0]["tls_host"], posted[0]["port"]) == ("site-pc.local", 8443)
    posted = _run_main(module, monkeypatch, tmp_path, b"scanner-secret",
                       env={"ROSY_SITE_TLS_HOST": "site-pc.local", "ROSY_SITE_HTTPS_PORT": "9443"})
    assert posted[0]["port"] == 9443


@pytest.mark.parametrize("token", [b"", b"abc\r\nX-Injected: 1", b"two words", b"tab\there",
                                   "caf\u00e9".encode("utf-8"), b"nul\x00byte"])
def test_token_with_control_or_non_printable_bytes_is_refused(tmp_path, monkeypatch, token):
    module = _module()
    with pytest.raises(SystemExit) as exit_info:
        _run_main(module, monkeypatch, tmp_path, token, env={"ROSY_SITE_TLS_HOST": "site-pc.local"})
    assert exit_info.value.code == 2


def test_bridge_keeps_strict_x509_verification(tmp_path):
    """A CA without key usage / key identifiers fails, on every Python version."""
    ca_file = _site_pki(tmp_path, "site-pc.local", strict=False)
    port, seen, thread = _proxy(tmp_path)
    with pytest.raises(ssl.SSLCertVerificationError):
        _module().post_scan([], tls_host="site-pc.local", port=port, ca_file=ca_file,
                            token="scanner-secret")
    thread.join(5)
    assert "head" not in seen
