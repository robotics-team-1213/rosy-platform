"""Connection recovery through Chromium, real HTTP sessions and encrypted SQLite."""
import threading
import json
import ssl
import subprocess
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from browser_harness import browser_tests_enabled, free_port, open_page
from review_app import make_server
from learning_oauth import OAuth
from test_learning_accounts import accounts  # noqa: F401 — real isolated account fixture
from test_learning_accounts_browser import sign_in
from test_learning_oauth import Provider
from test_review_app import open_store


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 320])
def test_connection_dialog_recovers_in_context(tmp_path, accounts, width):
    """Anonymous preview stays put; connection status reflects verified scopes."""
    playwright = pytest.importorskip('playwright.sync_api')
    review = tmp_path / 'review'; review.mkdir()
    server = make_server(open_store(review), free_port(), accounts=accounts)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, width, 900, url=origin)
            try:
                destination = '/accounts?return=%2Fpixels%3Fframe%3D0'
                page.goto(origin + destination, wait_until='networkidle')
                expect = playwright.expect
                trigger = page.get_by_role('button', name='계정과 Hugging Face 연결')
                expect(trigger).to_be_visible()
                assert page.url == origin + destination
                page.evaluate("""() => document.addEventListener('click', event => {
                    if (event.target.closest('a[href="/api/account/login?return=/accounts"]')) event.preventDefault();
                })""")

                def focus_before_refresh_completes(route):
                    response = route.fetch()
                    page.get_by_role('dialog', name='계정과 연결').get_by_role(
                        'link', name='Rosy Account로 로그인').evaluate(
                            "node => { node.dataset.refreshFocus = 'preserved'; node.focus(); }")
                    route.fulfill(response=response)

                page.route('**/api/accounts/session', focus_before_refresh_completes, times=1)
                trigger.click()
                dialog = page.get_by_role('dialog', name='계정과 연결')
                expect(dialog).to_be_visible()
                expect(dialog.get_by_role('link', name='Rosy Account로 로그인')).to_have_attribute(
                    'href', '/api/account/login?return=/accounts')
                login = dialog.get_by_role('link', name='Rosy Account로 로그인')
                page.wait_for_load_state('networkidle')
                expect(login).to_have_attribute('data-refresh-focus', 'preserved')
                expect(login).to_be_focused()
                login.click()
                assert page.evaluate("sessionStorage.getItem('rosy.learning.login-return')") == '/pixels?frame=0'
                page.keyboard.press('Escape')
                expect(dialog).not_to_be_visible()
                expect(trigger).to_be_focused()
                sign_in(page, origin, accounts, 'alice')
                page.wait_for_url(origin + '/pixels?frame=0')
                assert page.evaluate("sessionStorage.getItem('rosy.learning.login-return')") is None
                trigger.click()
                expect(dialog).to_contain_text('Hugging Face 연결 필요')
                _, actor = accounts._session(accounts._user('alice'))
                accounts.connect_oauth(actor, 'hf-alice', 'alice-hf', 'fixture-read-only',
                    accounts.clock() + 300, scopes=['read-repos'])
                page.reload(wait_until='networkidle')
                trigger.click()
                expect(dialog).to_contain_text('Hugging Face 재연결 필요')
                accounts.connect_oauth(actor, 'hf-alice', 'alice-hf', 'fixture-only-credential',
                    accounts.clock() + 300, scopes=['read-repos', 'write-repos', 'manage-repos'])
                page.reload(wait_until='networkidle')
                trigger.click()
                expect(dialog).to_contain_text('읽기 · 쓰기 · 저장소 관리 가능')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                stored = page.evaluate('JSON.stringify({...localStorage}) + JSON.stringify({...sessionStorage})')
                assert 'fixture-only-credential' not in stored
                rejected = page.evaluate("""async () => {
                    const {learningReturn} = await import('/learning-connections.js');
                    return ['https://evil.example/', '//evil.example/', '/\\\\evil.example/',
                        '/api/accounts/logout', '/learning/%5Cevil', '/%2Fevil.example/'].map(learningReturn);
                }""")
                assert rejected == [None] * 6
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_hf_connection_returns_to_exact_review_task(tmp_path, accounts):
    """Real CSRF, PKCE, signed provider proof and callback; only HF is substituted."""
    playwright = pytest.importorskip('playwright.sync_api')
    origin = f'https://127.0.0.1:{free_port()}'
    callback = origin + '/oauth/huggingface/callback'
    config = accounts.config()
    config.update(public_origin=origin, oauth={'client_id':'client', 'redirect_uri':callback})
    accounts.config_path.write_text(json.dumps(config))
    provider = Provider()
    provider.scope = 'openid profile read-repos gated-repos write-repos manage-repos'
    review = tmp_path / 'review'; review.mkdir()
    server = make_server(open_store(review), urlsplit(origin).port,
                         accounts=accounts, oauth=OAuth(accounts, transport=provider))
    cert, key = tmp_path / 'cert.pem', tmp_path / 'tls-key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                    '-out', str(cert), '-days', '1', '-subj', '/CN=localhost'], check=True, capture_output=True)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            page = browser.new_page(ignore_https_errors=True, viewport={'width':320, 'height':900})
            try:
                page.goto(origin + '/accounts', wait_until='networkidle')
                sign_in(page, origin, accounts, 'alice')
                target = '/pixels?frame=0&status=pending#review'
                page.goto(origin + target, wait_until='networkidle')

                def authorize(route):
                    query = parse_qs(urlsplit(route.request.url).query)
                    assert {'read-repos', 'write-repos', 'manage-repos'} <= set(query['scope'][0].split())
                    assert query['code_challenge_method'] == ['S256']
                    provider.claims = {'iss':'https://huggingface.co', 'aud':'client', 'sub':'invited-alice',
                        'exp':int(time.time()) + 300, 'iat':int(time.time()), 'nonce':query['nonce'][0]}
                    route.fulfill(status=302, headers={'Location':callback + '?' + urlencode(
                        {'state':query['state'][0], 'code':'fixture-code'})})

                page.route('https://huggingface.co/oauth/authorize**', authorize)
                page.get_by_role('button', name='계정과 Hugging Face 연결').click()
                dialog = page.get_by_role('dialog', name='계정과 연결')
                with page.expect_request('**/api/accounts/oauth') as started:
                    dialog.get_by_role('button', name='Hugging Face 연결', exact=True).click()
                assert started.value.post_data_json == {'purpose':'link'}
                assert started.value.headers.get('x-pinky-token')
                page.wait_for_url(origin + target)
                playwright.expect(page.get_by_role('button', name='계정과 Hugging Face 연결')).to_contain_text('연결됨')
                session = page.request.get(origin + '/api/accounts/session').json()
                assert session['user_id'] == 'alice'
                assert {'read-repos', 'write-repos', 'manage-repos'} <= set(session['connections'][0]['scopes'])
                assert page.evaluate("sessionStorage.getItem('rosy.learning.connection-return')") is None
                assert 'oauth-private' not in page.evaluate('JSON.stringify({...localStorage, ...sessionStorage})')
                page.goto(origin + '/accounts', wait_until='networkidle')
                assert page.url == origin + '/accounts'
                config['users'].append({'user_id':'viewer', 'username':'viewer', 'memberships':{'one':['view']}})
                accounts.config_path.write_text(json.dumps(config))
                sign_in(page, origin, accounts, 'viewer')
                page.get_by_role('button', name='계정과 Hugging Face 연결').click()
                expect = playwright.expect
                dialog = page.get_by_role('dialog', name='계정과 연결')
                expect(dialog).to_contain_text('자료 가져오기 권한이 필요합니다')
                expect(dialog.get_by_role('button', name='Hugging Face 연결', exact=True)).to_have_count(0)
                expect(dialog.get_by_role('button', name='Hugging Face 다시 연결', exact=True)).to_have_count(0)
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
