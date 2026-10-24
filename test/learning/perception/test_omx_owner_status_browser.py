"""Real Chromium checks observer selection, failure clearing and no control claim."""
import threading
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


@pytest.fixture
def empty_learning_center(tmp_path):
    center = SimpleNamespace(bind_workspace=lambda project: None,
        profiles=SimpleNamespace(list=lambda: []),
        snapshot=lambda: {'datasets': [], 'runs': [], 'methods': {},
            'owner_status': {'configured': False, 'targets': []}})
    server = make_server(ReviewStore(tmp_path/'review', empty_training=True),
                         free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('width', [1440, 390])
def test_purposeful_workspace_keeps_goal_and_explains_one_next_action(empty_learning_center, width):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            expect = playwright.expect
            page.goto(empty_learning_center+'/learning/omx', wait_until='networkidle')
            expect(page.locator('#journey-goal')).to_contain_text('아직 선택하지 않았습니다')
            expect(page.locator('#journey-next')).to_have_attribute('href', '#profile-panel')
            expect(page.locator('#journey-reason')).to_contain_text('같은 과제')
            expect(page.locator('#stage-question')).to_contain_text('무엇을 성공')
            expect(page.locator('#profile-panel')).to_be_visible()
            expect(page.locator('#train-section')).to_be_hidden()
            page.locator('#profile-task').fill('블록을 집고 유지 · 낙하 실패 · 트레이 복원')
            page.locator('#profile-add-arm').click()
            page.locator('#workflow-view').click()
            expect(page.locator('#train-section')).to_be_visible()
            expect(page.locator('#profile-task')).to_have_value('블록을 집고 유지 · 낙하 실패 · 트레이 복원')
            page.go_back()
            expect(page.locator('#train-section')).to_be_hidden()
            expect(page.locator('#profile-arms > fieldset')).to_have_count(1)
            page.locator('#workflow-view').click()
            page.locator('#workflow-view').click()
            expect(page.locator('#profile-task')).to_have_value('블록을 집고 유지 · 낙하 실패 · 트레이 복원')
            page.locator('#omx-sections a[href="#capture-section"]').click()
            page.wait_for_function('document.querySelector("#stage-question").getBoundingClientRect().top >= document.querySelector("ui-topbar").getBoundingClientRect().bottom - 1')
            expect(page.locator('#stage-purpose')).to_contain_text('영상만')
            expect(page.locator('#stage-done')).to_contain_text('행동')
            expect(page.locator('#capture-section')).to_contain_text('아직 연결되지 않았습니다')
            expect(page.locator('#profile-panel')).to_be_hidden()
            expect(page.locator('#journey-goal')).to_contain_text('아직 선택하지 않았습니다')
            page.locator('#stage-next').click()
            expect(page.locator('#dataset-section')).to_be_visible()
            expect(page.locator('#stage-question')).to_contain_text('학습에 쓸 수')
            page.locator('#omx-sections a[href="#profile-panel"]').click()
            expect(page.locator('#profile-task')).to_have_value('블록을 집고 유지 · 낙하 실패 · 트레이 복원')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        finally:
            browser.close()


def test_next_action_uses_matching_evidence_and_clears_readiness_on_failure(empty_learning_center):
    playwright = pytest.importorskip('playwright.sync_api')
    profile = {'name': '집기 비교', 'task': '블록 집어서 유지', 'mode': 'independent',
               'arms': [{'id': 'arm'}], 'cameras': []}
    state = {'datasets': [{'id': 'data', 'name': '검수 시범', 'profile': profile}],
             'runs': [], 'methods': {'act': {'available': True}},
             'owner_status': {'configured': False, 'targets': []}}
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/api/learning/omx/center', lambda route: route.fulfill(json=state))
            page.goto(empty_learning_center+'/learning/omx', wait_until='networkidle')
            expect = playwright.expect
            expect(page.locator('#journey-goal')).to_contain_text('아직 선택하지 않았습니다')
            expect(page.locator('#start')).to_be_disabled()
            page.locator('#dataset').select_option('data')
            expect(page.locator('#journey-goal')).to_contain_text('블록 집어서 유지')
            expect(page.locator('#journey-next')).to_have_attribute('href', '#train-section')
            state['runs'] = [{'id': 'run', 'dataset_id': 'data', 'method': 'act', 'status': 'succeeded',
                              'result': {'evaluation': {'frames': 1, 'action_mae': 0.1}}}]
            page.locator('#refresh').click()
            expect(page.locator('#journey-next')).to_have_attribute('href', '#comparison-section')
            expect(page.locator('#journey-reason')).to_contain_text('별도 실물 시험')
            other = dict(profile, task='다른 과제')
            page.evaluate('(profile)=>document.dispatchEvent(new CustomEvent("omx-profile-selected", {detail:{id:"other",revision:1,profile}}))', other)
            expect(page.locator('#journey-next')).to_have_attribute('href', '#dataset-section')
            expect(page.locator('#journey-reason')).to_contain_text('다릅니다')
            page.route('**/api/learning/omx/center', lambda route: route.fulfill(status=503, json={'error': 'unavailable'}))
            page.locator('#refresh').click()
            expect(page.locator('#journey-reason')).to_contain_text('아직 확인하지 못했습니다')
        finally:
            browser.close()


@pytest.mark.parametrize('width', [1440, 390])
def test_learning_cards_and_submenus_open_real_sections_and_restore_task(empty_learning_center, width):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            expect = playwright.expect
            page.goto(empty_learning_center+'/learning', wait_until='networkidle')
            expect(page.locator('#learning-start')).to_contain_text('成功'.replace('成功', '성공률'))
            page.locator('#learning-start a[href="/learning/omx#profile-panel"]').click()
            expect(page.locator('#profile-panel')).to_have_attribute('open', '')
            expect(page.locator('#profile-task')).to_be_focused()
            for button in ['profile-new', 'profile-add-arm', 'profile-add-camera']:
                assert page.locator('#'+button).bounding_box()['height'] >= 40
            page.locator('#profile-task').fill('블록 집기 · 2초 유지 · 낙하 실패 · 트레이 복원')
            for target in ['owner-section', 'capture-section', 'dataset-section', 'reward-section', 'train-section', 'comparison-section']:
                link = page.locator(f'#omx-sections a[href="#{target}"]')
                link.click()
                expect(page.locator('#'+target)).to_be_visible()
                expect(page.locator('#profile-panel')).to_be_hidden()
                expect(link).to_have_attribute('aria-current', 'location')
                assert page.url.endswith('#'+target)
            page.locator('#omx-sections a[href="#profile-panel"]').click()
            expect(page.locator('#profile-task')).to_have_value('블록 집기 · 2초 유지 · 낙하 실패 · 트레이 복원')
            page.go_back()
            expect(page.locator('#omx-sections a[href="#comparison-section"]')).to_have_attribute('aria-current', 'location')
            page.go_forward()
            expect(page.locator('#profile-task')).to_be_focused()
            page.reload(wait_until='networkidle')
            expect(page.locator('#profile-panel')).to_have_attribute('open', '')
            expect(page.locator('#profile-task')).to_be_focused()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors
        finally:
            browser.close()


def test_empty_learning_choices_keep_explanation_and_account_return_path(empty_learning_center):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            expect = playwright.expect
            page.goto(empty_learning_center+'/learning/omx#profile-panel', wait_until='networkidle')
            for selector, text in [('#owner-target', '상태 연결 설정 없음'),
                                   ('#prepared-set', '등록된 검수 시연 없음'),
                                   ('#dataset', '등록된 학습 데이터 없음'),
                                   ('#profile-record', '저장된 프로필 없음')]:
                expect(page.locator(selector+' option:checked')).to_have_text(text)
                expect(page.locator(selector)).to_be_disabled()
            page.locator('#omx-sections a[href="#dataset-section"]').click()
            expect(page.locator('#empty-prepared')).to_be_visible()
            expect(page.locator('#empty-datasets')).to_be_visible()
            page.locator('#empty-prepared a').click()
            expect(page.locator('#connection-panel')).to_have_attribute('open', '')
            expect(page.locator('#kind')).to_have_value('omx')
            expect(page.locator('#name')).to_be_focused()
            page.goto(empty_learning_center+'/learning/omx', wait_until='networkidle')
            page.locator('#learning-account-link').click()
            expect(page.locator('#account-setup')).to_be_visible()
            expect(page.locator('#login-panel')).to_be_visible()
            expect(page.locator('#username, #password, #login-submit')).to_have_count(0)
            expect(page.locator('#account-login')).to_be_hidden()
            expect(page.locator('#login-help')).to_contain_text('준비')
            expect(page.locator('#account-retry')).to_be_enabled()
            expect(page.locator('#account-setup')).to_contain_text('Hugging Face')
            page.locator('#account-setup a[href="/learning/omx#profile-panel"]').click()
            expect(page.locator('#profile-panel')).to_have_attribute('open', '')
        finally:
            browser.close()


def test_every_learning_rail_destination_renders_content(empty_learning_center):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(empty_learning_center+'/learning/omx', wait_until='networkidle')
            hrefs = '(els)=>els.map(e=>e.getAttribute("href"))'
            links = page.locator('.ui-rail-nav a').evaluate_all(hrefs)
            # D-857 §3: five stages; every page is the stage entry or one sub-menu click away (two clicks at most).
            assert links == ['/learning', '/catalog', '/', '/learning/tasks', '/learning/evaluate']

            def opened(selector, href):
                page.locator(selector).click()
                page.wait_for_load_state('load')  # the SIM page keeps polling, so the network never idles
                playwright.expect(page.locator('main')).to_be_visible()
                playwright.expect(page.locator('[data-learning-account-entry]')).to_have_attribute('href', '/accounts')
                playwright.expect(page.locator('[data-learning-account-entry]')).to_be_visible()
                assert len(page.locator('main').inner_text().strip()) > 40
                assert page.url == empty_learning_center+href
            reached = set()
            for href in links:
                opened(f'.ui-rail-nav a[href="{href}"]', href)
                for sub in page.locator('.ui-subnav-nav a').evaluate_all(hrefs):
                    opened(f'.ui-rail-nav a[href="{href}"]', href)
                    opened(f'.ui-subnav-nav a[href="{sub}"]', sub)
                    reached.add(sub)
            assert reached == {'/catalog', '/learning/camera', '/', '/pixels', '/learning/omx', '/learning/vlm',
                               '/learning/tasks', '/learning#pipeline', '/learning/sim'}
            assert not errors
        finally:
            browser.close()


def test_owner_observation_is_separate_from_control_and_failure_clears_previous_state(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    calls = []
    observation = dict(status='observed', owner={'state': 'hold', 'reason': 'operator_pause', 'observed_sequence': 12},
        received_at='2026-10-21T00:00:00+00:00', physical_control_available=False,
        feedback_freshness_verified=False, workcell_id='cell', instance_id='arm')
    def read(workcell):
        calls.append(workcell)
        return observation
    center = SimpleNamespace(bind_workspace=lambda project: None,
        profiles=SimpleNamespace(list=lambda: []), read_owner_status=read,
        snapshot=lambda: {'datasets': [], 'runs': [], 'methods': {},
            'owner_status': {'configured': True, 'physical_control_available': False,
                'targets': [{'workcell_id': 'cell', 'instance_id': 'arm'}]}})
    store = ReviewStore(tmp_path/'review', empty_training=True)
    server = make_server(store, free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                expect = playwright.expect
                expect(page.locator('#learning-account-link')).to_have_attribute('href', '/accounts')
                expect(page.locator('#learning-account-state')).to_contain_text('계정 서버 연결 준비 중')
                page.locator('#learning-task-link').click()
                expect(page.locator('#profile-panel')).to_have_attribute('open', '')
                expect(page.locator('#profile-task')).to_be_focused()
                expect(page.locator('#owner-target')).to_have_value('cell')
                expect(page.locator('#owner-status')).to_contain_text('보류')
                expect(page.locator('#owner-details')).to_contain_text('12')
                expect(page.locator('#owner-control-status')).to_contain_text('실물 학습 제어는 연결되지 않았습니다')
                assert calls and set(calls) == {'cell'}
                observation.clear()
                observation.update(status='unavailable', reason='OWNER_READBACK_UNAVAILABLE',
                    physical_control_available=False, feedback_freshness_verified=False)
                page.locator('#owner-refresh').click()
                expect(page.locator('#owner-status')).to_contain_text('조회할 수 없습니다')
                expect(page.locator('#owner-details')).to_have_text('')
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_late_response_from_previous_workcell_cannot_replace_current_selection(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    started, release = threading.Event(), threading.Event()
    block = [False]
    def read(workcell):
        if workcell == 'left' and block[0]:
            started.set()
            assert release.wait(10)
        return dict(status='observed', workcell_id=workcell, instance_id=workcell+'-arm',
            owner={'state': 'hold' if workcell == 'left' else 'active', 'reason': None, 'observed_sequence': 9},
            received_at='fixture-query-time', physical_control_available=False)
    center = SimpleNamespace(bind_workspace=lambda project: None,
        profiles=SimpleNamespace(list=lambda: []), read_owner_status=read,
        snapshot=lambda: dict(datasets=[], runs=[], methods={}, owner_status=dict(configured=True,
            targets=[dict(workcell_id=cell, instance_id=cell+'-arm') for cell in ('left', 'right')])))
    server = make_server(ReviewStore(tmp_path/'review', empty_training=True), free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f'http://127.0.0.1:{server.server_port}/learning/omx?view=all', wait_until='networkidle')
                expect = playwright.expect
                expect(page.locator('#owner-status')).to_contain_text('left-arm')
                block[0] = True
                page.locator('#owner-refresh').click()
                assert started.wait(5)
                page.locator('#owner-target').select_option('right')
                expect(page.locator('#owner-status')).to_contain_text('right-arm')
                with page.expect_response(lambda response: response.url.endswith('/owner-status/left')):
                    release.set()
                expect(page.locator('#owner-status')).to_contain_text('right-arm')
                expect(page.locator('#owner-status')).not_to_contain_text('left-arm')
            finally:
                release.set()
                browser.close()
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
