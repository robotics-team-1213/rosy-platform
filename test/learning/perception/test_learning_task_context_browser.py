"""Task navigation preserves loaded selections without admitting stale URL IDs."""
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from browser_harness import browser_tests_enabled
from test_omx_center_http import running

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def snapshot():
    profile = {'schema': 'rosy.omx.learning-profile/2', 'name': 'Fixture profile',
               'mode': 'independent', 'arms': [{'id': 'arm'}]}
    task = dict(id='task-one', name='Carry sample', objective='Deliver sample',
                success='Reaches tray', failure='Drops', reset='Return sample',
                adapter='omx', mode='independent', runnable=True, revision='a' * 64,
                profile_id='profile-one', profile_revision='b' * 64,
                participants=[dict(robot_id='robot-one', component_id='arm', role='carrier')])
    return dict(token='fixture-token', project_id='fixture', host_id='model',
                center_configured=True, sim_configured=False, sim_contexts=[],
                robots=[dict(id='robot-one', name='Fixture arm', kind='omx', device_id='fixture')],
                tasks=[task], profiles=[dict(id='profile-one', revision='b' * 64, profile=profile)],
                datasets=[dict(id='data-one', name='Synthetic fixture', revision='c' * 64,
                               source='synthetic_smoke', profile=profile)],
                methods={'act': {'available': True}}, runs=[
                    dict(id='run-one', status='succeeded', method='act', dataset_id='data-one',
                         learning_task={'task_id': 'task-one'}, result={'evaluation': {'frames': 4}})])


def test_task_url_restores_loaded_context_and_workbench_links(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    state = snapshot()
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 390, 'height': 844})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/learning/tasks', lambda route: route.fulfill(json=state))
            page.goto(base + '/learning/tasks?task=task-one&profile=profile-one&dataset=data-one')
            expect = playwright.expect
            expect(page.locator('#task-select')).to_have_value('task-one')
            expect(page.locator('#run-dataset')).to_have_value('data-one')
            for selector, section in [('#task-workbench-profile', 'profile-panel'),
                                      ('#task-workbench-review', 'dataset-section'),
                                      ('#task-workbench-training', 'train-section'),
                                      ('[data-task-run="run-one"] [data-task-comparison]', 'comparison-section')]:
                link = page.locator(selector)
                expect(link).to_have_attribute('href', re.compile('dataset=data-one'))
                parsed = urlsplit(link.get_attribute('href'))
                assert parsed.path == '/learning/omx' and parsed.fragment == section
                assert parse_qs(parsed.query) == dict(task=['task-one'], profile=['profile-one'], dataset=['data-one'])
            page.locator('#run-dataset').select_option('')
            assert 'dataset=' not in page.locator('#task-workbench-review').get_attribute('href')
            page.reload()
            expect(page.locator('#task-select')).to_have_value('task-one')
            expect(page.locator('#run-dataset')).to_have_value('')
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize('query', ['task=missing', 'profile=missing', 'dataset=missing',
                                  'task=task-one&profile=other', 'task=task-one&task=other'])
def test_stale_or_ambiguous_context_is_recoverable_without_substitution(tmp_path, query):
    playwright = pytest.importorskip('playwright.sync_api')
    state = snapshot()
    with running(tmp_path) as (base, _), playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/api/learning/tasks', lambda route: route.fulfill(json=state))
            page.goto(base + '/learning/tasks?' + query)
            expect = playwright.expect
            expect(page.locator('#tasks-context-error')).to_be_visible()
            expect(page.locator('#tasks-context-error')).to_contain_text('선택')
            expect(page.locator('#task-select')).to_have_value('')
            expect(page.locator('#run-dataset')).to_have_value('')
            expect(page.locator('#run-start')).to_be_disabled()
            page.locator('#tasks-context-reset').click()
            expect(page.locator('#tasks-context-error')).to_be_hidden()
            page.locator('#task-select').select_option('task-one')
            page.locator('#run-dataset').select_option('data-one')
            expect(page.locator('#run-start')).to_be_enabled()
            state['datasets'] = []
            page.locator('#tasks-refresh').click()
            expect(page.locator('#tasks-context-error')).to_be_visible()
            expect(page.locator('#run-start')).to_be_disabled()
        finally:
            browser.close()
