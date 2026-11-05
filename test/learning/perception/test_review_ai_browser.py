"""Browser proof of AI candidate publication and read-only review history."""
from contextlib import contextmanager
import threading

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import make_server
from review_ai_jobs import Jobs
from test_review_ai_jobs import workspace
from test_review_flow_browser import open_action_disclosure

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='requires explicit Chromium run')


@contextmanager
def ai_browser(tmp_path, backend=None):
    playwright = pytest.importorskip('playwright.sync_api')
    store = workspace(tmp_path)
    jobs = Jobs(store, backend=backend)
    server = make_server(store, free_port(), ai_jobs=jobs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(f'http://127.0.0.1:{server.server_port}/?frame=0', wait_until='networkidle')
                playwright.expect(page.locator('#image-message')).to_be_hidden()
                yield page, store, jobs, playwright.expect
                assert not errors
            finally:
                browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def command(page, text):
    page.keyboard.press('Control+k')
    page.get_by_role('textbox', name='기능 검색어').fill(text)
    page.keyboard.press('Enter')


@pytest.mark.parametrize('state,title', [
    ('not_requested', 'AI 확인 요청 전'), ('queued', 'AI 확인 대기'), ('running', 'AI 확인 실행 중'),
    ('failed', 'AI 확인 실패'), ('cancelled', 'AI 확인 취소됨'), ('stale', '입력 변경 · AI 재확인 필요'),
    ('succeeded', '저장된 AI 의견 없음')])
def test_pixel_missing_opinion_shows_request_state_instead_of_read_error(tmp_path, state, title):
    with ai_browser(tmp_path) as (page, store, jobs, expect):
        value = {'available': False, 'reason': 'not_requested' if state == 'not_requested' else 'no_report',
                 'check': {'state': state, 'version': 1}}
        page.route('**/api/vlm-feedback/0', lambda route: route.fulfill(json=value))
        page.goto(page.url.split('/?')[0] + '/pixels?frame=0', wait_until='networkidle')
        expect(page.locator('#pixel-vlm-state')).to_have_text(title)
        expect(page.locator('#pixel-vlm-note')).not_to_contain_text('읽을 수 없습니다')
        expect(page.locator('#pixel-vlm-note')).to_contain_text('저장된 픽셀 v1 기준')


def test_existing_opinion_does_not_hide_a_new_pending_or_failed_ai_check(tmp_path):
    with ai_browser(tmp_path) as (page, _, _, _):
        for state, title in [('queued', 'AI 확인 대기'), ('running', 'AI 확인 실행 중'),
                             ('failed', 'AI 확인 실패'), ('cancelled', 'AI 확인 취소됨'),
                             ('stale', '입력 변경 · AI 재확인 필요')]:
            result = page.evaluate("""async state => {
              const {feedbackPresentation} = await import('/history.js');
              return feedbackPresentation({available:true,current:true,unknown_pixels:0,review_blocked:false,
                feedback:{verdict:'no_obvious_concern',issue:'none',note:'earlier saved opinion'},
                check:{state,version:1},model:'fixture',model_digest:'e'.repeat(64)});
            }""", state)
            assert result['title'] == title and result['state'] != 'ready'
            assert 'earlier saved opinion' in result['details']


def test_feedback_presentation_rejects_bad_count_without_throwing(tmp_path):
    with ai_browser(tmp_path) as (page, store, jobs, expect):
        value = page.evaluate("""async () => {
            const {feedbackPresentation} = await import('/history.js');
            return feedbackPresentation({available:true,current:true,unknown_pixels:null,
                feedback:{verdict:'no_obvious_concern',issue:'none',note:'Fixture'}});
        }""")
        assert value['state'] == 'warning'


def test_keyboard_ai_draft_publishes_candidate_without_overwriting_review(tmp_path):
    with ai_browser(tmp_path, lambda *_: {'boxes': [{'label': 'person', 'bbox_xyxy': [1, 1, 12, 12]}]}) as (page, store, jobs, expect):
        before = store.get(0)
        expect(page.locator('#review-ai-object_draft')).to_be_enabled()
        command(page, 'AI 객체 초안 만들기')
        expect(page.locator('#review-ai-jobs')).to_contain_text('초안 후보 저장됨', timeout=15000)
        expect(page.locator('#review-ai-jobs')).to_contain_text('미인증 로컬 작업자')
        provenance = page.locator('#review-ai-provenance')
        expect(provenance.locator('p').first).to_be_hidden()
        provenance.locator('summary').click()
        expect(provenance.locator('p').first).to_be_visible()
        with page.expect_response('**/api/review-ai/0'):
            page.get_by_role('button', name='AI 실행 상태 다시 조회').evaluate('node=>node.click()')
        expect(provenance.locator('summary')).to_be_focused()
        page.get_by_role('button', name='AI 실행 상태 다시 조회').click()
        expect(provenance.locator('p').first).to_be_visible()
        assert store.get(0) == before
        assert jobs.status(0)['jobs'][0]['state'] == 'succeeded'
        command(page, 'AI 결과 목록 조회')
        expect(page.locator('#model-draft-select option')).to_have_count(1)
        expect(page.locator('#model-draft-select')).to_contain_text('미인증 로컬 작업자')
        expect(page.locator('#model-candidates')).to_be_enabled()
        assert store.get(0) == before
        open_action_disclosure(page, '#review-versions')
        page.locator('#review-versions').get_by_role('button', name='이력 불러오기', exact=True).click()
        expect(page.locator('#review-versions li ui-button')).to_have_count(1)
        page.locator('#review-versions li ui-button').first.click()
        expect(page.locator('#review-versions section')).to_contain_text('이전 버전 v1')
        expect(page.locator('#review-versions section canvas')).to_be_visible()
        expect(page.locator('#review-versions section')).to_contain_text('traffic_light')
        assert store.get(0) == before


def test_no_configuration_explains_disabled_pixel_ai_and_history_missing(tmp_path):
    with ai_browser(tmp_path) as (page, store, jobs, expect):
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
        expect(page.locator('#review-ai-pixel_draft')).to_be_disabled()
        expect(page.locator('#review-ai-mask_check')).to_be_disabled()
        expect(page.locator('#review-ai-jobs')).to_contain_text('AI 실행 설정이 없습니다')
        assert '설정' in page.locator('#review-ai-mask_check').get_attribute('reason')
        open_action_disclosure(page, '#review-versions')
        page.locator('#review-versions').get_by_role('button', name='이력 불러오기', exact=True).click()
        expect(page.locator('#review-versions')).to_contain_text('아직 저장된 이력이 없습니다')
        page.locator('#pixel-filter').select_option('approved')
        expect(page.locator('#review-ai-jobs')).to_have_count(0)
        expect(page.locator('#review-versions')).to_have_count(0)
        assert not jobs.status(0)['jobs']


def test_pixel_unsaved_gesture_blocks_ai_and_result_reload(tmp_path):
    with ai_browser(tmp_path, lambda *_: {'boxes': []}) as (page, store, jobs, expect):
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        expect(page.locator('#pixel-title')).to_have_text('사진 1 픽셀 검수')
        expect(page.locator('#review-ai-mask_check')).to_be_enabled()
        page.locator('#pixel-class').select_option('0')
        page.locator('#pixel-canvas').focus(); page.keyboard.press('t')
        page.keyboard.down('Space'); page.keyboard.press('Alt+ArrowRight'); page.keyboard.up('Space')
        expect(page.locator('#pixel-draft')).to_contain_text('1획')
        before = page.locator('#pixel-draft').inner_text()
        expect(page.locator('#review-ai-mask_check')).to_be_disabled()
        open_action_disclosure(page, '#review-ai-jobs')
        expect(page.locator('#review-ai-jobs').get_by_role('button', name='AI 결과 목록 조회')).to_be_disabled()
        command(page, 'AI 실행 상태 다시 조회')
        expect(page.locator('#pixel-draft')).to_have_text(before)
        assert not jobs.status(0)['jobs']


@pytest.mark.parametrize('editing', [False, True])
def test_mask_check_automatically_refreshes_opinion_without_replacing_unsaved_pixels(tmp_path, editing):
    import review_masks
    started, release = threading.Event(), threading.Event()
    def backend(*_):
        started.set(); assert release.wait(30)
        return {'feedback': {'verdict': 'concern', 'issue': 'missed_visible_road', 'note': 'Check the visible floor'}}
    try:
        with ai_browser(tmp_path, backend) as (page, store, jobs, expect):
            page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
            before = review_masks.get(store, 0)
            expect(page.locator('#pixel-ai-summary')).to_contain_text('AI 확인 요청 전')
            page.locator('#review-ai-mask_check').click()
            assert started.wait(5)
            expect(page.locator('#pixel-vlm-state')).to_contain_text('AI 확인 실행 중')
            if editing:
                page.locator('#pixel-class').select_option('0')
                page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
                expect(page.locator('#pixel-draft')).to_contain_text('1점 선택')
                expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')
            draft = page.locator('#pixel-draft').inner_text()
            release.set()
            expect(page.locator('#review-ai-jobs')).to_contain_text('참고 의견 저장됨', timeout=15000)
            if editing:
                expect(page.locator('#pixel-draft')).to_have_text(draft)
                expect(page.locator('#pixel-vlm-note')).to_contain_text('Check the visible floor', timeout=15000)
                page.keyboard.press('Escape')
            expect(page.locator('#pixel-vlm-note')).to_be_visible()
            expect(page.locator('#pixel-vlm-note')).to_contain_text('Check the visible floor', timeout=15000)
            expect(page.locator('#pixel-vlm-details')).to_contain_text('저장된 픽셀 v1 기준')
            if not editing:
                expect(page.locator('#pixel-draft')).to_have_text(draft)
            assert review_masks.get(store, 0) == before
            expect(page.locator('#review-ai-mask_check')).to_be_enabled()
            page.locator('#review-ai-mask_check').click()
            expect(page.locator('#review-ai-jobs > ul > li')).to_have_count(2)
            open_action_disclosure(page, '#pixel-vlm-details')
            provenance = page.locator('#review-ai-provenance')
            provenance.locator('summary').click()
            with page.expect_response('**/api/review-ai/0'):
                page.get_by_role('button', name='AI 실행 상태 다시 조회').evaluate('node=>node.click()')
            expect(provenance.locator('summary')).to_be_focused()
            assert set(provenance.locator('[data-job]').evaluate_all('nodes=>nodes.map(node=>node.dataset.job)')) == {job['id'] for job in jobs.status(0)['jobs']}
            provenance.locator('summary').click()
            for width, height in [(1366, 768), (390, 844)]:
                page.set_viewport_size({'width': width, 'height': height})
                for theme in ['dark', 'light']:
                    page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
                    folds = page.locator('details:visible').count()
                    import os
                    if output := os.getenv('ROSY_UIUX_SCREENSHOT_DIR'):
                        import json
                        from pathlib import Path
                        root = Path(output).expanduser()
                        root.mkdir(parents=True, exist_ok=True)
                        name = f'pixel-configured-evidence-{editing}-{theme}-{width}x{height}'
                        page.screenshot(path=str(root / f'{name}.png'), full_page=True)
                        (root / f'{name}.json').write_text(json.dumps(dict(
                            state='configured AI evidence', editing=editing, theme=theme,
                            viewport=page.viewport_size, visible_folds=folds, filename=f'{name}.png'),
                            ensure_ascii=False, indent=2), encoding='utf-8')
                    assert folds < 3
                    assert page.locator('details details').count() == 0
    finally:
        release.set()


@pytest.mark.parametrize('old_status', [200, 503])
def test_delayed_old_opinion_response_cannot_replace_new_check_result(tmp_path, old_status):
    import review_masks
    backend = lambda *_: {'feedback': {'verdict': 'concern', 'issue': 'missed_visible_road', 'note': 'Latest saved-mask advice'}}
    with ai_browser(tmp_path, backend) as (page, store, jobs, expect):
        page.add_init_script("""const originalFetch=window.fetch;
          window.fetch=async(...args)=>{
            const response=await originalFetch(...args);
            if(String(args[0]).includes('/api/vlm-feedback/0')){
              if(response.status>=500)setTimeout(()=>{window.feedbackReads=(window.feedbackReads||0)+1;},0);
              const json=response.json.bind(response);
              response.json=async()=>{const value=await json();setTimeout(()=>{window.feedbackReads=(window.feedbackReads||0)+1;},0);return value;};
            }
            return response;
          };""")
        held = []
        def delay_first(route):
            if not held:
                held.append(route)
            else:
                route.continue_()
        page.route('**/api/vlm-feedback/0', delay_first)
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='domcontentloaded')
        expect(page.locator('#review-ai-mask_check')).to_be_enabled()
        assert len(held) == 1
        before = review_masks.get(store, 0)
        page.locator('#review-ai-mask_check').click()
        expect(page.locator('#pixel-vlm-note')).to_contain_text('Latest saved-mask advice', timeout=15000)
        page.locator('#pixel-class').select_option('0')
        page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
        expect(page.locator('#pixel-draft')).to_contain_text('1점 선택')
        expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')
        draft = page.locator('#pixel-draft').inner_text()
        reads = page.evaluate('window.feedbackReads||0')
        held[0].fulfill(status=old_status, json={'available': False, 'reason': 'not_requested', 'check': {'state': 'not_requested'}, 'error': 'Old request failed'})
        page.wait_for_function('before => (window.feedbackReads||0)>before', arg=reads)
        expect(page.locator('#pixel-vlm-note')).to_contain_text('Latest saved-mask advice')
        expect(page.locator('#pixel-vlm-state')).not_to_have_text('AI 의견 조회 실패')
        expect(page.locator('#pixel-draft')).to_have_text(draft)
        assert review_masks.get(store, 0) == before


