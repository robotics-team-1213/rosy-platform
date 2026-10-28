"""Remaining Fleet procedures keep long operational values inside their content column."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled
from test_fleet_header_browser import _fleet

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium layout scenario')
WIDTHS = [320, 390, 480, 768, 1440]
DOCS = ['login', 'profile', 'accounts', 'policy', 'learning']
HOST = '.'.join(['a' * 60] * 3 + ['example'])
IDENTITY = 'operator-' + 'a' * 87
GRANTS = [{'resource': 'site:layout', 'capabilities': ['accounts.manage']}]
SESSION = {'via': 'cookie', 'account_id': 'layout-account', 'session_family': 'layout-family',
           'revision': 1, 'role': 'policy-admin', 'site_resource': 'site:layout', 'grants': GRANTS}


def api(route):
    path = urlsplit(route.request.url).path
    responses = {
        '/api/fleet/auth/session': SESSION,
        '/api/fleet/auth/connection': {'configured': False},
        '/api/fleet/auth/setup': {'configured': True, 'issuer': 'https://' + HOST,
            'clients': [{'client_id': IDENTITY, 'resources': ['site:layout'],
                         'redirect_uris': ['https://' + HOST + '/callback/' + 'b' * 96]}]},
        '/api/fleet/auth/accounts': [{'login': IDENTITY, 'principal_id': IDENTITY, 'enabled': True,
            'role': 'policy-admin', 'revision': 1, 'grants': GRANTS}],
        '/api/fleet/auth/profile': {'login': IDENTITY, 'principal_id': IDENTITY,
            'display_name': '운영 담당자', 'email': 'account@' + HOST, 'role': 'policy-admin', 'grants': GRANTS},
        '/api/fleet/policy-governance/workcells': {'workcells': []},
    }
    assert route.request.method == 'GET', 'layout fixture must not perform account or policy writes'
    route.fulfill(status=200 if path in responses else 404,
                  json=responses.get(path, {'detail': 'fixture endpoint unavailable'}))


def capture(page, name):
    if value := os.environ.get('ROSY_SHOT_DIR'):
        root = Path(value).expanduser(); root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / (name + '.png')))


def fits(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', WIDTHS)
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_long_learning_values_and_step_groups(tmp_path, monkeypatch, width, theme):
    from playwright.sync_api import expect
    config = tmp_path / 'learning.json'
    config.write_text(json.dumps({'model': 'https://' + HOST}), encoding='utf-8')
    monkeypatch.setenv('ROSY_LEARNING_APPS_CONFIG', str(config))
    with _fleet(tmp_path) as (browser, origin):
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        page.add_init_script(f"localStorage.setItem('rosy.theme', '{theme}')")
        page.goto(origin + '/console/learning')
        expect(page.locator('[data-host=model]')).to_contain_text(HOST)
        capture(page, f'learning-{theme}-{width}')
        fits(page)
        expect(page.locator('.learning-steps-list li > span')).to_have_count(3)
        for step in page.locator('.learning-steps-list li').all():
            assert step.locator('span').bounding_box()['x'] > step.bounding_box()['x']
        assert page.locator('.learning-host').evaluate_all('nodes => nodes.every(n => n.scrollWidth <= n.clientWidth + 1)')
        page.close()


@pytest.mark.parametrize('width', WIDTHS)
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_procedures_share_inset_and_keep_account_values_reachable(tmp_path, width, theme):
    from playwright.sync_api import expect
    with _fleet(tmp_path) as (browser, origin):
        for name in DOCS:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script(f"localStorage.setItem('rosy.theme', '{theme}')")
            page.route('**/api/fleet/**', api)
            page.goto(origin + '/console/' + name)
            if name == 'accounts':
                expect(page.locator('#account-clients')).to_contain_text(HOST)
                expect(page.locator('#account-content')).to_be_visible()
                page.locator('#account-list ui-button').click()
                expect(page.locator('#account-heading')).to_contain_text(IDENTITY)
            elif name == 'profile':
                expect(page.locator('#profile-content')).to_be_visible()
            elif name == 'policy':
                expect(page.locator('#policy-verdict')).to_contain_text('설정된 OMX 작업셀이 없습니다')
            capture(page, f'{name}-{theme}-{width}')
            fits(page)
            assert page.locator('main').evaluate("n => getComputedStyle(n).paddingLeft === getComputedStyle(document.documentElement).getPropertyValue('--inset-task-page').trim()")
            page.get_by_role('button', name='테마:', exact=False).focus()
            assert not errors
            page.close()


@pytest.mark.parametrize('width', WIDTHS)
def test_lightweight_header_is_complete_without_javascript(tmp_path, width):
    from playwright.sync_api import expect
    with _fleet(tmp_path) as (browser, origin):
        for name in DOCS:
            page = browser.new_page(viewport={'width': width, 'height': 1000}, java_script_enabled=False)
            response = page.goto(origin + '/console/' + name)
            assert '<!-- fleet:document-header:start -->' in response.text()
            expect(page.locator('ui-topbar ui-brand')).to_have_count(1)
            expect(page.locator('ui-topbar [data-theme-cycle]')).to_have_count(1)
            fits(page)
            page.close()


@pytest.mark.parametrize('status', [200, 401, 503])
def test_policy_without_verified_workcell_has_no_actionable_forms(tmp_path, status):
    from playwright.sync_api import expect
    with _fleet(tmp_path) as (browser, origin):
        page = browser.new_page(viewport={'width': 320, 'height': 1000})
        def serve(route):
            if urlsplit(route.request.url).path.endswith('/workcells') and status != 200:
                route.fulfill(status=status, json={'detail': 'fixture unavailable'})
            else:
                api(route)
        page.route('**/api/fleet/**', serve)
        page.goto(origin + '/console/policy')
        expect(page.locator('#policy-verdict')).not_to_have_attribute('state', 'pending')
        capture(page, f'policy-unavailable-{status}-320')
        for element in ['policy-incident-report', 'policy-sync-owner', 'policy-window-request', 'policy-proposal-submit']:
            expect(page.locator('#' + element)).not_to_be_visible()
        fits(page)
        page.close()
