"""Real Console assets and lifecycle; fixture model answers never move devices."""
import pytest
from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in real Chromium scenario')


def test_operator_can_select_english_text_and_voice_locale(site):
    from playwright.sync_api import expect, sync_playwright
    api = {**API, '/api/fleet/assistant/status': {'available':True, 'mode':'READ_ONLY', 'reason':None}}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts)
        try:
            def answer(route):
                body = route.request.post_data_json
                posts.append(body)
                route.fulfill(status=202, json={**body, 'state':'ANSWERED', 'response':'Hello. Current Fleet observations.',
                    'facts':[], 'created_at':1000., 'completed_at':1000., 'reason':None, 'action_admissible':False})
            page.route('**/api/fleet/assistant/messages', answer)
            page.locator('#context-tools-tab').click()  # D-926: AI lives in the tools tab
            page.locator('#assistant-toggle').click()
            page.locator('#assistant-locale').select_option('en-US')
            page.locator('#assistant-input').fill('What is the robot status?')
            page.locator('#assistant-send').click()
            expect(page.locator('#assistant-messages')).to_contain_text('Hello.')
            assert posts[-1]['locale'] == 'en-US' and not errors
        finally:
            browser.close()


@pytest.mark.parametrize('size', [(1440, 900), (390, 844)])
def test_assistant_panel_text_safe_account_scoped_and_safety_visible(site, size):
    from playwright.sync_api import expect, sync_playwright
    api = {**API, '/api/fleet/assistant/status': {'available':True, 'mode':'READ_ONLY', 'reason':None}}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            def answer(route):
                body = route.request.post_data_json
                posts.append(body)
                route.fulfill(status=202, json={**body, 'state':'ANSWERED', 'response':'<img src=x onerror=alert(1)>',
                    'facts':[{'ref':'robot:r1','text':'r1 온라인','observed_at':1000.}],
                    'created_at':1000., 'completed_at':1000., 'reason':None, 'action_admissible':False})
            page.route('**/api/fleet/assistant/messages', answer)
            page.locator('#context-tools-tab').click()  # D-926: AI lives in the tools tab
            page.locator('#assistant-toggle').click()
            expect(page.locator('#assistant-panel')).to_be_visible()
            expect(page.locator('#assistant-send')).to_be_enabled()
            page.locator('#assistant-input').fill('현재 상태 알려줘')
            page.locator('#assistant-send').click()
            expect(page.locator('#assistant-messages')).to_contain_text('<img src=x onerror=alert(1)>')
            assert page.locator('#assistant-messages img').count() == 0
            assert len(posts) == 1
            estop = page.locator('#estop').bounding_box()
            assert estop and 0 <= estop['y'] < size[1]
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            api['/api/fleet/session'] = {'principal_id':'alice','role':'operator'}
            page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
            page.clock.run_for(2000)
            expect(page.locator('#assistant-messages li')).to_have_count(0)
            page.locator('#assistant-close').click()
            expect(page.locator('#assistant-toggle')).to_be_focused()
            expect(page.locator('#fleet-main')).to_be_visible()
            assert not errors
        finally:
            browser.close()


def test_pending_result_resumes_after_same_account_page_restore(site):
    from playwright.sync_api import expect, sync_playwright
    api = {**API, '/api/fleet/assistant/status': {'available':True, 'mode':'READ_ONLY'}}
    with sync_playwright() as playwright:
        posts, body = [], {}
        browser, page, errors = _open(playwright, site, api, posts)
        try:
            def submit(route):
                body.update(route.request.post_data_json)
                posts.append(dict(body))
                route.fulfill(status=202, json={**body, 'state':'PENDING', 'created_at':1000., 'facts':[]})
            page.route('**/api/fleet/assistant/messages', submit)
            page.route('**/api/fleet/assistant/messages/*', lambda route: route.fulfill(json={
                **body, 'state':'ANSWERED', 'response':'확인한 상태입니다.', 'facts':[], 'created_at':1000.}))
            page.locator('#context-tools-tab').click()  # D-926: AI lives in the tools tab
            page.locator('#assistant-toggle').click()
            expect(page.locator('#assistant-send')).to_be_enabled()
            page.locator('#assistant-input').fill('상태 알려줘')
            page.locator('#assistant-send').click()
            expect(page.locator('#assistant-messages')).to_contain_text('요청 접수')
            page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
            page.clock.run_for(3000)
            expect(page.locator('#assistant-messages')).to_contain_text('확인한 상태입니다.')
            expect(page.locator('#assistant-input')).to_be_enabled()
            assert len(posts) == 1 and not errors
        finally:
            browser.close()


