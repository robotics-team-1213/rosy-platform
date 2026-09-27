"""Browser checks for capability-fail-closed role surfaces."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from browser_harness import open_page

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "hmi" / "dashboard"


def _route_panel_test(page) -> None:
    """Load shared elements used by the dashboard shell."""
    ui_source = (ROOT / "src" / "hmi" / "web" / "ui.js").read_text(encoding="utf-8")
    page.route("http://rosy.test/common/ui.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=ui_source))
    pose_source = (WEB / "panels" / "setup" / "pose-evidence.js").read_text(encoding="utf-8")
    page.route("http://rosy.test/assets/panels/setup/pose-evidence.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=pose_source))
    document = (
        '<!doctype html><html><head>'
        '<script type="module" src="/common/ui.js"></script>'
        '</head><body></body></html>'
    )
    page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
        status=200, content_type="text/html",
        body=document))


def _unmount_panel(page) -> None:
    page.evaluate("""() => {
      const mounted = window.__unmount;
      if (typeof mounted === 'function') return mounted();
      if (typeof mounted?.unmount === 'function') return mounted.unmount();
      throw new Error('panel mount did not return a cleanup handle');
    }""")


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
        _route_panel_test(page)
        source = (WEB / "panels" / "setup" / "localization.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/setup/localization.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
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
        assert "사용할 수 없는 기능" in page.locator("[role=status]").filter(has_text="사용할 수 없는 기능").first.inner_text()
        assert page.evaluate("window.__apiCalls") == []
        _unmount_panel(page)
        assert page.evaluate("window.__stopped") is True
        assert errors == []
        browser.close()



def test_setup_localization_preserves_pending_pose_and_slam_actions_during_capability_poll():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "setup" / "localization.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/setup/localization.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/setup/localization.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {}; const calls = [];
          const store = {poll(path, interval, onData, onError) {
            callbacks[path] = {interval, onData, onError}; return () => {};
          }};
          const pending = {};
          const api = (path, options) => {
            calls.push({path, method: options.method});
            return new Promise((resolve, reject) => { pending[path] = {resolve, reject}; });
          };
          window.__callbacks = callbacks; window.__calls = calls; window.__pending = pending;
          window.__unmount = mount(root, {role:'operator', store, api});
          callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true});
          window.confirm = () => true;
        }""")
        assert page.evaluate("window.__callbacks['/api/v1/system/capabilities'].interval") == 10_000
        page.locator("main form").evaluate("node => node.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
        page.wait_for_function("window.__calls.length === 1")
        pose_button = page.locator("main form ui-button[type=submit]")
        assert pose_button.is_disabled()
        pose_status = page.locator("main > ui-status[role=status]").nth(1)
        pending_pose_feedback = pose_status.inner_text()
        page.evaluate("window.__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true})")
        page.locator("main form").evaluate("node => node.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
        assert pose_button.is_disabled()
        assert pose_status.inner_text() == pending_pose_feedback
        assert page.evaluate("window.__calls") == [{"path": "/api/v1/localization/initialpose", "method": "POST"}]
        page.evaluate("window.__pending['/api/v1/localization/initialpose'].resolve({accepted:true})")
        page.wait_for_function("document.querySelector('main form ui-button[type=submit]').disabled === false")

        slam_buttons = page.locator("main section.ui-readback ui-button")
        start = slam_buttons.nth(0)
        start.click()
        page.wait_for_function("window.__calls.length === 2")
        pending_slam_feedback = pose_status.inner_text()
        assert slam_buttons.evaluate_all("nodes => nodes.every(node => node.disabled)")
        page.evaluate("window.__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true})")
        start.dispatch_event("click")
        assert slam_buttons.evaluate_all("nodes => nodes.every(node => node.disabled)")
        assert pose_status.inner_text() == pending_slam_feedback
        assert page.evaluate("window.__calls") == [
            {"path": "/api/v1/localization/initialpose", "method": "POST"},
            {"path": "/api/v1/slam/start", "method": "POST"},
        ]
        page.evaluate("window.__pending['/api/v1/slam/start'].resolve({accepted:true})")
        page.wait_for_function("[...document.querySelectorAll('main section.ui-readback ui-button')].every(node => !node.disabled)")
        _unmount_panel(page)
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
        _route_panel_test(page)
        source = (WEB / "panels" / "setup" / "docking.js").read_text(encoding="utf-8")
        state_logic = (ROOT / "src" / "hmi" / "web" / "core_ui_logic.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/setup/docking.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.route("http://rosy.test/common/core_ui_logic.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=state_logic))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
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
        assert "최신이 아니어서" in page.locator("[role=status]").filter(has_text="최신이 아니어서").first.inner_text()
        assert page.locator("[data-dock-id='dock-a'] ui-button").evaluate("node => node.disabled === true")
        assert page.evaluate("window.__apiCalls") == []
        _unmount_panel(page)
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
        _route_panel_test(page)
        source = (WEB / "panels" / "console" / "docking.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/docking.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/docking.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, _interval, onData) { callbacks[path] = onData; if(path==='/api/v1/system/capabilities') window.__capabilities=onData; return () => {}; }};
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
        _unmount_panel(page)
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
        _route_panel_test(page)
        source = (WEB / "panels" / "host" / "operations.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/host/operations.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
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
        assert "Host Agent" in page.locator("[role=status]").all_inner_texts()[0]
        page.locator(".surface-disclosure summary").filter(has_text="응답 세부 정보").first.click()
        details = page.locator(".surface-disclosure .surface-message").all_inner_texts()
        assert any("agent offline" in text for text in details)
        assert page.locator("ui-button").evaluate_all("nodes => nodes.every(node => node.disabled === true)")
        assert page.evaluate("window.__calls") == []
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_admin_security_preserves_token_and_safety_action_feedback_across_polling():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "system" / "security.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/system/security.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/system/security.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {}; const calls = [];
          const store = {poll(path, interval, onData, onError) {
            callbacks[path] = {interval, onData, onError}; return () => {};
          }};
          const api = (path, options = {}) => {
            calls.push({path, method: options.method || 'GET'});
            if (path === '/api/v1/system/tokens' && !options.method) {
              return Promise.reject(new Error('fixture token list offline'));
            }
            if (options.method === 'DELETE') return Promise.resolve({deleted: true});
            if (options.method === 'POST') return Promise.resolve({token: 'fixture-one-time-secret'});
            if (options.method === 'PUT') return new Promise(resolve => { window.__resolveSafety = resolve; });
            throw new Error(`unexpected request ${options.method} ${path}`);
          };
          window.__callbacks = callbacks; window.__calls = calls;
          window.__unmount = mount(root, {role:'administrator', store, api});
          window.confirm = () => true;
        }""")
        assert page.evaluate("window.__callbacks['/api/v1/system/tokens'].interval") == 30_000
        assert page.evaluate("window.__callbacks['/api/v1/safety/state'].interval") == 15_000
        page.evaluate("""window.__callbacks['/api/v1/system/tokens'].onData({tokens:[
          {id:'old-token',label:'old',role:'operator',source:'test',current:false}
        ]})""")
        page.evaluate("""window.__callbacks['/api/v1/safety/state'].onData({
          limits:{manual_linear:0.4,manual_angular:1.2},
          battery:{warning_percent:30,critical_percent:20,deep_percent:10,critical_policy:'STOP'},
          fleet_loss_policy:'HOLD'
        })""")

        token_section = page.locator("main > section.ui-readback").nth(0)
        token_status = token_section.locator("ui-status").nth(0)
        credential_status = token_section.locator("ui-status").nth(1)
        read_status = token_section.locator("ui-status").nth(2)
        token_list = token_section.locator("ul[aria-label]")
        assert token_list.is_visible() and "old" in token_list.inner_text()
        page.evaluate("window.__callbacks['/api/v1/system/tokens'].onError(new Error('fixture token poll failed'))")
        assert token_list.is_hidden() and token_list.locator("li").count() == 0
        assert "fixture token poll failed" in read_status.inner_text()

        page.evaluate("""window.__callbacks['/api/v1/system/tokens'].onData({tokens:[
          {id:'delete-token',label:'delete-me',role:'operator',source:'test',current:false}
        ]})""")
        page.locator('[data-token-id="delete-token"] ui-button').click()
        page.wait_for_function("""document.querySelector(
          'main > section.ui-readback ui-status[role=status]'
        )?.textContent.includes('삭제했습니다')""")
        assert token_list.is_hidden()
        assert "delete-me" in token_status.inner_text() and "삭제했습니다" in token_status.inner_text()
        assert "fixture token list offline" in read_status.inner_text()

        page.locator('main > section.ui-readback').nth(0).locator('[name="label"]').fill('new-secret')
        page.locator('main > section.ui-readback').nth(0).locator('form').evaluate(
            "node => node.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
        page.wait_for_function("""document.querySelectorAll(
          'main > section.ui-readback'
        )[0].querySelectorAll('[role=status]')[1]?.textContent.includes('fixture-one-time-secret')""")
        secret = credential_status.inner_text()
        assert "fixture-one-time-secret" in secret
        assert "fixture token list offline" in read_status.inner_text()
        assert "CORE" in token_status.inner_text()

        safety_section = page.locator("main > section.ui-readback").nth(1)
        safety_form = safety_section.locator("form")
        safety_read_status = safety_section.locator("ui-status").nth(0)
        safety_action_status = safety_section.locator("ui-status").nth(1)
        safety_form.locator('[name="manual_linear"]').fill('0.8')
        page.evaluate("""window.__callbacks['/api/v1/safety/state'].onData({
          limits:{manual_linear:0.55,manual_angular:1.6},
          battery:{warning_percent:33,critical_percent:23,deep_percent:13,critical_policy:'RETURN_HOME'},
          fleet_loss_policy:'STOP'
        })""")
        assert safety_form.locator('[name="manual_linear"]').input_value() == '0.8'
        assert "수정 중" in safety_read_status.inner_text()
        assert credential_status.inner_text() == secret

        safety_form.evaluate("node => node.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
        assert safety_form.locator('input,select,ui-button').evaluate_all("nodes => nodes.every(node => node.disabled)")
        assert "보내는 중" in safety_action_status.inner_text()
        page.evaluate("""window.__callbacks['/api/v1/safety/state'].onData({
          limits:{manual_linear:0.6,manual_angular:1.8},
          battery:{warning_percent:35,critical_percent:25,deep_percent:15,critical_policy:'STOP'},
          fleet_loss_policy:'RETURN_HOME'
        })""")
        assert safety_form.locator('[name="manual_linear"]').input_value() == '0.8'
        assert safety_form.locator('input,select,ui-button').evaluate_all("nodes => nodes.every(node => node.disabled)")
        page.evaluate("""window.__resolveSafety({
          limits:{manual_linear:0.7,manual_angular:1.1},
          battery:{warning_percent:31,critical_percent:21,deep_percent:11,critical_policy:'RETURN_HOME'},
          fleet_loss_policy:'HOLD'
        })""")
        page.wait_for_function("""document.querySelector(
          'main > section.ui-readback:nth-of-type(2) input[name=manual_linear]'
        )?.value === '0.7'""")
        assert safety_form.locator('[name="manual_linear"]').input_value() == '0.7'
        assert safety_form.locator('[name="manual_angular"]').input_value() == '1.1'
        assert safety_form.locator('[name="fleet_loss_policy"]').input_value() == 'HOLD'
        assert "CORE" in safety_action_status.inner_text()
        assert credential_status.inner_text() == secret
        assert len([call for call in page.evaluate("window.__calls") if call["method"] == "PUT"]) == 1
        _unmount_panel(page)
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
        _route_panel_test(page)
        module = (WEB / "panels" / "console" / "map.js").read_text(encoding="utf-8")
        map_source = (WEB / "map.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/map.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=module))
        page.route("http://rosy.test/assets/map.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=map_source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
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
        _unmount_panel(page)
        assert set(page.evaluate("window.__stopped")) == {
            "/api/v1/robot/state", "/api/v1/system/capabilities", "/api/v1/host/commissioning",
        }
        assert errors == []
        browser.close()


def test_console_map_actions_require_hardware_runtime():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 390, 844)
        _route_panel_test(page)
        module = (WEB / "panels" / "console" / "map.js").read_text(encoding="utf-8")
        map_source = (WEB / "map.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/map.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=module))
        page.route("http://rosy.test/assets/map.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=map_source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        disabled = page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/map.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, _interval, onData) { callbacks[path] = onData; return () => {}; }};
          const api = async (path) => path === '/api/v1/map'
            ? {map_id:'map-a', width:2, height:2, resolution:1, origin:{x:0,y:0}, data:[0,0,0,0]}
            : {};
          window.__unmount = mount(root, {role:'operator', api, store});
          callbacks['/api/v1/system/capabilities']({navigation:{goal_navigation:true}});
          callbacks['/api/v1/host/commissioning']({runtime_mode:'motor'});
          const button = root.querySelector('[data-map-click="goal"]');
          const motor = button.disabled;
          callbacks['/api/v1/host/commissioning']({runtime_mode:'hardware'});
          return [motor, button.disabled];
        }""")
        assert disabled == [True, False]
        _unmount_panel(page)
        assert errors == []
        browser.close()


@pytest.mark.parametrize("hold_ms,release", [(240, True), (3_150, False)])
def test_console_teleop_sends_repeated_hold_and_terminal_zero(hold_ms, release):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        module = (WEB / "panels" / "console" / "teleop.js").read_text(encoding="utf-8")
        state_logic = (ROOT / "src" / "hmi" / "web" / "core_ui_logic.js").read_text(encoding="utf-8")
        ticker = (ROOT / "src" / "hmi" / "web" / "hold-ticker.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/teleop.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=module))
        page.route("http://rosy.test/common/core_ui_logic.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=state_logic))
        page.route("http://rosy.test/common/hold-ticker.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=ticker))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
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
          callbacks['/api/v1/host/commissioning'].onData({runtime_mode:'hardware'});
          window.__button = root.querySelector('.surface-teleop-controls ui-button');
          if (!window.__button || window.__button.disabled) throw new Error('eligible low-speed teleop button is not ready');
          window.__button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:1}));
        }""")
        page.wait_for_timeout(hold_ms)
        if release:
            page.evaluate("window.__button.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1}))")
        page.wait_for_timeout(30)
        calls = page.evaluate("window.__calls")
        assert len(calls) >= 3
        assert all(call["path"] == "/api/v1/teleop" for call in calls)
        assert any(call["body"]["linear"] > 0 for call in calls)
        assert all(abs(call["body"]["linear"]) <= 0.03 for call in calls)
        assert calls[-1]["body"] == {"linear": 0, "angular": 0}
        if not release:
            assert "2초 한도" in page.locator("ui-status").filter(has_text="2초 한도").first.inner_text()
        _unmount_panel(page)
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
        _route_panel_test(page)
        module = (WEB / "panels" / "console" / "camera.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/camera.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=module))
        page.route("http://rosy.test/assets/client.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body="export const session={token:'test'}; export const authHeaders=()=>({});"))
        page.route("http://rosy.test/assets/vision.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body="export function createVisionPreview(){return {start(){window.__started=(window.__started||0)+1;},stop(){window.__stopped=(window.__stopped||0)+1;}};}"))
        page.route("http://rosy.test/assets/camera-capture.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body="export function createCameraCapture(){return {state(){return {ready:false,recording:false,saved:false,supported:false,message:'WAITING'};},unavailable(){},recordAction(){},dispose(){}};} export function evidenceBody(){} export function saveCameraFile(){}"))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/camera.js');
          const root = document.createElement('main'); document.body.append(root);
          window.__unmount = mount(root, {role:'viewer', api:async()=>({})});
          Object.defineProperty(document, 'hidden', {configurable:true, value:true});
          document.dispatchEvent(new Event('visibilitychange'));
        }""")
        assert page.locator("img#vision-frame").get_attribute("alt") == "전방 카메라 실시간 영상"
        assert page.locator("#vision-storage option").count() == 3
        assert page.locator("#vision-storage option[value=robot]").get_attribute("disabled") is not None
        assert page.locator("#vision-screenshot").evaluate("el => el.disabled === true")
        assert page.locator("#vision-record-start").evaluate("el => el.disabled === true")
        assert page.evaluate("window.__started") == 1
        assert page.evaluate("window.__stopped") == 1
        _unmount_panel(page)
        assert page.evaluate("window.__stopped") == 2
        assert errors == []
        browser.close()


def test_console_mode_requires_navigation_capability_and_stops_held_motion():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "console" / "mode.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/mode.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/mode.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, _interval, onData) { callbacks[path] = onData; if(path==='/api/v1/system/capabilities') window.__capabilities=onData; return () => {}; }};
          const calls=[]; window.__calls=calls; window.__stoppedMotion=0;
          window.addEventListener('rosy:stop-motion',()=>window.__stoppedMotion++);
          window.__unmount=mount(root,{role:'operator',store,api:async(path,options)=>calls.push({path,body:JSON.parse(options.body)})});
          callbacks['/api/v1/robot/state']({mode:'IDLE'});
          callbacks['/api/v1/system/capabilities']({navigation:{goal_navigation:false}});
          window.confirm=()=>true;
          const nav=root.querySelector('[data-mode="NAVIGATION"]'); nav.click();
          window.__navButton=nav;
        }""")
        assert page.locator("[data-mode='NAVIGATION']").evaluate("button=>button.disabled")
        assert page.evaluate("window.__calls") == []
        page.evaluate("""() => {
          // Feed a positive capability snapshot after the fail-closed readback.
          window.__capabilities({navigation:{goal_navigation:true}});
          window.__navButton.click();
        }""")
        page.wait_for_timeout(30)
        assert page.evaluate("window.__calls") == [{"path":"/api/v1/mode","body":{"mode":"NAVIGATION"}}]
        assert page.evaluate("window.__stoppedMotion") == 1
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_line_follow_keeps_stop_available_when_navigation_capability_is_missing():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "console" / "line-follow.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/console/line-follow.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/console/line-follow.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks={}; const store={poll(path,_interval,onData){callbacks[path]=onData;return()=>{};}};
          const calls=[]; window.__calls=calls;
          window.__unmount=mount(root,{role:'operator',store,api:async(path,options)=>{calls.push({path,method:options.method,body:JSON.parse(options.body)});return {mode:'OFF'};}});
          callbacks['/api/v1/line-follow']({mode:'IR_LINE',state:'TRACKING',confidence:.9});
          callbacks['/api/v1/system/capabilities']({navigation:{goal_navigation:false}});
          root.querySelector('ui-button:first-of-type').click();
          root.querySelectorAll('ui-button')[1].click();
        }""")
        page.wait_for_timeout(20)
        assert page.evaluate("window.__calls") == [{"path":"/api/v1/line-follow/mode","method":"PUT","body":{"mode":"OFF"}}]
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_admin_dock_registration_requires_loaded_types_and_fresh_pose():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "setup" / "dock-admin.js").read_text(encoding="utf-8")
        logic = (WEB.parent / "web" / "core_ui_logic.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/setup/dock-admin.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.route("http://rosy.test/common/core_ui_logic.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=logic))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/setup/dock-admin.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks={}; const store={poll(path,_interval,onData,_onError){callbacks[path]=onData;return()=>{};}};
          const calls=[]; window.__calls=calls;
          window.__unmount=mount(root,{role:'administrator',store,api:async(path,options={})=>{
            calls.push({path,method:options.method||'GET',body:options.body?JSON.parse(options.body):null});
            return path.endsWith('/types')?{name:'test_type',detector:'simulated'}:{};
          }});
          window.__callbacks=callbacks;
          document.querySelector('[name="dock_id"]').value='dock-1';
          document.querySelector('[name="dock_type"]').value='test_type';
          document.querySelector('[name="dock_type"]').dispatchEvent(new Event('input',{bubbles:true}));
          document.querySelector('form').requestSubmit();
          callbacks['/api/v1/docking/types']({types:[{name:'test_type',detector:'simulated'}]});
        }""")
        page.wait_for_timeout(20)
        assert page.evaluate("window.__calls") == []
        page.evaluate("""() => {
          window.__callbacks['/api/v1/robot/state']({map_id:'map-1',pose:{x:1,y:2,yaw:0.5},evidence:{pose:{evidence:'fresh'}}});
          window.confirm=()=>true;
          document.querySelector('form').requestSubmit();
        }""")
        page.wait_for_timeout(30)
        assert page.evaluate("window.__calls") == [{
            "path":"/api/v1/docking/docks","method":"POST",
            "body":{"id":"dock-1","type":"test_type","x":1,"y":2,"yaw":0.5,"map_id":"map-1"},
        }]
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_setup_traffic_policy_stages_before_confirmed_apply():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "setup" / "traffic-policy.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/setup/traffic-policy.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount}=await import('/assets/panels/setup/traffic-policy.js');
          const root=document.createElement('main');document.body.append(root);
          const callbacks={};const store={poll(path,_interval,onData){callbacks[path]=onData;return()=>{};}};
          const calls=[];window.__calls=calls;
          window.__unmount=mount(root,{store,api:async(path,options)=>{
            calls.push({path,method:options.method,body:options.body?JSON.parse(options.body):null});
            if(path.endsWith('/stage'))return {active:{policy_revision:'old'},staged:{policy_revision:'candidate',mode:'ENFORCED'},status:{state:'DISABLED'}};
            if(path.endsWith('/apply'))return {active:{policy_revision:'candidate'},status:{state:'ENFORCED'}};
            return {};
          }});
          callbacks['/api/v1/traffic']({active:{policy_revision:'old',mode:'ADVISORY',approach_distance_m:1,stop_distance_m:.3,stop_dwell_s:1,min_confidence:.8},simulation_signal:{available:false},status:{state:'DISABLED'}});
          window.confirm=()=>true;
        }""")
        page.locator('[name="policy_revision"]').fill("candidate")
        page.locator("ui-button").filter(has_text="정책 검토본 저장").click()
        page.wait_for_function("window.__calls.length === 1")
        assert page.evaluate("window.__calls[0].path") == "/api/v1/traffic/policy/stage"
        assert not page.locator("ui-button").filter(has_text="정지 상태에서 적용").is_disabled()
        page.locator("ui-button").filter(has_text="정지 상태에서 적용").click()
        page.wait_for_function("window.__calls.length === 2")
        assert page.evaluate("window.__calls[1].path") == "/api/v1/traffic/policy/apply"
        _unmount_panel(page)
        assert errors == []
        browser.close()
