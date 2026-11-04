"""Task-first journey in Chromium; all learning data and actions are fixtures."""
import os
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')
TASK = 'c20a953e-1f03-43d3-9fbc-74f68b7af001'
PREPARED = 'a' * 32
REVIEW = 'c20a953e-1f03-43d3-9fbc-74f68b7af002'


@pytest.fixture
def workflow_page(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    center = SimpleNamespace(bind_workspace=lambda project: None,
        profiles=SimpleNamespace(list=lambda: []),
        snapshot=lambda: {'datasets': [], 'runs': [], 'methods': {}})
    server = make_server(ReviewStore(tmp_path / 'review', empty_training=True), free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            state = {'tasks': [], 'robots': [], 'profiles': [], 'datasets': [], 'runs': [],
                'methods': {}, 'token': 'fixture', 'host_id': 'model', 'native_inputs': [],
                'capabilities': {}, 'workflows': {}}
            page.route('**/api/learning/tasks', lambda route: route.fulfill(json=state))
            yield page, state, f'http://127.0.0.1:{server.server_port}', playwright.expect
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def selected(state, *, attached=False):
    source = {'prepared_id': PREPARED, 'name': 'Table demonstration', 'source_revision': 'b' * 64,
        'latest_review_id': REVIEW, 'trainable': {'ok': True}, 'fixture_only': False,
        'segment_review': {'version': 2, 'document': {'segments': []}}}
    state['tasks'] = [{'id': TASK, 'name': 'Move the cup', 'objective': 'Place cup on tray'}]
    state['native_inputs'] = [source]
    state['workflows'][TASK] = {'task_id': TASK, 'stage': 'learn' if attached else 'record',
        'blocked_reason': '' if attached else '실물 조종·녹화 연결이 준비되지 않았습니다.',
        'next_action': {'kind': 'learn' if attached else 'attach', 'label': '학습 준비' if attached else '기존 시연 연결',
            'href': '#workflow-learn' if attached else '#workflow-prepare'},
        'completion': {'recording_complete': False, 'review_complete': attached,
            'training_complete': False, 'offline_evaluation_complete': False,
            'physical_evaluation_complete': False, 'application_approved': False},
        'inputs': [source] if attached else [], 'runs': [],
        'setup': {'arms': [{'id': 'arm', 'joint_names': ['joint'], 'units': 'rad'}],
            'cameras': [{'id': 'top', 'role': 'top'}], 'device_verified': False},
        'methods': [{'id': 'act', 'label': '사람의 시연 따라 배우기', 'state': 'available', 'reason': '', 'requirements': []},
            {'id': 'hilserl', 'label': '사람 개입 강화학습', 'state': 'unavailable',
             'reason': '실행 환경과 보상 준비가 필요합니다.', 'requirements': ['보상', '초기화']}],
        'recording': {'available': False, 'reason': '실물 조종·녹화 연결이 준비되지 않았습니다.', 'task_card_export': True}}
    return source, state['workflows'][TASK]


def test_empty_task_entry_and_expert_management(workflow_page):
    page, state, base, expect = workflow_page
    page.goto(base + '/learning/tasks', wait_until='networkidle')
    expect(page.get_by_role('heading', name='학습 과제', exact=True)).to_be_visible()
    expect(page.get_by_role('link', name='새 학습 과제', exact=True)).to_have_attribute('href', '/learning/tasks/manage#task-title')
    expect(page.locator('#workflow-empty')).to_be_visible()
    expect(page.get_by_role('link', name='전문가 설정', exact=True)).to_have_attribute('href', '/learning/tasks/manage')
    assert page.locator('#robot-form').count() == 0


def test_selected_task_reopens_and_explicitly_attaches_native_input(workflow_page):
    page, state, base, expect = workflow_page
    source, flow = selected(state)
    posts = []
    def attach(route):
        posts.append(route.request.post_data_json)
        flow['inputs'] = [source]
        route.fulfill(json={'ok': True})
    page.route('**/api/learning/tasks/native-input', attach)
    page.goto(base + '/learning/tasks', wait_until='networkidle')
    page.get_by_role('link', name='Move the cup · 이어서 하기').click()
    expect(page).to_have_url(base + '/learning/tasks?task=' + TASK)
    expect(page.locator('#workflow-stage-track .ui-stage')).to_have_count(5)
    expect(page.locator('#workflow-record')).to_contain_text('실물 조종·녹화 연결이 준비되지 않았습니다.')
    assert not posts
    page.locator('#workflow-native-source').select_option(PREPARED)
    page.locator('#workflow-attach').click()
    expect(page.locator('#workflow-inputs')).to_contain_text('Table demonstration')
    assert posts[0]['task_id'] == TASK
    assert posts[0]['source_revision'] == source['source_revision']
    page.reload(wait_until='networkidle')
    expect(page.locator('#workflow-task-title')).to_have_text('Move the cup')
    expect(page.locator('#workflow-inputs')).to_contain_text('Table demonstration')
    expect(page.locator('#workflow-record-start')).to_be_disabled()


def test_review_train_retry_stop_and_vector_result(workflow_page):
    page, state, base, expect = workflow_page
    source, flow = selected(state, attached=True)
    posts, stops = [], []
    def start(route):
        posts.append(route.request.post_data_json)
        if len(posts) == 1:
            route.fulfill(status=503, json={'error': 'reply lost'})
        else:
            flow['runs'] = [{'id': 'fixture-run', 'status': 'running', 'native': True}]
            route.fulfill(json=flow['runs'][0])
    def stop(route):
        stops.append(route.request.post_data_json)
        flow['runs'][0].update(status='cancelled')
        route.fulfill(json=flow['runs'][0])
    page.route('**/api/learning/omx/center/native-run', start)
    page.route('**/api/learning/omx/center/stop', stop)
    page.goto(base + '/learning/tasks?task=' + TASK, wait_until='networkidle')
    expect(page.locator('#workflow-review-link')).to_have_attribute('href', f'/learning/omx?task={TASK}&prepared={PREPARED}#dataset-section')
    expect(page.locator('#workflow-train-start')).to_be_disabled()
    page.locator('#workflow-review-selection').select_option('episodes')
    page.locator('#workflow-train-start').click()
    expect(page.locator('#workflow-error')).to_contain_text('reply lost')
    page.locator('#workflow-train-start').click()
    expect(page.locator('#workflow-runs')).to_contain_text('학습 중')
    assert posts[0] == posts[1]
    assert posts[0]['task_id'] == TASK and posts[0]['compute_host'] == 'model'
    assert posts[0]['review_id'] == REVIEW and posts[0]['prepared_id'] == PREPARED
    page.get_by_role('button', name='이 학습 중지').click()
    expect(page.locator('#workflow-runs')).to_contain_text('취소됨')
    assert stops == [{'id': 'fixture-run'}]
    flow['runs'] = [{'id': 'fixture-run', 'status': 'succeeded', 'native': True,
        'result': {'evaluation': {'joint_names': ['shoulder_pan.pos', 'elbow.pos'],
            'mae_per_joint': [0.125, 0.125], 'train_mean_baseline_mae_per_joint': [0.25, 0.25],
            'samples': 4, 'split': 'eval', 'model_reloaded_in_new_process': True,
            'physical_task_success': None}}}]
    flow['stage'] = 'results'
    flow['completion'].update(training_complete=True, offline_evaluation_complete=True)
    page.reload(wait_until='networkidle')
    expect(page.locator('#workflow-runs')).to_contain_text('0.125')
    expect(page.locator('#workflow-results')).to_contain_text('실물 평가')
    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
        page.get_by_role('tab', name='결과', exact=True).click()
        target = Path(output)
        target.mkdir(parents=True, exist_ok=True)
        for theme in ('dark', 'light'):
            page.evaluate('theme => window.RosyTheme.set(theme)', theme)
            for width, height in ((1366, 768), (390, 844), (320, 568)):
                page.set_viewport_size({'width': width, 'height': height})
                page.evaluate('() => { document.activeElement?.blur(); window.scrollTo(0, 0); }')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(target / f'learning-workflow-results-{theme}-{width}x{height}.png'), full_page=True)


def test_recording_card_uses_explicit_options_without_device_execution(workflow_page, tmp_path):
    import json
    page, state, base, expect = workflow_page
    selected(state)
    posts = []
    def prepare(route):
        posts.append(route.request.post_data_json)
        route.fulfill(json={'card': {'schema': 'rosy.omx-task-card.v1', 'fixture_only': True},
            'filename': 'fixture-recording.json', 'device_execution': False,
            'requires_owner_preflight': True})
    page.route('**/api/learning/tasks/recording-card', prepare)
    page.goto(base + '/learning/tasks?task=' + TASK, wait_until='networkidle')
    page.get_by_text('현장 녹화 준비 안내', exact=True).click()
    for key in ('root', 'episode', 'reset', 'count'):
        expect(page.locator('#workflow-card-' + key)).to_have_value('')
    for key, value in [('root', '/fixture/recordings'), ('episode', '30'), ('reset', '10'), ('count', '2')]:
        page.locator('#workflow-card-' + key).fill(value)
    with page.expect_download() as downloaded:
        page.locator('#workflow-card-export').click()
    target = tmp_path / 'recording-card.json'
    downloaded.value.save_as(target)
    assert json.loads(target.read_text())['fixture_only'] is True
    assert posts == [{'task_id': TASK, 'record': {'root_prefix': '/fixture/recordings',
        'episode_time_s': 30, 'reset_time_s': 10, 'num_episodes': 2}}]
    expect(page.locator('#workflow-card-status')).to_contain_text('녹화나 장치 동작은 시작되지 않았습니다.')
    expect(page.locator('#workflow-record-start')).to_be_disabled()


def test_completion_uses_backend_evidence_flags(workflow_page):
    page, state, base, expect = workflow_page
    _, flow = selected(state, attached=True)
    flow.update(stage='results', blocked_reason='')
    flow['completion'].update(recording_complete=True, review_complete=True,
        training_complete=True, offline_evaluation_complete=True)
    page.goto(base + '/learning/tasks?task=' + TASK, wait_until='networkidle')
    for stage in ('record', 'review', 'learn'):
        expect(page.locator(f'#workflow-tab-{stage}').locator('..')).to_have_attribute('data-state', 'done')
    for key in ('recording_complete', 'review_complete', 'training_complete', 'offline_evaluation_complete'):
        expect(page.locator(f'[data-evidence="{key}"]')).to_have_text('완료 근거 있음')
    for key in ('physical_evaluation_complete', 'application_approved'):
        expect(page.locator(f'[data-evidence="{key}"]')).to_have_text('미확인')
    flow['completion'].update(physical_evaluation_complete=True, application_approved=True)
    page.reload(wait_until='networkidle')
    for key in ('physical_evaluation_complete', 'application_approved'):
        expect(page.locator(f'[data-evidence="{key}"]')).to_have_text('완료 근거 있음')


def test_integrity_refresh_is_explicit_while_status_polls_use_cache(workflow_page):
    page, state, base, expect = workflow_page
    state.update(native_inputs_checked_at='2026-10-29T09:00:00+00:00', native_inputs_cached=True)
    page.route('**/api/learning/tasks/native-inputs', lambda route: route.fulfill(json={'native_inputs': []}))
    page.add_init_script("""(() => {
        const fetch = window.fetch.bind(window), interval = window.setInterval.bind(window);
        window.__workflowRequests = [];
        window.fetch = (url, options) => {
            if (String(url).startsWith('/api/learning/tasks')) window.__workflowRequests.push(String(url));
            return fetch(url, options);
        };
        window.setInterval = (callback, delay, ...args) => interval(callback, delay === 5000 ? 200 : delay, ...args);
    })();""")
    page.goto(base + '/learning/tasks', wait_until='domcontentloaded')
    page.wait_for_function("() => window.__workflowRequests.filter(url => url === '/api/learning/tasks').length >= 3")
    calls = page.evaluate('window.__workflowRequests')
    assert calls[:2] == ['/api/learning/tasks/native-inputs', '/api/learning/tasks']
    assert calls.count('/api/learning/tasks/native-inputs') == 1
    expect(page.locator('#workflow-status')).to_contain_text('자료 확인 시각')
    expect(page.locator('#workflow-status')).to_contain_text('다시 확인으로 갱신')
    page.locator('#workflow-refresh').click()
    page.wait_for_function("() => window.__workflowRequests.filter(url => url === '/api/learning/tasks/native-inputs').length === 2")


def test_task_tabs_keep_one_panel_and_keyboard_selection_across_refresh(workflow_page):
    page, state, base, expect = workflow_page
    selected(state, attached=True)
    page.goto(base + '/learning/tasks?task=' + TASK, wait_until='networkidle')
    tabs = page.get_by_role('tablist', name='과제 작업')
    expect(tabs.get_by_role('tab')).to_have_count(5)
    expect(page.get_by_role('tabpanel')).to_have_count(1)
    expect(tabs.get_by_role('tab', name='학습', exact=True)).to_have_attribute('aria-selected', 'true')
    tabs.get_by_role('tab', name='결과', exact=True).click()
    expect(page).to_have_url(base + '/learning/tasks?task=' + TASK + '#workflow-results')
    expect(page.locator('#workflow-learn')).to_be_hidden()
    page.locator('#workflow-refresh').click()
    expect(tabs.get_by_role('tab', name='결과', exact=True)).to_have_attribute('aria-selected', 'true')
    page.reload(wait_until='networkidle')
    expect(page.locator('#workflow-results')).to_be_visible()
    tabs.get_by_role('tab', name='결과', exact=True).focus()
    page.keyboard.press('Home')
    expect(tabs.get_by_role('tab', name='준비', exact=True)).to_be_focused()
    expect(page.locator('#workflow-prepare')).to_be_visible()
    page.keyboard.press('ArrowRight')
    expect(page.locator('#workflow-record')).to_be_visible()
    expect(page.get_by_role('tabpanel')).to_have_count(1)


def test_launch_stop_pending_and_failed_run_have_distinct_recovery_states(workflow_page):
    page, state, base, expect = workflow_page
    _, flow = selected(state, attached=True)
    flow['stage'] = 'results'
    flow['runs'] = [{'id':'fixture-run', 'status':'launching', 'native':True}]
    def stop(route):
        flow['runs'][0]['status'] = 'stopping'
        route.fulfill(json={'id':'fixture-run','status':'stopping'})
    page.route('**/api/learning/omx/center/stop', stop)
    page.goto(base+'/learning/tasks?task='+TASK, wait_until='networkidle')
    expect(page.locator('#workflow-runs')).to_contain_text('시작 준비 중')
    page.get_by_role('button', name='이 학습 중지').click()
    expect(page.get_by_role('button', name='중지 처리 중', exact=True)).to_be_disabled()
    flow['runs'][0].update(status='failed', error='fixture recovery reason')
    page.locator('#workflow-refresh').click()
    expect(page.locator('#workflow-runs')).to_contain_text('fixture recovery reason')
    expect(page.locator('#workflow-runs').get_by_role('link')).to_have_count(0)
    expect(page.locator('[data-evidence="offline_evaluation_complete"]')).to_have_text('미확인')


def test_reopening_active_task_exposes_status_and_stop(workflow_page):
    page,state,base,expect = workflow_page
    _,flow = selected(state,attached=True)
    flow['runs'] = [{'id':'fixture-run','status':'running','native':True}]
    flow['next_action'] = {'label':'진행 중인 학습 확인','href':'#workflow-results'}
    page.goto(base+'/learning/tasks?task='+TASK,wait_until='networkidle')
    expect(page.get_by_role('tab',name='결과',exact=True)).to_have_attribute('aria-selected','true')
    expect(page.get_by_role('button',name='이 학습 중지')).to_be_visible()
    page.get_by_role('tab',name='학습',exact=True).click()
    page.locator('#workflow-next').click()
    expect(page.get_by_role('button',name='이 학습 중지')).to_be_visible()


def test_review_selects_an_explicit_source_shared_with_training(workflow_page):
    page,state,base,expect = workflow_page
    source,flow = selected(state,attached=True)
    other = dict(source,prepared_id='d'*32,name='Second demonstration')
    state['native_inputs'].append(other)
    flow['inputs'].append(other)
    page.goto(base+'/learning/tasks?task='+TASK,wait_until='networkidle')
    page.get_by_role('tab',name='검수',exact=True).click()
    expect(page.locator('#workflow-review-link')).to_be_hidden()
    page.get_by_label('작업할 시연',exact=True).select_option(other['prepared_id'])
    expect(page.locator('#workflow-review-summary')).to_contain_text('Second demonstration')
    expect(page.locator('#workflow-review-link')).to_have_attribute('href',f'/learning/omx?task={TASK}&prepared={other["prepared_id"]}#dataset-section')
    page.get_by_role('tab',name='학습',exact=True).click()
    page.locator('#workflow-refresh').click()
    expect(page.locator('#workflow-train-source')).to_have_value(other['prepared_id'])


def test_selected_task_expert_link_retains_task_profile_and_dataset(workflow_page):
    page, state, base, expect = workflow_page
    selected(state)
    state['tasks'][0]['profile_id'] = 'profile-one'
    page.goto(base+'/learning/tasks?task='+TASK+'&dataset=data-one',wait_until='networkidle')
    expected='/learning/tasks/manage?task='+TASK+'&dataset=data-one&profile=profile-one#run-title'
    expect(page.locator('#workflow-expert-link')).to_have_attribute('href',expected)
