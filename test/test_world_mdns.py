"""Tests for ROSY World <-> Non-World Docker + mDNS federation."""

from __future__ import annotations

import datetime
import json
import os
import socket
import ssl
import sys
import threading
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "applications" / "world"))
sys.path.insert(0, str(ROOT / "test"))

import serve  # noqa: E402
import world_mdns  # noqa: E402
from test_world_env_adapters import _make_bundle  # noqa: E402


def _world_row(
    host="rosy-world.local",
    address="192.168.1.40",
    port=8140,
    txt='"product=rosy" "role=world" "proto=rosy-world/1" "tls=none" "worlds_api=1"',
):
    return f"=;eth0;IPv4;ROSY World;_rosy-world._tcp;local;{host};{address};{port};{txt}"


def test_world_mdns_xml_render_and_atomic_publish(tmp_path: Path) -> None:
    xml_text = world_mdns.render_world_service(8140)
    root = ElementTree.fromstring(xml_text)
    svc = root.find("service")
    assert svc.findtext("type") == "_rosy-world._tcp"
    assert svc.findtext("port") == "8140"
    assert {item.text for item in svc.findall("txt-record")} >= {
        "product=rosy", "role=world", "proto=rosy-world/1", "tls=none", "worlds_api=1",
    }

    with pytest.raises(ValueError):
        world_mdns.render_world_service(0)
    with pytest.raises(ValueError):
        world_mdns.render_world_service(8140, tls=False, tls_host="rosy-world.local")

    out = tmp_path / "rosy-world.service"
    world_mdns.publish_world_service(out, 8140)
    assert out.is_file()
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o644


def test_world_and_fleet_mdns_parsers_reject_bad_records() -> None:
    rows = "\n".join((
        _world_row(),
        _world_row(),  # duplicate interface deduplicated
        _world_row(host="evil.example"),
        _world_row(address="127.0.0.1"),
        _world_row(address="100.64.0.12"),
        _world_row(address="169.254.1.5"),
        _world_row(port=0),
        _world_row(txt='"product=rosy" "role=world" "role=world" "proto=rosy-world/1" "tls=none"'),
        _world_row().replace("_rosy-world._tcp", "_http._tcp"),
        "+;eth0;IPv4;unresolved;_rosy-world._tcp;local",
    ))
    parsed = world_mdns.parse_avahi_world(rows)
    assert len(parsed) == 1
    assert parsed[0]["hostname"] == "rosy-world.local"
    assert parsed[0]["scheme"] == "http" and parsed[0]["port"] == 8140

    fleet_rows = "\n".join((
        '=;eth0;IPv4;ROSY Fleet;_rosy-fleet._tcp;local;rosy-fleet-r.local;192.168.1.20;8443;"product=rosy" "role=fleet" "proto=site-v1" "tls=required"',
        '=;eth0;IPv4;Bad;_rosy-fleet._tcp;local;192.168.1.20;192.168.1.20;8443;"product=rosy" "role=fleet" "proto=site-v1" "tls=required"',
    ))
    fleets = world_mdns.parse_avahi_fleet(fleet_rows)
    assert fleets == [{"hostname": "rosy-fleet-r.local", "address": "192.168.1.20", "port": 8443, "scheme": "https"}]


def test_discover_world_endpoint_and_api_mdns(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path)
    server = serve.make_server(bundle, "127.0.0.1", 0, mdns_host="rosy-world.local", fleet_mdns_host="rosy-fleet-r.local")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        origin = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(f"{origin}/api/mdns", timeout=5) as resp:
            assert resp.headers["Cache-Control"] == "no-store"
            meta = json.loads(resp.read().decode("utf-8"))
        assert meta == {
            "schema": "rosy.world.mdns.v1",
            "service_type": "_rosy-world._tcp",
            "hostname": "rosy-world.local",
            "port": port,
            "fleet_mdns_host": "rosy-fleet-r.local",
            "worlds_api": "/api/worlds",
        }

        # Container NSS fallback resolves `.local` to live server health check and returns `.local` URL.
        endpoint = world_mdns.discover_world_endpoint(
            "rosy-world.local",
            default_port=port,
            browse_fn=lambda _svc: None,
            resolve_fn=lambda _host, _p: "127.0.0.1",
        )
        assert endpoint == f"http://rosy-world.local:{port}"

        # Unhealthy / wrong port fails closed.
        with pytest.raises(ValueError, match="health check failed"):
            world_mdns.discover_world_endpoint(
                "rosy-world.local",
                default_port=port + 1,
                browse_fn=lambda _svc: None,
                resolve_fn=lambda _host, _p: "127.0.0.1",
            )
    finally:
        server.stop_event.set()
        server.shutdown()
        server.server_close()


