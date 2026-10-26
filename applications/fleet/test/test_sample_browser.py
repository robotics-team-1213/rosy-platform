"""Real application documents on the standalone sample origin; no intercepted API calls."""
import threading
import time
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled

from test_sample_server import load_engine

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')


@pytest.fixture
def sample_site():
    engine = load_engine()
    from http_host import make_server
    server = make_server(engine, 'http://localhost:0')
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield engine, f'http://localhost:{server.server_address[1]}'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(5)


@pytest.mark.parametrize('path', ['/console', '/console/install', '/console/site-map', '/console/cell',
                                  '/console/accounts', '/console/policy', '/console/profile', '/console/login'])
def test_eight_pages_use_same_frontend_without_unhandled_requests(sample_site, path):
    from playwright.sync_api import sync_playwright, expect
    engine, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            response = context.request.post(origin + '/api/fleet/auth/login',
                headers={'Origin': origin}, data={'login': 'sample', 'password': 'CHANGE_ME'})
            assert response.status == 204
            page = context.new_page()
            errors, external, failed = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: external.append(req.url)
                    if urlsplit(req.url).netloc != urlsplit(origin).netloc and req.url.startswith('http') else None)
            page.on('response', lambda res: failed.append((res.status, res.url)) if res.status >= 500 else None)
            assert page.goto(origin + path).status == 200
            expect(page.locator('body')).to_be_visible()
            page.wait_for_timeout(1800)
            assert not external, external
            assert not errors, errors
            assert not engine.unhandled, engine.unhandled
            assert not failed, failed
        finally:
            browser.close()


def test_control_unit_form_approves_then_reads_existing_task_result(sample_site):
    from playwright.sync_api import sync_playwright, expect
    engine, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            assert page.request.post(origin + '/api/fleet/auth/login', headers={'Origin': origin},
                data={'login': 'sample', 'password': 'CHANGE_ME'}).status == 204
            page.goto(origin + '/console?view=work')
            page.locator('#work-integrations > summary').click()
            panel = page.locator('#control-unit-work')
            expect(panel).to_contain_text('R')
            panel.locator('summary').click()
            expect(panel.locator('#control-unit-yaw')).to_have_value('0')
            panel.locator('#control-unit-robot_id').fill('sample-robot')
            panel.locator('#control-unit-x').fill('1')
            panel.locator('#control-unit-y').fill('2')
            panel.get_by_role('button', name='대상 관제에 요청', exact=True).click()
            expect(panel).to_contain_text('현장 승인 대기')
            panel.get_by_role('button', name='이 관제에서 승인', exact=True).click()
            expect(panel).to_contain_text('현장 승인 sample')
            expect(panel).to_contain_text('연결된 작업 sample-task-1')
            engine.advance('monitoring', 'complete')
            expect(panel).to_contain_text('작업 완료', timeout=10000)
            panel.get_by_role('button', name='새 요청 작성', exact=True).click()
            expect(panel.locator('#control-unit-x')).to_have_value('0')
            expect(panel.locator('#control-unit-yaw')).to_have_value('0')
            assert not engine.unhandled, engine.unhandled
        finally:
            browser.close()


def test_profile_save_and_logout_use_sample_session(sample_site):
    from playwright.sync_api import sync_playwright, expect
    _, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(origin + '/console/login?return=/console/profile')
            page.locator('[data-login=login]').fill('sample')
            page.locator('[data-login=password]').fill('CHANGE_ME')
            page.locator('[data-login=submit]').click()
            expect(page.locator('#profile-id')).to_have_text('sample')
            page.locator('#profile-name').fill('프런트 개발자')
            page.locator('#profile-name-save').click()
            expect(page.locator('#profile-status')).to_contain_text('저장하고 다시 확인')
            page.reload()
            expect(page.locator('#profile-name')).to_have_value('프런트 개발자')
            response = page.request.post(origin + '/api/fleet/auth/logout', headers={'Origin': origin}, data={})
            assert response.status == 204
            page.reload()
            expect(page.locator('#profile-login')).to_be_visible()
        finally:
            browser.close()


def test_cancel_all_button_keeps_dispatch_enabled(sample_site):
    from playwright.sync_api import sync_playwright, expect
    _, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            assert page.request.post(origin + '/api/fleet/auth/login', headers={'Origin':origin},
                data={'login':'sample', 'password':'CHANGE_ME'}).status == 204
            page.goto(origin + '/console')
            page.locator('#cancel-all').click()
            expect(page.locator('#cancel-all-result')).to_contain_text('1/1')
            expect(page.locator('#dispatch-rearm')).to_be_hidden()
            state = page.request.get(origin + '/api/fleet/dispatch-control').json()
            assert state['dispatch_enabled'] is True and state['generation'] == 1
        finally:
            browser.close()


