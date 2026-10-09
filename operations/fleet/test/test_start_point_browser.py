"""Real Chromium start-point workflow with fake robot transport, not field proof.

D-540 5: start points live in install's 카메라 설치·보정 task and are picked on the map-fit
top-down picture; the operate console has none of the setup tools.
"""
import os
import json
from pathlib import Path
import threading
import time

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, open_token_access, safe_listener

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore
from fleet.swarm.robots import RobotEndpoint
from test_overhead_tracking_api import APPROVAL

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium scenario')
ROOT = Path(__file__).resolve().parents[3]


def capture_console(page, name):
    directory = os.environ.get('ROSY_UX_EVIDENCE_DIR')
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        page.evaluate('window.scrollTo(0, 0)')
        page.screenshot(path=str(target / name), full_page=True)


@pytest.fixture
def browser_site(tmp_path):
    from playwright.sync_api import sync_playwright
    robot=FakeRobot('robot-a', state={'robot_id':'robot-a','mode':'IDLE'})
    console=FleetConsole([RobotEndpoint('robot-a','http://127.0.0.1:8080','robot-rest')],[robot])
    source=SightingSource('north','source-token',('robot-a',),'track','corners',(30,31,32,33),
                          corner_world_m=((0,0),(6.4,0),(6.4,3.6),(0,3.6)))
    sightings=SightingService([source],known_robot_ids=console.robot_ids)
    tracking=TrackingService([source],calibrations=TrackingCalibrationStore(tmp_path/'sightings.sqlite3'))
    tracking.approve({**APPROVAL,'source_id':'north','map_id':'track'},approved_by='op')
    # D-540 9: start-point writes need a named operator, so the token names one.
    from hashlib import sha256
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    users={sha256(b'operator-secret').hexdigest():{'principal_id':'op','role':'operator'},
           # the unnamed shared credential resolves to the principal `site-console`
           sha256(b'shared-secret').hexdigest():{'principal_id':'site-console','role':'operator'}}
    tasks=FleetTaskService(FleetTaskStore(tmp_path/'tasks.sqlite3'),robot_ids={'robot-a'})
    app=create_app(console,site_users=users,task_service=tasks,web_common=ROOT/'shared/web',
                   sightings=sightings,tracking=tracking,start_task_dispatcher=False)
    listener=safe_listener()
    origin=f'http://127.0.0.1:{listener.getsockname()[1]}'
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',timeout_graceful_shutdown=3,timeout_keep_alive=1))
    worker=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);worker.start()
    try:
        deadline=time.monotonic()+20
        while not server.started and worker.is_alive() and time.monotonic()<deadline: time.sleep(.02)
        assert server.started
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(viewport={'width':1440,'height':1000})
                page.add_init_script("sessionStorage.setItem('rosy-console-token','operator-secret')")
                page.origin=origin
                page.fleet_app=app  # lets a test seed server state (tethers) directly
                yield page, robot, tracking
            finally: browser.close()
    finally:
        server.should_exit=True;worker.join(timeout=20);listener.close()
        assert not worker.is_alive()


# The calibration task needs a Rosy Cam frame and site lanes to draw the top-down picture.
# 640×360 matches APPROVAL's image; the 6.4×3.6 m track is the approved map 'track'.
SITE_LANES={'maps':[{'map_id':'track','source_ids':['north'],
                     'bounds_m':{'min_x':0.0,'min_y':0.0,'max_x':6.4,'max_y':3.6},
                     'polylines':[{'points':[[0.3,0.4],[6.1,0.4]]},{'points':[[0.3,3.2],[6.1,3.2]]}],
                     'paint_triangles':[]}]}
LEASE={'source_id':'north','lease':'test-lease','frame_path':'/api/vision/sources/north/frame','expires_in_s':60}
FRAME='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#556070"/></svg>'


def open_install(page, lanes=SITE_LANES):
    page.route('**/api/fleet/site-lanes',lambda route:route.fulfill(status=200,json=lanes))
    page.route('**/api/fleet/vision/sources',lambda route:route.fulfill(status=200,json={'sources':['north']}))
    page.route('**/api/fleet/vision/lease',lambda route:route.fulfill(status=200,json=LEASE))
    page.route('**/api/vision/sources/north/frame',lambda route:route.fulfill(
        status=200,content_type='image/svg+xml',body=FRAME,
        headers={'X-Frame-Rectified':'false','X-Frame-Seq':'42','X-Frame-Age-Ms':'20'}))
    page.goto(page.origin+'/console/install')
    tab=page.get_by_role('tab',name='카메라 설치·보정')
    if tab.is_visible(): tab.click()
    else: page.locator('.ui-task-compact select').select_option('calibration')


