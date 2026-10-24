"""Photo-first review and compact navigation at desktop and phone sizes."""
import os

import pytest
from browser_harness import browser_tests_enabled
import review_masks
from test_review_cycle import CLASSES
from test_review_flow_browser import browser_workspace

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def test_review_photo_and_result_are_in_first_view(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    base = page.url.split('?')[0].rstrip('/')
    for width, height in [(1280, 720), (390, 800)]:
        page.set_viewport_size({'width': width, 'height': height})
        for route, canvas, result in [('/', '#canvas', '#object-result'),
                                      ('/pixels', '#pixel-canvas', '#pixel-result')]:
            page.goto(base + route, wait_until='networkidle')
            box = page.locator(canvas).bounding_box()
            assert box and box['y'] <= height * .4, (route, width, height, box)
            assert min(box['y'] + box['height'], height) - box['y'] >= box['height'] / 3
            if route == '/pixels':
                for panel in ['#pixel-view-status', '#review-ai-jobs', '.pixel-vlm-feedback']:
                    bounds = page.locator(panel).bounding_box()
                    assert bounds and bounds['y'] >= box['y'] + box['height'], (panel, bounds, box)
            expect(page.locator(result)).to_contain_text('저장')
            assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
            if width == 390:
                actions = ['#prev-frame', '#next-frame', '#next-pending'] if route == '/' else ['#pixel-prev', '#pixel-next', '#pixel-undo']
                for action in actions:
                    expect(page.locator(f'{action} .ui-icon')).to_be_visible()
                    assert page.locator(action).get_attribute('aria-label')


@pytest.mark.parametrize('route', ['/learning', '/catalog', '/', '/pixels', '/learning/vlm', '/learning/evaluate'])
@pytest.mark.parametrize('width,height', [(390, 844), (320, 568)])
def test_learning_compact_header_stays_within_first_view_budget(browser_workspace, route, width, height):
    page, _, _ = browser_workspace
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(page.url.split('?')[0].rstrip('/') + route, wait_until='networkidle')
    topbar = page.locator('ui-topbar').bounding_box()
    assert topbar['height'] <= height * 0.2, (route, topbar, height)
    # D-741: the app bar is one row (app, theme); navigation stays in the rail.
    assert page.locator('ui-topbar h1, ui-topbar nav').count() == 0
    brand = page.locator('ui-topbar ui-brand').bounding_box()
    theme = page.locator('ui-topbar .theme-label select').bounding_box()
    assert brand['x'] + brand['width'] <= theme['x'], (route, brand, theme)
    rail = page.locator('.ui-rail').bounding_box()
    assert rail['y'] == topbar['y'] + topbar['height'], (route, rail, topbar)
    assert set(page.locator('.workspace-tabs a').evaluate_all('links => links.map(link => new URL(link.href).pathname)')) == {
        '/learning', '/catalog', '/', '/learning/tasks', '/learning/evaluate',
    }
    assert page.locator('.workspace-tabs a[aria-current="page"]').count() == 1
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
