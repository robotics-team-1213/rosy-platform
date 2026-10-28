"""The production composition binds revocation to the real MediaMTX kick API (D-789 T2)."""

from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import ssl
import sys
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID
from core_common.protocol.media_tokens import sign_media, verify_media


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
SESSION = '00000000-0000-4000-8000-000000000042'
PATH = 'robots/rosy_01/front'


def _serve(handler, context=None):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    if context is not None:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def site(tmp_path):
    media_key = Ed25519PrivateKey.generate()
    private = media_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption())
    public = tmp_path / 'rosy_01.pub.pem'
    public.write_bytes(media_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    tls_key = Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(tls_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
            .sign(tls_key, None))
    ca, tls_private = tmp_path / 'core-ca.pem', tmp_path / 'core-key.pem'
    ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    tls_private.write_bytes(tls_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
    state = {'online': True, 'kick_status': 200, 'kicks': [], 'validated': []}

    class Core(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            presented = self.headers.get('Authorization', '')[7:]
            state['validated'].append(self.path)
            claims = verify_media(presented, {'media-1': public.read_bytes()}, robot_id='rosy_01',
                                  audience='site:lab', now=state['now'])
            data = json.dumps(dict(active=state['online'], grant_id=claims.jti, robot_id='rosy_01',
                                   path=claims.path, action=claims.action, audience=claims.aud,
                                   expires_at=claims.exp)).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    class MediaMTX(BaseHTTPRequestHandler):
        def do_POST(self):
            state['kicks'].append((self.path, self.headers.get('Authorization')))
            self.send_response(state['kick_status'])
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, tls_private)
    core, core_thread = _serve(Core, context)
    mediamtx, mediamtx_thread = _serve(MediaMTX)
    admin = tmp_path / 'media-admin'
    admin.write_text('local-media-admin\n')
    config = {'audience': 'site:lab', 'admin_token_file': str(admin),
              'mediamtx_api': f'http://127.0.0.1:{mediamtx.server_port}',
              'robots': {'rosy_01': {'core_url': f'https://localhost:{core.server_port}',
                                     'core_ca': str(ca), 'keys': {'media-1': str(public)}}}}

    def token(action='read', grant_id='a' * 32, now=100):
        return sign_media(dict(iss='robot:rosy_01', aud='site:lab', sub='owner', jti=grant_id,
            robot_id='rosy_01', path=PATH, action=action, iat=now, exp=now + 60), private, 'media-1')

    try:
        yield config, token, state, core
    finally:
        for server, thread in ((core, core_thread), (mediamtx, mediamtx_thread)):
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def module():
    assert (ROOT / 'src/rosy_media/main.py').is_file(), 'D-789 production media composition missing'
    return importlib.import_module('rosy_media.main')


def _viewer(authority, token, state, now=100):
    state['now'] = now
    assert authority.intent(token(now=now), now=now)
    assert authority.authorize(token(now=now), 'read', PATH, SESSION, now=now)


def test_core_revocation_kicks_exact_session_through_local_mediamtx_api(site):
    config, token, state, _ = site
    authority, admin, port = module().build(config)
    assert (admin, port) == ('local-media-admin', 9121)
    _viewer(authority, token, state)
    assert state['validated'] == ['/api/v1/vision/media/validate'] * 2
    state['now'] = 101
    authority.tick(now=101)
    assert state['kicks'] == []
    state['online'] = False
    authority.tick(now=102)
    assert state['kicks'] == [(f'/v3/webrtc/sessions/kick/{SESSION}', 'Bearer local-media-admin')]
    assert authority.bound_session(token(), now=102) is None


def test_unreachable_core_fails_closed_with_a_real_kick(site):
    config, token, state, core = site
    authority, _, _ = module().build(config)
    _viewer(authority, token, state)
    core.shutdown()
    core.server_close()
    authority.tick(now=101)
    assert [path for path, _ in state['kicks']] == [f'/v3/webrtc/sessions/kick/{SESSION}']


def test_refused_kick_keeps_session_retryable_and_fails_the_tick(site):
    config, token, state, _ = site
    authority, _, _ = module().build(config)
    _viewer(authority, token, state)
    state['online'], state['kick_status'], state['now'] = False, 500, 101
    with pytest.raises(RuntimeError):
        authority.tick(now=101)  # the server ticker then withholds its heartbeat
    state['kick_status'] = 200
    authority.tick(now=101.5)
    assert len(state['kicks']) == 2


@pytest.mark.parametrize('field,value', [('core_url', 'http://localhost:8443'),
                                         ('core_url', 'https://u:p@localhost:8443'),
                                         ('core_url', 'https://localhost:8443/api')])
def test_robot_core_origin_must_be_fixed_https(site, field, value):
    config, _, _, _ = site
    config['robots']['rosy_01'][field] = value
    with pytest.raises(ValueError):
        module().build(config)
