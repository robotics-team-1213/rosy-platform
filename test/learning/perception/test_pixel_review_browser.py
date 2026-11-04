"""Real browser pixel editing and approval guards on isolated synthetic originals."""
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
import numpy as np

from test_review_flow_browser import browser_workspace, serve
from test_review_app import bright_store, open_store
from test_review_cycle import CLASSES
import review_masks

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason='requires explicit local Chromium browser run')


def test_pixel_multiple_lane_classes_require_explicit_choice(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES.replace(b'name: lane_line', b'name: left_lane'))
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels', wait_until='networkidle')
    expect(page.locator('#pixel-class')).to_have_value('')
    expect(page.locator('#pixel-fill')).to_be_disabled()
    page.locator('#pixel-canvas').click(position={'x': 8, 'y': 8})
    expect(page.locator('#pixel-draft')).to_contain_text('클래스를 선택')
    page.locator('#pixel-class').select_option('1')
    expect(page.locator('#pixel-fill')).to_be_enabled()
    page.locator('#pixel-canvas').click(position={'x': 8, 'y': 8})
    expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')


@pytest.mark.parametrize('width,height', [(1366, 768), (1920, 1080), (768, 900), (390, 844)])
def test_pixel_workspace_has_stable_canvas_tools_and_one_inspector(browser_workspace, width, height):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': height})
    open_pixels(page, store, expect, panels=False)
    for selector in ['#pixel-class', '#pixel-coverage', '#pixel-result', '#pixel-complete', '#pixel-approve']:
        expect(page.locator('.pixel-review-column ' + selector)).to_have_count(1)
    expect(page.locator('#pixel-tool-rail #pixel-brush-tool')).to_have_count(1)
    expect(page.locator('#pixel-tool-options #pixel-radius')).to_have_count(1)
    expect(page.locator('#pixel-viewport-controls .review-viewport-controls')).to_have_count(1)
    canvas = page.locator('#pixel-canvas').bounding_box()
    tools = page.locator('#pixel-tool-rail').bounding_box()
    inspector = page.locator('.pixel-review-column').bounding_box()
    if width >= 1024:
        assert tools['x'] + tools['width'] <= canvas['x'] + 1
        assert inspector['x'] >= canvas['x'] + canvas['width'] - 1
    else:
        assert inspector['y'] >= canvas['y'] + canvas['height'] - 1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_selected_pixel_tool_options_stay_above_canvas_without_other_tool_settings(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect, panels=False)
    page.locator('#pixel-brush-tool').click()
    expect(page.locator('#pixel-tool-options #pixel-radius')).to_be_visible()
    expect(page.locator('#pixel-tolerance-mode')).to_be_hidden()
    expect(page.locator('#pixel-sample-apply')).to_be_hidden()
    options = page.locator('#pixel-tool-options').bounding_box()
    canvas = page.locator('#pixel-canvas').bounding_box()
    assert options['y'] + options['height'] <= canvas['y'] + 1
    page.locator('#pixel-flood').click()
    expect(page.locator('#pixel-radius')).to_be_hidden()
    expect(page.locator('#pixel-tolerance-mode')).to_be_visible()
    expect(page.locator('#pixel-sample-apply')).to_be_visible()


@pytest.mark.parametrize('status,reason', [(403, '권한'), (503, '서비스')])
def test_pixel_workspace_failure_reason_stays_visible_when_editor_is_hidden(browser_workspace, status, reason):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect, panels=False)
    page.route('**/api/workspace*', lambda route: route.fulfill(status=status, json={'error': 'fixture unavailable'}))
    page.locator('#pixel-reload').click()
    expect(page.locator('#pixel-content')).to_be_hidden()
    expect(page.locator('#pixel-error')).to_be_visible()
    expect(page.locator('#pixel-error')).to_contain_text(reason)
    expect(page.locator('#pixel-reload')).to_be_enabled()


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_pixel_decision_resize_preserves_checks_and_keyboard_focus(browser_workspace, theme):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.evaluate("theme => RosyTheme.set(theme)", theme)
    complete, background = page.locator('#pixel-complete'), page.locator('#pixel-background')
    complete.check()
    background.check()
    complete.focus()
    approve_disabled = page.locator('#pixel-approve').is_disabled()
    for step, width in enumerate((390, 1440, 320, 1440)):
        page.set_viewport_size({'width': width, 'height': 844})
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(complete).to_be_focused()
        expect(complete).to_be_checked()
        expect(background).to_be_checked()
        assert page.locator('#pixel-approve').is_disabled() == approve_disabled
        assert page.locator('.pixel-decision-panel:has(#pixel-complete)').count() == 1
        decision = page.locator('.pixel-decision-panel:has(#pixel-complete)').bounding_box()
        if width < 1024:
            canvas = page.locator('#pixel-canvas').bounding_box()
            assert decision['y'] >= canvas['y'] + canvas['height'] - 1
            assert page.locator('.pixel-review-column .pixel-decision-panel').count() == 1
        else:
            canvas = page.locator('#pixel-canvas').bounding_box()
            assert decision['x'] >= canvas['x'] + canvas['width'] - 1
        box = complete.bounding_box()
        header = page.locator('ui-topbar').bounding_box()
        assert max(0, header['y'] + header['height']) - 1 <= box['y']
        assert box['y'] + box['height'] <= 845
        if width >= 1024:
            tools = page.locator('#pixel-tool-rail').bounding_box()
            assert tools['y'] >= header['y'] + header['height'] - 1
            assert page.locator('#pixel-next').evaluate('''node => {
                const r = node.getBoundingClientRect();
                return node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
            }''')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            name = f'pixel-decision-{theme}-{step}-{width}'
            page.screenshot(path=str(target / f'{name}-viewport.png'))
            page.screenshot(path=str(target / f'{name}-workspace.png'), full_page=True)
        hit = complete.evaluate('''node => {
            const r = node.getBoundingClientRect();
            const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return {visible: node.contains(hit), hit: hit?.outerHTML.slice(0, 300),
                box: r.toJSON(), scroll: window.scrollY};
        }''')
        assert hit['visible'], hit


