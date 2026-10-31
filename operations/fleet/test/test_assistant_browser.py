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
