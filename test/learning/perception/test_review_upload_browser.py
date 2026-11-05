"""A user uploads image bytes from their own browser, without a server path."""
import base64
import threading

import pytest
from browser_harness import browser_tests_enabled
from review_app import make_server
import review_masks
from test_review_app import open_store
from test_review_cycle import CLASSES
from test_review_upload import payload

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


def test_catalog_uploads_selected_client_image(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    store = open_store(tmp_path)
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
            page.goto(f'http://127.0.0.1:{server.server_port}/catalog', wait_until='domcontentloaded')
            playwright.expect(page.locator('#image-files')).to_be_enabled()
            page.locator('#image-files').set_input_files({'name': 'client.png', 'mimeType': 'image/png',
                                                        'buffer': base64.b64decode(payload()['data'])})
            playwright.expect(page.locator('#upload-selection')).to_have_text('선택한 사진 1장')
            page.locator('#image-upload').click()
            playwright.expect(page.locator('#upload-status')).to_contain_text('업로드 완료 1장')
            assert len(store.list_frames()) == 3
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
