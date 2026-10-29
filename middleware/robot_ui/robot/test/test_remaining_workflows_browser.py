"""Procedure results and confirmation targets survive live readbacks."""
from test_panel_copy_evidence_browser import panel, pytestmark, MOUNT
from playwright.sync_api import expect
import pytest
import os
from pathlib import Path
from uuid import uuid4


@pytest.mark.parametrize('method', ['POST', 'DELETE'])
@pytest.mark.parametrize('read_failed', [False, True])
@pytest.mark.parametrize('width', [320, 390, 768, 1440])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_ssh_write_failure_survives_followup_read_and_explicit_retry(panel, method, read_failed, width, theme):
    page = panel('system/security.js', role='administrator', width=width)
    page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
    section = page.locator('section').filter(has=page.get_by_role('heading', name='임시 SSH 비밀번호', exact=True))
    page.evaluate("""() => {
      window.sshWrites = 0;
      window.__api = async (_path, options = {}) => {
        if (options.method) { sshWrites++; throw new Error('fixture write rejected'); }
        return {enabled: true, expires_at: 'fixture expiry'};
      };
    }""")
    # The initial read has already completed; a failed action must not lose its result to this read.
    if method == 'DELETE':
        section.locator('form').evaluate('form => form.requestSubmit()')
        expect(section.get_by_text('임시 비밀번호 켜짐 · 만료 fixture expiry', exact=True)).to_be_visible()
    page.evaluate('sshWrites = 0')
    if read_failed:
        page.evaluate("""() => {window.__api = async (_path, options = {}) => {
          if (options.method) { sshWrites++; throw new Error('fixture write rejected'); }
          throw new Error('fixture read rejected');
        };}""")
    control = section.get_by_role('button', name='임시 비밀번호 발급' if method == 'POST' else '지금 끄기', exact=True)
    control.focus()
    page.keyboard.press('Space' if method == 'DELETE' else 'Enter')
    expected = '발급에 실패했습니다: fixture write rejected' if method == 'POST' else '끄지 못했습니다: fixture write rejected'
    expect(section.get_by_text(expected, exact=True)).to_be_visible()
    expect(section.get_by_text('SSH 비밀번호 상태를 가져오지 못했습니다. 호스트 에이전트를 확인하세요.' if read_failed else '임시 비밀번호 켜짐 · 만료 fixture expiry', exact=True)).to_be_visible()
    assert page.evaluate('sshWrites') == 1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    capture_dir = os.environ.get('ROSY_UI_CAPTURE_DIR')
    if capture_dir:
        from browser_harness import save_temp_screenshot
        destination = Path(capture_dir) / f'ssh-{method}-{read_failed}-{width}-{theme}-{uuid4().hex}.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        section.scroll_into_view_if_needed()
        save_temp_screenshot(page, str(destination))
    if not read_failed:
        page.evaluate("""() => {window.__api = async (_path, options = {}) => {
          if (options.method) { sshWrites++; return {password:'fixture-one-time-credential', expires_at:'fixture expiry'}; }
          return {enabled: false};
        };}""")
        control.click()
        expect(section.get_by_text(expected, exact=True)).to_have_count(0)
        expect(section.get_by_text('임시 비밀번호는 꺼져 있습니다(키 로그인만 가능).', exact=True)).to_be_visible()


def test_ssh_initial_read_blocks_actions_until_state_is_known(panel):
    page = panel('system/security.js', role='administrator')
    page.evaluate("""() => {
      __unmount(); document.querySelector('#root').replaceChildren();
      window.sshWrites = 0;
      window.__api = (_path, options = {}) => {
        if (options.method) { sshWrites++; return Promise.resolve({}); }
        return new Promise(resolve => window.finishSsh = resolve);
      };
    }""")
    page.evaluate(MOUNT, ['/assets/panels/system/security.js', 'administrator'])
    section = page.locator('section').filter(has=page.get_by_role('heading', name='임시 SSH 비밀번호', exact=True))
    for control in section.locator('ui-button').all():
        expect(control).to_be_disabled()
        assert control.get_attribute('reason') == '상태 확인 중'
    section.locator('form').evaluate('form => form.requestSubmit()')
    assert page.evaluate('sshWrites') == 0
    page.evaluate('finishSsh({enabled: true})')
    for control in section.locator('ui-button').all():
        expect(control).to_be_enabled()


@pytest.mark.parametrize('method', ['POST', 'DELETE'])
def test_ssh_mutations_lock_both_actions_through_readback(panel, method):
    page = panel('system/security.js', role='administrator')
    section = page.locator('section').filter(has=page.get_by_role('heading', name='임시 SSH 비밀번호', exact=True))
    page.evaluate("""() => {window.__api = async (_path, options = {}) => options.method
      ? {password:'fixture-one-time-credential-before', expires_at:'fixture expiry'} : {enabled:true};}""")
    section.locator('form').evaluate('form => form.requestSubmit()')
    expect(section.get_by_text('임시 비밀번호 켜짐 · 만료 알 수 없음', exact=True)).to_be_visible()
    page.evaluate("""() => {
      window.sshWrites = 0;
      window.__api = (_path, options = {}) => {
        if (options.method) { sshWrites++; return new Promise(resolve => window.finishWrite = resolve); }
        return new Promise(resolve => window.finishRead = resolve);
      };
    }""")
    section.get_by_role('button', name='임시 비밀번호 발급' if method == 'POST' else '지금 끄기', exact=True).click()
    for control in section.locator('ui-button').all():
        expect(control).to_be_disabled()
    section.locator('form').evaluate('form => form.requestSubmit()')
    assert page.evaluate('sshWrites') == 1
    page.evaluate("finishWrite({password:'fixture-one-time-credential', expires_at:'fixture expiry'})")
    page.wait_for_function("typeof finishRead === 'function'")
    for control in section.locator('ui-button').all():
        expect(control).to_be_disabled()
    page.evaluate('finishRead({enabled: true})')
    for control in section.locator('ui-button').all():
        expect(control).to_be_enabled()


