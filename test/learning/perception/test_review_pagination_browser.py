"""Both editors bound thumbnails and navigate across SQL page boundaries."""
import threading
import json
from urllib.parse import parse_qs, urlparse

import pytest

from browser_harness import browser_tests_enabled
from review_app import make_server
from test_review_app import open_store
from test_review_cycle import CLASSES
import review_masks
from test_review_flow_browser import browser_workspace

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('pixel', [False, True])
@pytest.mark.parametrize('lookup', ['after', 'around'])
@pytest.mark.parametrize('failed', [False, True])
def test_next_pending_locks_editing_until_both_lookups_finish(browser_workspace, pixel, lookup, failed):
    page, store, expect = browser_workspace
    base = page.url.split('?')[0].rstrip('/')
    store.update(1, {'version': store.get(1)['version'], 'action': 'reopen'})
    if pixel:
        review_masks.bind_classes(store, CLASSES)
        page.goto(base + '/pixels?frame=0', wait_until='networkidle')
        page.locator('#pixel-class').select_option('4')
        page.locator('#pixel-brush-tool').click()
    else:
        page.goto(base + '/?frame=0', wait_until='networkidle')
        page.locator('#reopen').click()
    prefix = 'pixel-' if pixel else ''
    canvas = page.locator('#pixel-canvas' if pixel else '#canvas')
    edit = page.locator('#pixel-brush-tool' if pixel else '#add')
    expect(edit).to_be_enabled()
    delayed = []
    def hold(route):
        query = parse_qs(urlparse(route.request.url).query)
        if lookup in query:
            delayed.append(route)
        else:
            route.continue_()
    page.route('**/api/workspace?*', hold)
    try:
        with page.expect_request(lambda request: lookup in parse_qs(urlparse(request.url).query)):
            page.locator('#' + prefix + 'next-pending').click()
        expect(edit).to_be_disabled()
        expect(page.locator('#pixel-next' if pixel else '#next-frame')).to_be_disabled()
        canvas.click(position={'x': 15, 'y': 15})
        if pixel:
            expect(page.locator('#pixel-save')).to_be_disabled()
            assert review_masks.get(store, 0)['version'] == 0
        else:
            assert len(store.get(0)['review']['boxes']) == 1
        assert len(delayed) == 1
        if failed:
            delayed.pop().fulfill(status=503, json={'error': 'held lookup failed'})
            expect(page.locator('#pixel-error' if pixel else '#error')).to_contain_text('검수 서비스를 사용할 수 없습니다')
        else:
            route = delayed.pop()
            route.fulfill(response=route.fetch())
        expect(edit).to_be_enabled()
        expect(canvas).to_be_focused()
        expected_frame = '0' if failed else '1'
        assert parse_qs(urlparse(page.url).query)['frame'] == [expected_frame]
        if pixel:
            canvas.click(position={'x': 20, 'y': 20})
            expect(page.locator('#pixel-save')).to_be_enabled()
            expect(page.locator('#pixel-next-pending')).to_be_disabled()
            page.locator('#pixel-save').click()
            expect(page.locator('#pixel-status')).to_contain_text('v1')
            assert review_masks.get(store, int(expected_frame))['version'] == 1
            if not failed:
                assert review_masks.get(store, 0)['version'] == 0
        else:
            page.locator('#add').click()
            expect(page.locator('#boxes .box-row')).to_have_count(2)
            assert len(store.get(int(expected_frame))['review']['boxes']) == 2
    finally:
        while delayed:
            delayed.pop().fulfill(status=503, json={'error': 'test cleanup'})
        page.unroute('**/api/workspace?*', hold)


@pytest.mark.parametrize('path,strip,next_button,title', [
    ('/', '#frames', '#next-frame', '#frame-title'),
    ('/pixels', '#pixel-frames', '#pixel-next', '#pixel-title')])
@pytest.mark.parametrize('first_id,stride', [(0, 1), (63, 3)])
def test_review_page_bounds_and_deep_link(tmp_path, path, strip, next_button, title, first_id, stride):
    playwright = pytest.importorskip('playwright.sync_api')
    store = open_store(tmp_path)
    with store.connect() as db:
        source, review = db.execute('SELECT source,review FROM frames WHERE id=0').fetchone()
        source = json.dumps(dict(json.loads(source), source_session='folder:scope:run'))
        db.execute('DELETE FROM frames')
        db.executemany('INSERT INTO frames VALUES (?,?,?,?,1)',
                       [(first_id + index * stride, source, review, 'pending') for index in range(125)])
        db.execute('INSERT INTO metadata VALUES (?,?)', ('review_source_prefix', json.dumps('folder:scope:')))
        if first_id:
            db.execute('INSERT INTO frames VALUES (0,?,?,?,1)',
                       (json.dumps(dict(json.loads(source), source_session='old')), review, 'pending'))
    if path == '/pixels':
        review_masks.bind_classes(store, CLASSES)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}{path}?frame={first_id + 59 * stride}', wait_until='domcontentloaded')
            if path == '/pixels':
                page.locator('.review-tool-nav a[href="#pixel-display-options"]').click()
            playwright.expect(page.locator(title)).to_have_text('사진 60' + (' 픽셀 검수' if path == '/pixels' else ''))
            playwright.expect(page.locator(f'{strip} [data-index="{first_id + 59 * stride}"]')).to_contain_text('사진 60')
            playwright.expect(page.locator(next_button)).to_be_enabled()
            assert page.locator(strip + ' .frame-thumb').count() == 60
            page.locator(next_button).click()
            playwright.expect(page.locator(title)).to_have_text('사진 61' + (' 픽셀 검수' if path == '/pixels' else ''))
            assert parse_qs(urlparse(page.url).query)['frame'] == [str(first_id + 60 * stride)]
            playwright.expect(page.locator(f'{strip} [data-index="{first_id + 60 * stride}"]')).to_contain_text('사진 61')
            if path == '/pixels':
                playwright.expect(page.locator('#pixel-frame option:checked')).to_contain_text('사진 61')
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
            with store.connect() as db:
                if path == '/pixels':
                    db.executemany('INSERT INTO masks(frame,version,status) VALUES (?,1,?)',
                                   [(first_id + index * stride, 'approved') for index in range(10)])
                else:
                    db.executemany('UPDATE frames SET status=? WHERE id=?',
                                   [('approved', first_id + index * stride) for index in range(10)])
            page.locator('#pixel-filter' if path == '/pixels' else '#filter').select_option('pending')
            playwright.expect(page.locator(title)).to_have_text('사진 51' + (' 픽셀 검수' if path == '/pixels' else ''))
            playwright.expect(page.locator(f'{strip} [data-index="{first_id + 10 * stride}"]')).to_contain_text('사진 1')
            playwright.expect(page.locator(f'{strip} [data-index="{first_id + 60 * stride}"]')).to_contain_text('사진 51')
            assert parse_qs(urlparse(page.url).query)['frame'] == [str(first_id + 60 * stride)]
            if path == '/pixels':
                playwright.expect(page.locator('#pixel-frame option:checked')).to_contain_text('사진 51')
                page.locator('.review-tool-nav a[href="#pixel-review"]').click()
                page.locator('#pixel-exclude').click()
                playwright.expect(page.locator('#pixel-decision')).to_contain_text('사진 51 픽셀 제외')
                playwright.expect(page.locator('#pixel-decision')).to_contain_text('다음 검수 대기 사진 51')
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