@pytest.mark.parametrize('editing', [False, True])
def test_requested_pixel_ai_previews_completion_only_when_editor_is_clean(tmp_path, editing):
    import base64
    import numpy as np
    import review_masks
    started, release = threading.Event(), threading.Event()

    def backend(*_):
        started.set()
        assert release.wait(30)
        return {'mask': base64.b64encode(review_masks.encode(np.zeros((24, 32), np.uint8))).decode()}

    try:
        with ai_browser(tmp_path, backend) as (page, store, jobs, expect):
            page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
            before = review_masks.get(store, 0)
            before_pixels = review_masks.pixels(store, before).copy()
            canvas = page.locator('#pixel-canvas')
            before_pixel = canvas.evaluate('node => Array.from(node.getContext("2d").getImageData(15,15,1,1).data)')
            page.locator('#review-ai-pixel_draft').click()
            assert started.wait(5)
            if editing:
                page.locator('#pixel-class').select_option('0')
                page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
                expect(page.locator('#pixel-draft')).to_contain_text('1점 선택')
                expect(page.locator('#pixel-draft')).to_contain_text('픽셀 미리보기')
                draft = page.locator('#pixel-draft').inner_text()
            release.set()
            expect(page.locator('#review-ai-jobs')).to_contain_text('초안 후보 저장됨', timeout=15000)
            if editing:
                expect(page.locator('#pixel-candidate-preview')).to_be_hidden()
                expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'false')
                expect(page.locator('#pixel-draft')).to_have_text(draft)
                expect(page.locator('#pixel-candidates option')).to_have_count(0)
                page.keyboard.press('Escape')
            expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'true')
            expect(page.locator('#pixel-candidate-preview')).to_be_hidden()
            expect(canvas).to_have_js_property('width', 32)
            expect(canvas).to_have_js_property('height', 24)
            expect(page.locator('#pixel-candidates option')).to_have_count(1)
            expect(page.locator('#pixel-candidates')).to_have_value(jobs.status(0)['jobs'][0]['result']['candidate_sha256'])
            assert canvas.evaluate('node => Array.from(node.getContext("2d").getImageData(15,15,1,1).data)') != before_pixel
            assert review_masks.get(store, 0)['version'] == before['version']
            assert np.array_equal(review_masks.pixels(store, review_masks.get(store, 0)), before_pixels)
    finally:
        release.set()


