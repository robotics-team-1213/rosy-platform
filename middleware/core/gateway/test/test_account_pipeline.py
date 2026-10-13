"""Real authority ledger -> PKCE receiver -> CORE, with no robot movement."""
import json
import time
from urllib.parse import urlsplit

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from core_common.protocol.account_client import AccountClient, AccountDenied


@pytest.fixture
def pipeline(tmp_path, core_client):
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.site_users import hash_password
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    issuer, robot = 'https://account.test', 'https://robot.test'
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
        account_config=config, start_task_dispatcher=False)
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
    yield core, TestClient(fleet, base_url=issuer), sessions, login, receiver, clock
    core.close(); backchannel.close()


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
    assert core.get('/api/v1/auth/whoami').status_code == 200
    assert core.post('/api/v1/teleop', json={'linear':0,'angular':0}, headers={'Origin':'https://robot.test'}).status_code == 403
    clock[0] += 270
    assert core.get('/api/account/session').json()['session_family'] == identity['session_family']
    sessions.revoke(fleet.cookies[COOKIE])
    clock[0] += 10
    assert core.get('/api/v1/auth/whoami').status_code == 401
    assert not core.get('/api/account/session').json()['authenticated']


def test_browser_sso_return_uses_real_cookies_and_authority_ui(pipeline):
    from browser_harness import browser_tests_enabled, launch_options
    if not browser_tests_enabled(): pytest.skip('opt-in Chromium scenario')
    from playwright.sync_api import sync_playwright
    core, fleet, _, _, _, _ = pipeline
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            context = browser.new_context()
            def forward(route):
                request = route.request
                client = fleet if urlsplit(request.url).hostname == 'account.test' else core
                client.cookies.clear()
                response = client.request(request.method, request.url, headers=request.all_headers(),
                    content=request.post_data_buffer, follow_redirects=False)
                route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
            context.route('https://**.test/**', forward)
            page = context.new_page()
            page.goto('https://robot.test/api/account/login?return=/dashboard')
            page.locator('[data-login=login]').fill('alice')
            page.locator('[data-login=password]').fill('test-password')
            page.locator('[data-login=submit]').click()
            page.wait_for_url('https://robot.test/dashboard')
            assert page.evaluate("fetch('/api/account/session').then(r=>r.json())")['authenticated']
            # A second app entry reuses the authority cookie: no password/code prompt.
            page.goto('https://robot.test/api/account/login?return=/pilot')
            page.wait_for_url('https://robot.test/pilot')
            assert page.evaluate("fetch('/api/account/session').then(r=>r.json())")['authenticated']
            cookies = context.cookies()
            app = next(c for c in cookies if c['name'] == 'rosy_app_account')
            assert app['httpOnly'] and app['secure'] and app['sameSite'] == 'Lax'
            assert all('refresh' not in c['name'] for c in cookies)
        finally:
            browser.close()