def test_credential_change_quarantines_old_conversation_before_session_returns(site):
    from playwright.sync_api import expect, sync_playwright
    api = {**API, '/api/fleet/session':{'principal_id':'alice','role':'operator'},
           '/api/fleet/assistant/status':{'available':True,'mode':'READ_ONLY'}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        deferred = []
        try:
            page.route('**/api/fleet/assistant/messages', lambda route: route.fulfill(status=202, json={
                **route.request.post_data_json, 'state':'ANSWERED', 'response':'Alice private answer', 'facts':[], 'created_at':1000.}))
            page.locator('#context-tools-tab').click()  # D-926: AI lives in the tools tab
            page.locator('#assistant-toggle').click()
            expect(page.locator('#assistant-send')).to_be_enabled()
            page.locator('#assistant-input').fill('Alice private question')
            page.locator('#assistant-send').click()
            expect(page.locator('#assistant-messages')).to_contain_text('Alice private answer')
            page.locator('#assistant-input').fill('Alice private draft')
            page.route('**/api/fleet/session', lambda route: deferred.append(route))
            page.evaluate("document.getElementById('console-token').value='new-credential';document.getElementById('token-save').click()")
            expect(page.locator('#assistant-messages li')).to_have_count(0)
            expect(page.locator('#assistant-input')).to_have_value('')
            for control in ('assistant-send', 'assistant-dictate', 'assistant-read'):
                expect(page.locator('#'+control)).to_be_disabled()
            assert deferred
            for route in deferred:
                route.fulfill(json={'principal_id':'bob','role':'operator'})
            expect(page.locator('#assistant-input')).to_be_enabled()
            assert not errors
        finally:
            browser.close()


def test_recording_is_cancelled_and_draft_reenabled_after_page_restore(site):
    from playwright.sync_api import expect, sync_playwright
    api = {**API, '/api/fleet/assistant/status':{'available':True,'mode':'READ_ONLY'}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            page.add_init_script('''{
                class LocalSpeech {
                    static async available() { return 'available'; }
                    start() { window.recognizing = true; }
                    abort() { window.recognizing = false; }
                    stop() { this.onend(); }
                }
                LocalSpeech.prototype.processLocally = false;
                window.SpeechRecognition = LocalSpeech;
            }''')
            # Reload so the real panel captures the browser's injected recognizer.
            page.reload(); page.clock.run_for(2000)
            page.locator('#context-tools-tab').click()  # D-926: AI lives in the tools tab
            page.locator('#assistant-toggle').click()
            page.locator('#assistant-dictate').click()
            expect(page.locator('#assistant-voice-state')).to_contain_text('듣고 있습니다')
            assert page.evaluate('window.recognizing') is True
            page.evaluate("dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true}));dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
            page.clock.run_for(2000)
            assert page.evaluate('window.recognizing') is False
            expect(page.locator('#assistant-input')).to_be_enabled()
            assert not errors
        finally:
            browser.close()


def test_assistant_control_handoff_picks_place_confirms_and_submits_navigation(site):
    from playwright.sync_api import expect, sync_playwright
    api = {
        **API,
        '/api/fleet/assistant/status': {
            'available': True, 'mode': 'READ_ONLY', 'reason': None, 'execution_enabled': True,
        },
        '/api/fleet/site-map': {
            'maps': [{
                'map_id': 'site-main',
                'polygon_m': [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]],
                'bounds_m': {'min_x': 0.0, 'min_y': 0.0, 'max_x': 2.0, 'max_y': 2.0},
            }],
        },
        '/api/fleet/site-map/active': {
            'version': 1,
            'activated_by': 'bob',
            'map': {
                'map_id': 'site-main',
                'places': [{'id': 'dock_a', 'name': '도크 A', 'kind': 'dock', 'x': 1.25, 'y': -0.5, 'yaw': 0.5}],
                'edges': [],
            },
        },
    }
    with sync_playwright() as playwright:
        posts, nav_posts = [], []
        browser, page, errors = _open(playwright, site, api, posts)
        try:
            def handle_msg(route):
                body = route.request.post_data_json
                posts.append(body)
                route.fulfill(status=202, json={
                    **body, 'state': 'ANSWERED', 'kind': 'CONTROL',
                    'response': '아래에서 이동 좌표를 확인해 접수해 주세요.',
                    'facts': [], 'created_at': 1000., 'completed_at': 9999999999., 'reason': None,
                    'action_admissible': False,
                })

            def handle_nav(route):
                body = route.request.post_data_json
                nav_posts.append(body)
                route.fulfill(status=200, json={
                    'accepted': True, 'queued': True,
                    'task': {'task_id': 'nav-task-42', 'robot_id': body['robot_id'], 'status': 'QUEUED'},
                })

            page.route('**/api/fleet/assistant/messages/*/navigation', handle_nav)
            page.route('**/api/fleet/assistant/messages', handle_msg)

            page.locator('#assistant-quick-toggle').click()
            expect(page.locator('#assistant-panel')).to_be_visible()
            expect(page.locator('#assistant-quick-toggle')).to_have_attribute('aria-expanded', 'true')
            expect(page.locator('#assistant-mode-tag')).to_contain_text('대화·명령 가능')

            page.locator('#assistant-robot').select_option('rosy_01')
            page.locator('[data-assistant-prompt="move"]').click()
            import re
            expect(page.locator('#assistant-input')).to_have_value(re.compile(r'rosy_01'))
            page.locator('#assistant-send').click()

            expect(page.locator('#assistant-messages')).to_contain_text('명령 제안')
            expect(page.locator('#assistant-messages')).to_contain_text('명령 대상: rosy_01')
            assert posts[-1]['selected_robot_id'] == 'rosy_01'

            page.locator('[data-assistant-place="true"]').select_option('dock_a')
            expect(page.locator('[data-assistant-coord="x"]')).to_have_value('1.25')
            expect(page.locator('[data-assistant-coord="y"]')).to_have_value('-0.50')
            expect(page.locator('[data-assistant-coord="yaw"]')).to_have_value('0.50')

            page.locator('[data-assistant-nav-submit="true"]').click()
            dialog = page.locator('dialog.ui-confirm')
            expect(dialog).to_be_visible()
            expect(page.locator('#estop')).to_be_visible()
            dialog.get_by_role('button', name='요청 전송').click()
            expect(dialog).to_be_hidden()

            assert nav_posts == [{'robot_id': 'rosy_01', 'x': 1.25, 'y': -0.5, 'yaw': 0.5}]
            expect(page.locator('.assistant-receipt')).to_contain_text('nav-task-42')
            expect(page.locator('.assistant-receipt a[href="/console?view=work"]')).to_be_visible()
            assert not errors
        finally:
            browser.close()


def test_assistant_control_readonly_and_conflict_refusal_never_dispatch(site):
    from playwright.sync_api import expect, sync_playwright
    api = {
        **API,
        '/api/fleet/assistant/status': {
            'available': True, 'mode': 'READ_ONLY', 'reason': None, 'execution_enabled': False,
        },
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            page.route('**/api/fleet/assistant/messages', lambda route: route.fulfill(status=202, json={
                **route.request.post_data_json, 'state': 'ANSWERED', 'kind': 'CONTROL',
                'response': '작업 화면에서 진행해 주세요.', 'facts': [],
                'created_at': 1000., 'completed_at': 9999999999., 'reason': None, 'action_admissible': False,
            }))
            page.locator('#assistant-quick-toggle').click()
            expect(page.locator('#assistant-mode-tag')).to_contain_text('조회 전용')
            page.locator('#assistant-robot').select_option('rosy_01')
            page.locator('#assistant-input').fill('rosy_01을 보내줘')
            page.locator('#assistant-send').click()
            expect(page.locator('.assistant-command-card')).to_contain_text('조회 전용 모드')
            expect(page.locator('.assistant-command-card a[href="/console?view=work&show=new"]')).to_be_visible()
            expect(page.locator('[data-assistant-nav-submit="true"]')).to_have_count(0)

            page.route('**/api/fleet/assistant/status', lambda route: route.fulfill(json={
                'available': True, 'mode': 'READ_ONLY', 'reason': None, 'execution_enabled': True,
            }))
            page.route('**/api/fleet/assistant/messages/*/navigation', lambda route: route.fulfill(
                status=409, json={'detail': 'ASSISTANT_CONTROL_EXPIRED'},
            ))
            page.locator('#assistant-new-chat').click()
            page.locator('#assistant-close').click()
            page.locator('#assistant-quick-toggle').click()
            expect(page.locator('#assistant-mode-tag')).to_contain_text('대화·명령 가능')
            page.locator('#assistant-input').fill('rosy_01 이동')
            page.locator('#assistant-send').click()
            page.locator('[data-assistant-coord="x"]').fill('1.0')
            page.locator('[data-assistant-coord="y"]').fill('2.0')
            page.locator('[data-assistant-nav-submit="true"]').click()
            dialog = page.locator('dialog.ui-confirm')
            expect(dialog).to_be_visible()
            dialog.get_by_role('button', name='요청 전송').click()
            expect(page.locator('.assistant-nav-error')).to_contain_text('30초')
            expect(page.locator('.assistant-receipt')).to_have_count(0)
            assert not errors
        finally:
            browser.close()


def test_assistant_catalog_object_syncs_camera_highlight_and_confirms_one_shot_task(site):
    import copy
    import json
    import time
    from playwright.sync_api import expect, sync_playwright

    now_s = time.time()
    api = copy.deepcopy(API)
    api['/api/fleet/assistant/status'] = {'available': True, 'mode': 'READ_ONLY', 'reason': None, 'execution_enabled': True}
    api['/api/fleet/charge-bays'] = {
        'schema_version': 'rosy.charge-bays.v1',
        'thresholds': {'go_percent': 15, 'leave_percent': 80},
        'bays': [{'bay': 'C1', 'state': 'free', 'robot_id': None}],
        'actions': [],
        'omx_cells': {'cell_s': {'station': {'station_place': 'S3'}, 'gate': {'phase': 'IDLE'}}},
        'omx_cell_tasks': [],
    }
    api['/api/fleet/pipeline/cell-objects'] = {
        'schema': 'rosy.cell-detected-objects.v1',
        'observed_at': now_s,
        'cells': {
            'cell_s': {
                'cell_id': 'cell_s',
                'cell_state_gen': 12,
                'arms': {
                    'arm_s': {
                        'schema': 'rosy.cell-detected-objects.v1', 'cell_id': 'cell_s', 'arm_id': 'arm_s',
                        'camera_role': 'arm_s_top', 'frame_wh': [640, 480], 'source_seq': 77,
                        'observed_at': now_s, 'ttl_s': 15.0, 'cell_state_gen': 12, 'stale': False,
                        'objects': [
                            {'object_ref': 'det:77:0', 'catalog_id': 'container-1', 'site': 'pinky',
                             'centre_mm': [14.0, -3.0], 'centre_px': [320.0, 240.0],
                             'corners_px': [[290, 210], [350, 210], [350, 270], [290, 270]],
                             'pickable': True, 'bind_tol_mm': 13.5},
                            {'object_ref': 'det:77:1', 'catalog_id': 'unmatched', 'site': 'pinky', 'centre_mm': [0.0, 0.0], 'pickable': True},
                        ],
                    }
                },
            }
        },
        'by_arm': {},
    }
    ans = {'/api/fleet/pipeline/cell-tasks': (200, {'task': {'task_id': 'ct-ai-1', 'arm_id': 'arm_s', 'status': 'QUEUED'}})}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, answers=ans, size=(1440, 900))
        try:
            page.route('**/api/fleet/assistant/messages', lambda route: route.fulfill(status=202, json={
                **route.request.post_data_json, 'state': 'ANSWERED', 'kind': 'CONTROL',
                'response': 'cell_s에서 container-1 객체가 확인됩니다.',
                'facts': [{'ref': 'cell_objects:cell_s', 'text': 'cell_s 카탈로그 객체: container-1@pinky(1개, 선택가능)', 'observed_at': 1000.}],
                'created_at': 1000., 'completed_at': 9999999999., 'reason': None, 'action_admissible': False,
            }))
            inspector = page.locator('#omx-right-inspector details.omx-pipeline-disclosure')
            inspector.locator('summary').click()
            inspector.locator('[data-dual-cam-toggle="true"]').click()

            page.locator('#assistant-quick-toggle').click()
            page.locator('#assistant-input').fill('container-1 옮겨줘')
            page.locator('#assistant-send').click()

            chip = page.locator('[data-assistant-obj-chip="det:77:0"]')
            expect(chip).to_be_visible()
            assert page.locator('[data-assistant-obj-chip="det:77:1"]').count() == 0
            chip.click()
            expect(page.locator('#omx-right-inspector [data-cam-object="det:77:0"].ai-highlighted')).to_have_count(1)

            page.locator('[data-assistant-obj-submit="true"]').click()
            dialog = page.locator('dialog.ui-confirm')
            expect(dialog).to_be_visible()
            dialog.locator('ui-button[kind="irreversible"]').click()
            expect(page.locator('#assistant-messages .assistant-receipt')).to_contain_text('ct-ai-1')

            task_posts = [body for path, body in posts if path == '/api/fleet/pipeline/cell-tasks']
            assert len(task_posts) == 1
            sent = json.loads(task_posts[0])
            assert sent['propose'] is False and sent['target_object']['catalog_id'] == 'container-1'
            assert sent['target_object']['expected_cell_state_gen'] == 12
            assert not errors
        finally:
            browser.close()
