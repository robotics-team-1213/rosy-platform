"""Browser checks for capability-fail-closed role surfaces."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from browser_harness import open_page


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "hmi" / "dashboard"

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


def test_setup_localization_fails_closed_when_capabilities_are_missing():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        source = (WEB / "panels" / "setup" / "localization.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/setup/localization.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/setup/localization.js');
          const root = document.createElement('main'); document.body.append(root);
          const apiCalls = [];
          const store = {poll(path, interval, onData, onError) {
            window.__caps = onData; window.__poll = path; return () => { window.__stopped = true; };
          }};
          const api = async (path) => { apiCalls.push(path); return {accepted: true}; };
          window.__apiCalls = apiCalls;
          window.__unmount = mount(root, {role: 'operator', api, store});
          window.__caps({navigation: {goal_navigation: false}, slam: false});
          window.confirm = () => true;
          root.querySelector('form').dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
          root.querySelector('ui-button').click();
        }""")
        assert page.evaluate("window.__poll") == "/api/v1/system/capabilities"
        assert page.locator("ui-button").evaluate_all("nodes => nodes.every(node => node.disabled)")
        assert "사용할 수 없는 기능" in page.locator("[role=status]").inner_text()
        assert page.evaluate("window.__apiCalls") == []
        page.evaluate("window.__unmount()")
        assert page.evaluate("window.__stopped") is True
        assert errors == []
        browser.close()


def test_setup_docking_refuses_teach_without_fresh_pose():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        source = (WEB / "panels" / "setup" / "docking.js").read_text(encoding="utf-8")
        state_logic = (ROOT / "src" / "hmi" / "web" / "core_ui_logic.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/setup/docking.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.route("http://rosy.test/common/core_ui_logic.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=state_logic))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/setup/docking.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, _interval, onData, onError) { callbacks[path] = {onData, onError}; return () => {}; }};
          const apiCalls = [];
          window.__apiCalls = apiCalls;
          window.__unmount = mount(root, {role: 'operator', store, api: async (path) => { apiCalls.push(path); }});
          callbacks['/api/v1/docking/status'].onData({supported: false, state: 'UNDOCKED'});
          callbacks['/api/v1/docking/docks'].onData({docks: [{id: 'dock-a', type: 'charger', map_id: 'map-a'}]});
          callbacks['/api/v1/robot/state'].onData({pose:{x:1,y:1},evidence:{pose:{evidence:'disconnected'}}});
          window.confirm = () => true;
          root.querySelector('[data-dock-id="dock-a"] ui-button').click();
        }""")
        assert "최신이 아니어서" in page.locator("[role=status]").inner_text()
        assert page.locator("[data-dock-id='dock-a'] ui-button").evaluate("node => node.disabled === true")
        assert page.evaluate("window.__apiCalls") == []
        page.evaluate("window.__unmount()")
        assert errors == []
        browser.close()


def test_console_docking_blocks_motion_when_capability_is_missing():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        source = (WEB / "panels" / "console" / "docking.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/docking.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/docking.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, _interval, onData) { callbacks[path] = onData; return () => {}; }};
          const calls = []; window.__calls = calls;
          window.__unmount = mount(root, {role:'operator',store,api:async path=>calls.push(path)});
          callbacks['/api/v1/docking/status']({supported:false,state:'UNDOCKED'});
          callbacks['/api/v1/docking/docks']({docks:[{id:'dock-a',type:'charger'}]});
          window.confirm=()=>true;
          root.querySelectorAll('ui-button').forEach(button=>button.click());
        }""")
        assert "막았습니다" in page.locator("[role=status]").inner_text()
        assert page.locator("ui-button").evaluate_all("nodes=>nodes.every(node=>node.disabled===true)")
        assert page.evaluate("window.__calls") == []
        page.evaluate("window.__unmount()")
        assert errors == []
        browser.close()