def open_pixels(page, store, expect, index=0, *, panels=True):
    review_masks.bind_classes(store, CLASSES)
    base = page.url.split('?')[0].rstrip('/')
    page.goto(base + f'/pixels?frame={index}', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v0')
    if panels:
        for control in ['#pixel-opacity', '#pixel-quick-classes', '#pixel-candidates', '#pixel-fill', '#pixel-tool-hint', '#pixel-class-help', '#pixel-frames', '#pixel-export']:
            details = page.locator(control).locator('xpath=ancestor::details[1]')
            if details.count() and details.is_visible() and details.get_attribute('open') is None:
                details.locator(':scope > summary').click()






@pytest.mark.parametrize('width', [1440, 390])
def test_unknown_fill_selected_class_preserves_other_labels_and_undo(browser_workspace, width):
    from review_app import Conflict
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    open_pixels(page, store, expect)
    review_masks.update(store, 0, {'version': 0, 'action': 'paint', 'label': 2,
                                  'radius': 0, 'points': [[2, 2]]}, Conflict)
    page.locator('#pixel-reload').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    before = review_masks.pixels(store, review_masks.get(store, 0)).copy()
    button = page.locator('#pixel-fill-unknown-class')
    expect(button).to_have_text('남은 미검수 선택 클래스로 채우기')
    page.locator('#pixel-class').select_option('255')
    expect(button).to_be_disabled()
    page.locator('#pixel-class').select_option('3')
    expect(button).to_be_enabled()
    page.once('dialog', lambda dialog: dialog.accept())
    button.click()
    expect(page.locator('#pixel-status')).to_contain_text('v2')
    after = review_masks.pixels(store, review_masks.get(store, 0))
    assert after[2, 2] == 2 and np.all(after[before == 255] == 3)
    assert review_masks.get(store, 0)['status'] == 'pending'
    expect(page.locator('#pixel-approve')).to_be_disabled()
    page.locator('#pixel-complete').check()
    page.locator('#pixel-background').check()
    expect(page.locator('#pixel-approve')).to_be_enabled()
    page.locator('#pixel-undo').click()
    expect(page.locator('#pixel-status')).to_contain_text('v3')
    assert np.array_equal(review_masks.pixels(store, review_masks.get(store, 0)), before)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [1440, 390])
