"""Account presentation and Fleet navigation in Chromium, without device writes."""
from urllib.parse import quote
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from browser_harness import browser_tests_enabled
from test_fleet_account_browser import account_backend, account_page, _credentials

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


def capture(page, name):
    if directory := os.environ.get('ROSY_SHOT_DIR'):
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target / name), full_page=True)


@pytest.mark.parametrize('width', [320, 1366])
def test_account_entry_uses_shared_heading_and_readable_layout(account_page, account_backend, width):
    page, origin = account_page
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(origin + '/console/login')
    expect(page.locator('[data-login=form]')).to_be_visible()
    expect(page.locator('ui-brand')).to_be_in_viewport()
    heading = page.get_by_role('heading', name='관제 로그인')
    assert heading.evaluate('(node) => getComputedStyle(node).fontSize') == '20px'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.locator('#login-back')).to_be_visible()
    capture(page, f'login-{account_backend}-{width}.png')


def test_fleet_navigation_and_profile_return_preserve_selected_subtab(account_page, account_backend):
    page, origin = account_page
    page.set_viewport_size({'width': 1366, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('response', lambda response: errors.append(f'asset {response.status}: {response.url}')
            if response.status >= 400 and '/api/' not in response.url else None)
    target = '/console?view=work&show=new'
    page.goto(origin + '/console/login?return=' + quote(target, safe=''))
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page).to_have_url(origin + target)
    expect(page.locator('#user-role')).to_have_text('운영자')
    for view, shows in [('work', ['', 'pending', 'done', 'new']),
                        ('records', ['', 'open', 'closed', 'facts', 'log'])]:
        page.locator(f'.doc-tabs a[href="/console?view={view}"]').click()
        for show in shows:
            path = f'/console?view={view}' + (f'&show={show}' if show else '')
            link = page.locator(f'.ui-subnav a[href="{path}"]')
            link.click()
            expect(page).to_have_url(origin + path)
            expect(page.locator(f'.ui-subnav[data-area={view}]')).to_be_visible()
            expect(page.locator(f'.ui-subnav a[href="{path}"]')).to_have_attribute('aria-current', 'page')
            if view == 'work':
                expect(page.locator('#work-new' if show == 'new' else '#work-overview')).to_be_visible()
    for path in ['/console', '/console/site-map', '/console/install']:
        page.locator(f'.doc-tabs a[href="{path}"]').click()
        expect(page).to_have_url(origin + path)
        page.locator('.doc-tabs a[href="/console"]').click()
        expect(page).to_have_url(origin + '/console')
        expect(page.locator('.ui-subnav[data-area=work]')).to_be_hidden()
        expect(page.locator('.ui-subnav[data-area=records]')).to_be_hidden()
        expect(page.locator('[aria-labelledby=map-heading]')).to_be_visible()
    page.locator('.doc-tabs a[href="/console?view=work"]').click()
    page.locator(f'.ui-subnav a[href="{target}"]').click()
    expect(page.locator('#user-role')).to_have_text('운영자')
    page.locator('#topbar-more').click()
    page.locator('#fleet-profile').click()
    expect(page.locator('#profile-id')).to_have_text('alice')
    capture(page, f'profile-{account_backend}.png')
    page.locator('#profile-back').click()
    expect(page).to_have_url(origin + target)
    expect(page.locator('#work-new')).to_be_visible()
    page.go_back()
    expect(page.locator('#profile-id')).to_have_text('alice')
    page.go_forward()
    expect(page).to_have_url(origin + target)
    assert not errors, errors


def test_new_work_explains_missing_kinds_without_redirecting(account_page):
    page, origin = account_page
    page.goto(origin + '/console/login')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page).to_have_url(origin + '/console')
    expect(page.locator('#user-role')).to_have_text('운영자')
    page.route('**/api/fleet/work', lambda route: route.fulfill(json={
        'kinds': [], 'rows': [], 'truncated_sources': [],
        'observed_at': '2026-10-20T00:00:00Z',
    }))
    target = '/console?view=work&show=new'
    page.goto(origin + target)
    expect(page.locator('#work-new-status')).to_contain_text('현재 만들 수 있는 작업이 없습니다')
    expect(page.locator('#work-new-move-item')).to_be_hidden()
    expect(page.locator('#work-new-cell-item')).to_be_hidden()
    expect(page).to_have_url(origin + target)
