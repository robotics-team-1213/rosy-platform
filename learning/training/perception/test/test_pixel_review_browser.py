"""Real browser pixel editing and approval guards on isolated synthetic originals."""
import os

import pytest

from test_review_flow_browser import browser_workspace
from test_review_cycle import CLASSES
import review_masks

pytestmark = pytest.mark.skipif(os.getenv('ROSY_RUN_BROWSER_TESTS') != '1',
                                reason='requires explicit local Chromium browser run')


def open_pixels(page, store, expect, index=0):
    review_masks.bind_classes(store, CLASSES)
    base = page.url.split('?')[0].rstrip('/')
    page.goto(base + f'/pixels?frame={index}', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v0')


@pytest.mark.parametrize('mode', ['manual', 'auto'])
def test_touch_flood_respects_explicit_tolerance_mode(browser_workspace, mode):
    original_page, store, expect = browser_workspace
    context = original_page.context.browser.new_context(
        has_touch=True, viewport={'width': 800, 'height': 1000})
    page = context.new_page()
    try:
        page.goto(original_page.url, wait_until='networkidle')
        open_pixels(page, store, expect)
        selector = page.locator('#pixel-tolerance-mode')
        expect(selector).to_have_value('auto')
        selector.select_option(mode)
        page.locator('#pixel-class').select_option('4')
        page.locator('#pixel-tolerance').fill('37')
        page.locator('#pixel-flood').click()
        with page.expect_request(lambda request: request.method == 'POST'
                                 and request.url.endswith('/api/masks/0')) as sent:
            page.locator('#pixel-canvas').tap(position={'x': 10, 'y': 10})
        payload = sent.value.post_data_json
        assert payload['action'] == 'flood'
        assert payload['label'] == 4 and payload['version'] == 0
        if mode == 'manual':
            assert payload['tolerance'] == 37
        else:
            assert 4 <= payload['tolerance'] <= 48
        expect(page.locator('#pixel-status')).to_contain_text('v1')
        review = review_masks.get(store, 0)
        assert review['version'] == 1 and review['status'] == 'pending'
        assert not review['complete'] and not review['background']
        expect(page.locator('#pixel-class')).to_have_value('4')
        expect(page.locator('#pixel-tolerance-mode')).to_have_value(mode)
    finally:
        context.close()


def test_unknown_pixels_cannot_be_approved_and_explicit_fill_persists(browser_workspace):
    page, store, expect = browser_workspace
    original = store.get(0)
    open_pixels(page, store, expect)
    expect(page.locator('#pixel-approve')).to_have_attribute('disabled', '')
    page.locator('#pixel-complete').check()
    expect(page.locator('#pixel-approve')).to_have_attribute('disabled', '')
    page.locator('#pixel-background').check()
    page.locator('#pixel-approve').click()
    expect(page.locator('#pixel-error')).to_contain_text('미검수')
    assert review_masks.get(store, 0)['version'] == 0
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    expect(page.locator('#pixel-complete')).not_to_be_checked()
    page.locator('#pixel-complete').check(); page.locator('#pixel-background').check()
    page.locator('#pixel-approve').click()
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 승인')
    assert store.get(0) == original
    page.reload(wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 승인')


def test_brush_cancellation_coordinates_and_undo(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-class').select_option('4')
    page.locator('#pixel-radius').fill('2')
    canvas = page.locator('#pixel-canvas')
    canvas.scroll_into_view_if_needed()
    r = canvas.bounding_box()
    def point(x, y):
        return r['x'] + x*r['width']/32, r['y'] + y*r['height']/24
    page.mouse.move(*point(10, 12)); page.mouse.down(); page.mouse.move(*point(15, 12))
    page.keyboard.press('Escape'); page.mouse.up()
    assert review_masks.get(store, 0)['version'] == 0
    page.mouse.move(*point(10, 12)); page.mouse.down(); page.mouse.move(*point(15, 12)); page.mouse.up()
    page.mouse.move(*point(20, 5)); page.mouse.down(); page.mouse.up()
    expect(page.locator('#pixel-draft')).to_contain_text('2획')
    expect(page.locator('#pixel-next')).to_have_attribute('disabled', '')
    assert review_masks.get(store, 0)['version'] == 0
    page.locator('#pixel-undo').click()
    expect(page.locator('#pixel-draft')).to_contain_text('1획')
    page.locator('#pixel-save').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    expect(page.locator('#pixel-draft')).to_have_text('')
    review = review_masks.get(store, 0)
    assert review_masks.pixels(store, review)[12, 10] == 4
    assert review_masks.pixels(store, review)[5, 20] == 255
    page.locator('#pixel-undo').click()
    expect(page.locator('#pixel-status')).to_contain_text('v2')
    assert review_masks.pixels(store, review_masks.get(store, 0))[12, 10] == 255


@pytest.mark.parametrize('width', [1440, 390])
def test_stale_pixel_revision_and_excluded_frame_are_guarded(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    open_pixels(page, store, expect)
    newer = review_masks.update(store, 0, {'version':0, 'action':'fill', 'label':2}, ValueError)
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-error')).to_contain_text('다른 탭')
    expect(page.locator('#pixel-approve')).to_have_attribute('disabled', '')
    assert review_masks.get(store, 0) == newer
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if width == 390:
        reload = page.locator('#pixel-reload').bounding_box()
        assert reload and reload['width'] >= width * .8 and reload['x'] + reload['width'] <= width
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        from pathlib import Path
        target = Path(output) / f'learning-pixels-conflict-{width}.png'
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
    page.locator('#pixel-reload').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.locator('#pixel-frame').select_option('1')
    expect(page.locator('#pixel-status')).to_contain_text('객체 제외')
    expect(page.locator('#pixel-fill')).to_have_attribute('disabled', '')
