"""Procedure results and confirmation targets survive live readbacks."""
from test_panel_copy_evidence_browser import panel, pytestmark
from playwright.sync_api import expect


def test_localization_results_have_independent_owners(panel):
    page = panel('setup/localization.js')
    page.evaluate("""() => {
      __callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true});
      window.__api = async path => { if (path.includes('initialpose')) throw new Error('pose rejected'); return {}; };
      window.confirm=()=>true;
    }""")
    page.locator('form').evaluate("form=>form.dispatchEvent(new Event('submit',{cancelable:true}))")
    page.get_by_text('초기 위치 요청을 완료하지 못했습니다: pose rejected', exact=True).wait_for()
    disclosure = page.locator('details').filter(has_text='SLAM 맵 준비')
    if disclosure.count(): disclosure.locator('summary').click()
    page.get_by_role('button', name='맵핑 시작', exact=True).click()
    dialog = page.locator('dialog.ui-confirm')
    if dialog.count(): dialog.locator('ui-button[kind=irreversible]').click()
    page.get_by_text('맵핑 시작 요청을 CORE가 받았습니다.', exact=True).wait_for()
    assert page.get_by_text('초기 위치 요청을 완료하지 못했습니다: pose rejected', exact=True).is_visible()


def test_host_terminal_result_survives_outage_and_missing_hold_is_unknown(panel):
    page = panel('host/operations.js', role='administrator')
    page.evaluate("""() => {
      __callbacks['/api/v1/host/network'].onData({available:true,ok:true,evidence:{evidence:'fresh'},data:{mode:'SITE_STA'}});
      __callbacks['/api/v1/host/commissioning'].onData({runtime_mode:'core',motor_hold:true,lidar_hold:false});
      window.__api=async()=>({available:true,ok:true}); window.confirm=()=>true;
    }""")
    page.get_by_role('button',name='사업장 Wi-Fi로 전환',exact=True).click()
    dialog=page.locator('dialog.ui-confirm')
    if dialog.count(): dialog.locator('ui-button[kind=irreversible]').click()
    page.get_by_text('네트워크 모드 전환을 요청했습니다.',exact=True).wait_for()
    page.evaluate("__callbacks['/api/v1/host/network'].onError(new Error('offline'))")
    assert page.get_by_text('네트워크 모드 전환을 요청했습니다.',exact=True).is_visible()
    card=page.locator('section').filter(has=page.get_by_role('heading',name='커미셔닝',exact=True))
    card.locator('summary').filter(has_text='전체 상태').click()
    assert card.locator('dt').filter(has_text='배터리').locator('+ dd').inner_text() == '확인 전'


def test_token_delete_rechecks_current_identity_after_confirmation(panel):
    page=panel('system/security.js',role='administrator')
    page.evaluate("__callbacks['/api/v1/system/tokens'].onData({tokens:[{id:'other',label:'Desk',role:'operator',current:false}]})")
    page.get_by_role('button',name='삭제…',exact=True).click()
    page.locator('dialog.ui-confirm').wait_for()
    page.evaluate("__callbacks['/api/v1/system/tokens'].onData({tokens:[{id:'other',label:'Desk',role:'operator',current:true}]})")
    page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
    page.wait_for_timeout(50)
    assert page.evaluate("__calls.filter(path=>path.includes('/tokens/'))") == []
    page.evaluate("""() => {window.__api=async(path,options={})=>options.method==='POST'?{token:'one-time-secret'}:new Promise((_resolve,reject)=>window.failReadback=reject);document.querySelector('form').requestSubmit();}""")
    page.wait_for_function("() => typeof window.failReadback==='function'")
    assert page.get_by_text('생성된 토큰은 다시 표시되지 않습니다. 안전한 곳에 기록하세요: one-time-secret',exact=True).is_visible()
    page.evaluate("() => {__unmount();window.closedDOM=document.querySelector('#root').innerHTML;failReadback(new Error('late token read failure'));}")
    page.wait_for_timeout(50)
    assert page.evaluate("document.querySelector('#root').innerHTML===window.closedDOM")


def test_live_confirmation_rejects_changed_target_and_unmounted_owner(panel):
    page=panel('host/operations.js',role='administrator')
    page.evaluate("""() => {
      __callbacks['/api/v1/host/release'].onData({available:true,ok:true,evidence:{evidence:'fresh'},data:{state:'IDLE',previous:'r1'}});
      const stop=document.createElement('ui-button'); stop.id='fixture-stop';stop.setAttribute('kind','irreversible');stop.dataset.alwaysLive='';stop.textContent='fixture stop';
      stop.addEventListener('click',()=>window.stopped=true);document.body.prepend(stop);
    }""")
    rollback=page.get_by_role('button',name='이전 릴리스로 복귀',exact=True)
    rollback.click()
    page.locator('dialog.ui-confirm').wait_for()
    page.locator('#fixture-stop').click()
    expect(page.locator('dialog.ui-confirm')).to_have_count(0)
    assert page.evaluate('window.stopped')
    assert page.evaluate('__calls') == []

    rollback.click()
    page.evaluate("__callbacks['/api/v1/host/release'].onData({available:true,ok:true,evidence:{evidence:'fresh'},data:{state:'IDLE',previous:'r2'}})")
    page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
    assert page.evaluate('__calls') == []
    rollback.click()
    page.evaluate("() => {window.oldExecute=document.querySelector('dialog.ui-confirm ui-button[kind=irreversible]');__unmount();}")
    expect(page.locator('dialog.ui-confirm')).to_have_count(0)
    page.evaluate('oldExecute.click()')
    assert page.evaluate('__calls') == []
    page=panel('setup/localization.js')
    page.evaluate("__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true})")
    page.locator('summary').click()
    page.get_by_role('button',name='맵핑 시작',exact=True).click()
    page.evaluate("__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:false})")
    page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
    assert page.evaluate('__calls') == []


