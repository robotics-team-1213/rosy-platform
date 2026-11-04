"""Operators pick Fleet-listed robots with the shared table; failures keep their selection."""
import copy
import json
import threading

import pytest
from browser_harness import browser_tests_enabled, free_port
from playwright.sync_api import expect, sync_playwright
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium owner list scenario')
DATA = {'project_id': 'fixture-project', 'token': 'fixture-token', 'profiles': [], 'robots': [], 'tasks': [],
        'datasets': [], 'runs': [], 'methods': {}}
LISTED = {'status': 'ok', 'reason': '', 'skipped': 1, 'checked_at': '2026-11-04T05:00:00+00:00', 'robots': [
    {'device_id': 'arm_s', 'name': 'Arm S', 'kind': 'omx', 'model_revision': 'OpenMANIPULATOR-X', 'online': False,
     'sources': ['profile'], 'registered': False},
    {'device_id': 'rosy_09', 'name': 'Pinky 09', 'kind': 'pinky', 'model_revision': 'unrecorded', 'online': True,
     'sources': ['roster', 'profile'], 'registered': False}]}


@pytest.fixture
def owner_page(tmp_path):
    server = make_server(ReviewStore(tmp_path / 'synthetic-review', empty_training=True), free_port())
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    state = {'data': copy.deepcopy(DATA), 'listed': copy.deepcopy(LISTED), 'posts': []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1366, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/learning/tasks**', lambda route: route.fulfill(json=state['data']))
            page.route('**/api/learning/robot-candidates', lambda route: route.fulfill(json=state['listed']))

            def register(route):
                body = json.loads(route.request.post_data)
                state['posts'].append(body)
                if body['device_id'] == 'rosy_09':
                    return route.fulfill(status=400, json={'error': 'fixture owner refused'})
                row = next(r for r in state['listed']['robots'] if r['device_id'] == body['device_id'])
                row['registered'] = True
                state['data']['robots'].append({'id': body['request_id'], 'name': row['name'], 'kind': row['kind'],
                    'model_revision': row['model_revision'], 'device_id': row['device_id'],
                    'owner': {'source': 'fleet'}})
                route.fulfill(json=state['data']['robots'][-1])
            page.route('**/api/learning/robots', register)
            yield page, state, f'http://127.0.0.1:{server.server_port}/learning/tasks/manage', errors
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_selected_owner_devices_register_and_failures_stay_selected(owner_page):
    page, state, url, errors = owner_page
    page.goto(url)
    expect(page.locator('#owner-state')).to_contain_text('등록 가능 2대')
    expect(page.locator('#owner-state')).to_contain_text('1대는 제외')
    table = page.locator('#owner-table')
    expect(table).to_contain_text('OMX 팔')
    expect(table).to_contain_text('장치 정보만 등록')
    expect(table).to_contain_text('모델 미기록')
    expect(page.locator('#robots ui-empty')).to_be_visible()
    register = page.locator('#owner-selection ui-button').filter(has_text='선택한 장치를 학습 로봇으로 등록')
    expect(register).to_have_attribute('reason', '항목을 먼저 선택하세요')
    page.get_by_label('Arm S 선택').check()
    page.get_by_label('Pinky 09 선택').check()
    expect(page.locator('#owner-selection')).to_contain_text('2개 선택')
    register.click()
    expect(page.locator('#tasks-error')).to_contain_text('Pinky 09: fixture owner refused')
    expect(page.locator('#owner-detail')).to_contain_text('1대 등록 · 1대 실패')
    expect(page.locator('#robots')).to_contain_text('Arm S')
    expect(page.locator('#robots')).to_contain_text('등록 때 확인')
    expect(page.get_by_label('Pinky 09 선택')).to_be_checked()
    expect(table).not_to_contain_text('Arm S')
    assert [set(body) for body in state['posts']] == [{'request_id', 'owner', 'device_id'}] * 2
    expect(page.locator('[data-robot]').first.locator('option').first).to_have_text('로봇 선택')
    assert not errors


@pytest.mark.parametrize('status,title', [('unconfigured', 'Fleet 연결 미설정'), ('unauthorized', 'Fleet 목록을 읽지 못했습니다')])
def test_owner_failures_explain_and_keep_manual_entry(owner_page, status, title):
    page, state, url, errors = owner_page
    state['listed'] = {'status': status, 'reason': f'fixture {status} reason', 'robots': [], 'skipped': 0}
    page.goto(url)
    expect(page.locator('#owner-state')).to_contain_text(title)
    expect(page.locator('#owner-state')).to_contain_text(f'fixture {status} reason')
    expect(page.locator('#owner-table')).to_be_hidden()
    toggle = page.locator('#robot-manual-toggle')
    expect(page.locator('#robot-form')).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute('aria-expanded', 'true')
    expect(page.locator('#robot-name')).to_be_focused()
    assert page.locator('#robot-kind option').all_inner_texts() == ['OMX 팔', 'Pinky 주행 로봇', '기타 로봇']
    assert not errors
