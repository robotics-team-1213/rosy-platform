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
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    review = review_masks.get(store, 0)
    assert review_masks.pixels(store, review)[12, 10] == 4
    page.locator('#pixel-undo').click()
    expect(page.locator('#pixel-status')).to_contain_text('v2')
    assert review_masks.pixels(store, review_masks.get(store, 0))[12, 10] == 255


def test_stale_pixel_revision_and_excluded_frame_are_guarded(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    newer = review_masks.update(store, 0, {'version':0, 'action':'fill', 'label':2}, ValueError)
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-error')).to_contain_text('다른 탭')
    expect(page.locator('#pixel-approve')).to_have_attribute('disabled', '')
    assert review_masks.get(store, 0) == newer
    page.locator('#pixel-reload').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.locator('#pixel-frame').select_option('1')
    expect(page.locator('#pixel-status')).to_contain_text('객체 제외')
    expect(page.locator('#pixel-fill')).to_have_attribute('disabled', '')
