"""Real Chromium regression checks for filtered selection and safe label undo."""
import os
import threading

import pytest

from test_review_app import open_store
from test_review_cycle import CLASSES, catalog
from review_app import make_server
import review_masks

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


@pytest.mark.parametrize('width', [390, 320])
def test_catalog_import_reaches_pending_review_on_phone(browser_workspace, tmp_path, width):
    page, store, expect = browser_workspace
    folder, _, _ = catalog(tmp_path)
    review_masks.bind_classes(store, CLASSES)
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + '/catalog', wait_until='networkidle')
    for form, field, action in [('import-form', 'catalog-path', 'import'),
                                ('cad-form', 'cad-path', 'cad')]:
        widths = page.evaluate("""selectors => selectors.map(selector =>
          document.querySelector(selector).getBoundingClientRect().width)""",
          [f'#{form}', f'#{form} label', f'#{field}', f'#{action}'])
        if width == 320:
            assert max(widths) - min(widths) <= 1, widths
        else:
            assert max(widths[1:]) - min(widths[1:]) <= 1, widths
        assert 44 <= page.locator(f'#{action}').bounding_box()['height'] <= 72
    page.locator('#catalog-path').fill(str(folder))
    page.locator('#import').click()
    expect(page.locator('#result')).to_contain_text('새 사진 1장 · 중복 표현 1개 · 새 픽셀 검수 대기 1장')
    assert len(store.list_frames()) == 3 and store.get(2)['status'] == 'pending'
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-import-result-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('a[href="/?filter=pending"]').click()
    expect(page.locator('#counts')).to_contain_text('대기 1')
    expect(page.locator('#status')).to_contain_text('검수 대기')
    if width == 320:
        assert abs(page.locator('#frames ui-button').first.bounding_box()['width']
                   - page.locator('#frames').bounding_box()['width']) <= 1
    if output:
        target = Path(output) / f'learning-import-pending-{width}.png'
        page.screenshot(path=str(target), full_page=True)


@pytest.mark.parametrize('route,left,right', [('/', '.review-stage', '.label-inspector'),
                                                   ('/pixels', '.pixel-layout > section', '.pixel-layout > aside')])
@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_review_editor_peer_widths(browser_workspace, route, left, right, width):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': 1000})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    boxes = [page.locator(selector).bounding_box() for selector in (left, right)]
    assert all(box and box['width'] > 0 for box in boxes)
    assert abs(boxes[0]['width'] - boxes[1]['width']) <= 1
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    for pane in (left, right):
        actions = page.locator(f'{pane} ui-actions').first
        buttons = actions.locator('ui-button').all()
        if buttons:
            widths = [button.bounding_box()['width'] for button in buttons]
            assert max(widths) - min(widths) <= 1, widths
    if width <= 390:
        if route == '/pixels':
            previous = page.locator('#pixel-prev').bounding_box()
            following = page.locator('#pixel-next').bounding_box()
            reload = page.locator('#pixel-reload').bounding_box()
            assert abs(previous['width'] - following['width']) <= 1
            assert previous['y'] == following['y']
            assert abs(reload['width'] - page.locator('.ui-workspace-bar').first.bounding_box()['width']) <= 1
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
@pytest.mark.parametrize('width', [1440, 800, 390])
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