def test_saved_dock_type_is_reported_when_pose_changes_before_registration(panel):
    page=panel('setup/dock-admin.js',role='administrator')
    page.evaluate("""() => {
      __callbacks['/api/v1/docking/types'].onData({types:[]});
      __callbacks['/api/v1/robot/state'].onData({map_id:'map-a',pose:{x:1,y:2,yaw:0},evidence:{pose:{evidence:'fresh'}}});
      window.__api=()=>new Promise(resolve=>window.finishType=resolve);
    }""")
    page.locator('[name=dock_id]').fill('dock-a')
    page.locator('[name=dock_type]').fill('charger-a')
    page.get_by_label('새 도크 유형 검출기',exact=True).select_option('simulated')
    page.locator('form').evaluate('form=>form.requestSubmit()')
    page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
    page.wait_for_function("() => typeof window.finishType==='function'")
    page.evaluate("""() => {__callbacks['/api/v1/robot/state'].onData({map_id:'map-a',pose:{x:3,y:2,yaw:0},evidence:{pose:{evidence:'fresh'}}});finishType({name:'charger-a',detector:'simulated'});}""")
    expect(page.locator('ui-status').filter(has_text='도크 유형은 저장됐습니다.').first).to_be_visible()
    assert page.evaluate('__calls') == ['/api/v1/docking/types']
    assert page.locator('datalist option[value="charger-a"]').count()==1
    assert page.locator('[name=dock_id]').input_value()=='dock-a'


def test_missing_and_future_diagnostic_values_stay_truthful_and_wrap(panel):
    page=panel('system/diagnostics.js')
    page.evaluate("__callbacks['/api/v1/diagnostics'].onData({health:'UNKNOWN',components:{}})")
    assert page.get_by_text('전체 상태: 확인 전',exact=True).is_visible()
    assert '장치 연결을 확인' in page.locator('li').inner_text()
    page.evaluate("__callbacks['/api/v1/diagnostics'].onData({health:'FUTURE',components:{lidar:'WARNING'}})")
    assert page.get_by_text('전체 상태: FUTURE',exact=True).is_visible()
    assert page.get_by_text('lidar: 주의',exact=True).is_visible()
    page=panel('system/events.js',width=390,height=844)
    page.add_style_tag(url='/assets/panels/system/events.css')
    page.evaluate("""() => {__callbacks['/api/v1/events?limit=10'].onData({events:[{type:'future.'.repeat(45),severity:'futureSeverity'},{type:'no.severity'},{type:'known',severity:'warning'}]});}""")
    assert page.locator('.event-type').last.inner_text() == 'future.'*45
    assert page.get_by_text('futureSeverity',exact=True).is_visible()
    assert page.get_by_text('주의',exact=True).is_visible()
    assert page.locator('.event-severity').nth(1).inner_text() == '—'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_display_follows_os_scheme_and_hardware_request_does_not_invent_measurement(panel):
    page=panel('system/display.js')
    page.emulate_media(color_scheme='light')
    page.add_script_tag(url='/common/theme.js')
    # Mount after the actual theme owner has loaded its canonical choices.
    page.evaluate("""async()=>{__unmount();document.querySelector('#root').replaceChildren();const {mount}=await import('/assets/panels/system/display.js');window.__unmount=mount(document.querySelector('#root'));RosyTheme.set('system');}""")
    expect(page.get_by_role('status')).to_contain_text('현재 화면: 밝게')
    assert page.locator('[data-theme-choice] svg').count() == 3
    page.emulate_media(color_scheme='dark')
    expect(page.get_by_role('status')).to_contain_text('현재 화면: 어둡게')
    assert page.evaluate('__calls') == []
    page=panel('host/hardware.js',role='administrator',width=390,height=844)
    page.add_style_tag(url='/assets/panels/host/hardware.css')
    page.evaluate("""() => {__callbacks['/api/v1/host/hardware'].onData({available:true,measured_at:'2026-10-03T00:00:00Z',devices:[]});window.__api=()=>new Promise(resolve=>window.finishRefresh=resolve);}""")
    before=page.locator('.hardware-measured dd').inner_text()
    refresh=page.get_by_role('button',name='보드 장치 점검 요청')
    refresh.click()
    page.evaluate('finishRefresh({accepted:true})')
    expect(page.locator('#hardware-action-note')).to_contain_text('완료 여부는 마지막 측정 시각')
    assert page.locator('.hardware-measured dd').inner_text()==before
    assert refresh.bounding_box()['width'] < page.locator('#root').bounding_box()['width']
