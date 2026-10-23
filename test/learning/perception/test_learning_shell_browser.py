"""Shared Learning navigation works without losing the review editor context."""
from urllib.parse import parse_qs, urlsplit

import os
from pathlib import Path

import review_masks
from test_review_cycle import CLASSES

import pytest

from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium browser run')


@pytest.mark.parametrize('width', [1440, 320])
def test_learning_shell_navigation_and_review_context(browser_workspace, width):
    page, _, expect = browser_workspace
    origin = urlsplit(page.url)
    base = f'{origin.scheme}://{origin.netloc}'
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(base + '/?frame=0&filter=all', wait_until='networkidle')
    nav = page.get_by_role('navigation', name='Learning 주 메뉴', exact=True)
    expect(nav).to_be_visible()
    assert nav.locator('a').all_text_contents() == ['홈', '자료', '정답', '학습', '평가·승격']
    expect(nav.locator('[aria-current="page"]')).to_have_text('정답')
    expect(page.locator('#canvas')).to_be_visible()
    selection = parse_qs(urlsplit(page.url).query)
    assert selection.get('frame') == ['0']
    assert selection.get('filter', ['all']) == ['all']
    assert page.locator('.learning-connections').count() == 1
    for link in nav.locator('a').all():
        bounds = link.bounding_box()
        assert bounds['height'] >= 44
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width
    training = nav.get_by_role('link', name='학습', exact=True)
    training.focus()
    expect(training).to_be_focused()
    page.keyboard.press('Enter')
    expect(page).to_have_url(base + '/learning?view=training')
    expect(page.get_by_role('navigation', name='Learning 주 메뉴').locator('[aria-current="page"]')).to_have_text('학습')
    page.goto(base + '/pixels?frame=0&filter=pending', wait_until='networkidle')
    subnav = page.get_by_role('navigation', name='정답 화면', exact=True)
    expect(subnav.get_by_role('link', name='픽셀 검수', exact=True)).to_have_attribute('aria-current', 'page')
    expect(subnav.get_by_role('link', name='객체 검수', exact=True)).to_have_attribute('href', '/?frame=0&filter=pending')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1440, 800, 390])
def test_empty_review_can_recover_at_declared_widths(browser_workspace, width):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    workspace = page.locator('.workspace')
    assert workspace.bounding_box()['width'] == min(page.locator('.ui-app-main').bounding_box()['width'], workspace.evaluate('(node) => parseFloat(getComputedStyle(node).maxWidth)'))
    # D-741: the path row (page heading) sits between the app bar and the work area.
    pathbar = page.locator('.ui-pathbar').bounding_box()
    assert page.locator('.workspace').bounding_box()['y'] == pathbar['y'] + pathbar['height']
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


@pytest.mark.parametrize('width', [1440, 390])
def test_object_to_pixel_review_keeps_photo_and_shows_decision(browser_workspace, width):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    store.update(1, {'version': store.get(1)['version'], 'action': 'reopen'})
    page.set_viewport_size({'width': width, 'height': 844})
    page.goto(page.url.split('?')[0] + '?frame=1', wait_until='networkidle')
    expect(page.locator('#frame-title')).to_have_text('사진 2')
    expect(page.locator('a[href="/pixels?frame=1"]')).to_have_count(3)
    page.get_by_role('navigation', name='정답 화면', exact=True).get_by_role('link', name='픽셀 검수', exact=True).click()
    expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 검수 대기')
    page.locator('#pixel-class').select_option('0')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.locator('#pixel-complete').check()
    page.locator('#pixel-background').check()
    page.locator('#pixel-approve').click()
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
    expect(page.locator('#pixel-decision')).to_contain_text('사진 2 픽셀 승인 · 다음 검수 대기 사진 1')
    assert not page.locator('#pixel-decision').is_hidden()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(Path(output) / f'learning-pixel-decision-{width}.png'), full_page=True)
    page.get_by_role('navigation', name='Learning 주 메뉴', exact=True).get_by_role('link', name='홈', exact=True).click()
    expect(page.locator('#review-counts')).to_contain_text('검수 대기 1장')
    expect(page.locator('#pixel-counts')).to_contain_text('승인 1장 · 검수 대기 1장')
    page.locator('#pixel-review-link').click()
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')


