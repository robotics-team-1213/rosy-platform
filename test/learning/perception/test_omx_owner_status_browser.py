"""Real Chromium checks observer selection, failure clearing and no control claim."""
import threading
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


def capture(page, name):
    if root := os.environ.get('ROSY_SCREENSHOT_DIR'):
        target = Path(root).expanduser() / name
        target.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(target))


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


@pytest.mark.parametrize('width', [320, 1440])
def test_all_tools_has_no_false_step_and_reveals_nested_keyboard_target(empty_learning_center, width):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            expect = playwright.expect
            page.goto(empty_learning_center+'/learning/omx?view=all', wait_until='networkidle')
            expect(page.locator('#stage-question')).to_have_text('전체 도구')
            expect(page.locator('#omx-sections [aria-current]')).to_have_count(0)
            capture(page, f'omx-all-tools-{width}.png')
            page.goto(empty_learning_center+'/learning/omx?view=all#native-review-heading', wait_until='networkidle')
            target = page.locator('#native-review-heading')
            expect(target).to_be_focused()
            assert target.evaluate('el=>{const r=el.getBoundingClientRect();return r.top>=document.querySelector("ui-topbar").getBoundingClientRect().bottom-1&&r.bottom<=innerHeight;}')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            capture(page, f'omx-nested-review-{width}.png')
        finally:
            browser.close()


def test_view_toggle_changes_only_view_and_retains_history_context(empty_learning_center):
    playwright = pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            expect = playwright.expect
            page.goto(empty_learning_center+'/learning/omx?source=fixed-context#dataset-section', wait_until='networkidle')
            page.locator('#workflow-view').click()
            assert page.evaluate('new URL(location.href).searchParams.get("source")') == 'fixed-context'
            expect(page.locator('#train-section')).to_be_visible()
            page.locator('#workflow-view').click()
            assert page.evaluate('new URL(location.href).searchParams.get("source")') == 'fixed-context'
            expect(page.locator('#train-section')).to_be_hidden()
            expect(page).to_have_url(empty_learning_center+'/learning/omx?source=fixed-context#dataset-section')
            page.go_back()
            expect(page.locator('#train-section')).to_be_visible()
        finally:
            browser.close()


def test_center_read_error_is_visible_from_conversion_stage_and_clears_on_recovery(empty_learning_center):
    playwright = pytest.importorskip('playwright.sync_api')
    failed = [True]
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            def center(route):
                route.fulfill(status=503 if failed[0] else 200, json={'error': 'fixture center unavailable'}
                    if failed[0] else {'datasets': [], 'runs': [], 'methods': {}})
            page.route('**/api/learning/omx/center', center)
            page.goto(empty_learning_center+'/learning/omx#dataset-section', wait_until='networkidle')
            expect = playwright.expect
            alert = page.locator('#center-read-error')
            expect(alert).to_be_visible()
            expect(alert).to_have_attribute('role', 'alert')
            expect(alert).to_contain_text('fixture center unavailable')
            expect(page.locator('#center-status')).to_be_visible()
            expect(page.locator('#train-section')).to_be_hidden()
            alert.scroll_into_view_if_needed()
            capture(page, 'omx-center-read-failure.png')
            failed[0] = False
            page.locator('#refresh').click()
            expect(alert).to_be_hidden()
            expect(page.locator('#center-status')).to_have_attribute('state', 'ready')
        finally:
            browser.close()


