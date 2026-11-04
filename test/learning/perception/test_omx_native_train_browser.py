"""Chromium exercises explicit saved-review submission and acknowledgement-loss retry."""
import threading
import os
from types import SimpleNamespace
import uuid
from urllib.parse import urlsplit, parse_qs

import pytest
from browser_harness import browser_tests_enabled, free_port, save_temp_screenshot
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


@pytest.mark.parametrize('context', ['', '&task=task-one', '&task=missing', '&task=task-one&task=other'])
def test_native_act_requires_saved_selection_and_retries_the_same_request(tmp_path, context):
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
                page.route('**/api/learning/tasks',lambda route:route.fulfill(json={
                    'project_id':'fixture','tasks':[{'id':'task-one','name':'Bound task'}],
                    'profiles':[],'robots':[],'datasets':[],'runs':[]}))
                base = f'http://127.0.0.1:{server.server_port}/learning/omx?view=all'+context+'#dataset-section'
                page.goto(base, wait_until='domcontentloaded')
                expect = playwright.expect
                expect(page.locator('#native-train-start')).to_be_disabled()
                page.locator('#native-train-review').select_option('episodes')
                if context:
                    expect(page.locator('#native-train-selection')).to_contain_text('학습 과제 화면')
                    expect(page.locator('#native-train-start')).to_be_disabled()
                    expect(page.locator('#native-train-workflow')).to_be_visible()
                    next_url=urlsplit(page.locator('#native-train-workflow').get_attribute('href'))
                    assert next_url.path == ('/learning/tasks' if context == '&task=task-one' else '/learning/tasks/manage')
                    assert parse_qs(next_url.query)['task'][0] in ('task-one','missing')
                    if os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
                        kind = 'duplicate' if context.count('task=') > 1 else 'missing' if 'missing' in context else 'selected'
                        for width in (1440, 390):
                            page.set_viewport_size({'width': width, 'height': 900})
                            page.locator('#native-train-form').scroll_into_view_if_needed()
                            save_temp_screenshot(page, f'native-{kind}-{width}.png')
                    page.locator('#native-train-form').evaluate("form => form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
                    page.wait_for_timeout(100)
                    assert posts == [] and not errors
                    return
                expect(page.locator('#native-train-selection')).to_contain_text(review_id)
                expect(page.locator('#native-train-start')).to_be_enabled()
                if os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
                    for width in (1440, 390):
                        page.set_viewport_size({'width': width, 'height': 900})
                        page.locator('#native-train-form').scroll_into_view_if_needed()
                        save_temp_screenshot(page, f'native-standalone-{width}.png')
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