def test_protected_point_selection_background_completion_and_visible_shortcuts(browser_workspace, width):
    from review_app import Conflict
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    open_pixels(page, store, expect)
    review_masks.update(store, 0, {'version': 0, 'action': 'paint', 'label': 2,
                                  'radius': 0, 'points': [[2, 2]]}, Conflict)
    page.locator('#pixel-reload').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    expect(page.locator('#pixel-preserve')).to_be_checked()
    expect(page.locator('#pixel-keys')).to_contain_text('Ctrl+Z')
    expect(page.locator('#pixel-keys')).to_contain_text('Esc')
    expect(page.locator('#pixel-keys')).to_contain_text('Enter')
    expect(page.locator('#pixel-undo')).to_contain_text('Ctrl+Z')
    page.locator('#pixel-class').select_option('3')
    canvas = page.locator('#pixel-canvas')
    canvas.click(position={'x': 10, 'y': 10})
    expect(page.locator('#pixel-draft')).to_contain_text('767픽셀 미리보기')
    expect(page.locator('#pixel-draft')).to_contain_text('허용치')
    page.locator('#pixel-sample-apply').click()
    expect(page.locator('#pixel-status')).to_contain_text('v2')
    marked = review_masks.pixels(store, review_masks.get(store, 0))
    assert marked[2, 2] == 2 and marked[10, 10] == 3
    canvas.focus()
    page.keyboard.press('Control+z')
    expect(page.locator('#pixel-status')).to_contain_text('v3')
    before = review_masks.pixels(store, review_masks.get(store, 0)).copy()
    finish = page.locator('#pixel-fill-unknown')
    expect(finish).to_have_text('나머지 배경으로 채우기')
    expect(finish).to_have_attribute('kind', 'quiet')
    page.once('dialog', lambda dialog: dialog.accept())
    finish.click()
    expect(page.locator('#pixel-status')).to_contain_text('v4')
    after = review_masks.pixels(store, review_masks.get(store, 0))
    assert np.array_equal(after[before != 255], before[before != 255])
    assert np.all(after[before == 255] == 0)
    assert review_masks.get(store, 0)['status'] == 'pending'
    expect(page.locator('#pixel-approve')).to_be_disabled()
    page.locator('#pixel-complete').check()
    page.locator('#pixel-background').check()
    expect(page.locator('#pixel-approve')).to_be_enabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / f'pixel-protected-background-{width}.png'), full_page=True)
    canvas.focus()
    page.keyboard.press('Control+z')
    expect(page.locator('#pixel-status')).to_contain_text('v5')
    assert np.array_equal(review_masks.pixels(store, review_masks.get(store, 0)), before)
    page.locator('#pixel-preserve').uncheck()
    canvas.click(position={'x': 10, 'y': 10})
    expect(page.locator('#pixel-draft')).to_contain_text('768픽셀 미리보기')
    page.locator('#pixel-sample-apply').click()
    expect(page.locator('#pixel-status')).to_contain_text('v6')
    assert np.all(review_masks.pixels(store, review_masks.get(store, 0)) == 3)


@pytest.mark.parametrize('width', [320, 390, 768, 1440])
@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('view', ['object', 'pixel'])
@pytest.mark.parametrize('key', ['Enter', 'Space'])
def test_class_choices_use_shared_controls_and_keep_keyboard_editing(browser_workspace, width, theme, view, key):
    page, store, expect = browser_workspace
    if view == 'pixel':
        open_pixels(page, store, expect)
    page.set_viewport_size({'width': width, 'height': 900})
    page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
    choices = page.locator(f'#{view}-quick-classes .review-class-chip')
    chip = choices.nth(2) if view == 'pixel' else page.locator('#object-quick-classes .review-class-chip[value="obstacle_box"]')
    expect(chip).to_have_attribute('kind', 'segment')
    assert chip.evaluate('el => el.tagName') == 'UI-BUTTON'
    assert chip.bounding_box()['height'] >= 48
    if view == 'object':
        expect(chip).to_be_disabled()
        page.get_by_role('button', name='박스 1 선택', exact=True).click()
    expect(chip).to_be_enabled()
    value = chip.get_attribute('value')
    if view == 'pixel':
        expect(page.locator('#pixel-class')).not_to_have_value(value)
    chip.focus()
    chip.press(key)
    expect(chip).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#pixel-canvas' if view == 'pixel' else '#canvas')).to_be_focused()
    if view == 'pixel':
        expect(page.locator('#pixel-class')).to_have_value(value)
        assert review_masks.get(store, 0)['version'] == 0
    else:
        expect(page.locator('#save-status')).to_contain_text('서버 저장됨')
        assert store.get(0)['review']['boxes'][0]['label'] == value == 'obstacle_box'
        assert store.get(0)['status'] == 'pending'
        expect(page.locator('#approve')).to_be_disabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    if os.environ.get('ROSY_UI_CAPTURE_DIR') and key == 'Enter':
        destination = Path(os.environ['ROSY_UI_CAPTURE_DIR'])
        destination.mkdir(parents=True, exist_ok=True)
        page.locator(f'#{view}-quick-classes').scroll_into_view_if_needed()
        page.screenshot(path=str(destination / f'class-controls-{view}-{theme}-{width}.png'))