def test_cell_document_preview_admission_and_terminal_read(sample_site):
    from playwright.sync_api import sync_playwright, expect
    _, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.request.post(origin + '/api/fleet/auth/login', headers={'Origin':origin},
                                 data={'login':'sample', 'password':'CHANGE_ME'})
            page = context.new_page()
            page.goto(origin + '/console/cell')
            for kind in ('recipe', 'cell'):
                page.locator(f'#{kind}-id').fill('sample')
                page.locator(f'#{kind}-load').click()
                expect(page.locator(f'#{kind}-revision')).to_contain_text('저장된 버전')
            page.locator('#compile').click()
            expect(page.locator('#summary')).to_contain_text('18회 전송')
            page.locator('#workcell').fill('sample-cell')
            page.locator('#instance').fill('sample-arm')
            page.locator('#propose').click()
            page.locator('#read-job').click()
            expect(page.locator('#job-summary')).to_contain_text('승인 대기')
            response = context.request.post(origin + '/api/fleet/missions/sample-cell-job-1/admit',
                headers={'Origin':origin}, data={'expected_generation':1})
            assert response.status == 403
            with page.expect_navigation(wait_until='load'):
                page.get_by_role('button', name='검토자로 로그인', exact=True).click()
            page.locator('.ui-subnav a[href="#mission-heading"]').click()
            page.locator('#mission-id').fill('sample-cell-job-1')
            page.locator('#read-job').click()
            expect(page.locator('#job-summary')).to_contain_text('승인 대기')
            page.locator('#admit').click()
            expect(page.locator('#job-summary')).to_contain_text('실행 대기')
            page.get_by_role('button', name='Cell 보류', exact=True).click()
            page.locator('#read-job').click()
            expect(page.locator('#job-summary')).to_contain_text('작업 보류')
            page.locator('#resume').click()
            expect(page.locator('#job-summary')).to_contain_text('실행 대기')
            page.get_by_role('button', name='Cell 목표 확인', exact=True).click()
            page.locator('#read-job').click()
            expect(page.locator('#job-summary')).to_contain_text('목표 확인 완료')
            page.reload()
            page.locator('.ui-subnav a[href="#mission-heading"]').click()
            page.locator('#mission-id').fill('sample-cell-job-1')
            page.locator('#read-job').click()
            expect(page.locator('#job-summary')).to_contain_text('목표 확인 완료')
            page.goto(origin + '/console?view=work')
            row = page.locator('[data-work-key][title*="sample-cell-job-1"]')
            expect(row).to_contain_text('끝남')
            row.click()
            expect(page.locator('#work-detail')).to_contain_text('sample-cell-job-1')
            expect(page.locator('#work-detail')).to_contain_text('목표 확인 완료')
        finally:
            browser.close()


def test_assistant_synthetic_voice_receipt_and_camera_panel(sample_site):
    from playwright.sync_api import sync_playwright, expect
    _, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.request.post(origin + '/api/fleet/auth/login', headers={'Origin':origin},
                                 data={'login':'sample', 'password':'CHANGE_ME'})
            page = context.new_page()
            page.goto(origin + '/console')
            page.locator('#assistant-toggle').click()
            expect(page.locator('#assistant-send')).to_be_enabled()
            page.locator('#assistant-dictate').click()
            page.get_by_role('button', name='샘플 음성 입력', exact=True).click()
            expect(page.locator('#assistant-input')).to_have_value('샘플 로봇의 상태를 알려줘')
            page.locator('#assistant-send').click()
            expect(page.locator('#assistant-messages')).to_contain_text('요청 접수')
            page.get_by_role('button', name='AI 답변', exact=True).click()
            expect(page.locator('#assistant-messages')).to_contain_text('실제 장치 명령은 보내지 않았습니다')
            page.locator('#assistant-close').click()
            page.locator('#context-tools-tab').click()
            page.locator('#robot-video summary').click()
            page.locator('[data-robot-video-choice="sample-robot"]').check()
            page.locator('[data-robot-video-start]').click()
            expect(page.locator('[data-robot-video-tile="sample-robot"]')).to_have_attribute('data-state', 'live')
            page.get_by_role('button', name='영상 지연', exact=True).click()
            expect(page.locator('[data-robot-video-tile="sample-robot"]')).to_have_attribute('data-state', 'stale')
            page.locator('[data-robot-video-stop]').click()
            expect(page.locator('[data-robot-video-stage]')).to_be_empty()
        finally:
            browser.close()


def test_cookie_login_stays_usable_when_camera_pairing_needs_named_token(sample_site):
    from playwright.sync_api import sync_playwright, expect
    _, origin = sample_site
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.request.post(origin + '/api/fleet/auth/login', headers={'Origin':origin},
                                 data={'login':'sample', 'password':'CHANGE_ME'})
            page = context.new_page()
            calls = []
            page.on('request', lambda request: calls.append(request.url) if '/pairing/v2/pending' in request.url else None)
            page.goto(origin + '/console/install?task=cameras')
            page.get_by_role('tab', name='카메라 연결 승인', exact=True).click()
            expect(page.locator('#camera-peer-status')).to_contain_text('고급 접속 토큰')
            expect(page.locator('#user-role')).to_have_attribute('title', 'sample · operator')
            assert not calls
            page.evaluate("sessionStorage.setItem('rosy-console-token', 'sample-operator')")
            page.reload()
            page.get_by_role('tab', name='카메라 연결 승인', exact=True).click()
            expect(page.locator('#camera-peer-requests')).to_contain_text('샘플 카메라')
        finally:
            browser.close()
