"""Public SO100 study UI; every network learning operation uses a fixture."""
import os
from pathlib import Path
import threading
from types import SimpleNamespace
import uuid

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import ReviewStore, make_server

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')
REVISION = '728583b5eaf9e739a7f119e2def466fa1d552402'
RUN = 'f4ae1463-a9b7-4fac-a01b-dee788428749'


@pytest.fixture
def public_page(tmp_path):
    playwright = pytest.importorskip('playwright.sync_api')
    center = SimpleNamespace(bind_workspace=lambda project: None, profiles=SimpleNamespace(list=lambda: []),
                             snapshot=lambda: {'runs': [], 'methods': {}, 'datasets': []})
    server = make_server(ReviewStore(tmp_path / 'review', empty_training=True), free_port(), omx_center=center)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={'width': 1366, 'height': 768})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                source = dict(repo_id='lerobot/svla_so100_pickplace', revision=REVISION, license='Apache-2.0',
                              robot_type='so100', episodes=50, available=True,
                              recipe=dict(train_episodes=list(range(8)), validation_episodes=[8],
                                          eval_episodes=[9], image_shape=[128, 128], steps=1000, batch_size=4))
                state = {'runs': [], 'methods': {}}
                page.route('**/api/workspace', lambda route: route.fulfill(json={'token': 'fixture'}))
                page.route('**/center/public-source', lambda route: route.fulfill(json=source))
                page.route('**/api/learning/omx/center', lambda route: route.fulfill(json=state))
                yield page, state, source, f'http://127.0.0.1:{server.server_port}/learning/public', playwright.expect
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def refresh(page, expect):
    page.locator('#public-refresh').click()
    expect(page.locator('#public-refresh')).to_be_enabled()


def test_source_confirmation_lost_reply_retry_and_stop(public_page):
    page, state, source, url, expect = public_page
    posts, stops = [], []

    def submit(route):
        posts.append(route.request.post_data_json)
        assert route.request.headers['x-pinky-token'] == 'fixture'
        if len(posts) == 1:
            route.fulfill(status=503, json={'error': '응답 유실 시험'})
        else:
            state['runs'] = [dict(id=RUN, execution_mode='public_train', status='running',
                                 progress={'phase': 'downloading'})]
            route.fulfill(json={'id': RUN, 'status': 'running'})

    def stop(route):
        stops.append(route.request.post_data_json)
        state['runs'][0]['status'] = 'stopping'
        route.fulfill(json=state['runs'][0])

    page.route('**/center/public-run', submit)
    page.route('**/center/stop', stop)
    page.goto(url, wait_until='domcontentloaded')
    expect(page.locator('#public-empty')).to_be_visible()
    expect(page.locator('#public-start')).to_be_disabled()
    expect(page.locator('#public-source-facts')).to_contain_text('SO100'.lower())
    expect(page.locator('#public-recipe')).to_contain_text('0, 1, 2, 3, 4, 5, 6, 7')
    page.locator('#public-confirm').check()
    expect(page.locator('#public-start')).to_be_enabled()
    page.locator('#public-start').click()
    expect(page.locator('#public-error')).to_contain_text('응답 유실 시험')
    expect(page.locator('#public-start')).to_contain_text('같은 학습 요청 다시 확인')
    page.locator('#public-start').click()
    expect(page.locator('#public-submit-status')).to_contain_text(RUN)
    expect(page.locator('#public-runs')).to_contain_text('원본 자료 내려받는 중')
    assert posts[0] == posts[1]
    assert posts[0] == dict(request_id=posts[0]['request_id'], repo_id=source['repo_id'], revision=REVISION,
                           steps=1000, batch_size=4, confirmed_source=True)
    assert uuid.UUID(posts[0]['request_id']).version == 4
    stop_button = page.locator('.public-run-header ui-button')
    expect(stop_button).to_contain_text('이 학습 중지')
    expect(stop_button).to_be_enabled()
    stop_button.click()
    expect(page.locator('#public-runs')).to_contain_text('중지 처리 중')
    expect(stop_button).to_be_disabled()
    assert stops == [{'id': RUN}]


