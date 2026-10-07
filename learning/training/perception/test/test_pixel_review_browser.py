"""Real browser pixel editing and approval guards on isolated synthetic originals."""
import os

import pytest
from browser_harness import browser_tests_enabled
import numpy as np

from test_review_flow_browser import browser_workspace
from test_review_cycle import CLASSES
import review_masks

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason='requires explicit local Chromium browser run')


def open_pixels(page, store, expect, index=0):
    review_masks.bind_classes(store, CLASSES)
    base = page.url.split('?')[0].rstrip('/')
    page.goto(base + f'/pixels?frame={index}', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v0')


def test_new_draft_requires_explicit_apply_in_pixel_screen(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    source = store.get(0)['source']
    path, digest = review_masks.freeze(store, review_masks.encode(
        np.full((source['height'], source['width']), 1, np.uint8)))
    with store.connect() as db:
        db.execute('INSERT INTO pixel_drafts VALUES (?,?,?,?)', (0, digest, path, 'c' * 64))
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    button = page.locator('#pixel-apply-candidate')
    expect(button).to_be_visible()
    expect(button).to_be_enabled()
    page.once('dialog', lambda dialog: dialog.accept())
    button.click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    current = review_masks.get(store, 0)
    assert current['status'] == 'pending' and current['approval'] is None
    assert np.all(review_masks.pixels(store, current) == 1)


@pytest.mark.parametrize('mode', ['manual', 'auto'])
def test_touch_samples_preview_then_apply_with_explicit_tolerance(browser_workspace, mode):
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
        with page.expect_request(lambda request: request.method == 'POST'
                                 and request.url.endswith('/api/mask-preview/0')) as preview:
            page.locator('#pixel-canvas').tap(position={'x': 10, 'y': 10})
        assert preview.value.post_data_json['tolerance'] == (37 if mode == 'manual' else 'auto')
        expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')
        assert review_masks.get(store, 0)['version'] == 0
        with page.expect_request(lambda request: request.method == 'POST'
                                 and request.url.endswith('/api/masks/0')) as sent:
            page.locator('#pixel-sample-apply').click()
        payload = sent.value.post_data_json
        assert payload['action'] == 'sample'
        assert payload['label'] == 4 and payload['version'] == 0
        if mode == 'manual':
            assert payload['tolerance'] == 37
        else:
            assert 8 <= payload['tolerance'] <= 40
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


@pytest.mark.parametrize('width', [1440, 800, 390, 320])
def test_pixel_decision_and_preparation_result_are_visible(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    open_pixels(page, store, expect)
    if width <= 390:
        field_widths = page.evaluate("""() => ({
          available: document.querySelector('.pixel-layout > section').getBoundingClientRect().width,
          labels: [...document.querySelectorAll('.pixel-layout .ui-workspace-bar > label')]
            .filter(node => node.getClientRects().length)
            .map(node => node.getBoundingClientRect().width),
          fields: [...document.querySelectorAll('.pixel-layout .ui-workspace-bar .ui-field')]
            .filter(node => node.getClientRects().length)
            .map(node => node.getBoundingClientRect().width),
        })""")
        assert len(field_widths['labels']) >= 5 and len(field_widths['fields']) >= 5
        assert all(abs(value - field_widths['available']) <= 1
                   for value in field_widths['labels'] + field_widths['fields']), field_widths
    if width == 320:
        navigation = page.evaluate("""() => ['#pixel-prev', '#pixel-next']
          .map(selector => document.querySelector(selector).getBoundingClientRect().width)""")
        assert min(navigation) >= 100 and abs(navigation[0] - navigation[1]) <= 1, navigation
    def shot(state):
        if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
            from pathlib import Path
            target = Path(output) / f'learning-pixels-{state}-{width}.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(target), full_page=True)
    page.locator('#pixel-exclude').click()
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 제외')
    assert review_masks.get(store, 0)['status'] == 'excluded'
    shot('excluded')
    page.locator('#pixel-reopen').click()
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 검수 대기')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-status')).to_contain_text('v3')
    page.locator('#pixel-complete').check()
    page.locator('#pixel-background').check()
    page.locator('#pixel-approve').click()
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 승인')
    assert review_masks.get(store, 0)['status'] == 'approved'
    shot('approved')
    page.locator('#pixel-export').click()
    expect(page.locator('#pixel-export-result')).to_contain_text('픽셀 승인 1장 준비')
    expect(page.locator('#pixel-class-help')).to_contain_text('미검수 255는 클래스가 아닙니다')
    assert page.evaluate('document.documentElement.scrollWidth - innerWidth') == 0
    shot('decision-result')

def test_pixel_decision_advances_to_next_editable_pending(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.locator('#pixel-complete').check(); page.locator('#pixel-background').check()
    page.locator('#pixel-approve').click()
    # Photo 2 is object-excluded, so its pixels cannot be edited: stay on photo 1.
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 승인')
    expect(page.locator('#pixel-title')).to_contain_text('사진 1')
    store.update(1, {'version': store.get(1)['version'], 'action': 'reopen'})
    page.reload(wait_until='networkidle')
    page.locator('#pixel-reopen').click()
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 검수 대기')
    page.locator('#pixel-filter').select_option('pending')
    page.locator('#pixel-class').select_option('4')
    page.locator('#pixel-exclude').click()
    expect(page.locator('#pixel-title')).to_contain_text('사진 2')
    # The paint class carries over so the next stroke is not silently the first class.
    expect(page.locator('#pixel-class')).to_have_value('4')
    expect(page.locator('#pixel-filter')).to_have_value('pending')
    assert review_masks.get(store, 0)['status'] == 'excluded'


def test_brush_cancellation_coordinates_and_undo(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-class').select_option('4')
    page.locator('#pixel-flood').click()
    page.locator('#pixel-radius').fill('2')
    canvas = page.locator('#pixel-canvas')
    canvas.scroll_into_view_if_needed()
    def point(x, y):
        r = canvas.bounding_box()
        return r['x'] + x*r['width']/32, r['y'] + y*r['height']/24
    page.mouse.move(*point(10, 12)); page.mouse.down(); page.mouse.move(*point(15, 12))
    page.keyboard.press('Escape'); page.mouse.up()
    assert review_masks.get(store, 0)['version'] == 0
    page.mouse.move(*point(10, 12)); page.mouse.down(); page.mouse.move(*point(15, 12)); page.mouse.up()
    expect(page.locator('#pixel-draft')).to_contain_text('1획')
    r = canvas.bounding_box()
    canvas.click(position={'x': 20*r['width']/32, 'y': 5*r['height']/24})
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


@pytest.mark.parametrize('width', [1440, 800, 390])
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


def test_pixel_screen_shows_classes_yaml_display_names(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES.replace(
        b'name: lane_line,', 'name: lane_line, display: 왼쪽 차선,'.encode()))
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v0')
    expect(page.locator('#pixel-legend')).to_contain_text('왼쪽 차선')
    expect(page.locator('#pixel-class option').nth(1)).to_have_text('왼쪽 차선')
    expect(page.locator('#pixel-class option').first).to_have_text('배경')



def test_pixel_number_keys_pick_class_and_x_excludes(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-canvas').focus()
    page.keyboard.press('2')
    expect(page.locator('#pixel-class')).to_have_value('1')
    page.keyboard.press('a')
    page.wait_for_timeout(300)
    assert review_masks.get(store, 0)['status'] == 'pending'
    page.keyboard.press('x')
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 제외')
    assert review_masks.get(store, 0)['status'] == 'excluded'


def test_pixel_legend_shows_default_korean_names(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    expect(page.locator('#pixel-legend')).to_contain_text('배경')
    expect(page.locator('#pixel-legend')).to_contain_text('차선')
    expect(page.locator('#pixel-class option').first).to_have_text('배경')


def test_pixel_a_works_right_after_ticking_checks_and_x_only_on_pending(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.locator('#pixel-complete').check(); page.locator('#pixel-background').check()
    page.keyboard.press('a')
    expect(page.locator('#pixel-status')).to_contain_text('픽셀 승인')
    page.locator('#pixel-canvas').focus()
    page.keyboard.press('x')
    page.wait_for_timeout(300)
    assert review_masks.get(store, 0)['status'] == 'approved'
