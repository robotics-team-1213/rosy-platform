"""Photo-first review and compact navigation at desktop and phone sizes."""
import os

import pytest
from browser_harness import browser_tests_enabled
import review_masks
from test_review_cycle import CLASSES
from test_review_flow_browser import browser_workspace

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


@pytest.mark.parametrize('route', ['/learning', '/', '/pixels', '/catalog', '/learning/omx', '/learning/vlm', '/learning/evaluate', '/learning/camera', '/learning/workspaces', '/learning/record', '/learning/tasks', '/learning/sim', '/classes', '/learning/imitate', '/learning/public', '/learning/tasks/manage'])
def test_learning_page_has_visible_current_path(browser_workspace, route):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='domcontentloaded')
    path = page.locator('.ui-pathbar')
    expect(path.get_by_role('link', name='Learning', exact=True)).to_have_attribute('href', '/learning')
    expect(path).to_contain_text('/')
    expect(path.locator('h1')).to_be_visible()
    assert path.evaluate('n => n.scrollWidth <= n.clientWidth')


@pytest.mark.parametrize('route', ['/learning/evaluate', '/learning/vlm'])
def test_learning_authority_copy_hides_internal_adr_ids(browser_workspace, route):
    page, _, expect = browser_workspace
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    text = page.locator('main').inner_text()
    import re
    assert not re.search(r'D-\d{3}', text)
    expect(page.locator('main')).to_contain_text('확정 정답')


def test_object_tools_use_real_views_without_hiding_approval(browser_workspace):
    page, _, expect = browser_workspace
    nav = page.get_by_role('navigation', name='객체 검수 도구')
    nav.get_by_role('link', name='자료 준비', exact=True).click()
    expect(page.locator('#prepare')).to_be_visible()
    expect(page.locator('#approve')).to_be_hidden()
    assert page.locator('ui-button[kind="primary"]:visible').count() == 1
    expect(page.locator('#object-keys')).to_be_hidden()
    nav.get_by_role('link', name='사진 검수', exact=True).click()
    expect(page.locator('#canvas')).to_be_visible()
    expect(page.locator('#approve')).to_be_visible()
    expect(page.locator('#canvas')).to_have_attribute('tabindex', '0')
    page.locator('#canvas').focus()
    page.keyboard.press('Shift+Tab')
    page.keyboard.press('Tab')
    expect(page.locator('#canvas')).to_be_focused()
    assert page.locator('details:visible').count() < 3
    page.locator('#canvas').focus()
    page.keyboard.press('?')
    expect(page.locator('#object-keys')).to_be_visible()
    page.go_back()
    expect(page.locator('#canvas')).to_be_visible()


