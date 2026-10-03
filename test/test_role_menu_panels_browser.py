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
    ui_source = (ROOT / "src" / "hmi" / "web_common" / "ui.js").read_text(encoding="utf-8")
    page.route("http://rosy.test/common/ui.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=ui_source))
    logic_source = (ROOT / "src" / "hmi" / "web_common" / "core_ui_logic.js").read_text(encoding="utf-8")
    confirmation_source = (ROOT / "src" / "hmi" / "web_common" / "confirmation.js").read_text(encoding="utf-8")
    page.route("http://rosy.test/common/confirmation.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=confirmation_source))
    geometry_source = (ROOT / "src" / "hmi" / "web_common" / "live-dialog-geometry.js").read_text(encoding="utf-8")
    page.route("http://rosy.test/common/live-dialog-geometry.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=geometry_source))
    page.route("http://rosy.test/common/core_ui_logic.js", lambda route: route.fulfill(
        status=200, content_type="application/javascript", body=logic_source))
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
        pose_status = page.locator("main > section.ui-readback ui-status[role=status]")
        pending_pose_feedback = pose_status.inner_text()
        page.evaluate("window.__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true})")
        page.locator("main form").evaluate("node => node.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
        assert pose_button.is_disabled()
        assert pose_status.inner_text() == pending_pose_feedback
        assert page.evaluate("window.__calls") == [{"path": "/api/v1/localization/initialpose", "method": "POST"}]
        page.evaluate("window.__pending['/api/v1/localization/initialpose'].resolve({accepted:true})")
        page.wait_for_function("document.querySelector('main form ui-button[type=submit]').disabled === false")

        page.locator("main details summary").click()
        slam_status = page.locator("main details ui-status[role=status]")
        slam_buttons = page.locator("main details ui-button")
        start = slam_buttons.nth(0)
        start.click()
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        page.wait_for_function("window.__calls.length === 2")
        pending_slam_feedback = slam_status.inner_text()
        assert slam_buttons.evaluate_all("nodes => nodes.every(node => node.disabled)")
        page.evaluate("window.__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true})")
        start.dispatch_event("click")
        assert slam_buttons.evaluate_all("nodes => nodes.every(node => node.disabled)")
        assert slam_status.inner_text() == pending_slam_feedback
        assert "초기 위치 설정 요청을 CORE가 받았습니다" in pose_status.inner_text()
        assert page.evaluate("window.__calls") == [
            {"path": "/api/v1/localization/initialpose", "method": "POST"},
            {"path": "/api/v1/slam/start", "method": "POST"},
        ]
        page.evaluate("window.__pending['/api/v1/slam/start'].resolve({accepted:true})")
        page.wait_for_function("[...document.querySelectorAll('main details ui-button')].every(node => !node.disabled)")
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_console_line_follow_readback_failure_and_action_feedback_are_independent():
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
          const root=document.createElement('main'); document.body.append(root);
          const callbacks={}; const store={poll(path,_interval,onData,onError){callbacks[path]={onData,onError};return()=>{};}};
          let resolveRequest; const calls=[]; window.__calls=calls;
          window.__unmount=mount(root,{role:'operator',store,api:async(path,options)=>{
            calls.push({path,method:options.method,body:JSON.parse(options.body)});
            return new Promise(resolve=>{resolveRequest=resolve;});
          }});
          window.__callbacks=callbacks; window.__resolveRequest=value=>resolveRequest(value);
          callbacks['/api/v1/line-follow'].onData({mode:'IR_LINE',state:'TRACKING',confidence:.9});
          callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}});
          callbacks['/api/v1/line-follow'].onError(new Error('fixture line status unavailable'));
        }""")
        panel = page.locator("main").last
        assert "fixture line status unavailable" in panel.locator("ui-status").first.inner_text()
        assert "TRACKING" not in panel.locator("dl").inner_text()
        assert panel.locator("ui-button").evaluate_all("nodes=>nodes.every(node=>node.disabled)")
        assert "내비게이션" in panel.locator("ui-status").nth(1).inner_text()

        page.evaluate("""() => {
          window.__callbacks['/api/v1/line-follow'].onData({mode:'OFF',state:'IDLE'});
          window.confirm=()=>true;
          document.querySelector('main:last-of-type ui-button').click();
        }""")
        page.wait_for_function("window.__calls.length === 1")
        action = panel.locator('ui-status[role="status"]').last
        page.evaluate("""() => {
          window.__callbacks['/api/v1/line-follow'].onData({mode:'OFF',state:'IDLE'});
          window.__callbacks['/api/v1/system/capabilities'].onError(new Error('fixture capability unavailable'));
        }""")
        assert panel.locator("ui-button").evaluate_all("nodes=>nodes.every(node=>node.disabled)")
        pending_feedback = action.inner_text()
        page.evaluate("window.__resolveRequest({})")
        page.wait_for_function("previous => [...document.querySelectorAll('ui-status[role=status]')].at(-1)?.textContent !== previous", arg=pending_feedback)
        # D-359 US-009 — the line-follow mode is spoken in Korean, never as the enum.
        assert "꺼짐" in panel.locator("ui-status").first.inner_text()
        assert "OFF" not in panel.locator("ui-status").first.inner_text()
        assert "IR_LINE" not in action.inner_text() and "적외선 센서" in action.inner_text()
        assert action.inner_text() != pending_feedback
        assert "CORE" in action.inner_text()
        assert page.evaluate("window.__calls") == [{
            "path":"/api/v1/line-follow/mode","method":"PUT","body":{"mode":"IR_LINE"},
        }]
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_console_docking_locks_pending_commands_and_preserves_selected_dock():
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
          const root=document.createElement('main'); document.body.append(root);
          const callbacks={}; const store={poll(path,_interval,onData,onError){callbacks[path]={onData,onError};return()=>{};}};
          const calls=[]; window.__calls=calls; let resolveRequest;
          window.__unmount=mount(root,{role:'operator',store,api:async(path,options)=>{
            calls.push({path,method:options.method}); return new Promise(resolve=>{resolveRequest=resolve;});
          }});
          window.__callbacks=callbacks; window.__resolveRequest=value=>resolveRequest(value);
          callbacks['/api/v1/docking/status'].onData({supported:true,state:'UNDOCKED'});
          callbacks['/api/v1/docking/docks'].onData({docks:[{id:'dock-a',type:'charger'},{id:'dock-b',type:'charger'}]});
          const select=root.querySelector('select'); select.value='dock-b'; select.dispatchEvent(new Event('change',{bubbles:true}));
          callbacks['/api/v1/docking/docks'].onData({docks:[{id:'dock-a',type:'charger'},{id:'dock-b',type:'charger'},{id:'dock-c',type:'charger'}]});
          window.confirm=()=>true; root.querySelector('ui-button').click();
        }""")
        panel = page.locator("main").last
        assert panel.locator("select").input_value() == "dock-b"
        assert page.evaluate("window.__calls") == [{"path":"/api/v1/docking/dock","method":"POST"}]
        assert panel.locator("select").is_disabled()
        assert panel.locator("ui-button").evaluate_all("nodes=>nodes.every(node=>node.disabled)")
        action = panel.locator('ui-status[role="status"]').last
        pending = action.inner_text()
        page.evaluate("""() => {
          window.__callbacks['/api/v1/docking/status'].onData({supported:true,state:'UNDOCKED'});
          window.__callbacks['/api/v1/docking/docks'].onData({docks:[{id:'dock-b',type:'charger'}]});
        }""")
        assert panel.locator("select").is_disabled()
        assert action.inner_text() == pending
        assert page.evaluate("window.__calls.length") == 1
        page.evaluate("window.__resolveRequest({})")
        page.wait_for_function("previous => [...document.querySelectorAll('ui-status[role=status]')].at(-1)?.textContent !== previous", arg=pending)
        assert not panel.locator("select").is_disabled()
        success = action.inner_text()
        assert "CORE" in success
        page.evaluate("window.__callbacks['/api/v1/docking/status'].onError(new Error('fixture docking status unavailable'))")
        assert "fixture docking status unavailable" in panel.locator("ui-status").first.inner_text()
        assert "UNDOCKED" not in panel.locator("dl").inner_text()
        assert panel.locator("ui-button").evaluate_all("nodes=>nodes.every(node=>node.disabled)")
        assert action.inner_text() == success
        page.evaluate("window.__callbacks['/api/v1/docking/docks'].onError(new Error('fixture dock list unavailable'))")
        assert panel.locator("select option").count() == 0
        assert "fixture dock list unavailable" in panel.locator("ui-status").nth(1).inner_text()
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
        state_logic = (ROOT / "src" / "hmi" / "web_common" / "core_ui_logic.js").read_text(encoding="utf-8")
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
        assert page.locator('[role="status"][state="warning"]').inner_text().strip()
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
        assert "호스트 에이전트" in page.locator("[role=status]").all_inner_texts()[0]
        page.locator(".surface-disclosure summary").filter(has_text="응답 세부 정보").first.click()
        details = page.locator(".surface-disclosure .surface-message").all_inner_texts()
        assert any("agent offline" in text for text in details)
        assert page.locator("ui-button").evaluate_all("nodes => nodes.every(node => node.disabled === true)")
        assert page.evaluate("window.__calls") == []
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_admin_host_system_get_failures_clear_only_their_own_readback():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "host" / "system.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/host/system.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/host/system.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, interval, onData, onError) {
            callbacks[path] = {interval, onData, onError}; return () => {};
          }};
          window.__callbacks = callbacks;
          window.__unmount = mount(root, {role:'administrator', store, api:async () => ({})});
          callbacks['/api/v1/system/runtime'].onData({hostname:'host-fixture',os:{pretty_name:'fixture OS'},architecture:'arm64'});
          callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:'robot-fixture',runtime_mode:'hardware'});
          callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true},slam:true});
          callbacks['/api/v1/system/inventory'].onData({descriptors:[{id:'lidar',state:'ready'},{id:'battery',state:'ready'}]});
        }""")
        assert page.evaluate("window.__callbacks['/api/v1/system/runtime'].interval") == 10_000
        assert page.evaluate("window.__callbacks['/api/v1/system/info'].interval") == 30_000
        assert page.evaluate("window.__callbacks['/api/v1/system/capabilities'].interval") == 15_000
        assert page.evaluate("window.__callbacks['/api/v1/system/inventory'].interval") == 15_000

        overview_status = page.locator("main .host-system-overview ui-status")
        details = page.locator("main details.host-system-detail")
        details.evaluate("node => { node.open = true; }")
        runtime_body = details.locator("section.ui-readback dl").nth(0)
        identity_body = details.locator("section.ui-readback dl").nth(1)
        inventory_body = details.locator("section.ui-readback dl").nth(2)
        assert "host-fixture" in runtime_body.inner_text()
        assert "robot-fixture" in identity_body.inner_text()
        assert "lidar" in inventory_body.inner_text()

        page.evaluate("window.__callbacks['/api/v1/system/runtime'].onError(new Error('fixture runtime offline'))")
        assert runtime_body.locator("dt").count() == 0
        assert "fixture runtime offline" in overview_status.nth(3).inner_text()
        assert "robot-fixture" in identity_body.inner_text()
        assert "내비게이션" in overview_status.nth(1).inner_text()
        assert "lidar" in inventory_body.inner_text()

        page.evaluate("window.__callbacks['/api/v1/system/info'].onError(new Error('fixture identity offline'))")
        assert identity_body.locator("dt").count() == 0
        assert "fixture identity offline" in overview_status.nth(0).inner_text()
        assert "fixture runtime offline" in overview_status.nth(3).inner_text()
        assert "내비게이션" in overview_status.nth(1).inner_text()
        assert "lidar" in inventory_body.inner_text()

        page.evaluate("window.__callbacks['/api/v1/system/capabilities'].onError(new Error('fixture capabilities offline'))")
        assert "fixture capabilities offline" in overview_status.nth(1).inner_text()
        assert "lidar" in inventory_body.inner_text()
        assert "fixture runtime offline" in overview_status.nth(3).inner_text()

        page.evaluate("window.__callbacks['/api/v1/system/inventory'].onError(new Error('fixture inventory offline'))")
        assert "fixture inventory offline" in overview_status.nth(2).inner_text()
        assert "lidar" not in inventory_body.inner_text()
        assert "fixture capabilities offline" in overview_status.nth(1).inner_text()
        assert "fixture identity offline" in overview_status.nth(0).inner_text()
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_console_mode_feedback_survives_state_and_capability_polling():
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
          const callbacks = {}; const calls = [];
          const store = {poll(path, interval, onData, onError) {
            callbacks[path] = {interval, onData, onError}; return () => {};
          }};
          const api = (path, options) => {
            calls.push({path, body:JSON.parse(options.body)});
            return new Promise(resolve => { window.__resolveMode = resolve; });
          };
          window.__callbacks = callbacks; window.__calls = calls;
          window.__unmount = mount(root, {role:'operator', store, api});
          callbacks['/api/v1/robot/state'].onData({mode:'IDLE'});
          callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}});
          window.confirm = () => true;
        }""")
        assert page.evaluate("window.__callbacks['/api/v1/robot/state'].interval") == 1_000
        assert page.evaluate("window.__callbacks['/api/v1/system/capabilities'].interval") == 5_000
        status = page.locator("main > ui-status")
        assert "대기" in status.nth(0).inner_text()
        assert "내비게이션" in status.nth(1).inner_text()
        page.locator('[data-mode="MANUAL"]').click()
        page.wait_for_function("window.__calls.length === 1")
        pending_feedback = status.nth(2).inner_text()
        page.evaluate("window.__callbacks['/api/v1/robot/state'].onData({mode:'IDLE'})")
        page.evaluate("window.__callbacks['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}})")
        assert status.nth(2).inner_text() == pending_feedback
        assert "대기" in status.nth(0).inner_text()
        page.evaluate("window.__resolveMode({accepted:true})")
        page.wait_for_function("document.querySelectorAll('main > ui-status')[2]?.textContent.includes('CORE가 받았습니다')")
        accepted_feedback = status.nth(2).inner_text()
        assert "대기" in status.nth(0).inner_text()
        assert "CORE가 받았습니다" in accepted_feedback
        page.evaluate("window.__callbacks['/api/v1/robot/state'].onData({mode:'MANUAL'})")
        page.evaluate("window.__callbacks['/api/v1/system/capabilities'].onError(new Error('fixture navigation unavailable'))")
        assert "수동" in status.nth(0).inner_text()
        assert "fixture navigation unavailable" in status.nth(1).inner_text()
        assert status.nth(2).inner_text() == accepted_feedback
        assert page.evaluate("window.__calls") == [{"path":"/api/v1/mode","body":{"mode":"MANUAL"}}]
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_console_teleop_keeps_readiness_reasons_separate_from_action_feedback():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        module = (WEB / "panels" / "console" / "teleop.js").read_text(encoding="utf-8")
        state_logic = (ROOT / "src" / "hmi" / "web_common" / "core_ui_logic.js").read_text(encoding="utf-8")
        ticker = (ROOT / "src" / "hmi" / "web_common" / "hold-ticker.js").read_text(encoding="utf-8")
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
          const callbacks = {}; const calls = []; window.__failZero = false;
          const store = {poll(path, interval, onData, onError) {
            callbacks[path] = {interval, onData, onError}; return () => {};
          }};
          const api = async (path, options) => {
            const body = JSON.parse(options.body); calls.push({path, body});
            if (window.__failZero && body.linear === 0 && body.angular === 0) {
              throw new Error('fixture terminal zero unavailable');
            }
            return {};
          };
          window.__callbacks = callbacks; window.__calls = calls;
          window.__unmount = mount(root, {role:'operator', api, store});
          window.__fresh = () => {
            callbacks['/api/v1/robot/state'].onData({mode:'MANUAL', pose:{x:1,y:1}, velocity:{linear:0,angular:0}, evidence:{pose:{evidence:'fresh'},velocity:{evidence:'fresh'}}});
            callbacks['/api/v1/system/capabilities'].onData({teleop:true});
            callbacks['/api/v1/safety/state'].onData({estop:false});
            callbacks['/api/v1/host/commissioning'].onData({runtime_mode:'hardware'});
          };
          window.__fresh();
          window.__button = root.querySelector('.surface-teleop-controls ui-button');
        }""")
        statuses = page.locator("main > ui-status")
        readiness, action = statuses.nth(0), statuses.nth(1)
        page.evaluate("window.__button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:1}))")
        page.wait_for_timeout(150)
        hold_feedback = action.inner_text()
        page.evaluate("window.__fresh()")
        assert action.inner_text() == hold_feedback

        page.evaluate("window.__button.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1}))")
        page.wait_for_function("window.__calls.at(-1)?.body.linear === 0 && window.__calls.at(-1)?.body.angular === 0")
        release_feedback = action.inner_text()
        for path, name, value in (
            ("/api/v1/robot/state", "state", "{mode:'MANUAL',pose:{x:1,y:1},velocity:{linear:0,angular:0},evidence:{pose:{evidence:'fresh'},velocity:{evidence:'fresh'}}}"),
            ("/api/v1/system/capabilities", "capabilities", "{teleop:true}"),
            ("/api/v1/safety/state", "safety", "{estop:false}"),
            ("/api/v1/host/commissioning", "commissioning", "{runtime_mode:'hardware'}"),
        ):
            page.evaluate(f"window.__callbacks[{path!r}].onError(new Error('fixture {name} unavailable'))")
            assert f"fixture {name} unavailable" in readiness.inner_text()
            assert action.inner_text() == release_feedback
            page.evaluate(f"window.__callbacks[{path!r}].onData({value})")
            assert f"fixture {name} unavailable" not in readiness.inner_text()

        page.evaluate("window.__button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:2}))")
        page.wait_for_timeout(120)
        page.evaluate("window.dispatchEvent(new CustomEvent('rosy:stop-motion',{detail:{waits:[]}}))")
        forced_stop_feedback = action.inner_text()
        page.evaluate("window.__fresh()")
        assert action.inner_text() == forced_stop_feedback
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_console_teleop_timeout_and_failed_stop_feedback_survive_polling():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        module = (WEB / "panels" / "console" / "teleop.js").read_text(encoding="utf-8")
        state_logic = (ROOT / "src" / "hmi" / "web_common" / "core_ui_logic.js").read_text(encoding="utf-8")
        ticker = (ROOT / "src" / "hmi" / "web_common" / "hold-ticker.js").read_text(encoding="utf-8")
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
          const callbacks = {}; window.__failZero = false;
          const store = {poll(path, interval, onData, onError) { callbacks[path]={interval,onData,onError}; return () => {}; }};
          const api = async (_path, options) => {
            const body = JSON.parse(options.body);
            if (window.__failZero && body.linear === 0 && body.angular === 0) throw new Error('fixture terminal zero unavailable');
            return {};
          };
          window.__callbacks = callbacks; window.__unmount = mount(root,{role:'operator',api,store});
          window.__fresh = () => {
            callbacks['/api/v1/robot/state'].onData({mode:'MANUAL',pose:{x:1,y:1},velocity:{linear:0,angular:0},evidence:{pose:{evidence:'fresh'},velocity:{evidence:'fresh'}}});
            callbacks['/api/v1/system/capabilities'].onData({teleop:true});
            callbacks['/api/v1/safety/state'].onData({estop:false});
            callbacks['/api/v1/host/commissioning'].onData({runtime_mode:'hardware'});
          };
          window.__fresh(); window.__button=root.querySelector('.surface-teleop-controls ui-button');
        }""")
        action = page.locator("main > ui-status").nth(1)
        page.evaluate("window.__button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:3}))")
        page.wait_for_timeout(2_150)
        timeout_feedback = action.inner_text()
        assert "2" in timeout_feedback
        page.evaluate("window.__fresh()")
        assert action.inner_text() == timeout_feedback

        page.evaluate("window.__button.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:4}))")
        page.wait_for_timeout(150)
        page.evaluate("window.__failZero=true; window.__button.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:4}))")
        page.wait_for_function("document.querySelectorAll('main > ui-status')[1]?.textContent.includes('fixture terminal zero unavailable')")
        failed_stop_feedback = action.inner_text()
        page.evaluate("window.__fresh()")
        assert action.inner_text() == failed_stop_feedback
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
        # D-371: the row button opens the shared confirm dialog; its execute button deletes.
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
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
        state_logic = (ROOT / "src" / "hmi" / "web_common" / "core_ui_logic.js").read_text(encoding="utf-8")
        ticker = (ROOT / "src" / "hmi" / "web_common" / "hold-ticker.js").read_text(encoding="utf-8")
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
        page.locator('dialog[open] ui-button[kind="irreversible"]').click()
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
        logic = (WEB.parent / "web_common" / "core_ui_logic.js").read_text(encoding="utf-8")
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
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
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
          callbacks['/api/v1/traffic']({active:{policy_revision:'old',mode:'MONITOR_ONLY',approach_distance_m:1,stop_distance_m:.3,stop_dwell_s:1,min_confidence:.8},simulation_signal:{available:false},status:{state:'DISABLED'}});
          window.confirm=()=>true;
        }""")
        page.locator('[name="policy_revision"]').fill("candidate")
        page.locator("ui-button").filter(has_text="정책 검토본 저장").click()
        page.wait_for_function("window.__calls.length === 1")
        assert page.evaluate("window.__calls[0].path") == "/api/v1/traffic/policy/stage"
        assert not page.locator("ui-button").filter(has_text="정지 상태에서 적용").is_disabled()
        page.locator("ui-button").filter(has_text="정지 상태에서 적용").click()
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        page.wait_for_function("window.__calls.length === 2")
        assert page.evaluate("window.__calls[1].path") == "/api/v1/traffic/policy/apply"
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_admin_host_identity_editor_is_single_and_preserves_save_feedback():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "host" / "system.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/host/system.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/host/system.js');
          const root = document.createElement('main'); document.body.append(root);
          const callbacks = {};
          const store = {poll(path, interval, onData, onError) {
            callbacks[path] = {interval, onData, onError}; return () => {};
          }};
          const api = () => new Promise(resolve => { window.__resolveIdentity = resolve; });
          window.__callbacks = callbacks;
          window.__unmount = mount(root, {role:'administrator', store, api});
          callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:'robot-fixture',runtime_mode:'hardware'});
        }""")
        form = page.locator("main .host-system-detail .ui-form")
        page.locator("main details.host-system-detail").evaluate("node => { node.open = true; }")
        identity_input = form.locator('[name="robot_name"]')
        save = form.locator('ui-button[type="submit"]')
        feedback = page.locator("main .host-system-detail ui-status[role='status']")
        identity_status = page.locator("main .host-system-overview ui-status").first
        assert page.evaluate("window.__callbacks['/api/v1/system/info'].interval") == 30_000
        for name in ("robot-fixture", "robot-fixture", "robot-fixture"):
            page.evaluate("name => window.__callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:name,runtime_mode:'hardware'})", name)
        assert page.locator("main .host-system-detail .ui-form").count() == 1

        identity_input.fill("draft-pinky")
        page.evaluate("window.__callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:'robot-fixture',runtime_mode:'hardware'})")
        page.evaluate("window.__callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:'robot-fixture',runtime_mode:'hardware'})")
        assert page.locator("main .host-system-detail .ui-form").count() == 1
        assert identity_input.input_value() == "draft-pinky"

        form.evaluate("node => node.requestSubmit()")
        assert identity_input.is_disabled() and save.is_disabled()
        pending = feedback.inner_text()
        assert pending
        page.evaluate("window.__callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:'robot-fixture',runtime_mode:'hardware'})")
        assert feedback.inner_text() == pending
        assert identity_input.input_value() == "draft-pinky"
        page.evaluate("window.__resolveIdentity({robot_name:'draft-pinky'})")
        page.wait_for_function("document.querySelector('main .host-system-detail ui-status[role=status]')?.getAttribute('state') === 'ready'")
        receipt = feedback.inner_text()
        assert receipt and identity_input.input_value() == "draft-pinky"
        assert identity_status.inner_text() != receipt

        page.evaluate("window.__callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:'robot-fixture',runtime_mode:'hardware'})")
        assert feedback.inner_text() == receipt
        assert identity_input.input_value() == "draft-pinky"
        page.evaluate("window.__callbacks['/api/v1/system/info'].onData({robot_id:'robot-a',robot_name:'draft-pinky',runtime_mode:'hardware'})")
        assert identity_input.input_value() == "draft-pinky"
        assert page.locator("main .host-system-detail .ui-form").count() == 1
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_console_map_readiness_freshness_and_action_feedback_are_independent():
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
          const nativeSetInterval=window.setInterval.bind(window);
          const callbacks={}; window.__intervals=callbacks;
          window.setInterval=(fn,ms,...args)=>{
            if(ms===10_000){callbacks[ms]=fn;return 10001;}
            return nativeSetInterval(fn,ms,...args);
          };
          const {mount}=await import('/assets/panels/console/map.js');
          const root=document.createElement('main');root.id='map-test-panel';document.body.append(root);
          const polls={};const store={poll(path,_interval,onData,onError){polls[path]={onData,onError};return()=>{};}};
          const calls=[];let hasGrid=false;let failPost=false;window.__calls=calls;
          window.__setGrid=value=>{hasGrid=value;};window.__failPost=value=>{failPost=value;};
          const grid={map_id:'fixture-map',width:2,height:2,resolution:1,origin:{x:0,y:0},data:[0,0,0,0]};
          const api=async(path,options={})=>{
            calls.push({path,method:options.method||'GET'});
            if(options.method==='POST'){if(failPost)throw new Error('fixture goal rejected');return {accepted:true};}
            if(path==='/api/v1/map')return hasGrid?grid:null;
            if(path==='/api/v1/navigation/path')return {poses:[]};
            if(path.startsWith('/api/v1/map/costmap'))return {data:[]};
            return {};
          };
          window.__polls=polls;
          window.__unmount=mount(root,{role:'operator',api,store,surfaces:[{id:'setup'}]});
          root.querySelectorAll('ui-status')[1].id='map-readiness-status';
          window.confirm=()=>{window.__confirmCalls=(window.__confirmCalls||0)+1;return true;};
          polls['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}});
          polls['/api/v1/host/commissioning'].onData({runtime_mode:'hardware'});
          polls['/api/v1/robot/state'].onData({pose:{x:.5,y:.5,yaw:0}});
        }""")
        panel = page.locator("main").last
        page.wait_for_function("document.querySelector('#map-status')?.textContent.includes('empty') || document.querySelector('#map-status')?.textContent.length > 0")
        map_freshness = panel.locator("#map-status")
        readiness = panel.locator("#map-readiness-status")
        action = panel.locator("ui-status[role=status]").last
        initial_action = action.inner_text()
        page.locator('[data-map-click="goal"]').click()
        page.locator("canvas").click(position={"x":30,"y":30})
        assert action.inner_text() and action.inner_text() != initial_action
        assert page.evaluate("window.__calls.filter(call=>call.method==='POST')") == []
        assert page.evaluate("window.__confirmCalls || 0") == 0
        no_map_action = action.inner_text()

        page.evaluate("""() => {
          window.__polls['/api/v1/robot/state'].onError(new Error('fixture robot state unavailable'));
          window.__polls['/api/v1/system/capabilities'].onError(new Error('fixture navigation unavailable'));
          window.__polls['/api/v1/host/commissioning'].onError(new Error('fixture commissioning unavailable'));
        }""")
        assert all(reason in readiness.inner_text() for reason in (
            "fixture robot state unavailable", "fixture navigation unavailable", "fixture commissioning unavailable")), readiness.inner_text()
        assert map_freshness.inner_text() != readiness.inner_text()
        assert action.inner_text() == no_map_action

        page.evaluate("window.__setGrid(true); window.__intervals[10000]()")
        page.wait_for_function("document.querySelector('#map-status')?.textContent.includes('fixture-map')")
        page.evaluate("window.__polls['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}}); window.__polls['/api/v1/host/commissioning'].onData({runtime_mode:'hardware'}); window.__polls['/api/v1/robot/state'].onData({pose:{x:.5,y:.5,yaw:0}})")
        page.locator('[data-map-click="goal"]').click()
        page.locator("canvas").click(position={"x":30,"y":30})
        page.evaluate("window.__polls['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:false}})")
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        assert page.evaluate("window.__calls.filter(call=>call.method==='POST')") == []
        page.evaluate("window.__polls['/api/v1/system/capabilities'].onData({navigation:{goal_navigation:true}})")
        page.locator("canvas").click(position={"x":30,"y":30})
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        page.wait_for_function("window.__calls.some(call=>call.method==='POST')")
        page.wait_for_function("[...document.querySelectorAll('#map-test-panel ui-status[role=status]')].at(-1)?.textContent.includes('CORE')")
        accepted = action.inner_text()
        page.evaluate("window.__intervals[10000]()")
        page.wait_for_timeout(50)
        assert action.inner_text() == accepted

        page.evaluate("window.__failPost(true); window.__intervals[10000]()")
        page.wait_for_function("[...document.querySelectorAll('#map-test-panel ui-status[role=status]')].at(-1)?.textContent.includes('CORE')")
        page.locator('[data-map-click="goal"]').click()
        page.locator("canvas").click(position={"x":45,"y":45})
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        page.wait_for_function("[...document.querySelectorAll('#map-test-panel ui-status[role=status]')].at(-1)?.textContent.includes('fixture goal rejected')")
        failed = action.inner_text()
        page.evaluate("window.__intervals[10000]()")
        page.wait_for_timeout(50)
        assert action.inner_text() == failed
        _unmount_panel(page)
        assert errors == []
        browser.close()


def test_device_hardware_refresh_feedback_survives_measurement_polls():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, errors = open_page(playwright, 390, 844)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")
        _route_panel_test(page)
        source = (WEB / "panels" / "host" / "hardware.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/host/hardware.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="load", timeout=5_000)
        page.evaluate("""async () => {
          const {mount}=await import('/assets/panels/host/hardware.js');
          const root=document.createElement('main');root.id='hardware-panel';document.body.append(root);
          const callbacks={};const store={poll(path,_interval,onData,onError){callbacks[path]={onData,onError};return()=>{};}};
          const calls=[];let resolvePost;let rejectPost=false;window.__calls=calls;
          window.__rejectRefresh=value=>{rejectPost=value;};window.__resolveRefresh=value=>resolvePost(value);
          const api=async(path,options={})=>{
            calls.push({path,method:options.method||'GET'});
            if(rejectPost)throw new Error('fixture refresh failed');
            return new Promise(resolve=>{resolvePost=resolve;});
          };
          window.__callbacks=callbacks;
          window.__unmount=mount(root,{role:'administrator',api,store});
          callbacks['/api/v1/host/hardware'].onData({available:true,measured_at:'2026-09-28T01:00:00Z',age_s:5,
            devices:[{id:'camera',label:'Camera',state:'ok',evidence:'fixture initial'}]});
        }""")
        panel = page.locator("#hardware-panel")
        measured = panel.locator(".hardware-measured dd")
        note = panel.locator(".hardware-note")
        action = panel.locator("#hardware-action-note")
        refresh = panel.locator(".hardware-refresh")
        assert refresh.get_attribute("aria-describedby") == action.get_attribute("id") == "hardware-action-note"
        assert action.is_hidden() and action.inner_text() == ""
        initial_measurement = measured.inner_text()
        refresh.click()
        assert action.is_visible() and action.inner_text()
        page.wait_for_function("window.__calls.length === 1")
        assert refresh.is_disabled()
        pending = action.inner_text()
        page.evaluate("window.__callbacks['/api/v1/host/hardware'].onData({available:true,measured_at:'2026-09-28T02:00:00Z',age_s:3,devices:[{id:'camera',label:'Camera',state:'ok',evidence:'fixture during POST'}]})")
        assert measured.inner_text() != initial_measurement
        assert action.inner_text() == pending
        page.evaluate("window.__resolveRefresh({accepted:true})")
        page.wait_for_function("previous => document.querySelector('#hardware-action-note')?.textContent !== previous", arg=pending)
        assert refresh.is_enabled()
        accepted = action.inner_text()
        page.evaluate("window.__callbacks['/api/v1/host/hardware'].onData({available:true,measured_at:'2026-09-28T03:00:00Z',age_s:1,devices:[{id:'camera',label:'Camera',state:'ok',evidence:'fixture after POST'}]})")
        assert measured.inner_text() != initial_measurement
        assert action.inner_text() == accepted
        page.evaluate("window.__rejectRefresh(true); document.querySelector('#hardware-panel .hardware-refresh').click()")
        page.wait_for_function("document.querySelector('#hardware-action-note')?.textContent.includes('fixture refresh failed')")
        failed = action.inner_text()
        page.evaluate("window.__callbacks['/api/v1/host/hardware'].onError(new Error('fixture measurement unavailable'))")
        assert "fixture measurement unavailable" in note.inner_text()
        assert action.inner_text() == failed
        assert page.evaluate("window.__calls") == [
            {"path":"/api/v1/host/hardware/refresh","method":"POST"},
            {"path":"/api/v1/host/hardware/refresh","method":"POST"},
        ]
        page.evaluate("window.__unmount()")
        assert errors == []
        browser.close()
