"""Real authority ledger -> PKCE receiver -> CORE, with no robot movement."""
import json
import time
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from core_common.protocol.account_client import AccountClient, AccountDenied, AccountUnavailable

ROOT = Path(__file__).resolve().parents[4]
for directory in (ROOT/'operations/fleet', ROOT/'test'):
    sys.path.insert(0, str(directory))


@pytest.fixture
def pipeline(tmp_path, core_client):
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.site_users import hash_password
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from browser_harness import safe_listener
    fleet_socket, robot_socket = safe_listener(), safe_listener()
    issuer, robot = (f'https://localhost:{sock.getsockname()[1]}' for sock in (fleet_socket, robot_socket))
    private = Ed25519PrivateKey.generate()
    key = tmp_path/'signing.pem'
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    key.chmod(0o600)
    settings = {'issuer':issuer, 'site_id':'one', 'key_id':'key-1', 'private_key_file':str(key),
        'bootstrap_admin_login':'alice', 'clients':{'robot-app':{
            'redirect_uris':[robot+'/api/account/callback'], 'resources':['robot:r1']}}}
    config = tmp_path/'authority.json'; config.write_text(json.dumps(settings)); config.chmod(0o600)
    console = FleetConsole([], [])
    fleet = create_app(console, task_service=FleetTaskService(FleetTaskStore(tmp_path/'fleet.db'), robot_ids=[]),
        site_logins={'alice':{'principal_id':'alice','role':'operator', 'password_scrypt':hash_password('test-password')}},
        account_config=config, web_common=ROOT/'shared/web', start_task_dispatcher=False)
    sessions = fleet.state.password_sessions
    def login():
        return sessions.issue('alice', remember=False, verified=sessions.check('test','alice','test-password'))
    manager = login(); actor = sessions.account_context(manager)
    sessions.update_account(manager, actor['account_id'], revision=actor['revision'], grants=[
        {'resource':'site:one','capabilities':['accounts.manage']},
        {'resource':'robot:r1','capabilities':['robot.read']}])
    authority = fleet.state.account_authority
    clock = [int(time.time())]
    authority.clock = lambda:clock[0]
    backchannel = TestClient(fleet, base_url=issuer)
    def post(endpoint, fields):
        response = backchannel.post('/api/fleet/auth/'+endpoint, data=fields)
        if response.status_code != 200: raise AccountDenied('Account refused')
        return response.json() if response.content else {}
    receiver = AccountClient(tmp_path/'receiver.db', issuer=issuer, client_id='robot-app', resource='robot:r1',
        callback=robot+'/api/account/callback', public_keys=authority.public_keys,
        encryption_key=Fernet.generate_key(), clock=lambda:clock[0], post=post)
    core, _ = core_client(dev_auth=False)
    core.app.state.account_client = receiver
    core.base_url = robot
    core.test_sockets = (fleet_socket, robot_socket)
    yield core, TestClient(fleet, base_url=issuer), sessions, login, receiver, clock
    core.close(); backchannel.close()
    fleet_socket.close(); robot_socket.close()