def test_two_sided_docker_compose_and_mdns_contracts() -> None:
    dockerfile = (ROOT / "applications/world/Dockerfile").read_text(encoding="utf-8")
    assert "libnss-mdns" in dockerfile and "mdns4_minimal" in dockerfile and "zeroconf==0.151.5" in dockerfile

    assert serve.WorldHTTPServer.request_queue_size >= 64

    world_compose = yaml.safe_load((ROOT / "applications/world/compose.yaml").read_text(encoding="utf-8"))
    for name in ("world", "real-bridge", "sim-swarm"):
        svc = world_compose["services"][name]
        assert "extra_hosts" not in svc
        assert svc["read_only"] is True
        assert svc["cap_drop"] == ["ALL"]
        assert any(isinstance(v, dict) and v.get("source") == "/run/avahi-daemon" and v.get("read_only") is True for v in svc["volumes"])
    assert "http://world:8140" in world_compose["services"]["real-bridge"]["command"]
    assert "http://world:8140" in world_compose["services"]["sim-swarm"]["command"]
    assert any(isinstance(v, dict) and v.get("target") == "/run/rosy-ca/site-ca.crt" for v in world_compose["services"]["real-bridge"]["volumes"])
    adv = world_compose["services"]["world-advertise"]
    assert adv["network_mode"] == "host" and "zeroconf" in " ".join(adv["command"])
    assert "--fleet-mdns-host" in " ".join(world_compose["services"]["real-bridge"]["command"])

    # Local LAN IPv4 discovery returns a list of valid private RFC1918 addresses (non-throwing).
    ips = world_mdns._local_lan_ipv4s()
    assert all(world_mdns._lan_ipv4(ip) for ip in ips)

    # Non-World side link overlay: configures Fleet's mDNS target without hosting a World container.
    link_compose = yaml.safe_load((ROOT / "deploy/site/compose.world-link.yaml").read_text(encoding="utf-8"))
    assert set(link_compose["services"]) == {"fleet"}
    assert "extra_hosts" not in link_compose["services"]["fleet"]
    assert "ROSY_WORLD_MDNS_HOST" in link_compose["services"]["fleet"]["environment"]
    assert "logging" not in link_compose["services"]["fleet"]

    # Co-located overlay uses Dockerfile + /run/avahi-daemon + mDNS host targets without overriding fleet logging.
    site_world = yaml.safe_load((ROOT / "deploy/site/compose.world.yaml").read_text(encoding="utf-8"))
    assert "logging" not in site_world["services"]["fleet"]
    bridge = site_world["services"]["world-real-bridge"]
    assert "--fleet-mdns-host" in " ".join(bridge["command"])
    assert bridge["environment"]["ROSY_FLEET_TOKEN_FILE"] == "/run/secrets/world_fleet_viewer_token"
    assert "world_fleet_viewer_token" in bridge["secrets"]
    assert "registry_token" not in bridge["secrets"]
    assert "world_fleet_viewer_token" in site_world["secrets"]
    for name in ("world", "world-real-bridge"):
        assert any(isinstance(v, dict) and v.get("source") == "/run/avahi-daemon" and v.get("read_only") is True for v in site_world["services"][name]["volumes"])

    unit = (ROOT / "deploy/site/rosy-world-advertise.service").read_text(encoding="utf-8")
    assert "world_mdns.py publish" in unit and "RestrictAddressFamilies=AF_UNIX" in unit
    assert "Environment=ROSY_WORLD_PORT=8140" in unit and "EnvironmentFile=-/run/rosy-site/world-public.env" in unit

    virtual_compose = yaml.safe_load((ROOT / "deploy/site/compose.virtual-closed-loop.yaml").read_text(encoding="utf-8"))
    assert "virtual-core-fleet" in virtual_compose["services"]
    assert virtual_compose["services"]["virtual-core-fleet"]["read_only"] is True
    for svc_name in ("virtual-core-fleet", "fleet-mdns"):
        assert any(isinstance(v, dict) and v.get("target") == "/world" for v in virtual_compose["services"][svc_name]["volumes"])
    mdns_cmd = virtual_compose["services"]["fleet-mdns"]["command"]
    assert mdns_cmd[3] == "advertise" and "--service-type" in mdns_cmd and "_rosy-fleet._tcp" in mdns_cmd


def test_probe_fleet_health_verifies_dot_local_san_when_dialing_ip(tmp_path: Path) -> None:
    """Regression test: dialing resolved IPv4 must still verify the TLS cert against the .local DNS SAN."""
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")]))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "rosy-fleet.local")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test CA")]))
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("rosy-fleet.local")]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    ca_file = tmp_path / "ca.crt"
    cert_file = tmp_path / "srv.crt"
    key_file = tmp_path / "srv.key"
    ca_file.write_bytes(ca.public_bytes(pem))
    cert_file.write_bytes(leaf.public_bytes(pem))
    key_file.write_bytes(leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file, key_file)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve_once() -> None:
        conn, _ = listener.accept()
        with conn, ctx.wrap_socket(conn, server_side=True) as tls:
            tls.recv(4096)
            tls.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{"status":"ok"}')
        listener.close()

    t = threading.Thread(target=serve_once, daemon=True)
    t.start()
    health = world_mdns.probe_fleet_health("127.0.0.1", port, hostname="rosy-fleet.local", ca_file=ca_file)
    t.join(3)
    assert health == {"status": "ok"}
