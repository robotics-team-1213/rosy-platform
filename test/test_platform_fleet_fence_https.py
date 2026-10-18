"""D-785: Fleet fence readback through the site HTTPS proxy with a pinned CA; real local TLS, no device."""
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import sys
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "middleware/devices/omx/agent/src"))

from rosy_agent.fleet_fence import HttpsFleetFenceReadback, fleet_fence_from_environment  # noqa: E402

TOKEN = "viewer-synthetic-token"
PATH = "/api/fleet/dispatch-control"


def _ca(tmp_path, stem, dns="site.test"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(dns)]), False).sign(key, hashes.SHA256()))
    ca = tmp_path / f"{stem}.pem"
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private = tmp_path / f"{stem}.key"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return ca, private


@pytest.fixture
def site(tmp_path):
    ca, private = _ca(tmp_path, "site")
    state = {"auth": [], "status": 200, "body": {"authority_epoch": 2, "generation": 8, "dispatch_enabled": True}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["auth"].append((self.path, self.headers.get("Authorization")))
            body = json.dumps(state["body"]).encode()
            self.send_response(state["status"])
            if state["status"] == 302:
                self.send_header("Location", "http://127.0.0.1:1/api/fleet/dispatch-control")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, private)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state.update(url=f"https://127.0.0.1:{server.server_port}{PATH}", ca=ca, tmp=tmp_path)
    yield state
    server.shutdown()
    server.server_close()


def _fence(site, **overrides):
    values = dict(ca_file=str(site["ca"]), tls_server_name="site.test")
    values.update(overrides)
    return HttpsFleetFenceReadback(site["url"], TOKEN, **values)


def test_matching_fence_reads_open_with_the_viewer_credential(site):
    assert _fence(site)(2, 8) is True
    assert site["auth"] == [(PATH, "Bearer " + TOKEN)]


@pytest.mark.parametrize("body", [
    {"authority_epoch": 2, "generation": 9, "dispatch_enabled": True},
    {"authority_epoch": 1, "generation": 8, "dispatch_enabled": True},
    {"authority_epoch": 2, "generation": 8, "dispatch_enabled": False},
])
def test_stale_or_closed_fence_reads_closed(site, body):
    site["body"] = body
    assert _fence(site)(2, 8) is False


@pytest.mark.parametrize("status", [302, 401, 503])
def test_non_200_and_redirects_read_closed(site, status):
    site["status"] = status
    assert _fence(site)(2, 8) is False


def test_another_ca_or_server_name_reads_closed_before_any_request(site):
    other, _ = _ca(site["tmp"], "other")
    assert _fence(site, ca_file=str(other))(2, 8) is False
    assert _fence(site, tls_server_name="fleet.test")(2, 8) is False
    assert site["auth"] == []


@pytest.mark.parametrize("url", [
    "https://site.test/api/fleet/dispatch-control", "https://0.0.0.0/api/fleet/dispatch-control",
    "https://127.0.0.1/wrong", "https://127.0.0.1/api/fleet/dispatch-control?x=1",
    "https://u@127.0.0.1/api/fleet/dispatch-control", "http://127.0.0.1/api/fleet/dispatch-control",
])
def test_configuration_refuses_names_and_ambiguous_endpoints(site, url):
    with pytest.raises(ValueError):
        HttpsFleetFenceReadback(url, TOKEN, ca_file=str(site["ca"]), tls_server_name="site.test")


@pytest.mark.parametrize("overrides", [{"ca_file": ""}, {"ca_file": "relative.pem"}, {"tls_server_name": ""},
                                       {"tls_server_name": "site test"}])
def test_configuration_requires_the_pinned_ca_and_name(site, overrides):
    with pytest.raises(ValueError):
        _fence(site, **overrides)


def test_environment_selects_https_only_with_ca_and_name(site, monkeypatch):
    monkeypatch.setenv("ROSY_FLEET_FENCE_URL", site["url"])
    monkeypatch.setenv("ROSY_FLEET_FENCE_TOKEN", TOKEN)
    monkeypatch.delenv("ROSY_FLEET_FENCE_CA", raising=False)
    monkeypatch.delenv("ROSY_FLEET_FENCE_TLS_NAME", raising=False)
    with pytest.raises(ValueError):
        fleet_fence_from_environment()
    monkeypatch.setenv("ROSY_FLEET_FENCE_CA", str(site["ca"]))
    monkeypatch.setenv("ROSY_FLEET_FENCE_TLS_NAME", "site.test")
    fence = fleet_fence_from_environment()
    assert isinstance(fence, HttpsFleetFenceReadback) and fence(2, 8) is True
