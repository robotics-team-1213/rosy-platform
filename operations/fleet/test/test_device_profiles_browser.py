"""Real installation DOM with stubbed Fleet reads/writes, never device acceptance."""

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from browser_harness import browser_tests_enabled, launch_options
from test_console_queue_inline_browser import site  # noqa: F401


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


@pytest.mark.parametrize('width', [1440, 390])
@pytest.mark.parametrize('role', ['operator', 'viewer'])
def test_installation_device_information_save_reload_and_viewer_guard(site, width, role):
    from playwright.sync_api import expect, sync_playwright

    saved = {'device_id': 'omx-s', 'display_name': '실습실 OMX S 한 팔', 'manufacturer': 'ROBOTIS',
             'model': 'OMX S 단일 팔', 'device_kind': 'manipulator', 'arm_count': 1,
             'hardware_ids': ['usb-bus-a', 'usb-bus-b'], 'updated_by': 'alice', 'updated_at': 1,
             'connection_status': 'not_checked', 'control_enabled': False}
    profiles = {} if role == 'operator' else {'omx-s': saved}
    writes, errors = [], []

    def serve(route):
        request = route.request
        path = urlparse(request.url).path
        if path == '/api/fleet/session':
            route.fulfill(json={'principal_id': 'alice', 'role': role})
        elif path == '/api/fleet/device-profiles':
            route.fulfill(json={'profiles': list(profiles.values())})
        elif path == '/api/fleet/device-profiles/omx-s':
            if request.method == 'PUT':
                writes.append(request.post_data_json)
                assert 'device_id' not in request.post_data_json
                profiles['omx-s'] = {**saved, **request.post_data_json}
            route.fulfill(json=profiles['omx-s'])
        else:
            route.fulfill(status=404, json={'detail': 'Not Found'})

    def open_information(page):
        page.goto(site + '/console/install')
        tab = page.get_by_role('tab', name='장치 정보', exact=True)
        if tab.is_visible():
            tab.click()
        else:
            page.locator('.ui-task-compact select').select_option('device-profiles')
        expect(page.locator('#device-profiles')).to_be_visible()
        expect(page.locator('[data-profile="list"]')).to_be_enabled()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_options())
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000 if width > 1000 else 844})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/**', serve)
            open_information(page)
            if role == 'operator':
                expect(page.locator('[data-profile="save"]')).to_be_enabled()
                for field in ('device_id', 'display_name', 'manufacturer', 'model'):
                    page.locator(f'[data-profile="{field}"]').fill(saved[field])
                page.locator('[data-profile="arm_count"]').fill('1')
                page.locator('[data-profile="hardware_ids"]').fill('\n'.join(saved['hardware_ids']))
                page.locator('[data-profile="save"]').click()
                expect(page.locator('[data-profile="status"]')).to_contain_text('저장하고 다시 확인했습니다')
                assert len(writes) == 1
                assert writes[0]['arm_count'] == 1
                assert writes[0]['hardware_ids'] == ['usb-bus-a', 'usb-bus-b']
                open_information(page)
            expect(page.locator('[data-profile="list"] option[value="omx-s"]')).to_have_count(1)
            page.locator('[data-profile="list"]').select_option('omx-s')
            expect(page.locator('[data-profile="display_name"]')).to_have_value(saved['display_name'])
            expect(page.locator('[data-profile="model"]')).to_have_value(saved['model'])
            expect(page.locator('[data-profile="arm_count"]')).to_have_value('1')
            expect(page.locator('[data-profile="hardware_ids"]')).to_have_value('usb-bus-a\nusb-bus-b')
            expect(page.locator('[data-profile="device_id"]')).to_be_disabled()
            expect(page.locator('[data-profile="saved"]')).to_contain_text('연결 미확인')
            if role == 'viewer':
                for field in ('display_name', 'model', 'arm_count', 'hardware_ids', 'save', 'new'):
                    expect(page.locator(f'[data-profile="{field}"]')).to_be_disabled()
                page.locator('[data-profile="save"]').dispatch_event('click')
                assert not writes
            expect(page.locator('#estop')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if output := os.environ.get('ROSY_SHOT_DIR'):
                folder = Path(output)
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f'device-information-{role}-{width}.png'
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(target), full_page=True)
                print(f'Device information screenshot: {target}')
            assert not errors
        finally:
            browser.close()
