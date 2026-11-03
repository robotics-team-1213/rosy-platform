"""Both editors bound thumbnails and navigate across SQL page boundaries."""
import threading

import pytest

from browser_harness import browser_tests_enabled
from review_app import make_server
from test_review_app import open_store

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('path,strip,next_button,title', [
    ('/', '#frames', '#next-frame', '#frame-title'),
    ('/pixels', '#pixel-frames', '#pixel-next', '#pixel-title')])
def test_review_page_bounds_and_deep_link(tmp_path, path, strip, next_button, title):
    playwright = pytest.importorskip('playwright.sync_api')
    store = open_store(tmp_path)
    with store.connect() as db:
        source, review = db.execute('SELECT source,review FROM frames WHERE id=0').fetchone()
        db.executemany('INSERT INTO frames VALUES (?,?,?,?,1)',
                       [(index, source, review, 'pending') for index in range(2, 125)])
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}{path}?frame=59', wait_until='domcontentloaded')
            playwright.expect(page.locator(title)).to_have_text('사진 60' + (' 픽셀 검수' if path == '/pixels' else ''))
            playwright.expect(page.locator(next_button)).to_be_enabled()
            assert page.locator(strip + ' .frame-thumb').count() == 60
            page.locator(next_button).click()
            playwright.expect(page.locator(title)).to_have_text('사진 61' + (' 픽셀 검수' if path == '/pixels' else ''))
            playwright.expect(page.locator(next_button)).to_be_enabled()
            assert page.locator(strip + ' .frame-thumb').count() == 60
            page.locator('#pixel-prev' if path == '/pixels' else '#prev-frame').click()
            playwright.expect(page.locator(title)).to_have_text('사진 60' + (' 픽셀 검수' if path == '/pixels' else ''))
            playwright.expect(page.locator(next_button)).to_be_enabled()
            page.locator(next_button).click()
            playwright.expect(page.locator(title)).to_have_text('사진 61' + (' 픽셀 검수' if path == '/pixels' else ''))
            page.get_by_text('다음 60장', exact=True).click()
            playwright.expect(page.locator(title)).to_have_text('사진 121' + (' 픽셀 검수' if path == '/pixels' else ''))
            assert page.locator(strip + ' .frame-thumb').count() == 5
            page.get_by_text('이전 60장', exact=True).click()
            playwright.expect(page.locator(title)).to_have_text('사진 61' + (' 픽셀 검수' if path == '/pixels' else ''))
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