@pytest.mark.parametrize('route,reload,content,empty,prepare,result,error', [
    ('/', '#reload', '#review-content', '#empty-review', '#prepare', '#export-result', '#error'),
    ('/pixels', '#pixel-reload', '#pixel-content', '#pixel-empty', '#pixel-export', '#pixel-export-result', '#pixel-error'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_review_permission_denial_blocks_work_until_reload(
    browser_workspace, route, reload, content, empty, prepare, result, error, width
):
    page, _, expect = browser_workspace
    output = os.getenv('ROSY_UIUX_SCREENSHOT_DIR')
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    page.route('**/api/workspace', lambda request: request.fulfill(
        status=403, content_type='application/json', body='{"error":"local host required"}'))
    page.locator(reload).click()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(empty)).to_be_visible()
    denied = '#empty-review p' if route == '/' else '#pixel-status'
    expect(page.locator(denied)).to_contain_text('권한')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output:
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-workspace-denied-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    page.unroute('**/api/workspace')
    page.locator('#show-all' if route == '/' else reload).click()
    expect(page.locator(content)).to_be_visible()

    page.route('**/api/prepare', lambda request: request.fulfill(
        status=403, content_type='application/json', body='{"error":"local workspace authorization required"}'))
    page.locator(prepare).click()
    expect(page.locator(result)).to_contain_text('권한')
    box = page.locator(result).bounding_box()
    assert box and box['y'] >= 0 and box['y'] + box['height'] <= 844
    expect(page.locator(error)).to_contain_text('권한')
    expect(page.locator(prepare)).to_be_disabled()
    expect(page.locator(reload)).to_be_enabled()
    if output:
        page.locator(result).scroll_into_view_if_needed()
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-prepare-denied-{width}.png'
        page.screenshot(path=str(target))
    page.unroute('**/api/prepare')
    page.locator(reload).click()
    expect(page.locator(prepare)).to_be_enabled()


@pytest.mark.parametrize('route,reload,content,empty,prepare,pending_text', [
    ('/', '#reload', '#review-content', '#empty-review', '#prepare', '검수 내용을 확인하는 중'),
    ('/pixels', '#pixel-reload', '#pixel-content', '#pixel-empty', '#pixel-export', '검수 내용을 확인하는 중'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_review_waiting_workspace_hides_stale_editing(
    browser_workspace, route, reload, content, empty, prepare, pending_text, width
):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    pending = []
    page.route('**/api/workspace', lambda request: pending.append(request))
    with page.expect_request('**/api/workspace'):
        page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    if route == '/pixels':
        expect(page.locator(empty)).to_be_hidden()
    else:
        expect(page.locator(empty)).to_be_visible()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(empty if route == '/' else '#pixel-status')).to_contain_text(pending_text)
    expect(page.locator(prepare)).to_be_disabled()
    assert pending
    pending.pop().continue_()
    expect(page.locator(content)).to_be_visible()
    expect(page.locator(prepare)).to_be_enabled()
    page.locator(reload).click()
    if route == '/pixels':
        expect(page.locator(empty)).to_be_hidden()
    else:
        expect(page.locator(empty)).to_be_visible()
    expect(page.locator(content)).to_be_hidden()
    expect(page.locator(prepare)).to_be_disabled()
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    assert pending
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-waiting-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    pending.pop().continue_()
    expect(page.locator(content)).to_be_visible()
    expect(page.locator(prepare)).to_be_enabled()


@pytest.mark.parametrize('route,status,content', [
    ('/', '#empty-review p', '#review-content'),
    ('/pixels', '#pixel-status', '#pixel-content'),
])
def test_review_delayed_workspace_shows_wait_age(browser_workspace, route, status, content):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    pending = []
    page.route('**/api/workspace', lambda request: pending.append(request))
    with page.expect_request('**/api/workspace'):
        page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    expect(page.locator(status)).to_contain_text('서버 응답 대기 3초', timeout=5000)
    expect(page.locator(content)).to_be_hidden()
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{"objects" if route == "/" else "pixels"}-delayed-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    pending.pop().continue_()
    expect(page.locator(content)).to_be_visible()
    if route == '/pixels':
        expect(page.locator(status)).not_to_contain_text('서버 응답 대기')
    else:
        expect(page.locator('#empty-review')).to_be_hidden()


@pytest.mark.parametrize('route,api,actions,status,retry', [
    ('/learning', 'learning', ('#new-task', '#connect'), '#learning-status', '#refresh'),
    ('/catalog', 'catalog', ('#import', '#cad'), '#catalog-load', '#catalog-retry'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_learning_list_and_catalog_wait_denial_and_retry(
    browser_workspace, route, api, actions, status, retry, width
):
    page, _, expect = browser_workspace
    output = os.getenv('ROSY_UIUX_SCREENSHOT_DIR')
    page.set_viewport_size({'width': width, 'height': 844})
    pending = []
    page.route(f'**/api/{api}', lambda request: pending.append(request))
    with page.expect_request(f'**/api/{api}'):
        page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    expect(page.locator(status)).to_contain_text('확인하는 중')
    for action in actions:
        expect(page.locator(action)).to_be_disabled()
    if route == '/learning':
        expect(page.locator('#jobs')).to_be_hidden()
    if output:
        from pathlib import Path
        target = Path(output) / f'learning-{api}-waiting-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    assert pending
    pending.pop().fulfill(status=403, content_type='application/json', body='{"error":"local host required"}')
    expect(page.locator(status)).to_contain_text('권한')
    for action in actions:
        expect(page.locator(action)).to_be_disabled()
    if route == '/learning':
        expect(page.locator('#review-counts')).to_contain_text('확인 불가')
        expect(page.locator('#search')).to_be_disabled()
    else:
        expect(page.locator('#catalog-path')).to_be_disabled()
    expect(page.locator(retry)).to_be_enabled()
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if output:
        target = Path(output) / f'learning-{api}-denied-{width}.png'
        page.screenshot(path=str(target))
    page.locator(retry).click()
    assert pending
    pending.pop().continue_()
    for action in actions:
        expect(page.locator(action)).to_be_enabled()
    expect(page.locator('#search' if route == '/learning' else '#catalog-path')).to_be_enabled()


@pytest.mark.parametrize('route,api,status,retry,recovered', [
    ('/', 'workspace', '#empty-review h2', '#show-all', '#review-content'),
    ('/pixels', 'workspace', '#pixel-status', '#pixel-reload', '#pixel-content'),
    ('/learning', 'learning', '#learning-status', '#refresh', '#connect'),
    ('/catalog', 'catalog', '#catalog-load', '#catalog-retry', '#import'),
])
@pytest.mark.parametrize('width', [1440, 800, 390])
def test_review_service_unavailable_is_distinct_from_connection_failure(
    browser_workspace, route, api, status, retry, recovered, width
):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.route(f'**/api/{api}', lambda request: request.fulfill(
        status=503, content_type='text/html', body='Service Unavailable'))
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    expect(page.locator(status)).to_contain_text('사용할 수 없습니다')
    expect(page.locator(retry)).to_be_visible()
    if route == '/pixels':
        expect(page.locator('#pixel-empty h3')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if route == '/learning':
        expect(page.locator('#learning-error')).to_be_hidden()
    if route in ('/', '/catalog') and width == 390:
        assert page.locator(retry).bounding_box()['width'] >= width * .8
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        name = 'objects' if route == '/' else route.lstrip('/')
        target = Path(output) / f'learning-{name}-unavailable-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    page.unroute(f'**/api/{api}')
    page.locator(retry).click()
    if route in ('/learning', '/catalog'):
        expect(page.locator(recovered)).to_be_enabled()
    else:
        expect(page.locator(recovered)).to_be_visible()


@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_object_decision_and_preparation_result_are_visible(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    def shot(state):
        if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
            from pathlib import Path
            target = Path(output) / f'learning-objects-{state}-{width}.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(target), full_page=True)
    page.locator('#exclude').click()
    expect(page.locator('#status')).to_have_text('제외')
    assert store.get(0)['status'] == 'excluded'
    shot('excluded')
    page.locator('#reopen').click()
    expect(page.locator('#status')).to_have_text('검수 대기')
    page.locator('#complete').check()
    page.locator('#approve').click()
    expect(page.locator('#status')).to_have_text('승인')
    assert store.get(0)['status'] == 'approved'
    shot('approved')
    page.locator('#prepare').click()
    expect(page.locator('#export-result')).to_contain_text('승인 1장 준비 완료')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    if width <= 390:
        navigation = page.locator('.frame-navigation').bounding_box()
        buttons = [page.locator(f'#{name}').bounding_box() for name in ('prev-frame', 'next-frame', 'next-pending')]
        assert all(abs(button['width'] - navigation['width']) <= 1 for button in buttons)
        assert buttons[0]['y'] < buttons[1]['y'] < buttons[2]['y']
    shot('decision-result')


@pytest.mark.parametrize('route,post,action,status,retry', [
    ('/learning', 'learning/register', '#connect', '#learning-status', '#refresh'),
    ('/catalog', 'import', '#import', '#catalog-load', '#catalog-retry'),
])
def test_learning_registration_denial_blocks_repeat_until_retry(
    browser_workspace, route, post, action, status, retry
):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    page.route(f'**/api/{post}', lambda request: request.fulfill(
        status=403, content_type='application/json', body='{"error":"local workspace authorization required"}'))
    if route == '/learning':
        page.locator('#new-task').click()
        page.locator('#name').fill('권한 확인')
        page.locator('#path').fill('X:/DevTemp/permission-check')
    else:
        page.locator('#catalog-path').fill('X:/DevTemp/permission-check')
    page.locator(action).click()
    expect(page.locator(status)).to_contain_text('권한')
    result = page.locator('#learning-error' if route == '/learning' else '#catalog-error')
    expect(result).to_contain_text('권한')
    box = result.bounding_box()
    assert box and box['y'] >= 0 and box['y'] + box['height'] <= 844
    expect(page.locator(action)).to_be_disabled()
    expect(page.locator(retry)).to_be_enabled()
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-{route.strip("/")}-submit-denied-390.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
    page.unroute(f'**/api/{post}')
    page.locator(retry).click()
    expect(page.locator(action)).to_be_enabled()


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


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_stale_undo_never_overwrites_other_tab(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    page.get_by_role('button', name='박스 1 삭제', exact=True).click()
    expect(page.locator('#undo')).not_to_have_attribute('disabled', '')
    row=store.get(0)
    newer=store.update(0, {'version':row['version'], 'action':'save',
                          'boxes':[{'label':'traffic_light','signal_state':'red',
                                    'bbox_xyxy':[2,3,13,15]}]})
    page.locator('#undo').click()
    expect(page.locator('#save-status')).to_contain_text('저장 실패')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
    expect(page.locator('#approve')).to_have_attribute('disabled', '')
    assert store.get(0) == newer
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if width == 390:
        reload = page.locator('#reload').bounding_box()
        assert reload and reload['width'] >= width * .8 and reload['x'] + reload['width'] <= width
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-objects-conflict-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('#reload').click()
    expect(page.get_by_label('박스 1 x0',exact=True)).to_have_value('2')
    expect(page.locator('#undo')).to_have_attribute('disabled', '')
