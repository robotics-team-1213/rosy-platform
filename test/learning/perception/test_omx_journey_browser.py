"""Task-scoped demonstration workbench keeps context and recovery visible."""
from urllib.parse import parse_qs, urlsplit

import pytest

from browser_harness import browser_tests_enabled
from test_omx_center_http import running

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def configure_snapshots(page):
    profile = dict(schema='rosy.omx.learning-profile/1', name='Fixture rig', task='Move sample',
                   mode='independent', arms=[dict(id='arm', joint_names=['joint'], units='rad')],
                   cameras=[dict(id='top', input_key='observation.images.top', arm_id=None,
                                 role='top', source_identity='fixture', placement='fixture',
                                 shape=[3, 8, 8], purposes=['policy'])])
    record = dict(id='profile-one', revision='a' * 64, profile=profile, created_by='fixture')
    datasets = [dict(id=key, name=key, revision='b' * 64, source='synthetic_smoke', profile=profile)
                for key in ['data-one', 'data-two']]
    task = dict(id='task-one', name='Move sample task', revision='c' * 64,
                profile_id=record['id'], profile_revision=record['revision'], profile=record,
                success='Reaches tray', failure='Drops', reset='Return sample', runnable=True)
    center = dict(datasets=datasets, runs=[], methods={'act': dict(available=True, devices=['cpu'])})
    tasks = dict(tasks=[task], profiles=[record], datasets=datasets, runs=[], project_id='fixture')
    page.route('**/api/learning/omx/center', lambda route: route.fulfill(json=center))
    page.route('**/api/learning/omx/center/profiles', lambda route: route.fulfill(json={'profiles': [record]}))
    page.route('**/api/learning/tasks', lambda route: route.fulfill(json=tasks))
    return center, tasks


@pytest.mark.parametrize('width,height', [(1366, 768), (390, 844)])
def test_empty_workbench_primary_action_is_above_fold(tmp_path, width, height):
    playwright = pytest.importorskip('playwright.sync_api')
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': height})
            page.goto(base + '/learning/omx')
            playwright.expect(page.locator('#journey-next')).to_be_visible()
            box = page.locator('#journey-next').bounding_box()
            assert box['y'] + box['height'] < height
            assert not page.locator('#learning-entry-heading').evaluate('n => n.parentElement.open')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


def test_task_workbench_restores_context_and_routes_training_to_task(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            configure_snapshots(page)
            page.goto(base + '/learning/omx?task=task-one&profile=profile-one&dataset=data-two#train-section')
            expect = playwright.expect
            expect(page.locator('#dataset')).to_have_value('data-two')
            expect(page.locator('#journey-task-status')).to_contain_text('Move sample task')
            expect(page.locator('#selected-profile-status')).to_contain_text('profile-one')
            link = page.locator('#journey-task-link')
            expect(link).to_contain_text('과제')
            assert urlsplit(link.get_attribute('href')).path == '/learning/tasks/manage'
            query = parse_qs(urlsplit(link.get_attribute('href')).query)
            assert query == dict(task=['task-one'], profile=['profile-one'], dataset=['data-two'])
            expect(page.locator('#start')).to_be_disabled()
            assert not errors
        finally:
            browser.close()


def test_stale_context_blocks_training_and_offers_explicit_reset(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            configure_snapshots(page)
            page.goto(base + '/learning/omx?task=missing&dataset=data-two#train-section')
            expect = playwright.expect
            expect(page.locator('#journey-context-status')).to_contain_text('찾을 수 없')
            expect(page.locator('#journey-context-reset')).to_be_visible()
            expect(page.locator('#start')).to_be_disabled()
            page.locator('#journey-context-reset').click()
            expect(page.locator('#journey-context-status')).to_have_text('')
            assert 'task' not in parse_qs(urlsplit(page.url).query)
        finally:
            browser.close()


def test_collection_plan_pins_result_and_data_without_posting_evidence(tmp_path):
    import json
    from pathlib import Path
    playwright = pytest.importorskip('playwright.sync_api')
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            center, _ = configure_snapshots(page)
            center['runs'] = [dict(id='run-one', dataset_id='data-two', dataset_revision='b' * 64,
                method='act', status='succeeded', learning_task={'task_id': 'task-one'},
                result={'version': '000003', 'evaluation': {'frames': 4, 'action_mae': .2}})]
            writes = []
            page.on('request', lambda req: writes.append(req.url) if req.method == 'POST' else None)
            page.goto(base + '/learning/omx?task=task-one&profile=profile-one&dataset=data-two#comparison-section')
            page.locator('#followup-run').select_option('run-one')
            page.locator('#followup-observation').fill('Check recovery after object occlusion')
            page.locator('#followup-next').fill('Record independent occlusion recovery demonstrations')
            with page.expect_download() as event:
                page.locator('#followup-download').click()
            plan = json.loads(Path(event.value.path()).read_text())
            assert plan['run_id'] == 'run-one' and plan['dataset_id'] == 'data-two'
            assert plan['dataset_revision'] == 'b' * 64 and plan['task_revision'] == 'c' * 64
            assert plan['evidence_status'] == 'operator_plan_only'
            assert plan['policy_version'] == '000003'
            assert plan['next_demonstration'] == 'Record independent occlusion recovery demonstrations'
            assert not writes
        finally:
            browser.close()


def test_workbench_rechecks_removed_task_on_refresh(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            _, tasks = configure_snapshots(page)
            page.goto(base + '/learning/omx?task=task-one&profile=profile-one&dataset=data-two#train-section')
            playwright.expect(page.locator('#journey-task-status')).to_contain_text('Move sample task')
            tasks['tasks'] = []
            page.locator('#refresh').click()
            playwright.expect(page.locator('#journey-context-status')).to_contain_text('찾을 수 없')
            playwright.expect(page.locator('#start')).to_be_disabled()
        finally:
            browser.close()


def test_profile_only_context_follows_explicit_selection_and_clear(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            _, tasks = configure_snapshots(page)
            second = dict(tasks['profiles'][0], id='profile-two', revision='d' * 64)
            tasks['profiles'].append(second)
            page.route('**/api/learning/omx/center/profiles', lambda route: route.fulfill(json={'profiles': tasks['profiles']}))
            page.goto(base + '/learning/omx?view=all&profile=profile-one#profile-panel')
            playwright.expect(page.locator('#selected-profile-status')).to_contain_text('profile-one')
            page.locator('#profile-record').select_option('profile-two')
            page.locator('#profile-use').click()
            playwright.expect(page.locator('#selected-profile-status')).to_contain_text('profile-two')
            assert parse_qs(urlsplit(page.url).query)['profile'] == ['profile-two']
            page.reload()
            playwright.expect(page.locator('#selected-profile-status')).to_contain_text('profile-two')
            page.locator('#profile-clear').click()
            assert 'profile' not in parse_qs(urlsplit(page.url).query)
            page.reload()
            playwright.expect(page.locator('#selected-profile-status')).to_contain_text('선택 없음')
        finally:
            browser.close()