def test_login_callback_refresh_revoke_and_core_scope(pipeline):
    core, fleet, sessions, login, receiver, clock = pipeline
    from fleet.server.password_session import COOKIE
    fleet.cookies.set(COOKIE, login())
    start = core.get('/api/account/login?return=/dashboard', follow_redirects=False)
    assert start.status_code == 303
    assert 'HttpOnly' in start.headers['set-cookie'] and 'SameSite=lax' in start.headers['set-cookie']
    authorization = fleet.get(start.headers['location'], follow_redirects=False)
    assert authorization.status_code == 302
    callback = core.get(authorization.headers['location'], follow_redirects=False)
    assert callback.status_code == 303
    identity = core.get('/api/account/session').json()
    assert identity['authenticated'] and identity['capabilities'] == ['robot.read']
    assert identity['profile'] == {'account_id':identity['account_id'],'login':'alice','display_name':'alice'}
    assert identity['profile_url'] == receiver.issuer + '/console/profile'
    sessions.profile(fleet.cookies[COOKIE], 'Updated Alice')
    assert core.get('/api/account/session').json()['profile']['display_name'] == 'Updated Alice'
    from core_common.protocol.account_client import AccountUnavailable
    original_post = receiver.post
    def unavailable_profile(endpoint, fields):
        if endpoint == 'userinfo':
            raise AccountUnavailable()
        return original_post(endpoint, fields)
    receiver.post = unavailable_profile
    unavailable = core.get('/api/account/session').json()
    assert unavailable['authenticated'] and unavailable['profile'] is None
    assert unavailable['capabilities'] == ['robot.read']
    receiver.post = original_post
    assert core.get('/api/v1/auth/whoami').status_code == 200
    assert core.post('/api/v1/teleop', json={'linear':0,'angular':0}, headers={'Origin':str(core.base_url).rstrip('/')}).status_code == 403
    clock[0] += 270
    assert core.get('/api/account/session').json()['session_family'] == identity['session_family']
    from starlette.websockets import WebSocketDisconnect
    with core.websocket_connect('wss://'+urlsplit(str(core.base_url)).netloc+'/ws/state',
                                headers={'Origin':str(core.base_url).rstrip('/')}) as ws:
        assert 'robot_id' in ws.receive_json()
        sessions.revoke(fleet.cookies[COOKIE])
        clock[0] += 10
        started = time.monotonic()
        with pytest.raises(WebSocketDisconnect) as closed:
            while time.monotonic()-started < 20:
                ws.receive_json()
        assert closed.value.code == 4401
        assert time.monotonic()-started < 15
    assert core.get('/api/v1/auth/whoami').status_code == 401
    assert not core.get('/api/account/session').json()['authenticated']


@pytest.fixture
def authenticated_pipeline(pipeline):
    core, fleet, _, login, _, _ = pipeline
    from fleet.server.password_session import COOKIE
    fleet.cookies.set(COOKIE, login())
    start = core.get('/api/account/login?return=/dashboard', follow_redirects=False)
    authorization = fleet.get(start.headers['location'], follow_redirects=False)
    assert core.get(authorization.headers['location'], follow_redirects=False).status_code == 303
    return pipeline


def test_logout_outage_returns_pending_and_clears_cookie(authenticated_pipeline):
    core, fleet, sessions, _, receiver, _ = authenticated_pipeline
    from fleet.server.password_session import COOKIE
    central_cookie = fleet.cookies[COOKIE]
    original = receiver.post

    def unavailable(endpoint, fields):
        raise AccountUnavailable()

    receiver.post = unavailable
    response = core.post('/api/account/logout', headers={'Origin': str(core.base_url).rstrip('/')})
    assert response.status_code == 503
    assert response.json() == {'authenticated': False, 'revocation_pending': True}
    assert 'Max-Age=0' in response.headers['set-cookie']
    assert 'rosy_app_account' not in core.cookies
    assert not core.get('/api/account/session').json()['authenticated']
    assert core.get('/api/v1/auth/whoami').status_code == 401
    assert sessions.account_context(central_cookie)
    receiver.post = original
    receiver.retry_revocations()
    assert sessions.account_context(central_cookie) is None


def test_core_lifespan_retries_pending_revocation(authenticated_pipeline, monkeypatch):
    import threading
    core, fleet, sessions, _, receiver, _ = authenticated_pipeline
    from fleet.server.password_session import COOKIE
    central_cookie = fleet.cookies[COOKIE]
    original = receiver.post

    def unavailable(endpoint, fields):
        raise AccountUnavailable()

    receiver.post = unavailable
    assert core.post('/api/account/logout', headers={'Origin': str(core.base_url).rstrip('/')}).status_code == 503
    receiver.post = original
    completed = threading.Event()
    retry = receiver.retry_revocations

    def tracked_retry():
        retry()
        completed.set()

    monkeypatch.setattr(receiver, 'retry_revocations', tracked_retry)
    with TestClient(core.app, base_url=str(core.base_url)):
        assert completed.wait(5), 'CORE startup must retry the durable revocation queue'
        assert sessions.account_context(central_cookie) is None
    with receiver.transaction() as db:
        assert db.execute('SELECT count(*) FROM app_account_revocations').fetchone()[0] == 0


