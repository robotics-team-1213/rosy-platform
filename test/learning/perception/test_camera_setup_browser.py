"""D-792 S2 browser proof: pick a reference, upload a photo, read the verdict and the dashed guide."""
import json
import threading

import cv2
import pytest
from browser_harness import browser_tests_enabled, free_port

from review_app import ReviewStore, make_server
from test_camera_setup import K, rotate, scene
from test_review_return import fixture_inputs

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


@pytest.mark.parametrize('width, height', [(1280, 900), (390, 800)])
def test_camera_page_checks_a_photo_against_the_reference(tmp_path, width, height):
    playwright = pytest.importorskip('playwright.sync_api')
    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path / 'state', source, human, images)
    home, moved = tmp_path / 'home.jpg', tmp_path / 'lower.jpg'
    cv2.imwrite(str(home), scene(), [cv2.IMWRITE_JPEG_QUALITY, 95])
    cv2.imwrite(str(moved), rotate(scene(), pan=1.5), [cv2.IMWRITE_JPEG_QUALITY, 95])
    server = make_server(store, free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': width, 'height': height})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            expect = playwright.expect
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/camera', wait_until='networkidle')
                expect(page.locator('#verdict')).to_contain_text('촬영 기준이 없습니다')
                page.locator('details summary').click()
                page.set_input_files('#reference-photo', str(home))
                page.fill('#camera-identity', 'omx-front-usb-1')
                page.fill('#intrinsics', json.dumps(K))
                page.locator('#reference-form ui-button[type=submit]').click()
                expect(page.locator('#reference-result')).to_contain_text('마커 없이', timeout=15000)
                expect(page.locator('#layout-field')).to_be_hidden()
                assert len(list((store.state / 'camera-setup').glob('*.json'))) == 1
                expect(page.locator('#fingerprint')).to_have_value(K['camera_info_sha256'])

                page.set_input_files('#check-photo', str(home))
                page.locator('#check-form ui-button[type=submit]').click()
                expect(page.locator('#verdict')).to_contain_text('맞음', timeout=15000)
                expect(page.locator('#verdict')).to_have_attribute('state', 'ready')
                expect(page.locator('#numbers dt')).to_have_count(10)

                page.set_input_files('#check-photo', str(moved))
                page.locator('#check-form ui-button[type=submit]').click()
                expect(page.locator('#verdict')).to_contain_text('조정 필요', timeout=15000)
                expect(page.locator('#numbers')).to_contain_text('pan 차이')
                assert page.evaluate("document.getElementById('view').width") == 640
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'no horizontal scroll'
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
