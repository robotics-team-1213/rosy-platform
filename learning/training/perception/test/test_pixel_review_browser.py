"""Real browser pixel editing and approval guards on isolated synthetic originals."""
import os

import pytest
from browser_harness import browser_tests_enabled
import numpy as np

from test_review_flow_browser import browser_workspace, serve
from test_review_app import bright_store
from test_review_cycle import CLASSES
import review_masks

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason='requires explicit local Chromium browser run')


def open_pixels(page, store, expect, index=0):
    review_masks.bind_classes(store, CLASSES)
    base = page.url.split('?')[0].rstrip('/')
    page.goto(base + f'/pixels?frame={index}', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v0')


def test_detail_view_and_mask_toggle_do_not_change_review(tmp_path):
    with serve(bright_store(tmp_path)) as (page, store, expect):
        open_pixels(page, store, expect)
        before = store.image(0).read_bytes()
        mask = review_masks.get(store, 0)
        page.locator('#pixel-mask-visible').uncheck()
        pixel = lambda: page.evaluate("""() => Array.from(document.querySelector('#pixel-canvas')
            .getContext('2d').getImageData(16, 12, 1, 1).data)""")
        original = pixel()
        page.locator('#pixel-view-detail').click()
        expect(page.locator('#pixel-view-status')).to_contain_text('명암 보정 보기')
        assert pixel() != original
        page.keyboard.press('v')
        expect(page.locator('#pixel-view-original')).to_have_attribute('aria-pressed', 'true')
        assert pixel() == original
        page.locator('#pixel-mask-visible').check()
        assert pixel() != original
        assert store.image(0).read_bytes() == before
        assert review_masks.get(store, 0)['version'] == mask['version']
        page.goto(page.url.split('/pixels')[0] + '/?frame=0', wait_until='networkidle')
        page.locator('#view-detail').click()
        expect(page.locator('#view-status')).to_contain_text('명암 보정 보기')
        assert store.get(0)['version'] == 1


def test_unknown_highlight_is_visual_only(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    y, x = np.argwhere(review_masks.pixels(store, review_masks.get(store, 0)) == 255)[0]
    pixel = lambda: page.evaluate("""([x, y]) => Array.from(document.querySelector('#pixel-canvas')
        .getContext('2d').getImageData(x, y, 1, 1).data)""", [int(x), int(y)])
    highlight = page.locator('#pixel-show-unknown')
    expect(highlight).to_be_checked()
    marked = pixel()
    highlight.uncheck()
    assert pixel() != marked
    assert review_masks.get(store, 0)['version'] == 0


def test_sparse_unknown_pixels_are_visible_and_never_shown_as_zero_percent(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    filled = review_masks.update(store, 0, {'version': 0, 'action': 'fill', 'label': 0}, ValueError)
    review_masks.update(store, 0, {'version': filled['version'], 'action': 'paint',
                                   'label': 255, 'radius': 0, 'points': [[10, 10]]}, ValueError)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    expect(page.locator('#pixel-coverage')).to_contain_text('(<1%)')
    sample = lambda: page.evaluate("""() => Array.from(document.querySelector('#pixel-canvas')
        .getContext('2d').getImageData(10, 10, 1, 1).data)""")
    highlighted = sample()
    page.locator('#pixel-show-unknown').uncheck()
    assert sample() != highlighted
    expect(page.locator('#pixel-approve')).to_be_disabled()


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
    expect(page.locator('#pixel-approve')).to_be_disabled()
    expect(page.locator('#pixel-approval-hint')).to_contain_text('미검수')
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
    assert page.locator('#pixel-approve').bounding_box()['y'] < page.locator('#pixel-class-help').bounding_box()['y']
    if width <= 390:
        field_widths = page.evaluate("""() => ({
          available: document.querySelector('.pixel-editor-column > section').getBoundingClientRect().width,
          labels: [...document.querySelectorAll('.pixel-layout .ui-workspace-bar > label, .pixel-quick-tools > label')]
            .filter(node => node.getClientRects().length)
            .map(node => node.getBoundingClientRect().width),
          fields: [...document.querySelectorAll('.pixel-layout .ui-workspace-bar .ui-field, .pixel-quick-tools > label .ui-field')]
            .filter(node => node.getClientRects().length)
            .map(node => node.getBoundingClientRect().width),
        })""")
        assert len(field_widths['labels']) >= 3 and len(field_widths['fields']) >= 3
        assert all(value <= field_widths['available'] for value in field_widths['labels']), field_widths
        assert all(abs(label-field) <= 1 for label, field in zip(field_widths['labels'], field_widths['fields'])), field_widths
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
    expect(page.locator('#pixel-class-help')).to_contain_text('255는 클래스가 아닙니다')
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
    page.locator('#pixel-brush-tool').click()
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


def test_zoom_pan_never_paints_and_brush_uses_zoomed_coordinates(browser_workspace):
    page, store, expect = browser_workspace
    object_tools = page.locator('.review-editor-tools').bounding_box()
    object_canvas = page.locator('#canvas').bounding_box()
    object_decision = page.locator('.label-inspector').bounding_box()
    open_pixels(page, store, expect)
    pixel_tools = page.locator('.pixel-quick-tools').bounding_box()
    pixel_canvas = page.locator('#pixel-canvas').bounding_box()
    pixel_decision = page.locator('.pixel-review-column').bounding_box()
    assert object_tools['x'] < object_canvas['x'] < object_decision['x']
    assert pixel_tools['x'] < pixel_canvas['x'] < pixel_decision['x']
    assert abs(object_tools['x']-pixel_tools['x']) <= 1
    page.locator('#pixel-class').select_option('4')
    page.locator('#pixel-brush-tool').click()
    stage = page.locator('.pixel-stage')
    canvas = page.locator('#pixel-canvas')
    original_width = canvas.bounding_box()['width']
    page.locator('.review-viewport-controls [aria-label^="확대"]').click()
    expect(page.locator('.review-zoom-level')).to_have_text('150%')
    assert canvas.bounding_box()['width'] > original_width
    page.locator('.review-viewport-controls [aria-label^="이동"]').click()
    box = stage.bounding_box()
    start = (box['x'] + box['width']/2, box['y'] + box['height']/2)
    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(start[0] - 100, start[1] - 40, steps=4)
    page.mouse.up()
    assert stage.evaluate('(node) => node.scrollLeft') > 0
    assert review_masks.get(store, 0)['version'] == 0
    expect(page.locator('#pixel-draft')).to_have_text('')
    expect(page.locator('.pixel-save-panel')).to_be_hidden()
    page.locator('.review-viewport-controls [aria-label^="이동"]').click()
    image = canvas.bounding_box()
    canvas.click(position={'x': image['width']/2, 'y': image['height']/2})
    expect(page.locator('.pixel-save-panel')).to_be_visible()
    page.locator('#pixel-save').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    expect(page.locator('.pixel-save-panel')).to_be_hidden()
    changed = np.argwhere(review_masks.pixels(store, review_masks.get(store, 0)) == 4)
    assert any(abs(y-12) <= 1 and abs(x-16) <= 1 for y, x in changed), changed.tolist()


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
    expect(page.locator('#pixel-class option[value="1"]')).to_have_text('왼쪽 차선')
    expect(page.locator('#pixel-class option[value="0"]')).to_have_text('배경')



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


def test_pixel_shortcuts_confirm_both_checks_and_move_without_approving(browser_workspace):
    page, store, expect = browser_workspace
    row = store.get(1)
    store.update(1, {'version': row['version'], 'action': 'reopen'})
    open_pixels(page, store, expect)
    page.locator('#pixel-canvas').focus()
    page.keyboard.press('c')
    page.keyboard.press('b')
    expect(page.locator('#pixel-complete')).to_be_checked()
    expect(page.locator('#pixel-background')).to_be_checked()
    assert review_masks.get(store, 0)['status'] == 'pending'
    page.keyboard.press('a')
    expect(page.locator('#pixel-approve')).to_be_disabled()
    expect(page.locator('#pixel-approval-hint')).to_contain_text('미검수')
    assert review_masks.get(store, 0)['status'] == 'pending'
    page.keyboard.press('n')
    expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
    assert review_masks.get(store, 0)['status'] == 'pending'


def test_pixel_photo_picker_returns_to_canvas_and_quick_tools(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.set_viewport_size({'width': 1280, 'height': 800})
    canvas = page.locator('#pixel-canvas').bounding_box()
    tools = page.locator('.pixel-quick-tools').bounding_box()
    assert abs(canvas['x'] - tools['x']) < 32 and tools['y'] < canvas['y']
    assert page.locator('#pixel-prev').bounding_box()['y'] < canvas['y']
    assert page.locator('#pixel-undo').bounding_box()['y'] < canvas['y']
    page.locator('#pixel-frame').select_option('1')
    expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
    expect(page.locator('#pixel-canvas')).to_be_focused()
    page.keyboard.press('ArrowLeft')
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
    page.locator('#pixel-quick-classes button').nth(1).click()
    expect(page.locator('#pixel-class')).to_have_value('1')
    expect(page.locator('#pixel-canvas')).to_be_focused()
    page.keyboard.press('t')
    expect(page.locator('#pixel-flood')).to_have_attribute('aria-pressed', 'false')
    page.keyboard.press('t')
    expect(page.locator('#pixel-flood')).to_have_attribute('aria-pressed', 'true')
    page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
    expect(page.locator('#pixel-sample-apply')).to_be_enabled()
    page.locator('#pixel-canvas').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.set_viewport_size({'width': 390, 'height': 800})
    assert page.locator('.pixel-quick-tools').bounding_box()['y'] < page.locator('#pixel-canvas').bounding_box()['y']
    assert review_masks.get(store, 0)['version'] == 1


def test_pixel_thumbnails_and_unknown_background_draft(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    thumbs = page.locator('#pixel-frames .pixel-frame-item')
    expect(thumbs).to_have_count(2)
    expect(thumbs.nth(0).locator('img')).to_have_attribute('loading', 'lazy')
    thumbs.nth(1).click()
    expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
    thumbs.nth(0).click()
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#pixel-fill-unknown').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    assert review_masks.get(store, 0)['status'] == 'pending'
    assert not np.any(review_masks.pixels(store, review_masks.get(store, 0)) == 255)
    expect(page.locator('#pixel-approve')).to_be_disabled()


def test_polygon_tool_previews_saves_and_undoes(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-class').select_option('4')
    canvas = page.locator('#pixel-canvas')
    canvas.focus()
    page.keyboard.press('p')
    expect(page.locator('#pixel-polygon-tool')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#pixel-polygon-tool .ui-icon')).to_have_count(1)
    box = canvas.bounding_box()
    for x, y in [(5, 5), (20, 5), (20, 18), (5, 18)]:
        canvas.click(position={'x': x * box['width'] / 32,
                               'y': y * box['height'] / 24})
    expect(page.locator('#pixel-draft')).to_contain_text('4개')
    assert review_masks.get(store, 0)['version'] == 0
    expect(page.locator('#pixel-next')).to_be_disabled()
    canvas.focus(); page.keyboard.press('Backspace')
    expect(page.locator('#pixel-draft')).to_contain_text('3개')
    canvas.focus(); page.keyboard.press('Enter')
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    mask = review_masks.pixels(store, review_masks.get(store, 0))
    assert mask[8, 15] == 4 and mask[1, 1] == 255
    expect(page.locator('#pixel-approve')).to_be_disabled()
    page.locator('#pixel-undo').click()
    expect(page.locator('#pixel-status')).to_contain_text('v2')
    assert review_masks.pixels(store, review_masks.get(store, 0))[8, 15] == 255
    page.locator('#pixel-brush-tool').click()
    page.locator('#pixel-radius').fill('0')
    canvas.focus(); page.keyboard.press(']')
    expect(page.locator('#pixel-radius')).to_have_value('1')
    page.keyboard.press('[')
    expect(page.locator('#pixel-radius')).to_have_value('0')
    box = canvas.bounding_box()
    canvas.click(position={'x': 8 * box['width'] / 32,
                           'y': 9 * box['height'] / 24})
    page.locator('#pixel-save').click()
    expect(page.locator('#pixel-status')).to_contain_text('v3')
    assert np.count_nonzero(review_masks.pixels(store, review_masks.get(store, 0)) != 255) == 1


def test_pixel_legend_shows_default_korean_names(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    expect(page.locator('#pixel-legend')).to_contain_text('배경')
    expect(page.locator('#pixel-legend')).to_contain_text('차선')
    expect(page.locator('#pixel-class option[value="0"]')).to_have_text('배경')


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
