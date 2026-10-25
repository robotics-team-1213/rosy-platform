"""Browser proof of AI candidate publication and read-only review history."""
from contextlib import contextmanager
import threading

import pytest
from browser_harness import browser_tests_enabled, free_port
from review_app import make_server
from review_ai_jobs import Jobs
from test_review_ai_jobs import workspace

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


def test_keyboard_ai_draft_publishes_candidate_without_overwriting_review(tmp_path):
    with ai_browser(tmp_path, lambda *_: {'boxes': [{'label': 'person', 'bbox_xyxy': [1, 1, 12, 12]}]}) as (page, store, jobs, expect):
        before = store.get(0)
        expect(page.locator('#review-ai-object_draft')).to_be_enabled()
        command(page, 'AI 객체 초안 만들기')
        expect(page.locator('#review-ai-jobs')).to_contain_text('초안 후보 저장됨', timeout=15000)
        expect(page.locator('#review-ai-jobs')).to_contain_text('미인증 로컬 작업자')
        assert store.get(0) == before
        assert jobs.status(0)['jobs'][0]['state'] == 'succeeded'
        command(page, 'AI 결과 목록 조회')
        expect(page.locator('#model-draft-select option')).to_have_count(1)
        expect(page.locator('#model-draft-select')).to_contain_text('미인증 로컬 작업자')
        expect(page.locator('#model-candidates')).to_be_enabled()
        assert store.get(0) == before
        page.locator('#review-versions summary').click()
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
        page.locator('#review-versions summary').click()
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
        expect(page.locator('#review-ai-jobs').get_by_role('button', name='AI 결과 목록 조회')).to_be_disabled()
        page.locator('#review-ai-jobs').get_by_role('button', name='AI 실행 상태 다시 조회').click()
        expect(page.locator('#pixel-draft')).to_have_text(before)
        assert not jobs.status(0)['jobs']


def test_history_pagination_and_pixel_snapshot_do_not_modify_current(tmp_path):
    import review_masks
    from review_app import Conflict
    with ai_browser(tmp_path) as (page, store, jobs, expect):
        for number in range(1, 24):
            review_masks.update(store, 0, {'version': number, 'action': 'fill', 'label': 0}, Conflict, actor='human-reviewer')
        before = review_masks.get(store, 0)
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        page.locator('#review-versions summary').click()
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
        page.goto(page.url.split('?')[0] + 'pixels?frame=0', wait_until='networkidle')
        expect(page.locator('#review-ai-jobs')).to_have_count(1)
        expect(page.locator('#review-versions')).to_have_count(1)
        held = []
        page.route('**/api/masks/1', lambda route: held.append(route))
        page.locator('.pixel-frame-item[data-index="1"]').click()
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
