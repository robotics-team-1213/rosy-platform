"""D-801: the media authority accepts site-issued READ grants only with Fleet's live recheck and
the robot's own media switch, and kicks the real session when either goes away."""

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
from core_common.protocol.media_tokens import sign_media


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
SESSION = '00000000-0000-4000-8000-000000000077'
PATH = 'robots/rosy_01/front'


def _pem(key, private):
    if private:
        return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
    return key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)


def _serve(handler, context=None):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    if context is not None:
        server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _json_handler(answer, calls):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            calls.append((self.path, self.headers.get('Authorization', '')))
            status, body = answer(self.path, self.headers.get('Authorization', '')[7:])
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass
    return Handler


@pytest.fixture
def site(tmp_path):
    robot_key, site_key, tls_key = (Ed25519PrivateKey.generate() for _ in range(3))
    (tmp_path / 'robot.pub').write_bytes(_pem(robot_key, False))
    (tmp_path / 'site.pub').write_bytes(_pem(site_key, False))
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(tls_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), critical=False)
            .sign(tls_key, None))
    (tmp_path / 'ca.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (tmp_path / 'tls.pem').write_bytes(_pem(tls_key, True))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / 'ca.pem', tmp_path / 'tls.pem')
    state = {'media_on': True, 'fleet_active': True, 'kicks': [], 'core': [], 'fleet': [], 'claims': {}}

    def core(path, token):
        return (200, {'active': False}) if state['media_on'] else (503, {'error': {'code': 'MEDIA_UNAVAILABLE'}})

    def fleet(path, token):
        claims = state['claims']
        return 200, ({'active': True, **claims} if state['fleet_active'] else {'active': False})

    class MediaMTX(BaseHTTPRequestHandler):
        def do_POST(self):
            state['kicks'].append(self.path)
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    servers = [_serve(_json_handler(core, state['core']), context), _serve(_json_handler(fleet, state['fleet']), context),
               _serve(MediaMTX)]
    (tmp_path / 'admin').write_text('local-admin')
    config = {'audience': 'site:lab', 'admin_token_file': str(tmp_path / 'admin'),
              'mediamtx_api': f'http://127.0.0.1:{servers[2].server_port}',
              'robots': {'rosy_01': {'core_url': f'https://localhost:{servers[0].server_port}',
                                     'core_ca': str(tmp_path / 'ca.pem'), 'keys': {'robot-1': str(tmp_path / 'robot.pub')}}},
              'site_issuer': {'fleet_url': f'https://localhost:{servers[1].server_port}',
                              'fleet_ca': str(tmp_path / 'ca.pem'), 'keys': {'site-1': str(tmp_path / 'site.pub')}}}

    def token(iss='site:lab', key=site_key, kid='site-1', robot='rosy_01', action='read', now=100):
        claims = dict(iss=iss, aud='site:lab', sub='kim', jti='d' * 32, robot_id=robot,
                      path=f'robots/{robot}/front', action=action, iat=now, exp=now + 60)
        state['claims'] = {'grant_id': claims['jti'], 'robot_id': robot, 'path': claims['path'],
                           'action': action, 'audience': 'site:lab', 'expires_at': claims['exp']}
        return sign_media(claims, _pem(key, True), kid)

    try:
        yield config, token, state, robot_key
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def build(config):
    assert (ROOT / 'src/rosy_media/main.py').is_file()
    return importlib.import_module('rosy_media.main').build(config)[0]


def test_site_grant_opens_a_session_after_fleet_and_robot_both_agree(site):
    config, token, state, _ = site
    authority = build(config)
    assert authority.intent(token(), now=100)
    assert authority.authorize(token(), 'read', PATH, SESSION, now=100)
    assert state['core'] and state['core'][0][1] == 'Bearer site-veto-probe'
    assert state['fleet'] and state['fleet'][0] == ('/api/fleet/media/validate', 'Bearer ' + token())


def test_robot_veto_refuses_new_grants_and_kicks_live_sessions(site):
    config, token, state, _ = site
    authority = build(config)
    assert authority.intent(token(), now=100) and authority.authorize(token(), 'read', PATH, SESSION, now=100)
    state['media_on'] = False
    authority.tick(now=101)
    assert state['kicks'] == [f'/v3/webrtc/sessions/kick/{SESSION}']
    assert authority.intent(token(now=101), now=101) is None


def test_fleet_revocation_or_logout_kicks_within_one_recheck(site):
    config, token, state, _ = site
    authority = build(config)
    assert authority.intent(token(), now=100) and authority.authorize(token(), 'read', PATH, SESSION, now=100)
    state['fleet_active'] = False
    authority.tick(now=101)
    assert state['kicks'] == [f'/v3/webrtc/sessions/kick/{SESSION}']


def test_site_cannot_publish_and_robot_keys_cannot_speak_for_the_site(site):
    config, token, state, robot_key = site
    authority = build(config)
    with pytest.raises(Exception):
        token(action='publish')                       # the token schema refuses a site publish grant
    assert authority.intent(token(key=robot_key, kid='robot-1'), now=100) is None
    assert authority.intent(token(robot='rosy_02'), now=100) is None
    assert authority.intent(token(key=Ed25519PrivateKey.generate()), now=100) is None


def test_unreachable_fleet_fails_closed(site):
    config, token, state, _ = site
    config['site_issuer']['fleet_url'] = 'https://localhost:1'
    authority = build(config)
    assert authority.intent(token(), now=100) is None