def test_history_pagination_and_pixel_snapshot_do_not_modify_current(tmp_path):
    import review_masks
    from review_app import Conflict
    with ai_browser(tmp_path) as (page, store, jobs, expect):
        for number in range(1, 24):
            review_masks.update(store, 0, {'version': number, 'action': 'fill', 'label': 0}, Conflict, actor='human-reviewer')
        before = review_masks.get(store, 0)
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        open_action_disclosure(page, '#review-versions')
        page.locator('#review-versions').get_by_role('button', name='이력 불러오기', exact=True).click()
        expect(page.locator('#review-versions li ui-button')).to_have_count(20)
        page.locator('#review-versions').get_by_role('button', name='이전 이력 더 보기').click()
        expect(page.locator('#review-versions li ui-button')).to_have_count(23)
        page.locator('#review-versions li ui-button').last.click()
        expect(page.locator('#review-versions section')).to_contain_text('이전 버전 v2')
        photo = page.locator('#review-versions section img')
        expect(photo).to_be_visible()
        expect(photo).to_have_js_property('naturalWidth', 32)
        assert review_masks.get(store, 0) == before


def test_frame_switch_removes_ai_and_versions_before_delayed_mask_failure(tmp_path):
    with ai_browser(tmp_path) as (page, store, jobs, expect):
        store.update(1, {'version': store.get(1)['version'], 'action': 'reopen'})
        page.route('**/api/vlm-feedback/0', lambda route: route.fulfill(json={
            'available': True, 'current': True, 'unknown_pixels': 0,
            'model': 'fixture-qwen', 'model_digest': 'a' * 64,
            'feedback': {'verdict': 'no_obvious_concern', 'issue': 'none', 'note': 'Opinion for photo one'}}))
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        expect(page.locator('#pixel-vlm-details')).to_contain_text('Opinion for photo one')
        expect(page.locator('#review-ai-jobs')).to_have_count(1)
        expect(page.locator('#review-versions')).to_have_count(1)
        held = []
        page.route('**/api/masks/1', lambda route: held.append(route))
        open_action_disclosure(page, '.pixel-frame-item[data-index="1"]')
        page.locator('.pixel-frame-item[data-index="1"]').click()
        expect(page.locator('#pixel-vlm-note')).to_have_text('')
        expect(page.locator('#pixel-vlm-details')).to_have_text('')
        expect(page.locator('#pixel-ai-summary')).to_be_hidden()
        expect(page.locator('#review-ai-jobs')).to_have_count(0)
        expect(page.locator('#review-versions')).to_have_count(0)
        expect(page.locator('#pixel-title')).to_have_text('사진 2 픽셀 검수')
        expect(page.locator('#pixel-canvas')).to_be_hidden()
        expect(page.locator('#pixel-source')).to_have_text('')
        expect(page.locator('#pixel-status')).not_to_contain_text('v1')
        expect(page.locator('#pixel-approve')).to_be_disabled()
        assert len(held) == 1
        held[0].fulfill(status=503, json={'error': 'fixture mask read failed'})
        expect(page.locator('#pixel-error')).to_contain_text('\uac80\uc218 \uc11c\ube44\uc2a4\ub97c \uc0ac\uc6a9\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4')
        expect(page.locator('#review-ai-jobs')).to_have_count(0)
        expect(page.locator('#review-versions')).to_have_count(0)
        expect(page.locator('#pixel-canvas')).to_be_hidden()
        expect(page.locator('#pixel-status')).to_have_attribute('state', 'warning')
        expect(page.locator('#pixel-source')).to_have_text('')
        expect(page.locator('#pixel-approve')).to_be_disabled()
        expect(page.locator('.pixel-vlm-feedback')).to_be_hidden()
        page.unroute('**/api/masks/1')
        page.locator('#pixel-reload').click()
        expect(page.locator('#pixel-canvas')).to_be_visible()
        expect(page.locator('#pixel-status')).to_contain_text('v0')
        expect(page.locator('#pixel-error')).to_be_hidden()
        expect(page.locator('#review-ai-jobs')).to_have_count(1)
        expect(page.locator('#review-versions')).to_have_count(1)
        assert not jobs.status(0)['jobs'] and not jobs.status(1)['jobs']


