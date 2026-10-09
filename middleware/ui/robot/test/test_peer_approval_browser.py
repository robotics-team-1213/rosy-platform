"""Component-only browser fixture, real shared dialog; no device/TLS acceptance."""
import json
import tempfile
from pathlib import Path
import unittest

from browser_harness import browser_tests_enabled

ROOT = Path(__file__).resolve().parents[4]
COMMON = ROOT / 'shared/web'
UI = ROOT / 'middleware/ui/robot'

HTML = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/common/tokens.css"><link rel="stylesheet" href="/common/components.css"><link rel="stylesheet" href="/styles.css"></head>
<body><main><article id="panel" class="settings-card" aria-labelledby="heading"><header><h3 id="heading">기기 연결 승인</h3></header>
<p class="host-note" data-peer-message role="status"></p><ul class="waypoint-list" data-peer-list></ul></article></main>
<script type="module">
import {confirmIrreversible} from '/common/ui.js'; import {createReceiverApprovals} from '/peer-approval.js';
window.writes=[]; window.alive=true; window.owner=new AbortController();
const ticket=()=>({current:()=>window.alive,signal:window.owner.signal});
const row={request_id:'A'.repeat(32),revision:3,label:'현장 태블릿',client_id:'pilot_01',role:'operator',display_code:'4F7K',client_key_sha256:'a'.repeat(64)};
async function api(path, options={}) { if(options.method==='POST'){writes.push({path,body:JSON.parse(options.body)});return {persistent:true};} if(path.endsWith('/identity'))return {tls_hostname:'receiver.fixture',tls_ca_sha256:'b'.repeat(64)}; return [row]; }
async function runConfirmed(message, opener, eligible, run, fail, pending,kind,action){
const owner=ticket(); if(!eligible())return; try{if(!await confirmIrreversible({message,action,opener,signal:owner.signal})||!owner.current()||!eligible())return; pending(true); await run(owner.current,owner);}catch(e){fail(e);}finally{pending(false);}}
window.panel=createReceiverApprovals({root:document.getElementById('panel'),api,isAdmin:()=>window.alive,captureLifetime:ticket,runConfirmed});
await window.panel.refresh(); window.ready=true;
</script></body></html>'''


@unittest.skipUnless(browser_tests_enabled(), "set ROSY_RUN_BROWSER_TESTS=1 for the Chromium check")
class ReceiverBrowser(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright

        evidence=tempfile.TemporaryDirectory()
        self.addCleanup(evidence.cleanup)
        self.evidence=Path(evidence.name)
        self.play = sync_playwright().start()
        self.browser = self.play.chromium.launch(headless=True)
        self.addCleanup(self.play.stop)
        self.addCleanup(self.browser.close)

    def page(self, width=390, scheme='https'):
        page = self.browser.new_page(viewport={'width': width, 'height': 844})
        self.addCleanup(page.close)
        def reply(route):
            path = route.request.url.split('receiver.fixture',1)[1]
            if path == '/':
                route.fulfill(status=200, content_type='text/html', body=HTML)
            else:
                file = COMMON / path[len('/common/'):] if path.startswith('/common/') else UI / path.lstrip('/')
                route.fulfill(status=200, content_type='text/css' if file.suffix=='.css' else 'application/javascript', body=file.read_bytes())
        page.route(scheme+'://receiver.fixture/**', reply)
        page.goto(scheme+'://receiver.fixture/')
        page.wait_for_function('window.ready===true')
        return page

    def test_shared_confirmation_cancel_and_owner_loss_submit_nothing(self):
        page = self.page()
        page.locator('#panel ui-button').filter(has_text='승인').click()
        page.locator('dialog ui-button').filter(has_text='취소').click()
        self.assertEqual([], page.evaluate('window.writes'))
        page.locator('#panel ui-button').filter(has_text='승인').click()
        page.evaluate('window.alive=false;window.owner.abort();window.panel.clear()')
        self.assertEqual(0, page.locator('dialog[open]').count())
        self.assertEqual([], page.evaluate('window.writes'))

    def test_explicit_remember_approval_and_responsive_real_component(self):
        for width in [390,1366]:
            page = self.page(width)
            self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width)
            page.screenshot(path=str(self.evidence / f'receiver-panel-{width}.png'))
            page.locator('#panel ui-button').filter(has_text='승인').click()
            page.locator('dialog ui-button').filter(has_text='연결 승인').click()
            page.wait_for_function('window.writes.length===1')
            result = page.evaluate('window.writes[0]')
            self.assertEqual({'action':'approve','revision':3,'persist_requested':True}, result['body'])
            self.assertIn('요청한 기기에서 연결을 마무리',page.locator('[data-peer-message]').inner_text())

    def test_http_only_receiver_has_truthful_unavailable_state(self):
        page = self.page(scheme='http')
        self.assertIn('HTTPS', page.locator('[data-peer-message]').inner_text())
        self.assertEqual(0,page.locator('#panel ui-button').count())
        self.assertEqual([],page.evaluate('window.writes'))


if __name__=='__main__':
    unittest.main()
