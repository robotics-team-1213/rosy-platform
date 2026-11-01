"""Stop receipts are visible feedback, never evidence of physical stopping."""
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
from playwright.sync_api import expect
from test_pilot_browser import _enter_drive, dev_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium stop scenario')


def capture(page, name):
    if value := os.environ.get('ROSY_SHOT_DIR'):
        root = Path(value).expanduser(); root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / (name + '.png')))


@pytest.mark.parametrize('width', [320, 390, 768, 1440])
@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('status,word', [(200, '요청 접수'), (403, '요청 거절'), (503, '결과 확인 불가')])
def test_stop_receipt_is_readable_and_keeps_control_live(tablet_page, width, theme, status, word):
    origin, page, errors = tablet_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.add_init_script(f"localStorage.setItem('rosy.theme', '{theme}')")
    page.route('**/api/v1/safety/stop', lambda route: route.fulfill(status=status, json={'estop': True, 'operations': []}))
    page.goto(origin + '/pilot')
    expect(page.locator('body')).to_have_attribute('data-pilot-screen', 'connect')
    stop, notice = page.locator('[data-estop]'), page.locator('#pilot-notice')
    stop.click()
    expect(notice).to_contain_text(word)
    expect(notice).to_be_visible()
    expect(stop).to_be_enabled()
    assert '정지 완료' not in notice.inner_text()
    for node in [notice, stop]:
        box = node.bounding_box()
        assert box and box['x'] >= 0 and box['x'] + box['width'] <= width + 1
    assert notice.evaluate('n => n.scrollWidth <= n.clientWidth + 1')
    capture(page, f'pilot-stop-{status}-{theme}-{width}')
    assert not errors


@pytest.mark.parametrize('kind', ['timeout', 'network', 'malformed', 'unauthorized'])
def test_unconfirmed_stop_has_a_bounded_result_and_no_unhandled_error(tablet_page, kind):
    origin, page, errors = tablet_page
    held = []
    def serve(route):
        if kind == 'timeout': held.append(route)
        elif kind == 'network': route.abort('failed')
        else: route.fulfill(status=401 if kind == 'unauthorized' else 200, json={})
    page.route('**/api/v1/safety/stop', serve)
    page.goto(origin + '/pilot')
    page.locator('[data-estop]').click()
    expect(page.locator('#pilot-notice')).to_contain_text('요청 거절' if kind == 'unauthorized' else '결과 확인 불가', timeout=10_000)
    expect(page.locator('[data-estop]')).to_be_enabled()
    assert not errors


def test_older_stop_reply_cannot_overwrite_a_newer_refusal(tablet_page):
    origin, page, errors = tablet_page
    held, calls = [], []
    def serve(route):
        calls.append(route.request.method)
        if len(calls) == 1: held.append(route)
        else: route.fulfill(status=403, json={})
    page.route('**/api/v1/safety/stop', serve)
    page.goto(origin + '/pilot')
    stop, notice = page.locator('[data-estop]'), page.locator('#pilot-notice')
    stop.click()
    expect(notice).to_contain_text('요청 중')
    expect(stop).to_be_enabled()
    stop.click()
    expect(notice).to_contain_text('요청 거절')
    held[0].fulfill(json={'estop': True, 'operations': []})
    page.wait_for_timeout(100)
    expect(notice).to_contain_text('요청 거절')
    assert calls == ['POST', 'POST'] and not errors


@pytest.mark.parametrize('width', [320, 768, 1440])
def test_stop_result_remains_visible_in_the_drive_screen(tablet_page, width):
    origin, page, errors = tablet_page
    page.set_viewport_size({'width': width, 'height': 900})
    _enter_drive(page, origin)
    page.route('**/api/v1/safety/stop', lambda route: route.fulfill(json={'estop': True, 'operations': []}))
    page.locator('[data-estop]').click()
    expect(page.locator('#pilot-notice')).to_contain_text('요청 접수')
    expect(page.locator('#pilot-notice')).to_be_visible()
    expect(page.locator('[data-estop]')).to_be_visible()
    capture(page, f'pilot-drive-stop-{width}')
    assert not errors


def test_connection_notice_replaces_stop_feedback_and_rejects_its_late_reply(tablet_page):
    origin, page, errors = tablet_page
    held = []
    page.route('**/api/v1/safety/stop', lambda route: held.append(route))
    page.goto(origin + '/pilot')
    page.locator('[data-estop]').click()
    expect(page.locator('#pilot-notice')).to_contain_text('요청 중')
    page.locator('form[data-pilot-token-form] ui-field input').fill(dev_server.DEV_TOKEN)
    page.locator('form[data-pilot-token-form] ui-button').click()
    expect(page.locator('[data-drive-enter]')).to_be_visible()
    assert page.locator('#pilot-notice').get_attribute('data-stop-state') is None
    held[0].fulfill(json={'estop': True, 'operations': []})
    page.wait_for_timeout(100)
    assert page.locator('#pilot-notice').get_attribute('data-stop-state') is None
    page.locator('[data-drive-enter]').click()
    expect(page.locator('body')).to_have_attribute('data-pilot-screen', 'drive')
    expect(page.locator('#pilot-notice')).to_be_hidden()
    assert not errors


@pytest.mark.parametrize('status', [404, 503])
def test_discovery_completion_keeps_a_real_stop_receipt(tablet_page, status):
    origin, page, errors = tablet_page
    held = []
    page.route('**/api/v1/sim/omx/target', lambda route: held.append(route))
    page.route('**/api/v1/safety/stop', lambda route: route.fulfill(json={'estop': True, 'operations': []}))
    page.goto(origin + '/pilot')
    page.locator('[data-estop]').click()
    notice = page.locator('#pilot-notice')
    expect(notice).to_contain_text('요청 접수')
    assert len(held) == 1
    held[0].fulfill(status=status, json={})
    expect(page.locator('form[data-pilot-token-form]' if status == 404 else '[data-discovery-retry]')).to_be_visible()
    expect(notice).to_contain_text('요청 접수')
    expect(notice).to_have_attribute('data-stop-state', 'received')
    assert not errors