def test_dirty_pixel_editor_receives_mixed_check_states_without_consuming_candidate(tmp_path):
    import base64
    import copy
    import numpy as np
    import review_masks
    from test_review_ai_jobs import finished
    from vlm_mask_feedback import read_current_feedback

    def backend(snapshot, _):
        if snapshot['action'] == 'mask_check':
            return {'feedback': {'verdict': 'concern', 'issue': 'missed_visible_road', 'note': 'Fresh collaborator opinion'}}
        return {'mask': base64.b64encode(review_masks.encode(np.zeros((24, 32), np.uint8))).decode()}

    with ai_browser(tmp_path, backend) as (page, store, jobs, expect):
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        expect(page.locator('#review-ai-pixel_draft')).to_be_enabled()
        before = review_masks.get(store, 0)
        page.locator('#pixel-class').select_option('0')
        page.locator('#pixel-brush-tool').click()
        page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
        draft = page.locator('#pixel-draft').inner_text()
        jobs.create(0, 'pixel_draft', before['version'], 'fixture-collaborator')
        generated = finished(jobs)
        assert generated['state'] == 'succeeded'
        jobs.create(0, 'mask_check', before['version'], 'fixture-collaborator')
        assert finished(jobs)['state'] == 'succeeded'
        status = jobs.status(0)
        feedback = read_current_feedback(store.state, 0)
        phase = {'state': 'queued'}

        def status_response(route):
            value = copy.deepcopy(status)
            for job in value['jobs']:
                if job['action'] == 'mask_check':
                    job['state'] = phase['state']
            route.fulfill(json=value)

        def feedback_response(route):
            value = copy.deepcopy(feedback)
            value['check']['state'] = phase['state']
            route.fulfill(json=value)

        page.route('**/api/review-ai/0', status_response)
        page.route('**/api/vlm-feedback/0', feedback_response)
        open_action_disclosure(page, '#review-ai-jobs')
        for state, title in [('queued', 'AI 확인 대기'), ('running', 'AI 확인 실행 중'),
                             ('failed', 'AI 확인 실패'), ('cancelled', 'AI 확인 취소됨'),
                             ('stale', '입력 변경 · AI 재확인 필요'), ('succeeded', '검토할 문제 있음')]:
            phase['state'] = state
            page.get_by_role('button', name='AI 실행 상태 다시 조회', exact=True).click()
            expect(page.locator('#pixel-vlm-state')).to_have_text(title)
            expect(page.locator('#pixel-draft')).to_have_text(draft)
            expect(page.locator('#pixel-candidates option')).to_have_count(0)
            expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'false')
            assert review_masks.get(store, 0)['version'] == before['version']
        expect(page.locator('#pixel-vlm-note')).to_contain_text('Fresh collaborator opinion')
        page.get_by_role('navigation', name='픽셀 검수 도구').get_by_role('link', name='사진 검수', exact=True).click()
        previews = []
        page.on('request', lambda request: previews.append(request.url) if '/api/draft-images/' in request.url else None)
        page.locator('#pixel-save').click()
        expect(page.locator('#pixel-status')).to_contain_text('v2')
        expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'true')
        expect(page.locator('#pixel-candidates')).to_have_value(generated['result']['candidate_sha256'])
        assert len(previews) == 1
        assert review_masks.get(store, 0)['status'] == 'pending'


