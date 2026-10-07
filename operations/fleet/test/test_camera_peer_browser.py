"""Real shared UI component fixture only; API/SQLite is covered separately, no device claims."""
from pathlib import Path
import pytest
from browser_harness import browser_tests_enabled

ROOT=Path(__file__).resolve().parents[3]
WEB=ROOT/'operations/fleet/fleet/server/web'
COMMON=ROOT/'shared/web'
source=(WEB/'install.html').read_text(encoding='utf-8')
PANEL=source[source.index('<section id="camera-peer-panel"'):source.index('</section>',source.index('<section id="camera-peer-panel"'))+10]
HTML='''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/common/tokens.css"><link rel="stylesheet" href="/common/components.css"><link rel="stylesheet" href="/styles.css"></head>
<body><main class="install-shell"><section class="panel camera-link">'''+PANEL+'''</section></main><script type="module">
import {confirmIrreversible} from '/common/ui.js'; import {createCameraPeerPanel} from '/camera-peer.js';
window.gets=[];window.failStatus=0;window.writes=[];window.alive=true;window.owner='named-owner';window.auth='old-owner-token';window.locked=false;window.abort=new AbortController();window.cleanup=[];
window.request={profile:'rosy.camera-peer/1',audience:'fleet-camera-ingest',device_kind:'overhead-camera',source_role:'camera',
request_id:'A'.repeat(32),state:'pending',revision:2,display_code:'4F7K',label:'긴 카메라 이름을 가진 천장 카메라',client_key_sha256:'a'.repeat(64)};
window.fetch=async(path,options={})=>{
 if(!options.method || options.method==='GET'){window.gets.push(path);if(window.failStatus)return {ok:false,status:window.failStatus};}
 if(options.method==='POST'){window.writes.push({path,body:options.body?JSON.parse(options.body):null});window.request=null;return {ok:true,json:async()=>({})};}
 const data=path.endsWith('/pending')?(path.includes('/v2/')?(window.request?[window.request]:[]):{paired_sources:[{source_id:'ceiling_north',has_credential:false}]}):
 path.endsWith('/identity')?{tls_ca_sha256:'b'.repeat(64)}:[];
 return {ok:true,json:async()=>data};};
const scope={capture:()=>({current:()=>window.alive,check:()=>{if(!window.alive)throw new DOMException('closed','AbortError');},signal:window.abort.signal}),
 guard:fn=>(...args)=>{if(window.alive)return fn(...args);},interval:()=>{},onDispose:fn=>window.cleanup.push(fn)};
window.panel=createCameraPeerPanel({scope,headers:()=>({Authorization:'Bearer '+window.auth}),identity:()=>({role:'operator',principal_id:window.owner}),locked:()=>window.locked,dialogs:{confirmIrreversible},onUnauthorized:()=>{window.locked=true}});
await panel.refresh();window.ready=true;
</script></body></html>'''


@pytest.fixture
def browser():
    if not browser_tests_enabled():
        pytest.skip("opt-in Chromium scenario; set ROSY_RUN_BROWSER_TESTS=1")
    # Explicit opt-in requires both the package and browser; dependency failure is real.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as play:
        browser=play.chromium.launch(headless=True)
        yield browser
        browser.close()


def page(browser,width=390):
    result=browser.new_page(viewport={'width':width,'height':844})
    def reply(route):
        path=route.request.url.split('receiver.fixture',1)[1]
        if path=='/':route.fulfill(status=200,content_type='text/html',body=HTML);return
        file=COMMON/path[len('/common/'):] if path.startswith('/common/') else WEB/path.lstrip('/')
        if not file.is_file():route.fulfill(status=404,body='');return
        route.fulfill(status=200,content_type='text/css' if file.suffix=='.css' else 'application/javascript',body=file.read_bytes())
    result.route('https://receiver.fixture/**',reply)
    result.goto('https://receiver.fixture/');result.wait_for_function('window.ready===true')
    return result


def test_real_confirmation_cancel_and_owner_change_submit_nothing(browser):
    current=page(browser)
    current.locator('#camera-peer-panel ui-button').filter(has_text='연결 승인').click()
    current.locator('dialog ui-button').filter(has_text='취소').click()
    assert current.evaluate('window.writes')==[]
    current.locator('#camera-peer-panel ui-button').filter(has_text='연결 승인').click()
    current.evaluate("window.owner='different-owner'")
    current.locator('dialog ui-button').filter(has_text='연결 승인').click()
    assert current.evaluate('window.writes')==[]
    current.close()


def test_real_component_desktop_mobile_and_explicit_remember_submit_once(browser,tmp_path):
    for width in [390,1366]:
        current=page(browser,width)
        assert current.evaluate('document.documentElement.scrollWidth')<=width
        current.screenshot(path=str(tmp_path/f'camera-peer-{width}.png'))
        current.locator('#camera-peer-panel ui-button').filter(has_text='연결 승인').click()
        assert '4F7K' in current.locator('dialog').inner_text()
        current.locator('dialog ui-button').filter(has_text='연결 승인').click()
        current.wait_for_function('window.writes.length===1')
        assert current.evaluate('window.writes[0].body')=={'action':'approve','revision':2,'source_id':'ceiling_north','persist_requested':True}
        assert '마무리' in current.locator('#camera-peer-status').inner_text()
        current.close()


def test_page_lifetime_cancel_closes_owned_confirmation(browser):
    current=page(browser)
    current.locator('#camera-peer-panel ui-button').filter(has_text='연결 승인').click()
    current.evaluate('window.alive=false;window.abort.abort();window.cleanup.forEach(fn=>fn())')
    assert current.locator('dialog[open]').count()==0
    assert current.evaluate('window.writes')==[]
    current.close()


def test_same_principal_credential_rotation_cannot_confirm_old_transaction(browser):
    current=page(browser)
    current.locator('#camera-peer-panel ui-button').filter(has_text='연결 승인').click()
    current.evaluate("window.auth='replacement-owner-token'")
    current.locator('dialog ui-button').filter(has_text='연결 승인').click()
    assert current.evaluate('window.writes')==[]
    current.evaluate('window.locked=true;window.panel.refresh()')
    assert current.locator('#camera-peer-panel').is_hidden()
    assert current.locator('#camera-peer-requests ui-button').count()==0
    current.close()


@pytest.mark.parametrize('status',[401,403,404])
def test_withdrawn_receiver_auth_clears_controls_and_stops_same_credential_polling(browser,status):
    current=page(browser)
    assert current.locator('#camera-peer-requests input.ui-field').count()==1
    assert current.locator('#camera-peer-requests label.ui-check').count()==1
    current.evaluate('(status)=>{window.failStatus=status}',status)
    current.evaluate('window.panel.refresh()')
    current.wait_for_function("document.getElementById('camera-peer-requests').childElementCount===0")
    if status==403:assert '권한' in current.locator('#camera-peer-status').inner_text()
    count=current.evaluate('window.gets.length')
    current.evaluate('window.panel.refresh()')
    assert current.evaluate('window.gets.length')==count
    assert current.evaluate('window.writes')==[]
    assert current.evaluate('window.locked')==(status==401)
    current.evaluate("window.failStatus=0;window.locked=false;window.cleanup.forEach(fn=>fn());window.panel.refresh()")
    current.locator('#camera-peer-requests input.ui-field').wait_for(state='visible')
    current.close()
