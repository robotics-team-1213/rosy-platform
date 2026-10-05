"""Real Chromium regression checks for filtered selection and safe label undo."""
import os
import threading

import pytest

from test_review_app import open_store
from review_app import make_server

pytestmark = pytest.mark.skipif(os.getenv('ROSY_RUN_BROWSER_TESTS') != '1',
                                reason='requires explicit local Chromium browser run')


@pytest.fixture
def browser_workspace(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    store = open_store(tmp_path)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width':1440, 'height':1000})
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(f'http://127.0.0.1:{server.server_port}', wait_until='networkidle')
        playwright.expect(page.locator('#image-message')).to_be_hidden()
        try:
            yield page, store, playwright.expect
            assert not errors
        finally:
            browser.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def test_arrow_keys_move_between_photos(browser_workspace):
    page, store, expect = browser_workspace

    def photo_loaded(title):
        expect(page.locator('#frame-title')).to_have_text(title)
        expect(page.locator('#image-message')).to_be_hidden()
        expect(page.locator('#save-status')).to_contain_text('서버 저장됨')

    photo_loaded('사진 1')
    # Number fields keep their native arrow behaviour and never move between photos.
    page.locator('input[aria-label="박스 1 x0"]').focus()
    page.keyboard.press('ArrowRight')
    photo_loaded('사진 1')
    page.locator('#canvas').focus()
    expect(page.locator('#next-frame')).not_to_have_attribute('disabled', '')
    page.keyboard.press('ArrowRight')
    photo_loaded('사진 2')
    expect(page.locator('#prev-frame')).not_to_have_attribute('disabled', '')
    page.keyboard.press('ArrowLeft')
    photo_loaded('사진 1')
    page.locator('#filter').select_option('excluded')
    photo_loaded('사진 2')
    expect(page.locator('#prev-frame')).to_have_attribute('disabled', '')
    page.locator('#canvas').focus()
    page.keyboard.press('ArrowLeft')
    page.keyboard.press('ArrowRight')
    photo_loaded('사진 2')
    assert [row['status'] for row in store.list_frames()] == ['approved', 'excluded']


def test_filter_selection_empty_recovery_and_reload(browser_workspace):
    page, store, expect = browser_workspace
    page.locator('#filter').select_option('excluded')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    expect(page.locator('#prev-frame')).to_have_attribute('disabled', '')
    expect(page.locator('#next-frame')).to_have_attribute('disabled', '')
    page.reload(wait_until='networkidle')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    page.locator('#filter').select_option('pending')
    expect(page.locator('#empty-review')).to_be_visible()
    expect(page.locator('#review-content')).to_be_hidden()
    page.reload(wait_until='networkidle')
    expect(page.locator('#empty-review')).to_be_visible()
    page.locator('#show-all').click()
    expect(page.locator('#frame-title')).to_have_text('사진 1')
    expect(page.locator('#review-content')).to_be_visible()
    assert [row['status'] for row in store.list_frames()] == ['approved', 'excluded']


def test_undo_restores_boxes_without_restoring_approval(browser_workspace):
    page, store, expect = browser_workspace
    original = store.get(0)['review']['boxes']
    page.locator('#filter').select_option('approved')
    expect(page.locator('#image-message')).to_be_hidden()
    page.get_by_role('button', name='박스 1 삭제', exact=True).click()
    expect(page.locator('#boxes details')).to_have_count(0)
    expect(page.locator('#filter')).to_have_value('all')
    expect(page.locator('#undo')).not_to_have_attribute('disabled', '')
    page.locator('#undo').focus(); page.keyboard.press('Enter')
    expect(page.locator('#boxes details')).to_have_count(1)
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
    assert store.get(0)['review']['boxes'] == original
    assert store.get(0)['status'] == 'pending'
    assert not store.get(0)['review']['complete_frame_review']
    assert store.get(0)['version'] == 3
    page.reload(wait_until='networkidle')
    expect(page.locator('#status')).to_have_text('검수 대기')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')


def test_stale_undo_never_overwrites_other_tab(browser_workspace):
    page, store, expect = browser_workspace
    page.get_by_role('button', name='박스 1 삭제', exact=True).click()
    expect(page.locator('#undo')).not_to_have_attribute('disabled', '')
    row=store.get(0)
    newer=store.update(0, {'version':row['version'], 'action':'save',
                          'boxes':[{'label':'traffic_light','signal_state':'red',
                                    'bbox_xyxy':[2,3,13,15]}]})
    page.locator('#undo').click()
    expect(page.locator('#save-status')).to_contain_text('저장 실패')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
    assert store.get(0) == newer
    page.locator('#reload').click()
    expect(page.get_by_label('박스 1 x0',exact=True)).to_have_value('2')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
