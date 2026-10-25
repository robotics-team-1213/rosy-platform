"""LOCAL simulated telemetry: real shared view, Fleet roster and robot panel. No device traffic."""
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled, save_temp_screenshot
from test_fleet_console_browser import ROOT, console_url, _open_console, _robot, MAP_GRID  # noqa: F401
from test_fleet_workcell_observation_browser import cell_url  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='set ROSY_RUN_BROWSER_TESTS=1')
ROBOT = ROOT / 'middleware/robot_ui/robot'


def health(evidence='fresh', status='active'):
    motors = []
    for arm in ('arm_a', 'arm_b'):
        for motor_id, joint in ((11,'shoulder_pan'), (12,'shoulder_lift'), (13,'elbow_flex'),
                                (14,'wrist_flex'), (15,'wrist_roll')):
            loaded = motor_id == 12 and arm == 'arm_a'
            motors.append(dict(group=arm,joint=joint,id=motor_id,sample_age_s=.2,
                               command_raw=2028,present_raw=2028,error_deg=0,pwm=-391 if loaded else 30,
                               pwm_limit=400,pwm_utilization=.9775 if loaded else .075,
                               temperature_c=65 if loaded else 31,temperature_limit_c=70,
                               voltage_v=12,min_voltage_v=6,max_voltage_v=14,
                               hardware_error=32 if status=='fault' and loaded else None,
                               warnings=['high_pwm','near_temperature_limit'] if loaded else []))
    return dict(schema_version='rosy.motor-health.v1',evidence=evidence,status=status,
                owner_id='LOCAL guarded owner',session_id='LOCAL-fixture-session',sample_age_s=.2,
                stale_after_s=2,motors=motors,stop_reasons=['arm_a ID12 hardware overload'] if status=='fault' else [])


def local_label(page, selector='body'):
    page.evaluate("""selector => {
      const label=document.createElement('p');label.textContent='LOCAL · simulated telemetry · no hardware acceptance';
      label.id='local-evidence';document.querySelector(selector).prepend(label);
    }""", selector)


@pytest.mark.parametrize('width', [320,390,1366])
def test_fleet_summary_and_selected_robot_share_motor_detail(console_url, width):
    from playwright.sync_api import sync_playwright
    robot = _robot('omx_local', {'x':1,'y':1,'yaw':0}, motor_health=health(),motor_health_age_s=.1)
    api = {'/api/fleet/state':{'fleet':{'online':1,'total':1},'robots':[robot]},
           '/api/fleet/map':MAP_GRID,'/api/fleet/formation':{'active':False}}
    with sync_playwright() as playwright:
        browser,page,errors = _open_console(playwright,api)
        page.set_viewport_size({'width':width,'height':844 if width<1000 else 900})
        page.goto(console_url,wait_until='networkidle')
        page.locator('#roster [data-motor-robot="omx_local"]').wait_for()
        assert '모터 주의' in page.inner_text('#roster')
        assert '주의 모터 1개' in page.inner_text('#roster')
        assert 'ID 12: PWM 사용률 높음' in page.inner_text('#roster')
        local_label(page, '#roster article')
        save_temp_screenshot(page.locator('#roster article'),f'motor_health_fleet_LOCAL_summary_{width}.png')
        page.locator('[data-select-robot-id="omx_local"]').click()
        panel=page.locator('#robot-workspace .motor-health')
        panel.wait_for()
        assert panel.locator('tbody tr').count()==10
        assert 'PWM 사용률 높음' in panel.inner_text()
        assert '-391 / 400' in panel.inner_text() and '목표 2028 / 현재 2028 tick' in panel.inner_text()
        assert panel.locator('[data-state-missing]').count() == 0
        assert page.evaluate('document.documentElement.scrollWidth-innerWidth')==0
        scroll=panel.locator('.motor-health-scroll')
        scroll.focus()
        page.keyboard.press('ArrowRight')
        if scroll.evaluate('element=>element.scrollWidth>element.clientWidth'):
            page.wait_for_function("document.activeElement.classList.contains('motor-health-scroll') && document.activeElement.scrollLeft>0")
        scroll.evaluate('element=>element.scrollLeft=0')
        local_label(page, '#robot-workspace .motor-health')
        page.locator('#local-evidence').scroll_into_view_if_needed()
        save_temp_screenshot(page,f'motor_health_fleet_LOCAL_{width}.png')
        assert errors==[]
        browser.close()


ROBOT_PAGE = """<!doctype html><html lang='ko'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<link rel='stylesheet' href='/common/tokens.css'><link rel='stylesheet' href='/common/components.css'>
<link rel='stylesheet' href='/common/motor-health.css'><link rel='stylesheet' href='/assets/styles.css'>
<link rel='stylesheet' href='/assets/panels/surface-panels.css'>
<link rel='stylesheet' href='/assets/shell/shell.css'>
<script type='module' src='/common/ui.js'></script></head><body>
<p>LOCAL · Robot console panel · simulated telemetry · no hardware acceptance</p>
<main class='surface-main'><ui-section id='motor-panel' class='surface-panel'></ui-section></main></body></html>"""


