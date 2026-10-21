import json
import threading

import pytest

from review_app import make_server
from storage_inventory import StorageInventory
from test_learning_accounts import accounts  # noqa: F401
from test_learning_collaboration import request
from test_review_app import open_store


def test_storage_http_read_permissions_paths_and_revocation(tmp_path, accounts):
    folder = tmp_path / 'review'; folder.mkdir(); store = open_store(folder)
    root = tmp_path / 'media'; root.mkdir(); (root / 'private-filename.mp4').write_bytes(b'abc')
    cfg = dict(project_id='one', roots=[dict(id='media', label='Media', role='raw', path=str(root))])
    storage = StorageInventory(store.db, cfg, 'one')
    server = make_server(store, 0, accounts=accounts, storage=storage)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        assert request(url, '/api/learning/storage')[0] == 401
        session, _ = accounts.login('bob', 'bob-password')
        token = request(url, '/api/accounts/session', session)[1]['token']
        status, data = request(url, '/api/learning/storage', session)
        assert status == 200 and data['roots'][0]['logical_bytes'] == 3
        assert str(root) not in json.dumps(data) and 'private-filename' not in json.dumps(data)
        body = dict(destination_id='media', download_bytes=1, staging_bytes=2, transform_bytes=3, upload_bytes=0)
        assert request(url, '/api/learning/storage/preflight', session, body, token)[0] == 200
        assert request(url, '/api/learning/storage/preflight', session, dict(body, path='/private'), token)[0] == 400
        accounts.logout(session)
        assert request(url, '/api/learning/storage', session)[0] == 401
        assert request(url, '/api/learning/storage/preflight', session, body, token)[0] == 403
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
    storage.project_id = 'two'
    with pytest.raises(ValueError, match='storage project'):
        make_server(store, 0, accounts=accounts, storage=storage)


@pytest.mark.parametrize('width', [1440, 320])
def test_storage_browser_inventory_preflight_and_failure(tmp_path, accounts, width):
    from browser_harness import browser_tests_enabled, free_port, open_page
    if not browser_tests_enabled(): pytest.skip('requires explicit Chromium browser run')
    playwright = pytest.importorskip('playwright.sync_api')
    folder = tmp_path / 'review'; folder.mkdir(); store = open_store(folder)
    root = tmp_path / 'pending'; root.mkdir(); (root / 'clip.mp4').write_bytes(b'x' * 2048)
    cfg = dict(project_id='one', roots=[dict(id='pending', label='Incoming media', role='pending', path=str(root))])
    storage = StorageInventory(store.db, cfg, 'one')
    server = make_server(store, free_port(), accounts=accounts, storage=storage)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        with playwright.sync_playwright() as runtime:
            browser, page, errors = open_page(runtime, width, 900, url=url)
            try:
                session, _ = accounts.login('bob', 'bob-password')
                page.context.add_cookies([dict(name='rosy_learning_session', value=session, url=url)])
                page.goto(url + '/learning', wait_until='networkidle')
                expect = playwright.expect
                expect(page.locator('#storage-roots')).to_contain_text('Incoming media')
                expect(page.locator('#storage-roots')).to_contain_text('파일 1개')
                expect(page.locator('#storage-roots')).to_contain_text('예상 잔여 미확인')
                page.keyboard.press('Control+k')
                page.get_by_role('textbox', name='기능 검색어').fill('공간 사전 점검')
                page.keyboard.press('Escape')
                page.locator('#storage-preflight ui-button').click()
                expect(page.locator('#storage-result')).to_contain_text('공간 추정 충족')
                page.locator('#storage-upload').fill('1')
                page.locator('#storage-preflight ui-button').click()
                expect(page.locator('#storage-result')).to_contain_text('공간 확인 보류')
                page.locator('#storage-download').fill('8000000')
                page.locator('#storage-preflight ui-button').click()
                expect(page.locator('#storage-result')).to_contain_text('공간 부족')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.route('**/api/learning/storage', lambda route: route.fulfill(status=503,
                    content_type='application/json', body='{"error":"storage unavailable"}'))
                page.locator('#storage-refresh').click()
                expect(page.locator('#storage-error')).to_contain_text('잠시 후 다시 시도하세요')
                expect(page.locator('#storage-roots')).to_have_text('')
                page.unroute('**/api/learning/storage')
                page.locator('#storage-refresh').click()
                expect(page.locator('#storage-roots')).to_contain_text('Incoming media')
                delayed = []
                snapshot = storage.snapshot()
                page.route('**/api/learning/storage', lambda route: delayed.append(route))
                with page.expect_request('**/api/learning/storage'):
                    page.locator('#storage-refresh').click()
                expect(page.locator('#storage-refresh')).to_be_disabled()
                assert delayed
                accounts.logout(session)
                page.locator('#refresh').click()
                expect(page.locator('#learning-status')).to_contain_text('확인할 수 없습니다')
                delayed[0].fulfill(status=200, content_type='application/json', body=json.dumps(snapshot))
                expect(page.locator('#storage-refresh')).to_be_enabled()
                expect(page.locator('#storage-roots')).to_have_text('')
                expect(page.locator('#storage-preflight')).to_be_hidden()
                assert not errors
            finally: browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