def test_ai_context_is_cleared_on_empty_filter_and_reload_failure(browser_workspace):
    page, store, expect = browser_workspace
    opinion = {'available': True, 'current': True, 'model': 'fixture-ai',
               'model_digest': 'fixture-version', 'unknown_pixels': 0,
               'review_blocked': False,
               'feedback': {'verdict': 'uncertain', 'issue': 'uncertain_visibility', 'note': 'fixture'}}
    page.route('**/api/vlm-feedback/*', lambda route: route.fulfill(json=opinion))
    open_pixels(page, store, expect)
    expect(page.locator('#pixel-vlm-state')).to_have_text('AI 판단 보류')
    expect(page.locator('#pixel-vlm-state')).to_have_attribute('state', 'warning')
    page.locator('#pixel-filter').select_option('approved')
    expect(page.locator('.pixel-vlm-feedback')).to_be_hidden()
    expect(page.locator('#review-people-summary')).to_contain_text('확인할 수 없습니다')
    page.locator('#pixel-all').click()
    expect(page.locator('#pixel-vlm-state')).to_have_text('AI 판단 보류')
    page.route('**/api/workspace*', lambda route: route.fulfill(status=503, json={'error': 'unavailable'}))
    page.locator('#pixel-reload').click()
    expect(page.locator('.pixel-vlm-feedback')).to_be_hidden()
    expect(page.locator('#pixel-error')).to_be_visible()
    expect(page.locator('#pixel-error')).to_contain_text('사용할 수 없습니다')
    expect(page.locator('#pixel-status')).to_contain_text('사용할 수 없습니다')
    expect(page.locator('#review-people-summary')).to_contain_text('확인할 수 없습니다')


