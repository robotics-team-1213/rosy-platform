"""Real TLS requests keep source credentials at CORE and scoped grants at media."""

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import ssl
import sys
import threading
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def implementation():
    assert (ROOT / 'src/rosy_media_edge/clients.py').is_file(), 'D-789 TLS source client is missing'
    return importlib.import_module('rosy_media_edge.clients')


@pytest.fixture
def tls_core(tmp_path):
    key = Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
            .sign(key, None))
    ca, private = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    calls, changes = [], {}

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            calls.append((self.command, self.path, self.headers.get('Authorization'), body))
            if self.path == '/api/v1/vision/media/source-grant':
                result = dict(grant_id='a'*32, token='narrow-publish-grant', expires_at=int(time.time())+60,
                    audience='site:lab', robot_id='rosy_01', path='robots/rosy_01/front', action='publish',
                    site_url=base)
                result.update(changes)
            elif self.path.endswith('/demand'):
                result = dict(active=True, robot_id='rosy_01', fps=15, target_bitrate=800000, max_bitrate=1000000)
            else:
                result = {'active': True, 'session_id': 'owned-session'}
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_POST = do_GET = do_DELETE = handle_request

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, private)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    base = f'https://localhost:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield base, str(ca), calls, changes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def client(module, base, ca):
    return module.CoreSourceClient(core_url=base, site_url=base, robot_id='rosy_01',
        audience='site:lab', source_token='source-only-credential', core_ca=ca, site_ca=ca)


def test_source_grants_use_validated_tls_and_never_forward_source_credential_to_site(tls_core):
    module = implementation()
    base, ca, calls, _ = tls_core
    source = client(module, base, ca)
    grant = source.source_grant()
    assert source.demand(grant)['active'] is True
    assert source.renew_session(grant)['active'] is True
    source.source_grant(grant_id=grant.grant_id)
    assert calls[0][2] == 'Bearer source-only-credential'
    assert calls[1][2] == calls[2][2] == 'Bearer narrow-publish-grant'
    assert calls[3][3]['grant_id'] == grant.grant_id
    assert all('?' not in entry[1] for entry in calls)


def test_source_client_does_not_disable_certificate_verification(tls_core):
    module = implementation()
    base, _, _, _ = tls_core
    with pytest.raises(module.MediaHTTPError):
        client(module, base, None).source_grant()


def test_source_client_refuses_cross_robot_grant(tls_core):
    module = implementation()
    base, ca, _, changes = tls_core
    changes['robot_id'] = 'another-robot'
    with pytest.raises(module.MediaHTTPError):
        client(module, base, ca).source_grant()


def test_source_client_rejects_plain_http_and_url_credentials():
    module = implementation()
    for url in ['http://localhost:9999', 'https://user:secret@localhost', 'https://localhost?token=x']:
        with pytest.raises(ValueError):
            client(module, url, None)