def test_pending_logout_does_not_revoke_new_login_family(authenticated_pipeline):
    core, fleet, sessions, login, receiver, _ = authenticated_pipeline
    from fleet.server.password_session import COOKIE
    old_cookie = fleet.cookies[COOKIE]
    original = receiver.post

    def unavailable_revoke(endpoint, fields):
        if endpoint == 'revoke':
            raise AccountUnavailable()
        return original(endpoint, fields)

    receiver.post = unavailable_revoke
    assert core.post('/api/account/logout', headers={'Origin': str(core.base_url).rstrip('/')}).status_code == 503
    fleet.cookies.set(COOKIE, login())
    new_cookie = fleet.cookies[COOKIE]
    assert sessions.account_context(old_cookie)['session_family'] != sessions.account_context(new_cookie)['session_family']
    start = core.get('/api/account/login?return=/dashboard', follow_redirects=False)
    authorization = fleet.get(start.headers['location'], follow_redirects=False)
    assert core.get(authorization.headers['location'], follow_redirects=False).status_code == 303
    receiver.post = original
    receiver.retry_revocations()
    assert sessions.account_context(old_cookie) is None
    assert sessions.account_context(new_cookie)
    assert core.get('/api/account/session').json()['authenticated']


@pytest.mark.parametrize('authority_state', ['offline', 'revoked'])
def test_account_media_revalidation_denies_authority_outage_and_revocation(
        authenticated_pipeline, tmp_path, authority_state):
    from core_api_web.api.media_binding import install_media
    from test_media_grant_api import configured_media
    core, fleet, sessions, _, receiver, _ = authenticated_pipeline
    from fleet.server.password_session import COOKIE
    install_media(core.app, {'vision': {'media': configured_media(tmp_path)}}, core.app.state.core)
    origin = {'Origin': str(core.base_url).rstrip('/')}
    path = '/api/v1/vision/media/grants'
    grant = core.post(path, json={'robot_id': core.app.state.core.identity.robot_id}, headers=origin)
    assert grant.status_code == 201
    credential = grant.json()
    if authority_state == 'revoked':
        sessions.revoke(fleet.cookies[COOKIE])
    else:
        def unavailable(endpoint, fields):
            raise AccountUnavailable()
        receiver.post = unavailable
    # Ordinary authentication still has a fresh cache; media must check the authority now.
    assert core.get('/api/v1/auth/whoami').status_code == 200
    checked = core.post('/api/v1/vision/media/validate',
                       headers={'Authorization': 'Bearer ' + credential['token']})
    assert checked.status_code == 200 and checked.json() == {'active': False}
    assert core.post(path + '/' + credential['grant_id'] + '/renew', headers=origin).status_code == 403


