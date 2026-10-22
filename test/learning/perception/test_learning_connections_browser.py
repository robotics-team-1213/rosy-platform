"""Connection recovery through Chromium, real HTTP sessions and encrypted SQLite."""
import threading

import pytest

from browser_harness import browser_tests_enabled, free_port, open_page
from review_app import make_server
from test_learning_accounts import accounts  # noqa: F401 — real isolated account fixture
from test_learning_accounts_browser import sign_in
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
                page.goto(origin + '/pixels?frame=0', wait_until='networkidle')
                expect = playwright.expect
                trigger = page.get_by_role('button', name='계정과 Hugging Face 연결')
                expect(trigger).to_be_visible()
                assert page.url == origin + '/pixels?frame=0'
                trigger.click()
                dialog = page.get_by_role('dialog', name='계정과 연결')
                expect(dialog).to_be_visible()
                expect(dialog.get_by_role('link', name='Rosy Account로 로그인')).to_have_attribute(
                    'href', '/api/account/login?return=%2Fpixels%3Fframe%3D0')
                page.keyboard.press('Escape')
                expect(dialog).not_to_be_visible()
                expect(trigger).to_be_focused()
                sign_in(page, origin, accounts, 'alice')
                trigger.click()
                expect(dialog).to_contain_text('Hugging Face 연결 필요')
                _, actor = accounts._session(accounts._user('alice'))
                accounts.connect_oauth(actor, 'hf-alice', 'alice-hf', 'fixture-only-credential',
                    accounts.clock() + 300, scopes=['read-repos', 'write-repos', 'manage-repos'])
                page.reload(wait_until='networkidle')
                trigger.click()
                expect(dialog).to_contain_text('읽기 · 쓰기 · 저장소 관리 가능')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                stored = page.evaluate('JSON.stringify({...localStorage}) + JSON.stringify({...sessionStorage})')
                assert 'fixture-only-credential' not in stored
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