def test_unavailable_loading_failure_and_progress_keep_focus(public_page):
    page, state, source, url, expect = public_page
    source.update(available=False, reason='학습 의존성을 확인하세요.')
    page.goto(url, wait_until='domcontentloaded')
    page.locator('#public-confirm').check()
    expect(page.locator('#public-start')).to_be_disabled()
    expect(page.locator('#public-start-reason')).to_contain_text('학습 의존성')
    source['available'] = True
    state['runs'] = [dict(id=RUN, execution_mode='public_train', status='launching', progress={'phase': 'preparing'})]
    refresh(page, expect)
    expect(page.locator('#public-start')).to_be_enabled()
    expect(page.locator('#public-runs')).to_contain_text('학습 자료 준비 중')
    stop = page.locator('.public-run-header ui-button')
    stop.focus()
    state['runs'][0].update(status='running', progress={'phase': 'training', 'step': 20, 'steps': 1000})
    expect(page.locator('#public-runs')).to_contain_text('20 / 1000', timeout=10000)
    expect(stop).to_be_focused()
    state['runs'][0].update(status='failed', error='학습 프로세스가 종료되었습니다.')
    refresh(page, expect)
    expect(page.locator('#public-runs')).to_contain_text('학습 프로세스가 종료되었습니다.')
    expect(page.locator('#public-runs a')).to_be_hidden()
    page.route('**/center/public-source', lambda route: route.fulfill(status=503, json={'error': '출처 연결 시험'}))
    refresh(page, expect)
    expect(page.locator('#public-source-status')).to_contain_text('출처 연결 시험')
    expect(page.locator('#public-start')).to_be_disabled()


def test_source_loading_and_pending_request_disable_start(public_page):
    page, state, source, url, expect = public_page
    held_source, held_run = [], []
    page.route('**/center/public-source', lambda route: held_source.append(route))
    page.route('**/center/public-run', lambda route: held_run.append(route))
    page.goto(url, wait_until='domcontentloaded')
    expect(page.locator('#public-source-status')).to_contain_text('확인하는 중')
    page.locator('#public-confirm').check()
    expect(page.locator('#public-start')).to_be_disabled()
    expect(page.locator('#public-start-reason')).to_contain_text('호스트를 확인하는 중')
    assert len(held_source) == 1
    held_source[0].fulfill(json=source)
    expect(page.locator('#public-start')).to_be_enabled()
    page.locator('#public-start').click()
    expect(page.locator('#public-start')).to_be_disabled()
    expect(page.locator('#public-start')).to_contain_text('요청 처리 중')
    assert len(held_run) == 1
    held_run[0].fulfill(json={'id': RUN, 'status': 'launching'})
    expect(page.locator('#public-submit-status')).to_contain_text(RUN)


@pytest.mark.parametrize('theme,width,height', [('dark', 1366, 768), ('light', 1366, 768),
                                               ('dark', 390, 844), ('light', 390, 844),
                                               ('dark', 320, 568), ('light', 320, 568)])
def test_evaluation_download_and_responsive_evidence(public_page, theme, width, height):
    page, state, source, url, expect = public_page
    state['runs'] = [dict(id=RUN, execution_mode='public_train', status='succeeded',
                         progress={'phase': 'finished', 'step': 1000, 'steps': 1000}, result={
        'evaluation': {'mae_per_joint': [0.1, 0.2], 'train_mean_baseline_mae_per_joint': [0.4, 0.5],
                       'joint_names': ['main_shoulder_pan', 'main_shoulder_lift'], 'samples': 36,
                       'model_reloaded_in_new_process': True, 'physical_learning_verified': False,
                       'policy_activation': False, 'units': 'source_dataset_native_unverified'}}),
        dict(id='native-hidden', execution_mode='native_train', status='succeeded')]
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url, wait_until='domcontentloaded')
    expect(page.locator('.public-table')).to_contain_text('main_shoulder_pan')
    expect(page.locator('.public-table')).to_contain_text('0.4')
    expect(page.locator('#public-runs')).to_contain_text('학습·평가 완료 · 1000 / 1000단계')
    expect(page.locator('#public-runs')).to_contain_text('실물 학습 성능 미검증 · 정책 적용 없음')
    expect(page.locator('#public-runs')).not_to_contain_text('native-hidden')
    expect(page.locator('#public-runs a')).to_have_attribute('href', f'/api/learning/omx/center/artifact/{RUN}')
    page.locator('html').evaluate('(element, theme) => element.dataset.theme = theme', theme)
    page.locator('#public-results').scroll_into_view_if_needed()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    screenshots = os.environ.get('ROSY_UIUX_SCREENSHOT_DIR')
    if screenshots:
        directory = Path(screenshots)
        directory.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(directory / f'public-learning-results-{theme}-{width}.png'), full_page=True)
