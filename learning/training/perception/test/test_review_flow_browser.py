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


@pytest.mark.parametrize('route,left,right', [('/', '.review-stage', '.label-inspector'),
                                                   ('/pixels', '.pixel-layout > section', '.pixel-layout > aside')])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_review_editor_peer_widths(browser_workspace, route, left, right, width):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    boxes = [page.locator(selector).bounding_box() for selector in (left, right)]
    assert all(box and box['width'] > 0 for box in boxes)
    assert abs(boxes[0]['width'] - boxes[1]['width']) <= 1
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{route.strip("/") or "objects"}-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_empty_review_can_recover_at_declared_widths(browser_workspace, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    assert page.locator('.workspace').bounding_box()['width'] == width
    topbar = page.locator('ui-topbar').bounding_box()
    assert page.locator('.workspace').bounding_box()['y'] == topbar['y'] + topbar['height']
    page.locator('#filter').select_option('pending')
    expect(page.locator('#empty-review')).to_be_visible()
    expect(page.locator('#review-content')).to_be_hidden()
    action = page.locator('#show-all')
    assert action.bounding_box()['width'] > 0
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-objects-empty-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    action.click()
    expect(page.locator('#frame-title')).to_have_text('사진 1')


@pytest.mark.parametrize('route,main', [('/learning', '#learning-main'), ('/catalog', '#catalog-main')])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_learning_pages_start_below_topbar(browser_workspace, route, main, width):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    topbar = page.locator('ui-topbar').bounding_box()
    assert page.locator(main).bounding_box()['y'] == topbar['y'] + topbar['height']
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{route.strip("/")}-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_empty_pixel_review_can_recover_at_declared_widths(browser_workspace, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    page.locator('#pixel-filter').select_option('approved')
    expect(page.locator('#pixel-empty')).to_be_visible()
    expect(page.locator('#pixel-content')).to_be_hidden()
    expect(page.locator('#pixel-title')).to_have_text('픽셀 검수')
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 승인 0장')
    expect(page.locator('#pixel-frame').locator('..')).to_be_hidden()
    expect(page.locator('#pixel-prev')).to_be_hidden()
    expect(page.locator('#pixel-next')).to_be_hidden()
    action = page.locator('#pixel-all')
    assert action.bounding_box()['x'] + action.bounding_box()['width'] <= width
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-pixels-empty-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    action.click()
    expect(page.locator('#pixel-content')).to_be_visible()
    expect(page.locator('#pixel-frame').locator('..')).to_be_visible()
    expect(page.locator('#pixel-next')).to_be_visible()


def test_pixel_review_first_use_leads_to_data_registration(browser_workspace):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    with store.connect() as db:
        db.execute('DELETE FROM frames')
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    expect(page.locator('#pixel-empty')).to_be_visible()
    expect(page.locator('#pixel-status')).to_contain_text('등록된 사진 0장')
    expect(page.locator('#pixel-filter').locator('..')).to_be_hidden()
    expect(page.locator('#pixel-all')).to_have_text('자료 등록 열기')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / 'learning-pixels-first-use-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('#pixel-all').click()
    assert page.url.endswith('/catalog')


def test_object_review_first_use_leads_to_data_registration(browser_workspace):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    with store.connect() as db:
        db.execute('DELETE FROM frames')
    page.reload(wait_until='networkidle')
    expect(page.locator('#empty-review')).to_be_visible()
    expect(page.locator('#review-content')).to_be_hidden()
    expect(page.locator('#filter').locator('..')).to_be_hidden()
    expect(page.locator('#show-all')).to_have_text('자료 등록 열기')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / 'learning-objects-first-use-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('#show-all').click()
    assert page.url.endswith('/catalog')


@pytest.mark.parametrize('route,empty,retry,content', [('/', '#empty-review', '#show-all', '#review-content'),
                                                       ('/pixels', '#pixel-empty', '#pixel-reload', '#pixel-content')])
@pytest.mark.parametrize('width', [1440, 390])
def test_workspace_disconnect_shows_reachable_retry(browser_workspace, route, empty, retry, content, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.route('**/api/workspace', lambda request: request.abort())
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    expect(page.locator(empty)).to_be_visible()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(retry)).to_be_visible()
    if route == '/':
        expect(page.locator('#empty-review h2')).to_have_text('검수 내용을 불러오지 못했습니다')
    else:
        expect(page.locator('#pixel-status')).to_contain_text('검수 내용을 불러오지 못했습니다')
        expect(page.locator('#pixel-frame').locator('..')).to_be_hidden()
    assert page.locator(retry).bounding_box()['y'] < 844
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-disconnect-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.unroute('**/api/workspace')
    page.locator(retry).click()
    expect(page.locator(content)).to_be_visible()


@pytest.mark.parametrize('route,reload,content', [('/', '#reload', '#review-content'),
                                                 ('/pixels', '#pixel-reload', '#pixel-content')])
def test_workspace_disconnect_hides_stale_review(browser_workspace, route, reload, content):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    expect(page.locator(content)).to_be_visible()
    page.route('**/api/workspace', lambda request: request.abort())
    page.locator(reload).click()
    expect(page.locator(content)).to_be_hidden()
    page.unroute('**/api/workspace')
    page.locator('#show-all' if route == '/' else '#pixel-reload').click()
    expect(page.locator(content)).to_be_visible()


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
