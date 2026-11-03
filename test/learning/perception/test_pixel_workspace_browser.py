"""Pixel workspace layout and explicit one-click completion on isolated labels."""
import os
from pathlib import Path

import numpy as np
import pytest

from browser_harness import browser_tests_enabled
from review_app import Conflict
import review_masks
from test_review_flow_browser import browser_workspace
from test_pixel_review_browser import open_pixels

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_pixel_workspace_layout_has_one_photo_navigation_and_unclipped_tools(browser_workspace, theme):
    page, store, expect = browser_workspace
    with store.connect() as db:
        source, review = db.execute('SELECT source,review FROM frames WHERE id=0').fetchone()
        db.executemany('INSERT INTO frames VALUES (?,?,?,?,1)',
                       [(index, source, review, 'pending') for index in range(2, 70)])
    open_pixels(page, store, expect)
    page.evaluate('theme => RosyTheme.set(theme)', theme)
    expect(page.locator('#pixel-complete, #pixel-background')).to_have_count(0)
    expect(page.locator('#pixel-approve')).to_have_text('완료')
    expect(page.locator('#pixel-photo-navigation')).to_have_count(1)
    expect(page.locator('#pixel-photo-navigation #pixel-prev')).to_have_count(1)
    expect(page.locator('#pixel-photo-navigation #pixel-next')).to_have_count(1)
    expect(page.locator('#pixel-photo-navigation #pixel-undo')).to_have_count(0)
    expect(page.locator('#pixel-photo-list #pixel-page-controls')).to_be_visible()
    for width in (390, 800, 1440, 2048):
        page.set_viewport_size({'width': width, 'height': 1120 if width == 2048 else 844})
        page.locator('#pixel-class').focus()
        expect(page.locator('#pixel-class')).to_be_focused()
        geometry = page.evaluate('''() => {
          const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
          const tools = document.querySelector('.pixel-quick-tools');
          return {width: innerWidth, pageWidth: document.documentElement.scrollWidth,
            tools: rect('.pixel-quick-tools'), column: rect('.pixel-editor-column'),
            photo: rect('.pixel-editor-column > section'), decision: rect('.pixel-review-column'),
            nav: rect('#pixel-photo-navigation'), prev: rect('#pixel-prev'),
            title: rect('#pixel-title'), next: rect('#pixel-next'), list: rect('#pixel-photo-list'),
            layout: rect('.pixel-layout'), focused: rect('#pixel-class'), height: innerHeight,
            overflow: getComputedStyle(tools).overflowY, maxHeight: getComputedStyle(tools).maxHeight,
            clientHeight: tools.clientHeight, scrollHeight: tools.scrollHeight};
        }''')
        assert geometry['pageWidth'] <= width
        assert geometry['overflow'] == 'visible' and geometry['maxHeight'] == 'none'
        assert geometry['scrollHeight'] <= geometry['clientHeight'] + 1
        assert geometry['prev']['right'] <= geometry['title']['left'] + 1
        assert geometry['title']['right'] <= geometry['next']['left'] + 1
        assert geometry['list']['top'] >= geometry['layout']['bottom'] - 1
        assert 0 <= geometry['focused']['top'] < geometry['height']
        assert geometry['focused']['bottom'] <= geometry['height'] + 1
        if width >= 1024:
            assert geometry['decision']['left'] >= geometry['column']['right']
            assert geometry['tools']['bottom'] <= geometry['photo']['top'] + 1
        else:
            assert geometry['tools']['top'] >= geometry['photo']['bottom'] - 1
            assert geometry['decision']['top'] >= geometry['tools']['bottom'] - 1
        if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            page.locator('#pixel-photo-navigation').scroll_into_view_if_needed()
            page.screenshot(path=str(target / f'pixel-workspace-{theme}-{width}.png'), full_page=True)


def partial_workspace(page, store, expect):
    open_pixels(page, store, expect)
    store.update(1, {'version': store.get(1)['version'], 'action': 'reopen'})
    review_masks.update(store, 0, {'version': 0, 'action': 'paint', 'label': 2,
                                  'radius': 0, 'points': [[2, 2]]}, Conflict)
    page.locator('#pixel-reload').click()
    expect(page.locator('#pixel-status')).to_contain_text('v1')
    return review_masks.pixels(store, review_masks.get(store, 0)).copy()


@pytest.mark.parametrize('width', [1440, 390])
def test_context_fill_preserves_undo_and_one_complete_click_approves_then_advances(browser_workspace, width):
    page, store, expect = browser_workspace
    page.set_viewport_size({'width': width, 'height': 844})
    before = partial_workspace(page, store, expect)
    context = page.locator('#pixel-result-note + #pixel-resolve-unknown')
    expect(context).to_be_visible()
    expect(context.locator('#pixel-resolve-background')).to_have_text('남은 767픽셀 배경으로 채우기')
    page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
    expect(context.locator('#pixel-resolve-background')).to_be_disabled()
    expect(page.locator('#pixel-approve')).to_be_disabled()
    page.locator('#pixel-sample-clear').click()
    expect(page.locator('#pixel-approve')).to_be_enabled()
    page.once('dialog', lambda dialog: dialog.accept())
    context.locator('#pixel-resolve-background').click()
    expect(page.locator('#pixel-status')).to_contain_text('v2')
    expect(page.locator('#pixel-approve')).to_be_focused()
    assert review_masks.get(store, 0)['status'] == 'pending'
    after = review_masks.pixels(store, review_masks.get(store, 0))
    assert after[2, 2] == 2 and np.all(after[before == 255] == 0)
    page.locator('#pixel-undo').click()
    expect(page.locator('#pixel-status')).to_contain_text('v3')
    assert np.array_equal(review_masks.pixels(store, review_masks.get(store, 0)), before)
    requests = []
    page.on('request', lambda request: requests.append(request.post_data_json)
            if request.method == 'POST' and request.url.endswith('/api/masks/0') else None)
    page.locator('#pixel-approve').click()
    expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
    assert [body['action'] for body in requests] == ['fill_unknown', 'approve']
    assert requests[1]['version'] == requests[0]['version'] + 1
    assert requests[1]['complete_frame_review'] is True and requests[1]['background_reviewed'] is True
    assert review_masks.get(store, 0)['status'] == 'approved'
    assert 'actor' not in requests[1]  # The server supplies authenticated provenance.
    assert store.history(0)['events']['pixel'][0]['action'] == 'approve'
    final = review_masks.pixels(store, review_masks.get(store, 0))
    assert final[2, 2] == 2 and np.all(final[before == 255] == 0)
    expect(context).to_be_hidden()
    expect(page.locator('#pixel-approve')).to_be_disabled()  # Entire next photo is unknown.
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def test_completion_fill_failure_does_not_send_approval(browser_workspace):
    page, store, expect = browser_workspace
    before = partial_workspace(page, store, expect)
    requests = []

    def fail_fill(route):
        body = route.request.post_data_json
        requests.append(body)
        if body['action'] == 'fill_unknown':
            route.fulfill(status=503, json={'error': 'fill unavailable'})
        else:
            route.continue_()

    page.route('**/api/masks/0', fail_fill)
    page.locator('#pixel-approve').click()
    expect(page.locator('#pixel-error')).to_be_visible()
    assert [body['action'] for body in requests] == ['fill_unknown']
    assert review_masks.get(store, 0)['version'] == 1
    assert review_masks.get(store, 0)['status'] == 'pending'
    assert np.array_equal(review_masks.pixels(store, review_masks.get(store, 0)), before)