@pytest.mark.parametrize('action', ['이 데이터로 학습 준비', '이 데이터 HF 보관 준비', '이 변환 중지'])
def test_conversion_poll_preserves_action_focus_and_falls_back_to_run_heading(empty_learning_center, action):
    playwright = pytest.importorskip('playwright.sync_api')
    run = {'id': 'conversion-fixture', 'name': 'Native conversion', 'prepared_id': 'prepared-fixture',
           'execution_mode': 'native_export', 'method': 'act', 'status': 'running' if action=='이 변환 중지' else 'succeeded',
           'progress': {'phase': 'verifying'},
           'result': {'dataset_id': 'converted-data', 'dataset_revision': 'f'*64, 'act_only': True}}
    snapshot = {'datasets': [], 'runs': [run], 'methods': {}}
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/api/learning/omx/center', lambda route: route.fulfill(json=snapshot))
            page.goto(empty_learning_center+'/learning/omx#dataset-section', wait_until='networkidle')
            expect = playwright.expect
            control = page.get_by_role('button' if action=='이 변환 중지' else 'link', name=action, exact=True)
            control.focus()
            before = page.locator('#center-status').inner_text()
            with page.expect_response('**/api/learning/omx/center'):
                pass
            expect(page.locator('#center-status')).not_to_have_text(before)
            expect(control).to_be_focused()
            run['name'] = 'Updated conversion'
            with page.expect_response('**/api/learning/omx/center'):
                pass
            expect(page.locator('#export-runs')).to_contain_text('Updated conversion')
            expect(control).to_be_focused()
            if action=='이 변환 중지':
                run['status'] = 'succeeded'
                with page.expect_response('**/api/learning/omx/center'):
                    pass
                heading = page.locator('#export-runs h3')
                expect(heading).to_contain_text('완료')
                expect(heading).to_be_focused()
        finally:
            browser.close()


def test_conversion_poll_retains_pending_stop_and_its_rejection(empty_learning_center):
    playwright = pytest.importorskip('playwright.sync_api')
    run = {'id': 'conversion-pending', 'name': 'Pending conversion', 'prepared_id': 'prepared-fixture',
           'execution_mode': 'native_export', 'method': 'act', 'status': 'running', 'progress': {}}
    held = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/api/learning/omx/center', lambda route: route.fulfill(json={'datasets': [], 'runs': [run], 'methods': {}}))
            page.route('**/api/learning/omx/center/stop', lambda route: held.append(route))
            page.goto(empty_learning_center+'/learning/omx#dataset-section', wait_until='networkidle')
            expect = playwright.expect
            stop = page.get_by_role('button', name='이 변환 중지', exact=True)
            with page.expect_request('**/api/learning/omx/center/stop'):
                stop.click()
            expect(stop).to_be_disabled()
            run['name'] = 'Progress while stopping'
            with page.expect_response('**/api/learning/omx/center'):
                pass
            expect(page.locator('#export-runs')).to_contain_text(run['name'])
            expect(stop).to_be_disabled()
            assert len(held) == 1
            held.pop().fulfill(status=503, json={'error': 'fixture stop rejected'})
            expect(page.locator('#export-runs [role="alert"]')).to_have_text('fixture stop rejected')
            expect(stop).to_be_enabled()
            run['name'] = 'Progress after rejection'
            with page.expect_response('**/api/learning/omx/center'):
                pass
            expect(page.locator('#export-runs')).to_contain_text(run['name'])
            expect(page.locator('#export-runs [role="alert"]')).to_have_text('fixture stop rejected')
        finally:
            browser.close()


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
                if href=='/':
                    playwright.expect(page.locator('#empty-review h2')).not_to_have_text('검수 내용을 확인하는 중')
                assert len(page.locator('main').inner_text().strip()) > 40
                assert page.url == empty_learning_center+href
            reached = set()
            for href in links:
                opened(f'.ui-rail-nav a[href="{href}"]', href)
                # The two editors carry the 정답 pages in their title row (.review-kinds), the others in the sub-menu.
                for sub in page.locator('.ui-subnav-nav a, .review-kinds a').evaluate_all(hrefs):
                    opened(f'.ui-rail-nav a[href="{href}"]', href)
                    opened(f':is(.ui-subnav-nav, .review-kinds) a[href="{sub}"]', sub)
                    reached.add(sub)
            assert reached == {'/catalog', '/learning/camera', '/', '/pixels', '/learning/omx', '/learning/vlm',
                               '/learning/tasks', '/learning#pipeline', '/learning/sim', '/learning/workspaces'}
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
