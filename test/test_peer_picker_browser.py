"""D-452 source fixture only: no operator login, service discovery or device action."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from browser_harness import browser_tests_enabled, open_page

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='set ROSY_RUN_BROWSER_TESTS=1 for Chromium')

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'operations/fleet/fleet/server/web'


@pytest.mark.parametrize('width', [390, 800, 1200])
def test_peer_picker_names_owner_navigation_and_session_lifetime(width):
    pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, width, 900)
        except Exception as exc:
            pytest.skip(f'Chromium unavailable: {exc}')

        def resource(route):
            path = urlsplit(route.request.url).path
            if path == '/fixture':
                html = (WEB / 'install.html').read_text(encoding='utf-8').replace(
                    '<script type="module" src="/console/assets/install.js"></script>', '')
                route.fulfill(status=200, content_type='text/html', body=html)
                return
            folder = ROOT / 'shared/web' if path.startswith('/common/') else WEB
            relative = path.removeprefix('/common/').removeprefix('/console/assets/')
            target = (folder / relative).resolve()
            if not target.is_relative_to(folder.resolve()) or not target.is_file():
                route.fulfill(status=404, body='Not Found')
                return
            import mimetypes
            route.fulfill(status=200, content_type=mimetypes.guess_type(str(target))[0] or
                          'application/octet-stream', body=target.read_bytes())

        page.route('http://rosy.test/**', resource)
        page.goto('http://rosy.test/fixture', wait_until='networkidle')
        page.evaluate("""async () => {
          const {createPeerPicker} = await import('/console/assets/peer-picker.js');
          const {createPageScope} = await import('/common/scope.js');
          const {createTaskChooser} = await import('/common/task-chooser.js');
          const el = id => document.getElementById(id), scope = createPageScope();
          const chooser = createTaskChooser({tasks: [
            {id:'peers', title:'장비 찾기', panel:el('peer-picker')},
            {id:'robots', title:'로봇 등록', panel:el('robot-enrollment')},
            {id:'cameras', title:'카메라 연결 승인', panel:el('camera-link')},
            {id:'calibration', title:'카메라 설치·보정', panel:el('camera-calibration')} ]});
          el('install-chooser').append(chooser.element); chooser.setReady();
          const peers = [{name:'긴장비이름'.repeat(12), role:'robot', peer_id:'pinky/one',
            approval:'approved', freshness:'unavailable', readiness:'unknown', address:'198.51.100.9'}];
          let mode = 'normal', locked = false, reads = 0;
          const picker = createPeerPicker({scope, el, isLocked:()=>locked, isActive:()=>true,
            sources:()=>[], onCamera:async()=>{throw Error('unexpected camera action');},
            call:async path=>{
              reads++;
              if (mode==='defer' && path.endsWith('/peers')) await new Promise(resolve=>window.resolveRead=resolve);
              if (mode==='error') throw Error('fixture failure');
              return path.endsWith('/state') ? {robots:[{robot_id:'pinky/one'}]} :
                {peers: mode==='empty'?[]:peers, scanner_state:mode==='expired'?'expired':'online'};
            }});
          window.fixture = {picker, scope, mode:value=>mode=value, reads:()=>reads,
            lock:()=>{locked=true;scope.invalidate();picker.reset();}};
          await picker.refresh();
        }""")
        owner = page.locator('#peer-list a')
        assert owner.get_attribute('href') == '/console?robot=pinky%2Fone'
        assert owner.bounding_box()['height'] >= 44
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert '198.51.100.9' not in page.locator('#peer-list').inner_text()
        page.locator('#peer-role').focus()
        page.keyboard.press('Tab')
        assert page.evaluate('document.activeElement.id') == 'peer-retry'
        assert page.evaluate("""async () => {
          const f=window.fixture, list=document.getElementById('peer-list');
          f.mode('empty');await f.picker.refresh();
          if(!list.hidden) return false;
          f.mode('expired');await f.picker.refresh();
          if(!document.getElementById('peer-status').textContent.includes('검색 정보 만료'))return false;
          if(document.documentElement.scrollWidth>innerWidth)return false;
          f.mode('error');await f.picker.refresh();
          if(!list.hidden||list.querySelector('a'))return false;
          if(document.documentElement.scrollWidth>innerWidth)return false;
          f.mode('normal');await f.picker.refresh();
          if(!list.querySelector('a'))return false;
          const reads=f.reads();f.mode('defer');const pending=f.picker.refresh();
          await f.picker.refresh();if(f.reads()!==reads+2)return false;
          f.lock();window.resolveRead();await pending;
          const lockedReads=f.reads();await f.picker.refresh();
          return list.hidden&&!list.children.length&&f.reads()===lockedReads;
        }""")
        assert errors == []
        browser.close()