@pytest.mark.parametrize('revocation_outage', [False, True], ids=['normal', 'pending-revocation'])
def test_browser_sso_return_uses_real_cookies_and_authority_ui(pipeline, tmp_path, revocation_outage):
    from browser_harness import browser_tests_enabled, launch_options
    if not browser_tests_enabled(): pytest.skip('opt-in Chromium scenario')
    from playwright.sync_api import sync_playwright, expect
    import threading
    import uvicorn
    from datetime import datetime, timedelta, timezone
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
    from cryptography.hazmat.primitives import hashes
    core, fleet, _, _, receiver, _ = pipeline
    tls_key = generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(tls_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
        .not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),False)
        .sign(tls_key,hashes.SHA256()))
    cert_file, key_file = tmp_path/'tls.crt', tmp_path/'tls.key'
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(tls_key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    servers, threads = [], []
    for client, listener in zip((fleet,core),core.test_sockets):
        server = uvicorn.Server(uvicorn.Config(client.app,log_level='error',ssl_keyfile=str(key_file),ssl_certfile=str(cert_file),timeout_graceful_shutdown=2))
        worker = threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True)
        servers.append(server); threads.append(worker); worker.start()
    deadline=time.monotonic()+20
    while not all(server.started for server in servers) and time.monotonic()<deadline: time.sleep(.02)
    assert all(server.started for server in servers)
    robot = str(core.base_url).rstrip('/')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            failures = []
            page.on('pageerror', lambda error: failures.append(str(error)))
            page.goto(robot+'/api/account/login?return=/dashboard')
            assert '/console/login?' in page.url, (page.url, page.locator('body').inner_text())
            assert not failures, failures
            page.locator('[data-login=login]').fill('alice')
            page.locator('[data-login=password]').fill('test-password')
            page.locator('[data-login=submit]').click()
            page.wait_for_url(robot+'/dashboard')
            assert page.evaluate("fetch('/api/account/session').then(r=>r.json())")['authenticated']
            profile = page.locator('[data-account-profile]:visible')
            expect(profile).to_contain_text('alice')
            expect(profile).to_have_attribute('href', receiver.profile_url)
            expect(profile).to_have_attribute('target', '_blank')
            # A second app entry reuses the authority cookie: no password/code prompt.
            page.goto(robot+'/api/account/login?return=/pilot')
            page.wait_for_url(robot+'/pilot')
            assert page.evaluate("fetch('/api/account/session').then(r=>r.json())")['authenticated']
            expect(page.locator('[data-account-profile]')).to_contain_text('alice')
            changed = context.request.patch(str(fleet.base_url).rstrip('/') + '/api/fleet/auth/profile',
                data={'display_name':'Browser Alice'}, headers={'Origin':str(fleet.base_url).rstrip('/')})
            assert changed.status == 200
            page.evaluate("import('/pilot/assets/client.js').then(module => module.restoreAccount())")
            expect(page.locator('[data-account-profile]')).to_contain_text('Browser Alice')
            with page.expect_popup() as opened:
                page.locator('[data-account-profile]').click()
            account_page = opened.value
            account_page.wait_for_url(receiver.profile_url)
            account_page.close()
            assert page.url == robot + '/pilot'
            from core_common.protocol.account_client import AccountUnavailable
            original_post = receiver.post
            def unavailable_profile(endpoint, fields):
                if endpoint == 'userinfo':
                    raise AccountUnavailable()
                return original_post(endpoint, fields)
            receiver.post = unavailable_profile
            page.evaluate("import('/pilot/assets/client.js').then(module => module.restoreAccount())")
            expect(page.locator('[data-account-profile]')).to_contain_text('\uc774\ub984 \ud655\uc778 \ubd88\uac00')
            assert page.evaluate("fetch('/api/account/session').then(r=>r.json())")['authenticated']
            receiver.post = original_post
            cookies = context.cookies()
            app = next(c for c in cookies if c['name'] == 'rosy_app_account')
            assert app['httpOnly'] and app['secure'] and app['sameSite'] == 'Lax'
            assert all('refresh' not in c['name'] for c in cookies)
            if revocation_outage:
                def unavailable_revoke(endpoint, fields):
                    if endpoint == 'revoke':
                        raise AccountUnavailable()
                    return original_post(endpoint, fields)
                receiver.post = unavailable_revoke
                page.get_by_text('로그아웃', exact=True).click()
                expect(page.get_by_text('이 앱에서 로그아웃했습니다. 전체 세션 회수는 연결 복구 후 완료됩니다.', exact=True)).to_be_visible()
            else:
                page.get_by_text('로그아웃', exact=True).click()
            expect(page.locator('[data-account-profile]')).to_be_hidden()
            assert not page.evaluate("fetch('/api/account/session').then(r=>r.json())")['authenticated']
            assert not failures, failures
        finally:
            browser.close()
            for server in servers: server.should_exit=True
            for thread in threads: thread.join(timeout=10)
            assert not any(thread.is_alive() for thread in threads)
