"""Chromium exercises explicit saved-review submission and acknowledgement-loss retry."""
import threading
from types import SimpleNamespace
import uuid

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_native_act_requires_saved_selection_and_retries_the_same_request(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    prepared_id, review_id = 'a'*32, str(uuid.uuid4())
    saved = dict(id=prepared_id, name='Native workflow browser fixture', episodes=[],
                 trainable={'ok': True}, latest_review_id=review_id, fixture_only=False,
                 segment_review={'version': 3, 'document': {'segments': []}})
    center = SimpleNamespace(bind_workspace=lambda project: None, profiles=SimpleNamespace(list=lambda: []),
        snapshot=lambda: {'datasets': [], 'runs': [], 'methods': {'act': {'available': True}}})
    store = ReviewStore(tmp_path/'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.add_init_script("Object.defineProperty(crypto,'randomUUID',{value:undefined})")
                errors, posts = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/api/learning/omx', lambda route: route.fulfill(json={'sets': [saved]}))
                def submit(route):
                    posts.append(route.request.post_data_json)
                    if len(posts) == 1:
                        route.fulfill(status=503, json={'error': 'reply lost'})
                    else:
                        route.fulfill(json={'id': 'native-job', 'status': 'running'})
                page.route('**/center/native-run', submit)
                base = f'http://127.0.0.1:{server.server_port}/learning/omx?view=all#dataset-section'
                page.goto(base, wait_until='domcontentloaded')
                expect = playwright.expect
                expect(page.locator('#native-train-start')).to_be_disabled()
                page.locator('#native-train-review').select_option('episodes')
                expect(page.locator('#native-train-selection')).to_contain_text(review_id)
                expect(page.locator('#native-train-start')).to_be_enabled()
                page.locator('#native-train-steps').fill('2')
                page.locator('#native-train-start').click()
                expect(page.locator('#native-train-status')).to_contain_text('reply lost')
                page.locator('#native-train-start').click()
                expect(page.locator('#native-train-status')).to_contain_text('native-job')
                assert posts[0] == posts[1]
                assert posts[0]['prepared_id'] == prepared_id and posts[0]['review_id'] == review_id
                assert posts[0]['steps'] == 2
                uuid.UUID(posts[0]['request_id'])
                page.locator('#native-train-review').select_option('segments')
                expect(page.locator('#native-train-selection')).to_contain_text('v3')
                page.locator('#native-train-start').click()
                expect(page.locator('#native-train-status')).to_contain_text('native-job')
                assert posts[-1]['segment_version'] == 3 and 'review_id' not in posts[-1]
                saved['fixture_only'] = True
                page.reload(wait_until='domcontentloaded')
                page.locator('#native-train-review').select_option('episodes')
                expect(page.locator('#native-train-start')).to_be_disabled()
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