def test_object_preparation_keeps_valid_commands_and_excludes_denied_work(browser_workspace):
    page, store, expect = browser_workspace
    page.locator('#reopen').click()
    expect(page.locator('#add')).to_be_enabled()
    nav = page.get_by_role('navigation', name='객체 검수 도구')
    nav.get_by_role('link', name='자료 준비', exact=True).click()
    page.keyboard.press('Control+k')
    page.get_by_role('textbox', name='기능 검색어').fill('새로고침')
    expect(page.locator('#review-command-results ui-button')).to_have_count(1)
    page.keyboard.press('Enter')
    expect(page.locator('#reload')).to_be_visible()
    expect(page.locator('#reload')).to_be_enabled()
    nav.get_by_role('link', name='자료 준비', exact=True).click()
    with page.expect_response(lambda response: '/api/workspace?' in response.url):
        page.keyboard.press('r')
    expect(page.locator('#reload')).to_be_visible()
    expect(page.locator('#reload')).to_be_enabled()
    nav.get_by_role('link', name='자료 준비', exact=True).click()
    before = len(store.get(0)['review']['boxes'])
    page.keyboard.press('Insert')
    expect(page.locator('#boxes .box-row')).to_have_count(before + 1)
    page.route('**/api/workspace*', lambda route: route.fulfill(status=403, json={'error': 'denied'}))
    page.locator('#reload').click()
    expect(page.locator('#review-content')).to_be_hidden()
    page.keyboard.press('Control+k')
    page.get_by_role('textbox', name='기능 검색어').fill('새로고침')
    expect(page.locator('#review-command-results ui-button')).to_have_count(0)
    page.keyboard.press('Escape')


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_review_photo_and_result_are_in_first_view(browser_workspace, theme):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    base = page.url.split('?')[0].rstrip('/')
    for width, height in [(1280, 720), (1440, 900), (390, 800), (390, 844)]:
        page.set_viewport_size({'width': width, 'height': height})
        for route, canvas, result in [('/', '#canvas', '#object-result'),
                                      ('/pixels', '#pixel-canvas', '#pixel-result')]:
            page.goto(base + route, wait_until='networkidle')
            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
            box = page.locator(canvas).bounding_box()
            assert box and box['y'] <= height * (.65 if route == '/pixels' else .4), (route, width, height, box)
            assert min(box['y'] + box['height'], height) - box['y'] >= box['height'] / 3
            if route == '/pixels':
                footer = page.locator('.pixel-canvas-footer').bounding_box()
                assert box['y'] + box['height'] <= height and footer['y'] + footer['height'] <= height
                inspector = page.locator('.pixel-review-column').bounding_box()
                for panel in ['#review-ai-jobs', '.pixel-vlm-feedback']:
                    expect(page.locator('.pixel-review-column ' + panel)).to_have_count(1)
                if width >= 1024:
                    assert inspector['x'] >= box['x'] + box['width'] - 1
                else:
                    assert inspector['y'] >= box['y'] + box['height'] - 1
                expect(page.locator('#pixel-viewport-controls .review-viewport-controls')).to_be_visible()
                assert not page.locator('#pixel-review-info').evaluate('node => node.open')
                assert not page.locator('#pixel-whole-frame-tools').evaluate('node => node.open')
                assert page.locator('#pixel-photo-list #pixel-page-controls').count() == 1
            expect(page.locator(result)).to_contain_text('저장')
            if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
                from pathlib import Path
                target = Path(output) / f'review-hierarchy-{route.strip("/") or "objects"}-{theme}-{width}x{height}.png'
                target.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(target), full_page=True)
                import json
                target.with_suffix('.json').write_text(json.dumps(dict(
                    state='review first view', route=route, theme=theme, viewport=page.viewport_size,
                    canvas=box, filename=target.name,
                    footer=page.locator('.pixel-canvas-footer').bounding_box() if route == '/pixels' else None),
                    ensure_ascii=False, indent=2), encoding='utf-8')
            assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
            if width == 390:
                actions = ['#prev-frame', '#next-frame', '#next-pending'] if route == '/' else ['#pixel-prev', '#pixel-next', '#pixel-undo']
                for action in actions:
                    expect(page.locator(f'{action} .ui-icon')).to_be_visible()
                    assert page.locator(action).get_attribute('aria-label')


@pytest.mark.parametrize('route', ['/learning', '/catalog', '/', '/pixels'])
@pytest.mark.parametrize('width,height', [(390, 844), (320, 568)])
def test_learning_compact_header_stays_within_first_view_budget(browser_workspace, route, width, height):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    topbar = page.locator('ui-topbar').bounding_box()
    assert topbar['height'] <= height * 0.2, (route, topbar, height)
    # D-741: the app bar is one row (app, account, theme cycle); navigation stays in the rail.
    assert page.locator('ui-topbar h1, ui-topbar nav').count() == 0
    brand = page.locator('ui-topbar ui-brand').bounding_box()
    theme = page.locator('ui-topbar [data-theme-cycle]').bounding_box()
    assert brand['x'] + brand['width'] <= theme['x'], (route, brand, theme)
    rail = page.locator('.ui-rail').bounding_box()
    assert rail['y'] == topbar['y'] + topbar['height'], (route, rail, topbar)
    assert set(page.locator('.workspace-tabs a').evaluate_all('links => links.map(link => new URL(link.href).pathname)')) == {
        '/learning', '/catalog', '/', '/learning/tasks', '/learning/evaluate',
    }
    assert page.locator('.workspace-tabs a[aria-current]').count() == 1
    for link in page.locator('.workspace-tabs a').all():
        bounds = link.bounding_box()
        assert bounds['height'] >= 44 and bounds['y'] + bounds['height'] <= rail['y'] + rail['height'], (route, bounds)
    title = page.locator('.ui-pathbar h1').bounding_box()
    assert title['y'] + title['height'] <= height, (route, title)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        name = route.strip('/') or 'objects'
        target = Path(output) / f'learning-header-{name}-{width}x{height}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))