def mount_robot(page, base):
    page.route('**/robot-motor-local',lambda route:route.fulfill(content_type='text/html',body=ROBOT_PAGE))
    def assets(route):
        name=route.request.url.split('/assets/',1)[1]
        path=ROBOT / name
        route.fulfill(content_type='text/css' if path.suffix=='.css' else 'text/javascript',body=path.read_bytes())
    page.route('**/assets/**',assets)
    page.goto(base+'/robot-motor-local',wait_until='networkidle')
    page.evaluate("""async () => {
      const {mount}=await import('/assets/panels/console/motor-health.js');
      window.__stop=mount(document.getElementById('motor-panel'),{store:{poll(path,ms,onData,onError){
        window.__health={path,ms,onData,onError};return()=>{window.__stopped=true;};}}});
    }""")


@pytest.mark.parametrize('width', [320,390,1366])
def test_robot_panel_evidence_states_age_while_waiting_and_retain_fault(console_url,width):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        page=browser.new_page(viewport={'width':width,'height':844 if width<1000 else 900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        mount_robot(page,console_url.rsplit('/',1)[0])
        assert page.evaluate('window.__health.path')=='/api/v1/motors/health'
        page.evaluate('sample=>window.__health.onData(sample)',health())
        panel=page.locator('#motor-panel')
        assert panel.get_attribute('data-evidence')=='fresh'
        assert panel.locator('tbody tr').count()==10
        save_temp_screenshot(page,f'motor_health_robot_LOCAL_fresh_{width}.png')
        page.wait_for_function("document.getElementById('motor-panel').dataset.evidence==='delayed'",timeout=5000)
        assert panel.locator('tbody tr[data-evidence="fresh"]').count()==0
        save_temp_screenshot(page,f'motor_health_robot_LOCAL_delayed_{width}.png')
        page.evaluate('sample=>window.__health.onData(sample)',health(status='fault'))
        assert 'arm_a ID12 hardware overload' in panel.inner_text()
        assert '하드웨어 오류 32' in panel.inner_text()
        assert panel.get_attribute('data-evidence')!='fresh'
        save_temp_screenshot(page,f'motor_health_robot_LOCAL_fault_{width}.png')
        page.evaluate('window.__health.onError(new Error("offline"))')
        assert panel.get_attribute('data-evidence')=='disconnected'
        assert '마지막 중단' in panel.inner_text()
        save_temp_screenshot(page,f'motor_health_robot_LOCAL_disconnected_{width}.png')
        unavailable=dict(schema_version='rosy.motor-health.v1',evidence='unavailable',status='unavailable',
                         sample_age_s=None,motors=[],support_reason='휠 모터별 관측을 제공하지 않습니다.')
        page.evaluate('sample=>window.__health.onData(sample)',unavailable)
        assert panel.get_attribute('data-evidence')=='unavailable'
        assert '휠 모터별 관측을 제공하지 않습니다.' in panel.inner_text()
        assert 'arm_a ID12 hardware overload' in panel.inner_text()
        assert panel.locator('tbody tr').count()==0
        save_temp_screenshot(page,f'motor_health_robot_LOCAL_unavailable_{width}.png')
        assert page.evaluate('document.documentElement.scrollWidth-innerWidth')==0
        page.evaluate('window.__stop()')
        assert page.evaluate('window.__stopped') is True
        assert errors==[]
        browser.close()


@pytest.mark.parametrize('width',[390,1366])
def test_cell_arm_health_uses_shared_view_without_double_aging_and_retains_fault(cell_url,width):
    from playwright.sync_api import expect, sync_playwright
    from test_fleet_workcell_observation_browser import observation_feed
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        page=browser.new_page(viewport={'width':width,'height':900})
        state,snapshot=observation_feed(page)
        payload={'status':'active','missing':False,'hold':False}
        def observations(route):
            if payload['hold']:
                state.held.append(route)
                return
            data=snapshot()
            for cell in data['workcells']:
                for arm in cell['arms']:
                    arm['source_age_s']=arm['receipt_age_s']=1.1
                    if payload['missing']:
                        continue
                    motor=health(status=payload['status'])
                    motor['sample_age_s']=1.1
                    motor['motors']=[{**row,'joint':f"joint{row['id']-10}",'sample_age_s':1.1}
                                     for row in motor['motors'] if row['group']==arm['arm_id']]
                    arm['motor_health']=motor
            route.fulfill(json=data)
        page.route('**/api/fleet/workcell-observations',observations)
        page.goto(cell_url)
        card=page.locator('[data-arm-source="feedback_a"]')
        expect(card.locator('.motor-health-summary')).to_contain_text('주의 모터 1개')
        assert card.locator('.motor-health-summary').get_attribute('data-evidence')=='fresh'
        card.locator('summary').click()
        expect(card.locator('.motor-health tbody tr')).to_have_count(5)
        assert '어깨 올림' in card.locator('.motor-health').inner_text()
        local_label(page,'[data-arm-source="feedback_a"] .motor-health')
        payload['status']='fault'
        expect(card.locator('.motor-health')).to_contain_text('하드웨어 오류 32')
        expect(card.locator('.motor-health-summary')).to_contain_text('고장 모터 1개')
        save_temp_screenshot(card,f'motor_health_cell_LOCAL_fault_{width}.png')
        payload['hold']=True
        expect(card.locator('.motor-health')).to_have_attribute('data-evidence','disconnected',timeout=6000)
        assert 'hardware overload' in card.inner_text()
        payload['hold']=False;payload['missing']=True
        expect(card.locator('.motor-health-summary')).to_contain_text('확인 불가')
        assert 'hardware overload' in card.inner_text()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        card.scroll_into_view_if_needed()
        save_temp_screenshot(page,f'motor_health_cell_LOCAL_{width}.png')
        assert not state.failed_assets,state.failed_assets
        page.unroute_all(behavior='ignoreErrors')
        browser.close()


@pytest.mark.parametrize('focus', ['table','select'])
def test_kept_fleet_card_reads_current_fault_and_offline_row(console_url,focus):
    from playwright.sync_api import sync_playwright
    robot = _robot('omx_local', {'x':1,'y':1,'yaw':0}, motor_health=health(),motor_health_age_s=.1)
    api = {'/api/fleet/state':{'fleet':{'online':1,'total':1},'robots':[robot]},
           '/api/fleet/map':MAP_GRID,'/api/fleet/formation':{'active':False}}
    with sync_playwright() as playwright:
        browser,page,errors = _open_console(playwright,api)
        page.goto(console_url,wait_until='networkidle')
        page.locator('[data-select-robot-id="omx_local"]').click()
        panel = page.locator('#robot-workspace .motor-health')
        panel.wait_for()
        if focus == 'select':
            # The retained form path is shared with a destination picker; this LOCAL field has no command handler.
            page.evaluate("""() => {const select=document.createElement('select');select.id='local-picker';
              const option=document.createElement('option');option.textContent='LOCAL';select.append(option);
              document.querySelector('#robot-workspace article').append(select);select.focus();}""")
        else:
            panel.locator('.motor-health-scroll').focus()
        page.evaluate("window.__kept=document.querySelector('#robot-workspace article')")
        robot['motor_health'] = health(status='fault')
        page.wait_for_function("document.querySelector('#robot-workspace .motor-health').textContent.includes('hardware overload')")
        assert '주의 모터 1개' in page.inner_text('#roster')
        assert 'hardware overload' in page.inner_text('#roster')
        assert page.evaluate("window.__kept===document.querySelector('#robot-workspace article')")
        if focus == 'table':
            local_label(page, '#robot-workspace .motor-health')
            page.locator('#local-evidence').scroll_into_view_if_needed()
            save_temp_screenshot(page,'motor_health_fleet_LOCAL_fault_1920.png')
        robot['online'] = False
        page.wait_for_function("document.querySelector('#robot-workspace .motor-health').dataset.evidence==='disconnected'")
        assert 'hardware overload' in panel.inner_text()
        if focus == 'table':
            save_temp_screenshot(page,'motor_health_fleet_LOCAL_disconnected_1920.png')
        assert errors == []
        browser.close()


@pytest.mark.parametrize('surface', ['fleet','robot'])
def test_slow_response_counts_browser_transit_against_sample_freshness(console_url,surface):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        if surface == 'fleet':
            robot = _robot('omx_local', {'x':1,'y':1,'yaw':0}, motor_health=health(),motor_health_age_s=0)
            api={'/api/fleet/state':{'fleet':{'online':1,'total':1},'robots':[robot]},
                 '/api/fleet/map':MAP_GRID,'/api/fleet/formation':{'active':False}}
            script="""(() => { const fetchNow=window.fetch.bind(window); window.fetch=async (url,options)=>{
              if(String(url).includes('/api/fleet/state')) await new Promise(resolve=>setTimeout(resolve,2500));
              return fetchNow(url,options);
            }; })();"""
            browser,page,errors=_open_console(playwright,api,init_script=script)
            page.goto(console_url,wait_until='domcontentloaded')
            summary=page.locator('#roster [data-motor-robot="omx_local"]')
            summary.wait_for()
            assert summary.get_attribute('data-evidence')=='delayed'
        else:
            browser=playwright.chromium.launch();page=browser.new_page()
            mount_robot(page,console_url.rsplit('/',1)[0])
            page.evaluate("""async sample=>{
              window.__stop();
              const {createStore}=await import('/assets/shell/store.js');
              const {mount}=await import('/assets/panels/console/motor-health.js');
              const store=createStore(async ()=>{await new Promise(resolve=>setTimeout(resolve,2500));return sample;});
              const scope=store.scope();
              window.__stop=mount(document.getElementById('motor-panel'),{store:scope});
            }""",health())
            panel=page.locator('#motor-panel')
            panel.locator('tbody tr').first.wait_for()
            assert panel.get_attribute('data-evidence')=='delayed'
        browser.close()
