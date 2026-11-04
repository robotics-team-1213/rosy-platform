"""Local profile drafts survive replacement cancellation and same-tab navigation."""
import json
import threading
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


@pytest.fixture
def profile_editor(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    profile = {'schema': 'rosy.omx.learning-profile/1', 'name': 'Saved fixture', 'task': 'Fixture task',
        'mode': 'independent', 'arms': [{'id': 'arm', 'joint_names': ['joint'], 'units': 'rad'}],
        'cameras': [{'id': 'top', 'input_key': 'observation.images.top', 'arm_id': None, 'role': 'top',
            'source_identity': 'fixture:top', 'placement': 'overhead', 'shape': [3, 8, 8], 'purposes': ['policy']}]}
    row = {'id': '11111111-1111-4111-8111-111111111111', 'revision': 'a' * 64,
           'profile': profile, 'created_by': 'fixture'}
    records, saves = [row], []

    def save(body, actor=None):
        saves.append(body)
        saved = dict(row, id='22222222-2222-4222-8222-222222222222', revision='b' * 64, profile=body['profile'])
        records.append(saved)
        return saved

    center = SimpleNamespace(bind_workspace=lambda project: None, hub=SimpleNamespace(bundles=lambda: []),
        profiles=SimpleNamespace(list=lambda: records, save=save),
        snapshot=lambda: {'datasets': [{'id': 'fixture', 'name': 'Fixture', 'profile': profile}],
                          'runs': [], 'methods': {}})
    server = make_server(ReviewStore(tmp_path / 'review', empty_training=True), free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route('**/api/learning/tasks', lambda route: route.fulfill(json={
                    'project_id': 'fixture-project', 'tasks': [], 'robots': [], 'runs': []}))
                url = f'http://127.0.0.1:{server.server_port}/learning/omx?view=all'
                page.goto(url, wait_until='networkidle')
                if page.locator('#dataset option').count() > 1:
                    page.locator('#dataset').select_option(index=1)
                page.locator('#profile-panel').evaluate('node => node.open = true')
                page.locator('#profile-clone').click()
                yield page, playwright.expect, url, saves
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('replacement', ['profile-new', 'profile-clone', 'profile-import-dataset', 'profile-bench'])
def test_cancel_replacement_preserves_exact_unsaved_inputs(profile_editor, replacement):
    page, expect, _, saves = profile_editor
    page.locator('#profile-name').fill('  Unsaved input  ')
    if replacement == 'profile-bench':
        page.locator('#profile-bench').set_input_files({'name': 'inventory.json', 'mimeType': 'application/json',
            'buffer': json.dumps({'schema': 'rosy.omx-bench-inventory/1', 'draft': {
                'schema': 'rosy.omx.learning-profile/1', 'name': 'Imported', 'task': '', 'mode': '',
                'arms': [], 'cameras': []}}).encode()})
    else:
        page.locator('#'+replacement).click()
    expect(page.locator('dialog.ui-confirm')).to_be_visible()
    page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
    expect(page.locator('#profile-name')).to_have_value('  Unsaved input  ')
    expect(page.locator('#profile-arms > fieldset')).to_have_count(1)
    expect(page.locator('#profile-draft-status')).to_contain_text('로컬 초안')
    assert saves == []


def test_reload_and_navigation_restore_draft_without_selecting_saved_profile(profile_editor):
    page, expect, url, saves = profile_editor
    page.locator('#profile-name').fill('Recover this unsaved profile')
    page.on('dialog', lambda dialog: dialog.accept())
    page.reload(wait_until='networkidle')
    expect(page.locator('#profile-name')).to_have_value('Recover this unsaved profile')
    expect(page.locator('#profile-draft-status')).to_contain_text('로컬 초안')
    expect(page.locator('#selected-profile-status')).not_to_contain_text('11111111-1111-4111-8111-111111111111')
    page.goto(url.replace('/learning/omx?view=all', '/learning/tasks'), wait_until='networkidle')
    page.goto(url, wait_until='networkidle')
    expect(page.locator('#profile-name')).to_have_value('Recover this unsaved profile')
    page.locator('#profile-save').click()
    expect(page.locator('#profiles-status')).to_contain_text('새 불변 프로필 저장됨')
    assert len(saves) == 1
    page.reload(wait_until='networkidle')
    page.locator('#profile-panel').evaluate('node => node.open = true')
    expect(page.locator('#profile-name')).to_have_value('')


def test_storage_failure_warns_and_keeps_editor_usable(profile_editor):
    page, expect, _, saves = profile_editor
    page.evaluate("() => { Storage.prototype.setItem = () => { throw new DOMException('Full', 'QuotaExceededError'); }; }")
    page.locator('#profile-name').fill('Keep editing without storage')
    expect(page.locator('#profile-draft-status')).to_contain_text('보관하지 못')
    expect(page.locator('#profile-name')).to_have_value('Keep editing without storage')
    page.locator('#profile-save').click()
    expect(page.locator('#profiles-status')).to_contain_text('새 불변 프로필 저장됨')
    assert len(saves) == 1


def test_edit_during_save_keeps_newer_draft_after_reply_and_reload(profile_editor):
    page, expect, _, _ = profile_editor
    pending = []
    page.route('**/center/profile', lambda route: pending.append(route))
    page.locator('#profile-name').fill('Submitted snapshot')
    page.locator('#profile-save').click()
    expect(page.locator('#profile-name')).to_be_disabled()
    page.locator('#profile-name').evaluate("node => { node.value = 'Newer unsaved edit'; node.dispatchEvent(new Event('input')); }")
    assert len(pending) == 1
    body = pending[0].request.post_data_json
    assert body['profile']['name'] == 'Submitted snapshot'
    pending[0].fulfill(json={'id': '22222222-2222-4222-8222-222222222222', 'revision': 'b' * 64,
                             'profile': body['profile'], 'created_by': 'fixture'})
    expect(page.locator('#profile-name')).to_have_value('Newer unsaved edit')
    expect(page.locator('#profile-name')).to_be_enabled()
    page.on('dialog', lambda dialog: dialog.accept())
    page.reload(wait_until='networkidle')
    expect(page.locator('#profile-name')).to_have_value('Newer unsaved edit')


def test_draft_is_not_restored_in_another_project(profile_editor):
    page, expect, _, _ = profile_editor
    page.locator('#profile-name').fill('Project one private input')
    page.unroute('**/api/learning/tasks')
    page.route('**/api/learning/tasks', lambda route: route.fulfill(json={
        'project_id': 'other-project', 'tasks': [], 'robots': [], 'runs': []}))
    page.on('dialog', lambda dialog: dialog.accept())
    page.reload(wait_until='networkidle')
    page.locator('#profile-panel').evaluate('node => node.open = true')
    expect(page.locator('#profile-name')).to_have_value('')


def test_legacy_collaboration_users_have_separate_drafts_after_reload(profile_editor):
    page, expect, _, saves = profile_editor
    user = {'id': 'user-a'}
    page.route('**/api/accounts/options', lambda route: route.fulfill(json={
        'enabled': True, 'rosy_account': False}))
    page.route('**/api/accounts/session', lambda route: route.fulfill(json={
        'project_id': 'fixture-project', 'user_id': user['id'], 'capabilities': []}))
    page.on('dialog', lambda dialog: dialog.accept())
    page.reload(wait_until='networkidle')
    page.locator('#profile-panel').evaluate('node => node.open = true')
    page.locator('#profile-name').fill('User A private draft')
    page.reload(wait_until='networkidle')
    expect(page.locator('#profile-name')).to_have_value('User A private draft')
    user['id'] = 'user-b'
    page.reload(wait_until='networkidle')
    page.locator('#profile-panel').evaluate('node => node.open = true')
    expect(page.locator('#profile-name')).to_have_value('')
    page.locator('#profile-name').fill('User B private draft')
    user['id'] = 'user-a'
    page.reload(wait_until='networkidle')
    expect(page.locator('#profile-name')).to_have_value('User A private draft')
    assert saves == []


def test_context_query_change_keeps_the_same_editor_draft(profile_editor):
    page, expect, url, _ = profile_editor
    page.on('dialog', lambda dialog: dialog.accept())
    page.goto(url + '&task=stale-task', wait_until='networkidle')
    page.locator('#profile-panel').evaluate('node => node.open = true')
    page.locator('#profile-name').fill('Keep after context reset')
    page.evaluate("history.replaceState(null, '', '/learning/omx?view=all')")
    page.reload(wait_until='networkidle')
    expect(page.locator('#profile-name')).to_have_value('Keep after context reset')
