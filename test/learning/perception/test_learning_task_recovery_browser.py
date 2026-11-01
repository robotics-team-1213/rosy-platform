"""Read recovery and progress updates must not erase action errors or keyboard context."""
import copy
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled, free_port
from playwright.sync_api import expect, sync_playwright
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium task scenario')
TASK = {'id': 'task-1', 'name': 'Fixture task', 'revision': 1, 'objective': 'Move fixture',
        'success': 'At target', 'failure': 'Dropped', 'reset': 'Return', 'mode': 'independent',
        'runnable': True, 'participants': [{'robot_id': 'robot-1', 'component_id': 'arm', 'role': 'primary'}]}
DATA = {'project_id': 'fixture-project', 'token': 'fixture-token', 'profiles': [],
        'robots': [{'id': 'robot-1', 'name': 'Fixture robot', 'kind': 'omx', 'device_id': 'fixture-arm'}],
        'tasks': [TASK], 'datasets': [{'id': 'initial', 'name': 'Initial', 'revision': 'a'},
                                    {'id': 'extra', 'name': 'Extra', 'revision': 'b'}],
        'runs': [{'id': 'run-1', 'method': 'hilserl', 'status': 'running', 'execution_mode': 'online_experience',
                  'dataset_id': 'initial', 'inputs': [], 'progress': {'tick': 0},
                  'learning_task': {'task_id': 'task-1'}}],
        'methods': {'act': {'available': True}, 'hilserl': {'available': True}}}


def capture(page, name):
    if value := os.environ.get('ROSY_SHOT_DIR'):
        root = Path(value).expanduser(); root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / f'learning-{name}.png'))


@pytest.fixture
def task_page(tmp_path):
    server = make_server(ReviewStore(tmp_path / 'synthetic-review', empty_training=True), free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    state = {'status': 200, 'gets': 0, 'data': copy.deepcopy(DATA)}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 390, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            def serve(route):
                if route.request.method == 'GET':
                    state['gets'] += 1
                    route.fulfill(status=state['status'], json=state['data'] if state['status'] == 200 else {'error': 'fixture read failed'})
                else:
                    route.fulfill(status=503, json={'error': 'fixture save rejected'})
            page.route('**/api/learning/tasks**', serve)
            page.route('**/api/learning/robots', serve)
            yield page, state, f'http://127.0.0.1:{server.server_port}/learning/tasks', errors
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


@pytest.mark.parametrize('status', [401, 503])
def test_automatic_read_recovery_clears_only_the_read_error(task_page, status):
    page, state, url, errors = task_page
    state['status'] = status
    page.goto(url)
    expect(page.locator('#tasks-error')).to_be_visible()
    capture(page, f'read-error-{status}')
    state['status'] = 200
    expect(page.locator('#tasks-status')).to_contain_text('최신 기록 확인됨', timeout=9000)
    expect(page.locator('#tasks-error')).to_be_hidden()
    capture(page, f'read-recovered-{status}')
    assert not errors


def test_failed_save_message_survives_successful_background_reads(task_page):
    page, state, url, errors = task_page
    page.goto(url)
    expect(page.locator('#tasks-status')).to_contain_text('최신 기록 확인됨')
    for key in ['robot-name', 'robot-kind', 'robot-model', 'robot-device']:
        page.locator('#' + key).fill('fixture-value')
    page.locator('#robot-save').click()
    expect(page.locator('#tasks-error')).to_contain_text('fixture save rejected')
    state['status'] = 503
    expect(page.locator('#tasks-error')).to_contain_text('fixture read failed', timeout=9000)
    state['status'] = 200
    expect(page.locator('#tasks-status')).to_contain_text('최신 기록 확인됨', timeout=9000)
    expect(page.locator('#tasks-error')).to_contain_text('fixture save rejected')
    assert not errors


@pytest.mark.parametrize('control', ['select', '[data-experience-submit]', '[data-run-stop]'])
def test_progress_poll_preserves_action_focus_and_completion_returns_to_heading(task_page, control):
    page, state, url, errors = task_page
    page.goto(url)
    page.select_option('#task-select', 'task-1')
    panel = page.locator('[data-continuous-run="run-1"]')
    expect(panel).to_be_visible()
    panel.locator('select').select_option('extra')
    panel.locator(control).focus()
    state['data']['runs'][0]['progress']['tick'] = 1
    count = state['gets']
    page.wait_for_timeout(5500)
    assert state['gets'] > count
    expect(panel.locator(control)).to_be_focused()
    expect(panel.locator('select')).to_have_value('extra')
    capture(page, 'focus-' + control.replace('[', '').replace(']', ''))
    state['data']['runs'][0]['status'] = 'succeeded'
    page.wait_for_timeout(5500)
    expect(page.locator('#task-runs article h3')).to_be_focused()
    expect(panel).to_have_count(0)
    assert not errors


@pytest.mark.parametrize('width', [320, 390, 768, 1440])
def test_review_shell_is_in_the_first_response_without_javascript(task_page, width):
    fixture, _, url, _ = task_page
    origin = urlsplit(url).scheme + '://' + urlsplit(url).netloc
    routes = ['/', '/learning', '/catalog', '/pixels', '/accounts', '/learning/tasks',
              '/learning/omx', '/learning/sim', '/learning/vlm', '/learning/evaluate',
              '/learning/camera', '/learning/workspaces']
    for route in routes:
        page = fixture.context.browser.new_page(viewport={'width': width, 'height': 900}, java_script_enabled=False)
        response = page.goto(origin + route)
        assert '<!-- review:header:start -->' in response.text(), route
        assert '<!-- review:rail:start -->' in response.text(), route
        expect(page.locator('ui-topbar ui-brand')).to_have_count(1)
        expect(page.locator('ui-topbar [data-theme-cycle]')).to_have_count(1)
        expect(page.locator('.ui-rail-nav > a')).to_have_count(5)
        box = page.locator('ui-topbar').bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1, (route, box)
        if route in ['/accounts', '/learning/tasks', '/catalog', '/learning/evaluate']:
            capture(page, f'shell-{width}-' + route.rsplit('/', 1)[-1])
        page.close()