def test_device_host_operations_block_writes_when_host_agent_is_absent():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        source = (WEB / "panels" / "host" / "operations.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/host/operations.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/host/operations.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, _interval, onData, onError) { callbacks[path] = {onData, onError}; return () => {}; }};
          const calls = []; window.__calls = calls;
          window.__unmount = mount(root, {role: 'administrator', store, api: async (path) => calls.push(path)});
          callbacks['/api/v1/host/network'].onData({available: false, detail: 'agent offline'});
          callbacks['/api/v1/host/release'].onData({available: false, detail: 'agent offline'});
          window.confirm = () => true;
          root.querySelectorAll('ui-button').forEach(button => button.click());
        }""")
        assert "agent offline" in page.locator("[role=status]").all_inner_texts()[0]
        assert page.locator("ui-button").evaluate_all("nodes => nodes.every(node => node.disabled === true)")
        assert page.evaluate("window.__calls") == []
        page.evaluate("window.__unmount()")
        assert errors == []
        browser.close()


def test_console_map_is_keyboard_focusable_and_viewer_cannot_send_a_goal():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        module = (WEB / "panels" / "console" / "map.js").read_text(encoding="utf-8")
        map_source = (WEB / "map.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/map.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=module))
        page.route("http://rosy.test/map.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=map_source))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/map.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {}; const stopped = [];
          const store = {poll(path, _interval, onData) { callbacks[path] = onData; return () => stopped.push(path); }};
          const calls = []; window.__calls = calls;
          const api = async (path, options = {}) => {
            calls.push({path, method: options.method || 'GET'});
            if (path === '/api/v1/map') return {map_id:'map-a', width:2, height:2, resolution:1, origin:{x:0,y:0}, data:[0,0,0,0]};
            if (path === '/api/v1/navigation/path') return {poses:[]};
            if (path.startsWith('/api/v1/map/costmap')) return {data:[]};
            return {};
          };
          window.__stopped = stopped;
          window.__unmount = mount(root, {role:'viewer', api, store});
          callbacks['/api/v1/robot/state']({pose:{x:0.5,y:0.5,yaw:0}, navigation:'IDLE'});
          callbacks['/api/v1/system/capabilities']({navigation:{goal_navigation:true}});
          window.confirm = () => { window.__confirmed = true; return true; };
          const canvas = root.querySelector('canvas'); canvas.focus();
          canvas.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
          canvas.dispatchEvent(new MouseEvent('click', {clientX:20,clientY:20,bubbles:true}));
        }""")
        assert page.locator("canvas").get_attribute("tabindex") is not None
        assert page.locator("canvas").get_attribute("aria-label")
        assert page.evaluate("window.__calls.filter(call => call.method === 'POST')") == []
        page.evaluate("window.__unmount()")
        assert set(page.evaluate("window.__stopped")) == {"/api/v1/robot/state", "/api/v1/system/capabilities"}
        assert errors == []
        browser.close()


def test_console_teleop_sends_repeated_hold_and_terminal_zero():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        module = (WEB / "panels" / "console" / "teleop.js").read_text(encoding="utf-8")
        state_logic = (ROOT / "src" / "hmi" / "web" / "core_ui_logic.js").read_text(encoding="utf-8")
        ticker = (ROOT / "src" / "hmi" / "web" / "hold-ticker.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/teleop.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=module))
        page.route("http://rosy.test/common/core_ui_logic.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=state_logic))
        page.route("http://rosy.test/common/hold-ticker.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=ticker))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/teleop.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, _interval, onData, onError) { callbacks[path] = {onData,onError}; return () => {}; }};
          const calls = []; window.__calls = calls;
          const api = async (path, options) => { calls.push({path,body:JSON.parse(options.body)}); return {}; };
          window.__unmount = mount(root, {role:'operator', api, store});
          callbacks['/api/v1/robot/state'].onData({mode:'MANUAL', pose:{x:1,y:1}, velocity:{linear:0,angular:0}, evidence:{pose:{evidence:'fresh'},velocity:{evidence:'fresh'}}});
          callbacks['/api/v1/system/capabilities'].onData({teleop:true});
          callbacks['/api/v1/safety/state'].onData({estop:false});
          const check = root.querySelector('input[type=checkbox]'); check.checked = true; check.dispatchEvent(new Event('change'));
          window.__button = root.querySelector('.surface-teleop-controls ui-button');
          window.__button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:1}));
        }""")
        page.wait_for_timeout(240)
        page.evaluate("window.__button.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1}))")
        page.wait_for_timeout(30)
        calls = page.evaluate("window.__calls")
        assert len(calls) >= 3
        assert all(call["path"] == "/api/v1/teleop" for call in calls)
        assert any(call["body"]["linear"] > 0 for call in calls)
        assert calls[-1]["body"] == {"linear": 0, "angular": 0}
        page.evaluate("window.__unmount()")
        assert errors == []
        browser.close()


def test_console_camera_preview_stops_on_hidden_document_and_unmount():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        module = (WEB / "panels" / "console" / "camera.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/camera.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=module))
        page.route("http://rosy.test/client.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body="export const session={token:'test'}; export const authHeaders=()=>({});"))
        page.route("http://rosy.test/vision.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body="export function createVisionPreview(){return {start(){window.__started=(window.__started||0)+1;},stop(){window.__stopped=(window.__stopped||0)+1;}};}"))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/camera.js');
          const root = document.createElement('main'); document.body.append(root);
          window.__unmount = mount(root, {role:'viewer', api:async()=>({})});
          Object.defineProperty(document, 'hidden', {configurable:true, value:true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        assert page.locator("img#vision-frame").get_attribute("alt") == "전방 카메라 실시간 영상"
        assert page.evaluate("window.__started") == 1
        assert page.evaluate("window.__stopped") == 1
        page.evaluate("window.__unmount()")
        assert page.evaluate("window.__stopped") == 2
        assert errors == []
        browser.close()
