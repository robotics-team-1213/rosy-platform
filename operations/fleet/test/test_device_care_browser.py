"""Robot information before actions, and care draft preservation in real Chromium."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from browser_harness import browser_tests_enabled, launch_options
from test_console_queue_inline_browser import API, _open, _robot, site  # noqa: F401


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


def profile():
    return {'device_id': 'arm-one', 'display_name': '실습 로봇', 'device_kind': 'manipulator', 'model': 'OMX',
            'manufacturer': '', 'arm_count': 1, 'hardware_ids': [], 'connection_status': 'not_checked',
            'control_enabled': False, 'source_kind': 'robot', 'source_id': 'rosy_01',
            'caution': '2·3번 관절 하중 주의', 'characteristics': None, 'characteristics_summary': None,
            'latest_analysis': None,
            'events': [{'kind': 'fault', 'text': '팔 처짐 관찰', 'actor': 'alice', 'created_at': 100}]}


def shot(page, name):
    if output := os.environ.get('ROSY_SHOT_DIR'):
        target = Path(output) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target), full_page=True)
        print(f'Robot profile screenshot: {target}')


@pytest.mark.parametrize('width', [1440, 390])
def test_robot_information_precedes_actions_and_failed_refresh_is_visible(site, width):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright
    api = {**API, '/api/fleet/state': {**API['/api/fleet/state'], 'robots': [_robot('rosy_01')]},
           '/api/fleet/trips': {'running': None, 'trips': [], 'open': []},
           '/api/fleet/device-profile-sources/robot/rosy_01': {'profile': profile()}}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, size=(width, 1000))
        try:
            page.locator('#roster [data-select-robot-id="rosy_01"]').click()
            page.clock.run_for(1500)
            card = page.locator('#robot-workspace article')
            info = card.locator('[data-robot-profile]')
            expect(info).to_contain_text('2·3번 관절 하중 주의')
            expect(info).to_contain_text('최근 하중 분석 없음')
            assert card.evaluate("""el => (el.querySelector('[data-robot-profile]')
                .compareDocumentPosition(el.querySelector('.robot-actions')) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0""")
            info.locator('summary').click()
            page.clock.run_for(1500)
            expect(info.locator('details')).to_have_attribute('open', '')
            expect(info).to_contain_text('팔 처짐 관찰')
            expect(info.locator('a')).to_have_attribute('href', '/console/install?profile=arm-one#device-profiles')
            expect(page.locator('#estop')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            shot(page, f'robot-profile-{width}.png')
            del api['/api/fleet/device-profile-sources/robot/rosy_01']
            page.clock.run_for(2500)
            expect(info).to_contain_text('프로필을 읽지 못했습니다')
            assert not posts and not errors
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('role', ['operator', 'viewer'])
def test_care_editor_keeps_draft_after_metadata_save_and_source_mapping(site, width, role):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright
    saved, writes = profile(), []

    def serve(route):
        request, path = route.request, urlparse(route.request.url).path
        if path == '/api/fleet/session':
            route.fulfill(json={'principal_id': 'alice', 'role': role})
        elif path == '/api/fleet/device-profiles':
            route.fulfill(json={'profiles': [saved]})
        elif path == '/api/fleet/device-profile-sources':
            route.fulfill(json={'sources': [{'source_kind': 'robot', 'source_id': 'rosy_01', 'label': '실습 로봇'}]})
        elif path == '/api/fleet/device-profiles/arm-one':
            if request.method == 'PUT':
                writes.append(path)
                saved.update(request.post_data_json)
            route.fulfill(json=saved)
        elif path == '/api/fleet/device-profiles/arm-one/care':
            if request.method == 'PUT':
                writes.append(path)
                saved.update(request.post_data_json)
            route.fulfill(json=saved)
        else:
            route.fulfill(status=404, json={'detail': 'Not Found'})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/**', serve)
            page.goto(site + '/console/install?profile=arm-one#device-profiles')
            expect(page.locator('[data-care="caution"]')).to_have_value(saved['caution'])
            if role == 'operator':
                page.locator('[data-care="caution"]').fill('높은 위치에서 처짐\n감속 후 점검')
                page.locator('[data-care="text"]').fill('정비 초안 유지')
                page.locator('[data-profile="display_name"]').fill('수정된 표시 이름')
                page.locator('[data-profile="save"]').click()
                expect(page.locator('[data-profile="status"]')).to_contain_text('저장하고 다시 확인했습니다')
                expect(page.locator('[data-care="caution"]')).to_have_value('높은 위치에서 처짐\n감속 후 점검')
                expect(page.locator('[data-care="text"]')).to_have_value('정비 초안 유지')
                page.locator('[data-care="save"]').click()
                expect(page.locator('[data-care="status"]')).to_contain_text('저장하고 다시 확인했습니다')
                assert saved['caution'] == '높은 위치에서 처짐\n감속 후 점검'
                assert saved['source_id'] == 'rosy_01'
                assert len(writes) == 2
            else:
                for key in ('caution', 'source', 'file', 'save', 'add'):
                    expect(page.locator(f'[data-care="{key}"]')).to_be_disabled()
                page.locator('[data-care="save"]').dispatch_event('click')
                assert not writes
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            shot(page, f'robot-care-{role}-{width}.png')
            assert not errors
        finally:
            browser.close()