def test_keyboard_pixel_cursor_samples_without_changing_photo(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-class').select_option('1')
    page.locator('#pixel-canvas').focus()
    page.keyboard.press('Alt+ArrowRight')
    expect(page.locator('#pixel-keyboard-position')).to_contain_text('17, 12')
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
    page.keyboard.press('Space')
    expect(page.locator('#pixel-draft')).to_contain_text('1점 선택')
    assert review_masks.get(store, 0)['version'] == 0
    expect(page.locator('#pixel-sample-apply')).to_be_enabled()
    page.keyboard.press('Enter')
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    assert np.any(review_masks.pixels(store, review_masks.get(store, 0)) == 1)


def test_keyboard_pixel_brush_saves_source_coordinates_and_cancels(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-class').select_option('4')
    page.locator('#pixel-canvas').focus(); page.keyboard.press('t')
    page.locator('#pixel-radius').fill('0')
    page.locator('#pixel-canvas').focus()
    page.keyboard.down('Space')
    page.keyboard.press('Alt+ArrowRight')
    page.keyboard.up('Space')
    expect(page.locator('#pixel-draft')).to_contain_text('1획')
    assert review_masks.get(store, 0)['version'] == 0
    page.keyboard.press('Control+s')
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    pixels = review_masks.pixels(store, review_masks.get(store, 0))
    assert pixels[12, 16] == pixels[12, 17] == 4
    page.locator('#pixel-canvas').focus()
    page.keyboard.down('Space'); page.keyboard.press('Alt+ArrowUp')
    page.keyboard.press('Escape'); page.keyboard.up('Space')
    expect(page.locator('#pixel-draft')).to_have_text('')
    assert review_masks.get(store, 0)['version'] == 1


def test_keyboard_pixel_polygon_uses_same_apply_and_undo(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-class').select_option('1')
    page.locator('#pixel-canvas').focus()
    page.keyboard.press('p')
    page.keyboard.press('Space')
    page.keyboard.press('Alt+Shift+ArrowRight'); page.keyboard.press('Space')
    page.keyboard.press('Alt+Shift+ArrowUp'); page.keyboard.press('Space')
    expect(page.locator('#pixel-draft')).to_contain_text('3개')
    page.keyboard.press('Enter')
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    page.keyboard.press('Control+z')
    expect(page.locator('#pixel-status')).to_contain_text('v2')
    assert np.all(review_masks.pixels(store, review_masks.get(store, 0)) == 255)


def test_keyboard_pixel_cursor_is_bounded_and_pan_never_paints(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    canvas = page.locator('#pixel-canvas'); canvas.focus()
    for _ in range(5):
        page.keyboard.press('Alt+Shift+ArrowRight'); page.keyboard.press('Alt+Shift+ArrowDown')
    expect(page.locator('#pixel-keyboard-position')).to_contain_text('31, 23')
    before = page.locator('#pixel-draft').inner_text()
    page.keyboard.press('h')
    page.keyboard.press('Alt+ArrowLeft'); page.keyboard.press('Space')
    expect(page.locator('#pixel-draft')).to_have_text(before)
    expect(page.locator('#pixel-sample-apply')).to_be_disabled()
    assert review_masks.get(store, 0)['version'] == 0


def test_command_search_preserves_fill_confirmation_and_reaches_ai_notes(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-class').select_option('1')
    page.keyboard.press('Control+k')
    page.get_by_role('textbox', name='기능 검색어').fill('선택 클래스로 전체 채우기')
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.keyboard.press('Enter')
    assert review_masks.get(store, 0)['version'] == 0
    page.keyboard.press('Control+k')
    page.get_by_role('textbox', name='기능 검색어').fill('AI 참고 의견')
    page.keyboard.press('Enter')
    expect(page.locator('.pixel-vlm-feedback')).to_have_attribute('open', '')
    expect(page.locator('.pixel-vlm-feedback > summary')).to_be_focused()
    assert review_masks.get(store, 0)['version'] == 0


@pytest.mark.parametrize('width', [1440, 1262, 390, 320])
def test_pixel_tools_are_readable_and_reachable_beside_photo(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 900})
    open_pixels(page, store, expect)
    page.locator('#pixel-quick-classes ui-button').nth(1).click()
    actions = page.locator('#pixel-tool-rail')
    if width >= 1024:
        assert actions.evaluate('el => el.scrollWidth <= el.clientWidth')
    for button in actions.locator('ui-button').all():
        expect(button.locator('span:not(.ui-icon)')).to_be_visible()
        button.scroll_into_view_if_needed()
        assert button.evaluate('''el => {
            const r = el.getBoundingClientRect();
            return el.contains(document.elementFromPoint(r.right - 4, r.y + r.height / 2));
        }''')
    if width < 1024:
        stage = page.locator('.pixel-stage').bounding_box()
        tools = actions.bounding_box()
        assert tools['y'] + tools['height'] <= stage['y'] + 1
    page.set_viewport_size({'width': 1440, 'height': 900})
    assert actions.bounding_box()['x'] < page.locator('#pixel-canvas').bounding_box()['x']


def test_review_workspace_purpose_stays_visible_on_photo_change(tmp_path):
    store = open_store(tmp_path)
    with serve(store) as (page, _, expect):
        open_pixels(page, store, expect)
        expect(page.locator('#pixel-workspace-mode')).to_contain_text('학습 후보')
        expect(page.locator('#pixel-view-status')).to_contain_text('학습 후보')
        page.locator('#pixel-next').click()
        expect(page.locator('#pixel-view-status')).to_contain_text('학습 후보')
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata (key,value) VALUES ('workspace_kind','evaluation')")
    with serve(store) as (page, _, expect):
        open_pixels(page, store, expect)
        expect(page.locator('#pixel-workspace-mode')).to_contain_text('고정 평가')
        expect(page.locator('#pixel-view-status')).to_contain_text('학습 제외')
        expect(page.locator('#pixel-preparation')).to_be_hidden()


def test_short_desktop_view_keeps_entire_photo_in_view(browser_workspace):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': 1262, 'height': 632})
    open_pixels(page, store, expect)
    canvas = page.locator('#pixel-canvas').bounding_box()
    assert canvas and canvas['y'] + canvas['height'] <= 632
    ratio = page.locator('#pixel-canvas').evaluate('node => node.width / node.height')
    assert abs(canvas['width'] / canvas['height'] - ratio) < .001
    source = store.get(0)['source']
    assert abs(ratio - source['width'] / source['height']) < .001


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
    page.locator('#pixel-display-options > summary').click()
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
        db.execute('INSERT INTO pixel_drafts (frame,sha256,path,catalog_sha256,origin) VALUES (?,?,?,?,?)',
                   (0, digest, path, 'c' * 64, 'sam3_obstacle_unknown_v12_base'))
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    button = page.locator('#pixel-apply-candidate')
    button.locator('xpath=ancestor::details[1]').locator(':scope > summary').click()
    expect(button).to_be_visible()
    expect(page.locator('#pixel-candidates')).to_contain_text('SAM3 장애물 보류 · 사람 확인 필요')
    expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'true')
    canvas_pixel = lambda: page.evaluate("""() => Array.from(document.querySelector('#pixel-canvas')
        .getContext('2d').getImageData(10, 10, 1, 1).data)""")
    proposed = canvas_pixel()
    page.locator('#pixel-preview-candidate').click()
    expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'false')
    assert canvas_pixel() != proposed
    assert review_masks.get(store, 0)['version'] == 0
    page.locator('#pixel-preview-candidate').click()
    expect(button).to_be_enabled()
    page.once('dialog', lambda dialog: dialog.accept())
    button.click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    current = review_masks.get(store, 0)
    assert current['status'] == 'pending' and current['approval'] is None
    assert np.all(review_masks.pixels(store, current) == 1)


def test_ai_proposal_and_brush_correction_save_together_without_replacing_human_labels(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'paint', 'label': 4,
                                  'radius': 0, 'points': [[0, 0]]}, ValueError)
    source = store.get(0)['source']
    path, digest = review_masks.freeze(store, review_masks.encode(
        np.full((source['height'], source['width']), 1, np.uint8)))
    with store.connect() as db:
        db.execute('INSERT INTO pixel_drafts (frame,sha256,path,catalog_sha256,origin) VALUES (?,?,?,?,?)',
                   (0, digest, path, 'c' * 64, 'sam3_obstacle_unknown_v12_base'))
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'true')
    assert review_masks.get(store, 0)['version'] == 1
    page.locator('#pixel-class').select_option('2')
    page.locator('#pixel-brush-tool').click()
    page.locator('#pixel-radius').fill('0')
    canvas = page.locator('#pixel-canvas')
    box = canvas.bounding_box()
    canvas.click(position={'x': 10.5 * box['width'] / source['width'],
                           'y': 10.5 * box['height'] / source['height']})
    page.locator('#pixel-save').click()
    expect(page.locator('#pixel-status')).to_contain_text('v3')
    expect(page.locator('#pixel-save')).to_be_disabled()
    current = review_masks.get(store, 0)
    mask = review_masks.pixels(store, current)
    assert mask[0, 0] == 4 and mask[10, 10] == 2 and mask[15, 15] == 1
    assert current['status'] == 'pending' and current['approval'] is None


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
        selector.select_option('manual')
        page.locator('#pixel-class').select_option('4')
        page.locator('#pixel-tolerance').fill('37')
        selector.select_option(mode)
        if mode == 'auto':
            expect(page.locator('#pixel-tolerance')).to_be_hidden()
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