def test_pixel_result_read_rechecks_dirty_state_after_held_mask_response(tmp_path):
    import base64
    import numpy as np
    import review_masks
    from test_review_ai_jobs import finished

    backend = lambda *_: {'mask': base64.b64encode(review_masks.encode(np.zeros((24, 32), np.uint8))).decode()}
    with ai_browser(tmp_path, backend) as (page, store, jobs, expect):
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        expect(page.locator('#review-ai-pixel_draft')).to_be_enabled()
        before = review_masks.get(store, 0)
        jobs.create(0, 'pixel_draft', before['version'], 'fixture-collaborator')
        assert finished(jobs)['state'] == 'succeeded'
        held = []

        def hold_mask(route):
            held.append(route)

        page.route('**/api/masks/0', hold_mask)
        try:
            open_action_disclosure(page, '#review-ai-jobs')
            result_button = page.locator('#review-ai-jobs .review-ai-actions > ui-button').filter(has_text='AI 결과 목록 조회')
            with page.expect_request('**/api/masks/0'):
                result_button.click()
            assert len(held) == 1
            page.get_by_role('navigation', name='픽셀 검수 도구').get_by_role('link', name='사진 검수', exact=True).click()
            page.locator('#pixel-class').select_option('0')
            page.locator('#pixel-brush-tool').click()
            page.locator('#pixel-canvas').click(position={'x': 10, 'y': 10})
            draft = page.locator('#pixel-draft').inner_text()
            with page.expect_response('**/api/masks/0'):
                held.pop().fulfill(json=review_masks.get(store, 0))
            expect(page.locator('#review-ai-jobs')).to_contain_text('AI 결과 목록을 조회했습니다.')
            expect(result_button).to_be_disabled()
            expect(page.locator('#pixel-candidates option')).to_have_count(0)
            expect(page.locator('#pixel-preview-candidate')).to_have_attribute('aria-pressed', 'false')
            expect(page.locator('#pixel-draft')).to_have_text(draft)
            assert review_masks.get(store, 0)['version'] == before['version']
        finally:
            for route in held:
                route.fulfill(json=review_masks.get(store, 0))
