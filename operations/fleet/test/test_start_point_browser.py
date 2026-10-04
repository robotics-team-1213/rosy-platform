"""Real Chromium start-point workflow with fake robot transport, not field proof."""
import os
import json
from pathlib import Path
import socket
import threading
import time

import pytest
import uvicorn

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.sightings import SightingService, SightingSource
from fleet.server.tracking import TrackingService
from fleet.server.tracking_calibration import TrackingCalibrationStore
from fleet.swarm.robots import RobotEndpoint
from test_overhead_tracking_api import APPROVAL

pytestmark = pytest.mark.skipif(os.environ.get('ROSY_BROWSER_TESTS') != '1', reason='opt-in Chromium scenario')
ROOT = Path(__file__).resolve().parents[3]


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
    app=create_app(console,console_token='operator-secret',web_common=ROOT/'shared/web',
                   sightings=sightings,tracking=tracking,start_task_dispatcher=False)
    listener=socket.socket();listener.bind(('127.0.0.1',0))
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
                page.goto(origin+'/console')
                yield page, robot, tracking
            finally: browser.close()
    finally:
        server.should_exit=True;worker.join(timeout=20);listener.close()
        assert not worker.is_alive()


def test_markerless_map_pick_save_reload_and_recalibration(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    expect(page.locator('#start-point-pick')).to_be_enabled(timeout=15000)
    expect(page.locator('#map-stage')).to_have_attribute('data-map-state','site',timeout=15000)
    page.locator('#start-point-pick').click()
    page.locator('#map-canvas').click(position={'x':400,'y':180})
    assert page.locator('#start-point-x').input_value()
    page.locator('#start-point-yaw').fill('90')
    page.locator('#start-point-save').click()
    expect(page.locator('#start-point-state')).to_contain_text('방향 90.0°',timeout=10000)
    assert not [call for call in robot.calls if call[0]=='navigation_goal']
    page.reload()
    expect(page.locator('#start-point-state')).to_contain_text('방향 90.0°',timeout=15000)
    tracking.approve({**APPROVAL,'source_id':'north','map_id':'track','frame_seq':99},approved_by='op')
    expect(page.locator('#start-point-state')).to_contain_text('보정이 바뀌었습니다',timeout=10000)
    assert not [call for call in robot.calls if call[0]=='navigation_goal']
    assert not errors


def test_token_switch_clears_start_reference_and_blocks_edits(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    expect(page.locator('#start-point-save')).to_be_enabled(timeout=15000)
    for field,value in [('x','1'),('y','.5'),('yaw','0')]:page.locator('#start-point-'+field).fill(value)
    page.locator('#start-point-save').click()
    expect(page.locator('#start-point-state')).to_contain_text('X 1.00',timeout=10000)
    if page.locator('#topbar-more').is_visible(): page.locator('#topbar-more').click()
    page.locator('#console-token').fill('invalid-token')
    page.locator('#token-save').click()
    expect(page.locator('#start-point-save')).to_be_disabled()
    assert page.locator('#start-point-x').input_value()==''
    assert not [call for call in robot.calls if call[0]=='navigation_goal']


def test_map_changed_during_pick_is_cancelled_and_grid_marker_is_drawn(browser_site):
    from playwright.sync_api import expect
    page, robot, tracking=browser_site
    grid={'map_id':'track','width':100,'height':60,'resolution':.064,'origin':{'x':0,'y':0,'yaw':0},'data':[0]*6000}
    state={'grid':grid}
    page.route('**/api/fleet/map',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(state['grid'])))
    page.reload()
    expect(page.locator('#map-stage')).to_have_attribute('data-map-state','ready',timeout=15000)
    expect(page.locator('#start-point-pick')).to_be_enabled(timeout=15000)
    page.evaluate("""() => {
      const ctx=document.getElementById('map-canvas').getContext('2d'), arc=ctx.arc;
      window.startArcs=[];ctx.arc=function(...args){window.startArcs.push(args);return arc.apply(this,args);};
    }""")
    for field,value in [('x','1'),('y','.5'),('yaw','30')]:page.locator('#start-point-'+field).fill(value)
    page.locator('#start-point-save').click()
    expect(page.locator('#start-point-state')).to_contain_text('X 1.00',timeout=10000)
    page.wait_for_function("window.startArcs.some(a=>Math.abs(a[0]-15.625)<.001 && Math.abs(a[1]-52.1875)<.001)")
    page.locator('#start-point-pick').click()
    state['grid']={**grid,'map_id':'other'}
    expect(page.locator('#map-tag')).to_contain_text('other',timeout=15000)
    page.locator('#map-canvas').click(position={'x':150,'y':100})
    expect(page.locator('#start-point-state')).to_contain_text('지도가 바뀌었습니다')
    assert not [call for call in robot.calls if call[0]=='navigation_goal']