def test_sam_points_preview_and_apply_use_the_same_indexed_selection(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    source = store.get(0)['source']
    selected = np.full((source['height'], source['width']), 255, np.uint8)
    selected[4:16, 4:16] = 4
    path, digest = review_masks.freeze(store, review_masks.encode(selected))
    with store.connect() as db:
        db.execute('INSERT INTO pixel_drafts (frame,sha256,path,catalog_sha256,origin) VALUES (?,?,?,?,?)',
                   (0, digest, path, 'c' * 64, 'sam3_points'))
    submitted = []
    complete = False
    job = {'id': 'a' * 32, 'action': 'sam_points', 'state': 'succeeded',
           'result': {'selection_sha256': digest, 'candidate_sha256': digest, 'selected_pixels': 144}}
    def sam_api(route):
        if route.request.method == 'POST':
            submitted.append(route.request.post_data_json)
            route.fulfill(json={'id': job['id'], 'state': 'queued'})
        else:
            route.fulfill(json={'actions': {**{name: {'available': False, 'reason': 'not configured'}
                for name in ['object_draft', 'pixel_draft', 'mask_check']},
                'sam_points': {'available': True, 'reason': ''}},
                'jobs': [job if complete else {**job, 'state': 'queued'}] if submitted else []})
    page.route('**/api/review-ai/0', sam_api)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    expect(page.locator('#pixel-selection-method option[value=sam]')).to_be_enabled()
    page.locator('#pixel-class').select_option('4')
    page.locator('#pixel-selection-method').select_option('sam')
    canvas = page.locator('#pixel-canvas')
    box = canvas.bounding_box()
    canvas.click(position={'x': 6.5 * box['width'] / source['width'],
                           'y': 6.5 * box['height'] / source['height']})
    page.locator('#pixel-sam-run').focus()
    page.keyboard.press('Enter')
    expect(page.locator('#pixel-sam-cancel')).to_be_focused()
    complete = True
    expect(page.locator('#pixel-sample-apply')).to_be_enabled()
    expect(page.locator('#pixel-sample-apply')).to_be_focused()
    assert submitted == [{'action': 'sam_points', 'version': 0, 'label': 4, 'points': [[6, 6]]}]
    assert review_masks.get(store, 0)['version'] == 0
    with page.expect_request(lambda request: request.method == 'POST'
                             and request.url.endswith('/api/masks/0')) as sent:
        page.locator('#pixel-sample-apply').click()
    assert sent.value.post_data_json['selection_sha256'] == digest
    assert sent.value.post_data_json['preserve_existing'] is True
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    current = review_masks.get(store, 0)
    np.testing.assert_array_equal(review_masks.pixels(store, current), selected)
    assert current['status'] == 'pending' and current['approval'] is None


@pytest.mark.parametrize('can_request,initially_busy', [(True, False), (True, True), (False, False)])
def test_raw_current_photo_prepares_ai_draft_without_a_button_and_never_auto_saves(
    browser_workspace, can_request, initially_busy
):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    source = store.get(0)['source']
    path, digest = review_masks.freeze(store, review_masks.encode(
        np.full((source['height'], source['width']), 1, np.uint8)))
    submitted = []
    finished = published = False
    busy = initially_busy
    def ai_api(route):
        nonlocal published
        if route.request.method == 'POST':
            submitted.append(route.request.post_data_json)
            route.fulfill(json={'id': 'c' * 32, 'state': 'queued'})
            return
        if finished and not published:
            with store.connect() as db:
                db.execute('INSERT INTO pixel_drafts (frame,sha256,path,catalog_sha256,origin) VALUES (?,?,?,?,?)',
                           (0, digest, path, 'c' * 64, 'sam3_road_v1_v12_base'))
            published = True
        job = {'id': 'c' * 32, 'action': 'pixel_draft', 'version': 0,
               'state': 'succeeded' if finished else 'queued', 'actor': 'local-unidentified',
               'image_sha256': source['image_sha256'], 'model': 'mock', 'model_digest': 'e' * 64,
               'created_at': 'fixture', 'updated_at': 'fixture',
               'result': {'candidate_sha256': digest, 'added_pixels': source['width'] * source['height']}}
        route.fulfill(json={'can_request': can_request, 'busy': busy,
                            'actions': {name: {'available': name == 'pixel_draft', 'reason': '' if name == 'pixel_draft' else 'not configured'}
                                        for name in ['object_draft', 'pixel_draft', 'mask_check', 'sam_points']},
                            'jobs': [job] if submitted else []})
    page.route('**/api/review-ai/0', ai_api)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    if not can_request:
        expect(page.locator('#review-ai-pixel_draft')).to_be_disabled()
        page.wait_for_timeout(900)
        assert submitted == []
        assert review_masks.get(store, 0)['version'] == 0
        return
    if initially_busy:
        expect(page.locator('#pixel-ai-generation-state')).to_contain_text('대기')
        assert submitted == []
        busy = False
    expect(page.locator('#review-ai-jobs')).to_contain_text('대기')
    assert submitted == [{'action': 'pixel_draft', 'version': 0}]
    finished = True
    expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'true')
    assert page.locator('#pixel-candidates').input_value() == digest
    assert review_masks.get(store, 0)['version'] == 0
    page.reload(wait_until='networkidle')
    expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'true')
    assert submitted == [{'action': 'pixel_draft', 'version': 0}]