@pytest.mark.parametrize('route', ['/learning', '/catalog', '/', '/pixels', '/learning/camera', '/learning/omx', '/learning/vlm', '/learning/evaluate'])
@pytest.mark.parametrize('width,height', [(390, 844), (320, 568)])
def test_learning_compact_header_stays_within_first_view_budget(browser_workspace, route, width, height):
    page, _, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    topbar = page.locator('ui-topbar').bounding_box()
    assert topbar['height'] <= height * 0.2, (route, topbar, height)
    # The application bar, primary destinations and contextual tools share one compact shell.
    assert page.locator('ui-topbar h1, ui-topbar nav').count() == 0
    brand = page.locator('ui-topbar ui-brand').bounding_box()
    theme = page.locator('ui-topbar [data-theme-cycle]').bounding_box()
    assert brand['x'] + brand['width'] <= theme['x'], (route, brand, theme)
    rail = page.locator('.ui-rail').bounding_box()
    assert rail['y'] == topbar['y'] + topbar['height'], (route, rail, topbar)
    assert page.locator('.learning-primary-nav a').count() == 5
    assert page.locator('.learning-primary-nav a[aria-current="page"]').count() == 1
    for link in page.locator('.learning-primary-nav a').all():
        bounds = link.bounding_box()
        assert bounds['height'] >= 44 and bounds['y'] + bounds['height'] <= rail['y'] + rail['height'], (route, bounds)
    title = page.locator('.ui-pathbar').bounding_box()
    assert title['y'] + title['height'] <= height, (route, title)
    for link in page.locator('.learning-review-nav a').all():
        bounds = link.bounding_box()
        assert bounds['height'] >= 44 and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width, (route, bounds)
    page.locator('.learning-settings summary').click()
    for link in page.locator('.learning-settings a').all():
        bounds = link.bounding_box()
        assert bounds['height'] >= 44 and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width, (route, bounds)
    page.keyboard.press('Escape')
    expect(page.locator('.learning-settings-menu')).to_be_hidden()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        name = route.strip('/') or 'objects'
        target = Path(output) / f'learning-header-{name}-{width}x{height}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))



# D-857 §3: each stage owns its pages; every existing page is one menu click plus at most one sub-menu click away.
STAGE_PAGES = [('홈', None, '/learning'), ('자료', '자료 등록', '/catalog'), ('자료', '카메라 맞춤', '/learning/camera'),
               ('정답', '객체 검수', '/'), ('정답', '픽셀 검수', '/pixels'), ('정답', 'OMX 구간', '/learning/omx'),
               ('정답', 'VLM 판단', '/learning/vlm'), ('학습', '학습 실행', '/learning?view=training'),
               ('학습', 'SIM 실험', '/learning/sim'), ('평가·승격', None, '/learning/evaluate')]


@pytest.mark.parametrize('width', [1280, 390])
def test_five_stage_menu_reaches_every_page_in_two_clicks(browser_workspace, width):
    page, _, expect = browser_workspace
    origin = urlsplit(page.url)
    base = f'{origin.scheme}://{origin.netloc}'
    page.set_viewport_size({'width': width, 'height': 844})
    for stage, sub, target in STAGE_PAGES:
        page.goto(base + '/learning/evaluate', wait_until='networkidle')
        page.get_by_role('navigation', name='Learning 주 메뉴', exact=True).get_by_role('link', name=stage, exact=True).click()
        page.wait_for_load_state('networkidle')
        if sub:
            subnav = page.get_by_role('navigation', name=f'{stage} 화면', exact=True)
            subnav.get_by_role('link', name=sub, exact=True).click()
            page.wait_for_load_state('networkidle')
            expect(page.get_by_role('navigation', name=f'{stage} 화면', exact=True).locator('[aria-current="page"]')).to_have_text(sub)
        address, wanted = urlsplit(page.url), urlsplit(target)  # editors add their own frame/filter keys
        assert address.path == wanted.path and parse_qs(address.query).get('view') == parse_qs(wanted.query).get('view'), page.url
        expect(page.get_by_role('navigation', name='Learning 주 메뉴', exact=True).locator('[aria-current="page"]')).to_have_text(stage)
        assert page.title().startswith('Rosy Learning — '), (target, page.title())
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), target
    page.goto(base + '/learning/evaluate?domain=vlm', wait_until='networkidle')
    expect(page.locator('#evaluate-filter')).to_contain_text('VLM 판단만')
    assert page.locator('.evaluate-source[data-domain="lane"]').count() == 0
    expect(page.locator('#promote-request')).to_be_disabled()
    page.locator('.learning-settings summary').click()
    page.get_by_role('link', name='저장 공간', exact=True).click()
    expect(page.locator('#storage-panel')).to_have_attribute('open', '')
    expect(page.get_by_role('navigation', name='Learning 주 메뉴', exact=True).locator('[aria-current="page"]')).to_have_text('홈')
