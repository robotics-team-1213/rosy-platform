"""Data pages must show failed reads and keep the user's account and import intent."""
import copy
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled
from test_review_app import open_store
from test_review_flow_browser import serve

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium data recovery')
JOB = {'id': 'a' * 32, 'repo_id': 'fixture/data', 'revision': 'b' * 40, 'requester_id': 'fixture',
       'status': 'completed', 'files': [], 'error': None}
CONNECTIONS = [{'connection_id': key, 'username': 'fixture-' + key, 'sharing': 'personal',
                'owner_id': 'fixture', 'scopes': ['read-repos', 'write-repos', 'manage-repos']} for key in ['a', 'b']]


def capture(page, name):
    if value := os.environ.get('ROSY_SHOT_DIR'):
        root = Path(value).expanduser(); root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / f'data-{name}.png'))


@pytest.fixture
def workspace(tmp_path):
    with serve(open_store(tmp_path)) as (page, _, expect):
        origin = '{0.scheme}://{0.netloc}'.format(urlsplit(page.url))
        state = {'status': 200, 'jobs': [copy.deepcopy(JOB)], 'gets': 0, 'hold_get': False, 'held_get': [],
                 'posts': [], 'post_status': 503, 'hold_post': False, 'held_post': [],
                 'connections': copy.deepcopy(CONNECTIONS), 'workspace_status': 200, 'links': [], 'configured': True}
        page.route('**/api/catalog', lambda route: route.fulfill(json={'token': 'fixture', 'catalog': '/fixture/original',
                   'cad_catalog': '/fixture/cad', 'imports': True, 'map_reference': None}))
        def imports(route):
            state['gets'] += 1
            if state['hold_get']: state['held_get'].append(route)
            else: route.fulfill(status=state['status'], json={'jobs': state['jobs']} if state['status'] == 200 else {'error': 'fixture list unavailable'})
        page.route('**/api/learning/imports', imports)
        def post(route):
            state['posts'].append((urlsplit(route.request.url).path, route.request.post_data_json))
            if state['hold_post']: state['held_post'].append(route)
            else: route.fulfill(status=state['post_status'], json={} if state['post_status'] == 200 else {'error': 'fixture operation rejected'})
        for path in ['review', 'retry', 'create']:
            page.route('**/api/learning/imports/' + path, post)
        page.route('**/api/accounts/repos/create', post)
        page.route('**/api/accounts/options', lambda route: route.fulfill(json={'enabled': True, 'oauth': False, 'rosy_account': True}))
        page.route('**/api/accounts/session', lambda route: route.fulfill(json={'token': 'fixture', 'user_id': 'fixture',
                   'project_id': 'alpha', 'capabilities': ['view', 'import', 'manage', 'publish'], 'connections': state['connections']}))
        page.route('**/api/learning/workspaces', lambda route: route.fulfill(status=state['workspace_status'],
                   json={'configured': state['configured'], 'workspaces': state['links']} if state['workspace_status'] == 200 else {'error': 'fixture workspace unavailable'}))
        yield page, state, origin, expect


@pytest.mark.parametrize('status,label', [('queued', '대기'), ('running', '가져오는 중'), ('failed', '실패'),
    ('interrupted', '중단됨'), ('cancelled', '취소됨'), ('blocked', '접근 차단'),
    ('rights_hold', '이용 권한 확인 필요'), ('future-state', '상태 확인 필요')])