def test_current_photo_ai_check_refreshes_opinion_without_manual_result_lookup(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, CLASSES)
    review_masks.update(store, 0, {'version': 0, 'action': 'paint', 'label': 1,
                                  'radius': 0, 'points': [[1, 1]]}, ValueError)
    submitted, feedback_reads = [], []
    finished = False
    def ai_api(route):
        if route.request.method == 'POST':
            submitted.append(route.request.post_data_json)
            route.fulfill(json={'id': 'b' * 32, 'state': 'queued'})
            return
        job = {'id': 'b' * 32, 'action': 'mask_check', 'version': 1,
               'state': 'succeeded' if finished else 'queued', 'actor': 'local-unidentified',
               'model': 'mock', 'model_digest': 'e' * 64, 'created_at': 'fixture', 'updated_at': 'fixture'}
        route.fulfill(json={'actions': {name: {'available': name == 'mask_check', 'reason': '' if name == 'mask_check' else 'not configured'}
                              for name in ['object_draft', 'pixel_draft', 'mask_check', 'sam_points']},
                            'jobs': [job] if submitted else []})
    def opinion_api(route):
        feedback_reads.append(True)
        value = {'available': False, 'reason': 'no_report' if submitted else 'not_requested',
                 'check': {'state': 'queued' if submitted else 'not_requested', 'version': 1}}
        if finished:
            value = {'available': True, 'current': True, 'model': 'mock', 'model_digest': 'e' * 64,
                     'feedback': {'verdict': 'no_obvious_concern', 'issue': 'none', 'note': '모의 의견'},
                     'unknown_pixels': 767, 'review_blocked': True,
                     'check': {'state': 'succeeded', 'version': 1}}
        route.fulfill(json=value)
    page.route('**/api/review-ai/0', ai_api)
    page.route('**/api/vlm-feedback/0', opinion_api)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    page.locator('#review-ai-mask_check').click()
    expect(page.locator('#pixel-vlm-state')).to_contain_text('AI 확인 대기')
    finished = True
    expect(page.locator('#pixel-vlm-state')).to_contain_text('뚜렷한 문제를 찾지 못함')
    assert submitted == [{'action': 'mask_check', 'version': 1}]
    assert len(feedback_reads) >= 3
    assert review_masks.get(store, 0)['version'] == 1


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
          labels: [...document.querySelectorAll('.pixel-tool-options .ui-field-label:has(select,input[type=number]), .pixel-review-column .ui-field-label:has(select,input[type=number])')]
            .filter(node => node.getClientRects().length)
            .map(node => node.getBoundingClientRect().width),
          fields: [...document.querySelectorAll('.pixel-tool-options .ui-field-label select, .pixel-tool-options .ui-field-label input[type=number], .pixel-review-column .ui-field-label select, .pixel-review-column .ui-field-label input[type=number]')]
            .filter(node => node.getClientRects().length)
            .map(node => node.getBoundingClientRect().width),
        })""")
        assert len(field_widths['labels']) >= 2 and len(field_widths['fields']) >= 2
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
    expect(page.locator('#pixel-title')).to_contain_text('사진 1')
    expect(page.locator('#pixel-frame')).to_have_value('1')
    assert 'frame=1' in page.url
    # The paint class carries over so the next stroke is not silently the first class.
    expect(page.locator('#pixel-class')).to_have_value('4')
    expect(page.locator('#pixel-filter')).to_have_value('pending')
    assert review_masks.get(store, 0)['status'] == 'excluded'


def test_pending_filter_omits_object_excluded_frame(browser_workspace):
    page, store, expect = browser_workspace
    open_pixels(page, store, expect)
    page.locator('#pixel-filter').select_option('pending')
    expect(page.locator('#pixel-frame option')).to_have_count(1)
    expect(page.locator('#pixel-frame')).to_have_value('0')


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
    canvas.focus(); page.keyboard.press('Control+z')
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
    page.locator('#pixel-class').select_option('')
    expect(page.locator('#pixel-tool-hint')).to_contain_text('픽셀 클래스를 선택')
    expect(page.locator('#pixel-brush-tool')).to_be_disabled()
    pixel_tools = page.locator('#pixel-tool-rail').bounding_box()
    pixel_canvas = page.locator('#pixel-canvas').bounding_box()
    pixel_decision = page.locator('.pixel-review-column').bounding_box()
    assert object_tools['x'] < object_canvas['x'] < object_decision['x']
    assert pixel_tools['x'] + pixel_tools['width'] <= pixel_canvas['x']
    assert pixel_canvas['x'] + pixel_canvas['width'] <= pixel_decision['x']
    page.locator('#pixel-class').select_option('4')
    expect(page.locator('#pixel-tool-hint')).to_be_hidden()
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
    if not page.locator('#pixel-whole-frame-tools').evaluate('node => node.open'):
        page.locator('#pixel-whole-frame-tools > summary').click()
    page.locator('#pixel-fill').click()
    expect(page.locator('#pixel-error')).to_contain_text('다른 탭')
    expect(page.locator('#pixel-approve')).to_have_attribute('disabled', '')
    assert review_masks.get(store, 0) == newer
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if width == 390:
        expect(page.locator('#pixel-reload')).to_be_focused()
        reload = page.locator('#pixel-reload').bounding_box()
        assert reload and reload['width'] >= 44 and reload['x'] + reload['width'] <= width
        assert 0 <= reload['y'] and reload['y'] + reload['height'] <= 844
        expect(page.locator('#pixel-reload')).to_have_count(1)
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


def test_drivable_class_can_be_selected_painted_and_saved(browser_workspace):
    page, store, expect = browser_workspace
    raw = (Path(__file__).resolve().parents[3] / 'learning/curation/perception/classes/lane_lr6_drivable.yaml').read_bytes()
    review_masks.bind_classes(store, raw)
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v0')
    chip = page.locator('#pixel-quick-classes ui-button').nth(5)
    expect(chip).to_contain_text('주행 가능 영역')
    page.locator('#pixel-quick-classes').locator('xpath=ancestor::details[1]').locator(':scope > summary').click()
    chip.click()
    expect(page.locator('#pixel-class')).to_have_value('5')
    expect(page.locator('#pixel-tool-hint')).to_contain_text('경계선 안쪽')
    page.locator('#pixel-brush-tool').click()
    page.locator('#pixel-canvas').click(position={'x': 16, 'y': 12})
    page.locator('#pixel-save').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    assert np.any(review_masks.pixels(store, review_masks.get(store, 0)) == 5)



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
    tools = page.locator('#pixel-tool-rail').bounding_box()
    assert tools['x'] < canvas['x'] and tools['y'] < canvas['y']
    assert page.locator('#pixel-prev').bounding_box()['y'] < canvas['y']
    for action in ['#pixel-prev', '#pixel-next', '#pixel-undo']:
        bounds = page.locator(action).bounding_box()
        assert 0 <= bounds['x'] and bounds['x'] + bounds['width'] <= page.viewport_size['width']
        assert 0 <= bounds['y'] < min(800, canvas['y'] + canvas['height'])
    page.locator('#pixel-frame').select_option('1')
    expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
    expect(page.locator('#pixel-canvas')).to_be_focused()
    page.keyboard.press('ArrowLeft')
    expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
    page.locator('#pixel-quick-classes ui-button').nth(1).click()
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
    assert page.locator('#pixel-tool-rail').bounding_box()['y'] < page.locator('#pixel-canvas').bounding_box()['y']
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


def test_pixel_page_copy_is_class_set_neutral(browser_workspace):
    page, store, expect = browser_workspace
    review_masks.bind_classes(store, (Path(__file__).resolve().parents[3] / 'learning' / 'curation' / 'perception' / 'classes' / 'lane_lr5.yaml').read_bytes())
    page.goto(page.url.split('?')[0].rstrip('/') + '/pixels?frame=0', wait_until='networkidle')
    expect(page.locator('#pixel-status')).to_contain_text('v0')
    expect(page.locator('#pixel-class option:checked')).to_have_text('클래스를 선택하세요')
    hints = ' '.join(page.locator('#pixel-main p').all_text_contents())   # static copy, open or closed
    for text in ('흰 차선', 'stop_line', 'crosswalk'):
        assert text not in hints