def test_ssh_one_time_credential_survives_read_failure(panel):
    page = panel('system/security.js', role='administrator')
    page.evaluate("""() => {window.__api = async (_path, options = {}) => {
      if (options.method === 'POST') return {password:'fixture-one-time-credential', expires_at:'fixture expiry'};
      throw new Error('read unavailable');
    };}""")
    section = page.locator('section').filter(has=page.get_by_role('heading', name='임시 SSH 비밀번호', exact=True))
    section.locator('form').evaluate('form => form.requestSubmit()')
    expect(section.get_by_text('임시 비밀번호가 발급되었습니다(rosy@로봇, fixture expiry까지).', exact=True)).to_be_visible()
    expect(section.get_by_text('SSH 비밀번호 상태를 가져오지 못했습니다. 호스트 에이전트를 확인하세요.', exact=True)).to_be_visible()
    expect(section.get_by_text('rosy 계정 비밀번호: fixture-one-time-credential · fixture expiry까지', exact=True)).to_be_visible()
    assert page.evaluate("Object.values(localStorage).concat(Object.values(sessionStorage)).join('').includes('fixture-one-time-credential')") is False


@pytest.mark.parametrize('method', ['GET', 'POST', 'DELETE'])
def test_ssh_late_response_does_not_mutate_disposed_panel(panel, method):
    page = panel('system/security.js', role='administrator')
    page.evaluate("""() => {window.__api = async (_path, options = {}) => {
      if (!options.method) return {enabled:true};
      return new Promise(resolve => window.finishSsh = resolve);
    };}""")
    section = page.locator('section').filter(has=page.get_by_role('heading', name='임시 SSH 비밀번호', exact=True))
    if method == 'DELETE':
        section.locator('form').evaluate('form => form.requestSubmit()')
        page.wait_for_function("typeof finishSsh === 'function'")
        page.evaluate("finishSsh({password:'fixture-one-time-credential-before', expires_at:'fixture expiry'})")
        expect(section.get_by_text('임시 비밀번호 켜짐 · 만료 알 수 없음', exact=True)).to_be_visible()
        section.get_by_role('button', name='지금 끄기', exact=True).click()
    else:
        if method == 'GET':
            page.evaluate("""() => {window.__api = async (_path, options = {}) => options.method
              ? {password:'fixture-one-time-credential-before', expires_at:'fixture expiry'}
              : new Promise(resolve => window.finishSsh = resolve);}""")
        section.locator('form').evaluate('form => form.requestSubmit()')
    page.wait_for_function("typeof finishSsh === 'function'")
    page.evaluate("""() => {
      __unmount(); window.closedDOM = document.querySelector('#root').innerHTML;
      window.closedCalls = __calls.length;
      finishSsh({enabled:true, password:'fixture-one-time-credential-late', expires_at:'fixture expiry'});
    }""")
    page.wait_for_timeout(50)
    assert page.evaluate("document.querySelector('#root').innerHTML === closedDOM")
    assert page.evaluate('__calls.length === closedCalls')


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
    page.get_by_text('고급 네트워크 작업',exact=True).click()
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


def test_lamp_test_shows_device_result_without_claiming_physical_identity(panel):
    page = panel('host/hardware.js', role='administrator')
    page.evaluate("""() => {
      __callbacks['/api/v1/host/hardware'].onData({available:true,measured_at:'2026-10-09T00:00:00Z',
        devices:[{id:'lamp',label:'후면 램프',state:'needs_human',evidence:'사람 확인 필요'}]});
      window.__api = async (path, options) => {
        __calls.push({path, body:options.body});
        return {accepted:true,request_id:'lamp-1'};
      };
    }""")
    page.get_by_role('button', name='후면 램프 자가 시험').click()
    expect(page.locator('#hardware-action-note')).to_contain_text('lamp-1')
    assert page.evaluate('__calls.at(-1)') == {
        'path': '/api/v1/host/hardware/test', 'body': '{"device":"lamp"}'
    }
    page.evaluate("""() => __callbacks['/api/v1/host/hardware'].onData({available:true,
      devices:[{id:'lamp',label:'후면 램프',state:'needs_human'}],
      test:{request_id:'other',action:'lamp',state:'done'}})""")
    assert '장치 시험 완료' not in page.locator('#hardware-action-note').inner_text()
    page.evaluate("""() => __callbacks['/api/v1/host/hardware'].onData({available:true,
      devices:[{id:'lamp',label:'후면 램프',state:'needs_human'}],
      test:{request_id:'lamp-1',action:'lamp',state:'done'}})""")
    expect(page.locator('#hardware-action-note')).to_contain_text('장치 시험 완료')
    expect(page.locator('#hardware-action-note')).to_contain_text('영상에서 몸체를 확인')

    viewer = panel('host/hardware.js', role='viewer')
    viewer.evaluate("""() => __callbacks['/api/v1/host/hardware'].onData({available:true,
      devices:[{id:'lamp',label:'후면 램프',state:'needs_human'}]})""")
    assert viewer.get_by_role('button', name='후면 램프 자가 시험').is_disabled()
