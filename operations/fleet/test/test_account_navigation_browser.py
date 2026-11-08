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
    heading = page.get_by_role('heading', name='계정 로그인')
    assert heading.evaluate('(node) => getComputedStyle(node).fontSize') == '20px'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    expect(page.locator('#login-back')).to_be_visible()
    expect(page.locator('#login-site')).to_contain_text(origin.split('://', 1)[1])
    expect(page.get_by_text('계정이 없거나 비밀번호를 잊었다면 현장 관리자에게 문의하세요.')).to_be_visible()
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
    with page.expect_popup() as opened:
        page.locator('#fleet-profile').click()
    profile = opened.value
    expect(profile.locator('#profile-id')).to_have_text('alice')
    capture(profile, f'profile-{account_backend}.png')
    profile.close()
    expect(page).to_have_url(origin + target)
    expect(page.locator('#work-new')).to_be_visible()
    assert not errors, errors


def test_area_is_chosen_before_the_console_modules_and_never_hides_the_page(account_page):
    page, origin = account_page
    page.route('**/console/assets/console.js', lambda route: route.abort())
    page.goto(origin + '/console?view=work&show=pending', wait_until='commit')
    expect(page.locator('.doc-tabs a[href="/console?view=work"]')).to_have_attribute('aria-current', 'page')
    expect(page.locator('.doc-tabs a[href="/console"]')).not_to_have_attribute('aria-current', 'page')
    expect(page.locator('.ui-subnav[data-area=work]')).to_be_visible()
    expect(page.locator('#console-screen')).to_have_text('승인 대기')
    expect(page.locator('#estop')).to_be_visible()
    # console.js never ran, so area-first's own timer must bring the panels back.
    expect(page.locator('#fleet-main')).to_have_css('visibility', 'visible', timeout=5000)


def test_policy_header_login_returns_to_policy(account_page):
    page, origin = account_page
    page.goto(origin + '/console/policy')
    expect(page.locator('#fleet-login')).to_have_attribute('href', '/console/login?return=%2Fconsole%2Fpolicy')


def test_accounts_refusal_does_not_loop_through_a_valid_login(account_page):
    page, origin = account_page
    page.goto(origin + '/console/login')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page.locator('#user-role')).to_have_attribute('title', 'alice · operator')
    def viewer(route):
        response = route.fetch()
        route.fulfill(response=response, json={**response.json(), 'role': 'viewer', 'grants': []})
    page.route('**/api/fleet/auth/session', viewer)
    page.goto(origin + '/console/accounts')
    expect(page.locator('#account-login')).to_have_attribute('href', '/console/login?return=%2Fconsole%2Faccounts&error=access_denied')
    page.locator('#account-login').click()
    expect(page.locator('#login-recovery')).to_be_visible()
    assert '/console/login' in page.url


def test_install_tasks_go_back_to_the_previous_task(account_page):
    page, origin = account_page
    page.goto(origin + '/console/install')
    first = page.locator('#install-chooser [role=tab]').first
    expect(first).to_have_attribute('aria-selected', 'true')
    page.get_by_role('tab', name='카메라 연결 승인').click()
    expect(page).to_have_url(origin + '/console/install#cameras')
    page.get_by_role('tab', name='카메라 설치·보정').click()
    expect(page).to_have_url(origin + '/console/install#calibration')
    page.go_back()
    expect(page.get_by_role('tab', name='카메라 연결 승인')).to_have_attribute('aria-selected', 'true')
    expect(page).to_have_url(origin + '/console/install#cameras')
    page.go_back()
    expect(first).to_have_attribute('aria-selected', 'true')
    expect(page).to_have_url(origin + '/console/install')
    page.go_forward()
    expect(page.get_by_role('tab', name='카메라 연결 승인')).to_have_attribute('aria-selected', 'true')
    expect(page).to_have_url(origin + '/console/install#cameras')


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


def test_back_after_login_does_not_return_to_the_login_page(account_page):
    page, origin = account_page
    page.goto(origin + '/console/policy')
    page.goto(origin + '/console/login?return=%2Fconsole%2Fpolicy')
    _credentials(page)
    page.locator('[data-login=submit]').click()
    expect(page).to_have_url(origin + '/console/policy')
    # The login page replaced itself: blank, policy, destination (4 without replace).
    assert page.evaluate('history.length') == 3