def test_markerless_pick_on_the_install_picture_save_reload_and_recalibration(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    open_install(page)
    expect(page.locator('#map-fit-figure')).to_be_visible(timeout=15000)
    expect(page.locator('#start-point-pick')).to_be_enabled(timeout=15000)
    page.locator('#start-point-pick').click()
    canvas=page.locator('#map-fit-canvas'); box=canvas.bounding_box()
    canvas.click(position={'x':box['width']/2,'y':box['height']/2})
    # topDownLayout pads the 6.4×3.6 m track by 0.1 m, so the picture centre is (3.2, 1.8).
    assert abs(float(page.locator('#start-point-x').input_value())-3.2)<.05
    assert abs(float(page.locator('#start-point-y').input_value())-1.8)<.05
    page.locator('#start-point-yaw').fill('90')
    page.locator('#start-point-save').click()
    expect(page.locator('#start-point-state')).to_contain_text('방향 90.0°',timeout=10000)
    capture_console(page, 'install-start-point.png')
    assert not [call for call in robot.calls if call[0]=='navigation_goal']
    open_install(page)
    expect(page.locator('#start-point-state')).to_contain_text('방향 90.0°',timeout=15000)
    tracking.approve({**APPROVAL,'source_id':'north','map_id':'track','frame_seq':99},approved_by='op')
    expect(page.locator('#start-point-state')).to_contain_text('보정이 바뀌었습니다',timeout=10000)
    assert not [call for call in robot.calls if call[0]=='navigation_goal']
    assert not errors


def test_saved_start_point_is_drawn_on_the_install_picture(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    open_install(page)
    expect(page.locator('#map-fit-figure')).to_be_visible(timeout=15000)
    expect(page.locator('#start-point-save')).to_be_enabled(timeout=15000)
    page.evaluate("""() => {
      const ctx=document.getElementById('map-fit-canvas').getContext('2d'), arc=ctx.arc;
      window.startArcs=[];ctx.arc=function(...args){window.startArcs.push(args);return arc.apply(this,args);};
    }""")
    for field,value in [('x','1'),('y','.5'),('yaw','30')]:page.locator('#start-point-'+field).fill(value)
    page.locator('#start-point-save').click()
    expect(page.locator('#start-point-state')).to_contain_text('X 1.00',timeout=10000)
    # 640/6.6 px per m from x0=-0.1, y1=3.7: (1, .5) -> (106.667, 310.303).
    page.wait_for_function("window.startArcs.some(a=>Math.abs(a[0]-106.667)<.01 && Math.abs(a[1]-310.303)<.01)")
    assert not [call for call in robot.calls if call[0]=='navigation_goal']


def test_calibration_changed_during_pick_cancels_it_and_saves_nothing(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    puts=[];page.on('request',lambda r:puts.append(r.url) if r.method in ('PUT','DELETE') else None)
    open_install(page)
    expect(page.locator('#map-fit-figure')).to_be_visible(timeout=15000)
    expect(page.locator('#start-point-pick')).to_be_enabled(timeout=15000)
    page.locator('#start-point-pick').click()
    expect(page.locator('#start-point-pick')).to_have_text('위치 선택 취소')
    tracking.approve({**APPROVAL,'source_id':'north','map_id':'track','frame_seq':77},approved_by='op')
    expect(page.locator('#start-point-pick')).to_have_text('카메라 평면에서 시작 위치 선택',timeout=10000)
    canvas=page.locator('#map-fit-canvas'); box=canvas.bounding_box()
    canvas.click(position={'x':box['width']/2,'y':box['height']/2})
    assert page.locator('#start-point-x').input_value()==''
    assert not puts
    assert not [call for call in robot.calls if call[0]=='navigation_goal']


def test_picture_of_another_map_cannot_be_picked(browser_site):
    """Lanes for another map: map-fit-view fleetFit refuses the calibration, so no picture and no pick."""
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    other={'maps':[{**SITE_LANES['maps'][0],'map_id':'other'}]}
    open_install(page, other)
    expect(page.locator('#start-point-pick')).to_be_enabled(timeout=15000)
    page.wait_for_timeout(3000)
    expect(page.locator('#map-fit-figure')).to_be_hidden()
    page.locator('#start-point-pick').click()
    expect(page.locator('#start-point-state')).to_contain_text('그림이 보일 때')
    expect(page.locator('#start-point-pick')).to_have_text('카메라 평면에서 시작 위치 선택')
    assert page.locator('#start-point-x').input_value()==''


def test_shared_site_token_cannot_write_start_points(browser_site):
    """D-540 9: the shared token (principal site-console) reads but cannot save or delete."""
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    page.add_init_script("sessionStorage.setItem('rosy-console-token','shared-secret')")
    open_install(page)
    for control in ('#start-point-save','#start-point-pick','#start-point-x'):
        expect(page.locator(control)).to_be_disabled(timeout=15000)
    expect(page.locator('#start-point-save')).to_have_attribute('reason','이름 있는 운영자 로그인이 필요합니다',timeout=15000)


def test_token_switch_clears_start_reference_and_blocks_edits(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    open_install(page)
    expect(page.locator('#start-point-save')).to_be_enabled(timeout=15000)
    for field,value in [('x','1'),('y','.5'),('yaw','0')]:page.locator('#start-point-'+field).fill(value)
    page.locator('#start-point-save').click()
    expect(page.locator('#start-point-state')).to_contain_text('X 1.00',timeout=10000)
    open_token_access(page)
    page.locator('#console-token').fill('invalid-token')
    page.locator('#token-save').click()
    expect(page.locator('#start-point-save')).to_be_disabled()
    assert page.locator('#start-point-x').input_value()==''
    assert not [call for call in robot.calls if call[0]=='navigation_goal']


def test_missing_calibration_shows_next_action_on_mobile(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking = browser_site
    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/api/fleet/calibrations', lambda route: route.fulfill(
        status=200, content_type='application/json', body='{"calibrations":[]}'))
    page.set_viewport_size({'width':390,'height':844})
    open_install(page)
    expect(page.locator('#start-point-state')).to_contain_text('보정을 먼저 적용', timeout=15000)
    expect(page.locator('#start-point-save')).to_be_disabled()
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    capture_console(page, 'calibration-mobile.png')
    assert not [call for call in robot.calls if call[0] == 'navigation_goal']
    assert not errors


def test_console_has_no_setup_tools_and_connection_guide_recovers(browser_site):
    """D-540 3: under the operate map only the legend and 관제 범위 안내 remain."""
    from playwright.sync_api import expect
    page, robot, tracking = browser_site
    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(page.origin+'/console')
    expect(page.locator('#dispatch-control')).to_be_visible(timeout=15000)
    for absent in ('#start-point-tools', '#start-point-save', '#tracking-relearn'):
        expect(page.locator(absent)).to_have_count(0)
    expect(page.locator('details.note > summary', has_text='관제 범위 안내')).to_have_count(1)
    open_token_access(page)
    page.locator('#console-token').fill('')
    page.locator('#token-save').click()
    expect(page.locator('#connection-guide')).to_be_visible()
    expect(page.locator('#roster')).to_contain_text('관제에 접속하면')
    expect(page.locator('#map-empty-title')).to_have_text('관제 접속 필요')
    expect(page.locator('#dispatch-control')).to_be_hidden()  # D-487: one lock banner
    capture_console(page, 'connection-desktop.png')
    page.locator('#connection-guide-action').click()
    expect(page.locator('#console-token')).to_be_focused()
    page.locator('#console-token').fill('operator-secret')
    page.locator('#console-token').press('Enter')
    expect(page.locator('#connection-guide')).to_be_hidden()
    expect(page.locator('#dispatch-control')).to_be_visible()
    capture_console(page, 'connected-desktop.png')
    assert not [call for call in robot.calls if call[0] == 'navigation_goal']
    assert not errors


def test_map_draws_the_travelled_trail_and_a_tether(browser_site):
    """D-594 trail from Fleet's recorded path (survives a reload) and a D-512 tether circle on the metre site view.
    The robot reports LOCALIZED in the map frame: a robot without localization (motor mode) may report odom."""
    page, robot, tracking = browser_site
    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
    from playwright.sync_api import expect
    page.goto(page.origin+'/console')
    expect(page.locator('#map-stage')).to_have_attribute('data-map-state', 'site', timeout=15000)

    def overlay(key, at_least):  # CSP forbids wait_for_function strings; poll with evaluate instead
        deadline = time.monotonic() + 15
        while (page.evaluate(f'window.__trailOverlay?.{key} || 0') < at_least) and time.monotonic() < deadline:
            page.wait_for_timeout(200)
        return page.evaluate(f'window.__trailOverlay?.{key} || 0')
    robot._state['pose'] = {'x': 1.0, 'y': 1.0, 'yaw': 0.0}
    robot._state['localization'] = {'state': 'LOCALIZED', 'pose_frame': 'map'}
    for x, y in ((1.6, 1.2), (2.4, 1.8), (3.2, 2.0)):
        page.wait_for_timeout(1300)
        robot._state['pose'] = {'x': x, 'y': y, 'yaw': 0.0}
    assert overlay('segments', 2) >= 2
    page.reload()  # the path is Fleet's record, not the page's
    expect(page.locator('#map-stage')).to_have_attribute('data-map-state', 'site', timeout=15000)
    assert overlay('segments', 2) >= 2
    page.fleet_app.state.tethers['robot-a'] = {'anchor_xy': [2.0, 1.5], 'radius_m': 1.0, 'set_by': 'op'}
    assert overlay('tethers', 1) == 1
    capture_console(page, 'map-trail-tether.png')
    assert not errors