@pytest.mark.parametrize('width', [320, 1440])
def test_catalog_import_states_follow_the_producer(workspace, status, label, width):
    page, state, origin, expect = workspace
    state['jobs'][0]['status'] = status
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(origin + '/catalog')
    expect(page.locator('#hf-imports ui-tag')).to_have_text(label)
    expect(page.locator('#hf-imports ui-button')).to_have_count(0)
    expect(page.locator('#hf-imports a[href="/accounts"]')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    capture(page, f'import-{status}-{width}')


@pytest.mark.parametrize('status', [401, 403, 503])
@pytest.mark.parametrize('width', [390, 1440])
def test_catalog_subread_failure_is_visible_and_recoverable(workspace, status, width):
    page, state, origin, expect = workspace
    state['hold_get'] = True
    page.set_viewport_size({'width': width, 'height': 900})
    with page.expect_request('**/api/learning/imports'):
        page.goto(origin + '/catalog')
    expect(page.locator('#hf-load')).to_have_attribute('state', 'pending')
    expect(page.locator('#import')).to_be_disabled()
    assert len(state['held_get']) == 1
    state['held_get'].pop().fulfill(status=status, json={'error': 'fixture list unavailable'})
    expect(page.locator('#hf-section')).to_be_visible()
    expect(page.locator('#hf-load')).to_have_attribute('state', 'error')
    expect(page.locator('#hf-retry')).to_be_enabled()
    if status in [401, 403]:
        expect(page.locator('#import')).to_be_disabled()
        expect(page.locator('#catalog-retry')).to_be_visible()
    capture(page, f'catalog-error-{status}-{width}')
    state['hold_get'] = False
    page.locator('#hf-retry').click()
    expect(page.locator('#hf-imports ui-tag')).to_have_text('검증 완료 · 보내기 전')
    expect(page.locator('#hf-load')).to_have_attribute('state', 'ready')
    expect(page.locator('#import')).to_be_enabled()
    assert not state['posts']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    capture(page, f'catalog-recovered-{status}-{width}')


def test_catalog_retry_preserves_drafts_and_marks_old_rows_unavailable(workspace):
    page, state, origin, expect = workspace
    page.goto(origin + '/catalog')
    send = page.locator('#hf-imports ui-button')
    expect(send).to_be_enabled()
    for key in ['catalog-path', 'cad-path', 'catalog-classes']: page.fill('#' + key, '/fixture/edited')
    state['status'] = 503
    page.locator('#hf-retry').click()
    expect(page.locator('#hf-load')).to_have_attribute('state', 'error')
    expect(send).to_be_disabled()
    state['status'] = 200
    page.locator('#hf-retry').click()
    expect(send).to_be_enabled()
    for key in ['catalog-path', 'cad-path', 'catalog-classes']:
        expect(page.locator('#' + key)).to_have_value('/fixture/edited')
    expect(page.locator('#hf-imports > article')).to_have_count(1)


@pytest.mark.parametrize('move_focus', [False, True])
def test_review_handoff_blocks_duplicate_actions_and_preserves_row_focus(workspace, move_focus):
    page, state, origin, expect = workspace
    state['jobs'].append(dict(JOB, id='c' * 32, repo_id='fixture/second'))
    state['hold_post'] = True
    page.goto(origin + '/catalog')
    buttons = page.locator('#hf-imports ui-button')
    expect(buttons).to_have_count(2)
    buttons.nth(0).click()
    for button in buttons.all(): expect(button).to_be_disabled()
    expect(page.locator('#import')).to_be_disabled()
    buttons.nth(1).dispatch_event('click')
    assert len(state['posts']) == 1 and len(state['held_post']) == 1
    capture(page, 'handoff-pending-' + str(move_focus))
    theme = page.locator('ui-topbar [data-theme-cycle]')
    if move_focus: theme.focus()
    state['jobs'][0]['review'] = {'added': 1, 'pixel_reviews_pending': 1, 'registered_by': 'fixture'}
    state['held_post'].pop().fulfill(json={})
    expect(page.locator('#hf-imports a[href="/?filter=pending"]')).to_be_visible()
    expect(theme if move_focus else page.locator('#hf-imports a[href="/?filter=pending"]')).to_be_focused()
    expect(page.locator('#hf-imports ui-button')).to_be_enabled()
    expect(page.locator('#import')).to_be_enabled()
    capture(page, 'handoff-received-' + str(move_focus))


def fill_import(page):
    for key, value in {'repo-id': 'fixture/data', 'revision': 'main', 'files': 'fixture.png',
                       'license': 'fixture', 'rights-evidence': 'synthetic permission'}.items(): page.fill('#' + key, value)
    page.check('#internal-use')


def ready_accounts(page, origin, expect):
    page.goto(origin + '/accounts')
    expect(page.locator('#account-status')).to_have_attribute('state', 'ready')
    expect(page.locator('#accounts-main')).to_have_attribute('aria-busy', 'false')


def test_account_write_error_survives_the_automatic_read_and_clears_on_retry(workspace):
    page, state, origin, expect = workspace
    state['jobs'][0]['status'] = 'failed'
    ready_accounts(page, origin, expect)
    retry = page.locator('#imports').get_by_role('button', name='같은 버전 재시도', exact=True)
    retry.click()
    expect(page.locator('#account-error')).to_contain_text('fixture operation rejected')
    page.locator('#account-error').scroll_into_view_if_needed()
    capture(page, 'account-operation-error')
    count = state['gets']
    page.wait_for_timeout(5500)
    assert state['gets'] > count
    expect(page.locator('#account-error')).to_contain_text('fixture operation rejected')
    state['status'] = 503
    page.wait_for_timeout(5500)
    expect(page.locator('#account-error')).to_contain_text('fixture list unavailable')
    state['status'] = 200
    page.wait_for_timeout(5500)
    expect(page.locator('#account-error')).not_to_contain_text('fixture list unavailable')
    expect(page.locator('#account-error')).to_contain_text('fixture operation rejected')
    state['post_status'] = 200
    retry.click()
    expect(page.locator('#account-error')).to_be_hidden()
    assert len(state['posts']) == 2


def test_account_refresh_keeps_both_selected_connections_and_request_identity(workspace):
    page, state, origin, expect = workspace
    ready_accounts(page, origin, expect)
    expect(page.locator('#connection option')).to_have_count(2)
    for key in ['connection', 'repo-connection']: page.select_option('#' + key, 'b')
    fill_import(page)
    page.fill('#manage-repo-id', 'fixture/keep')
    page.locator('#reload').click()
    expect(page.locator('#accounts-main')).to_have_attribute('aria-busy', 'false')
    for key in ['connection', 'repo-connection']: expect(page.locator('#' + key)).to_have_value('b')
    for key in ['connection', 'repo-connection']:
        page.locator('#' + key).scroll_into_view_if_needed()
        capture(page, 'account-preserved-' + key)
    expect(page.locator('#repo-id')).to_have_value('fixture/data')
    page.locator('#import-form').evaluate('form => form.requestSubmit()')
    expect(page.locator('#account-error')).to_contain_text('fixture operation rejected')
    assert state['posts'][-1][1]['connection_id'] == 'b'
    page.locator('#repo-create-form').evaluate('form => form.requestSubmit()')
    expect(page.locator('#accounts-main')).to_have_attribute('aria-busy', 'false')
    assert state['posts'][-1][0].endswith('/repos/create') and state['posts'][-1][1]['connection_id'] == 'b'


def test_removed_connection_requires_a_new_explicit_choice(workspace):
    page, state, origin, expect = workspace
    ready_accounts(page, origin, expect)
    expect(page.locator('#connection option')).to_have_count(2)
    for key in ['connection', 'repo-connection']: page.select_option('#' + key, 'b')
    fill_import(page)
    page.fill('#manage-repo-id', 'fixture/keep')
    state['connections'] = [CONNECTIONS[0]]
    page.locator('#reload').click()
    expect(page.locator('#accounts-main')).to_have_attribute('aria-busy', 'false')
    for key in ['connection', 'repo-connection']: expect(page.locator('#' + key)).to_have_value('')
    for key in ['connection', 'repo-connection']:
        page.locator('#' + key).scroll_into_view_if_needed()
        capture(page, 'account-reselect-' + key)
    page.locator('#import-form').evaluate('form => form.requestSubmit()')
    page.locator('#repo-create-form').evaluate('form => form.requestSubmit()')
    expect(page.locator('#account-error')).to_contain_text('관리 계정을 선택하세요')
    assert not state['posts']
    page.locator('#reload').click()
    expect(page.locator('#accounts-main')).to_have_attribute('aria-busy', 'false')
    for key in ['connection', 'repo-connection']: expect(page.locator('#' + key)).to_have_value('')


def test_first_available_connection_can_be_selected_after_initial_empty_state(workspace):
    page, state, origin, expect = workspace
    state['connections'] = []
    ready_accounts(page, origin, expect)
    state['connections'] = [CONNECTIONS[0]]
    page.locator('#reload').click()
    expect(page.locator('#accounts-main')).to_have_attribute('aria-busy', 'false')
    for key in ['connection', 'repo-connection']: expect(page.locator('#' + key)).to_have_value('a')


@pytest.mark.parametrize('status', [401, 403, 503])
@pytest.mark.parametrize('width', [390, 1440])
def test_workspaces_retry_recovers_without_duplicate_or_stale_links(workspace, status, width):
    page, state, origin, expect = workspace
    state['workspace_status'] = status
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(origin + '/learning/workspaces')
    expect(page.locator('#workspaces-status')).to_have_attribute('state', 'error')
    capture(page, f'workspaces-error-{status}-{width}')
    page.locator('#workspaces-retry').click()
    expect(page.locator('#workspaces-status')).to_have_attribute('state', 'error')
    state['workspace_status'] = 200
    state['links'] = [{'label': 'fixture workbench', 'kind': 'review', 'note': 'fixture', 'url': '/pixels'}]
    page.locator('#workspaces-retry').click()
    expect(page.locator('#workspaces > li')).to_have_count(2)
    expect(page.locator('#workspaces-status')).to_have_attribute('state', 'ready')
    expect(page.locator('#workspaces-retry')).to_be_focused()
    state['workspace_status'] = 503
    page.locator('#workspaces-retry').click()
    expect(page.locator('#workspaces-status')).to_have_attribute('state', 'error')
    expect(page.locator('#workspaces > li')).to_have_count(0)
    state.update(workspace_status=200, links=[], configured=False)
    page.locator('#workspaces-retry').click()
    expect(page.locator('#workspaces-status')).to_contain_text('설정이 없습니다')
    expect(page.locator('#workspaces > li')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    capture(page, f'workspaces-recovered-{status}-{width}')


def test_workspaces_retry_does_not_steal_focus_from_another_control(workspace):
    page, _, origin, expect = workspace
    page.goto(origin + '/learning/workspaces')
    expect(page.locator('#workspaces-retry')).to_be_enabled()
    held = []
    page.route('**/api/learning/workspaces', lambda route: held.append(route))
    page.locator('#workspaces-retry').click()
    expect(page.locator('#workspaces-retry')).to_be_disabled()
    theme = page.locator('ui-topbar [data-theme-cycle]')
    theme.focus()
    assert len(held) == 1
    held[0].fulfill(json={'configured': True, 'workspaces': []})
    expect(page.locator('#workspaces-retry')).to_be_enabled()
    expect(theme).to_be_focused()
