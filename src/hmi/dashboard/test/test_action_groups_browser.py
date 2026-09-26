"""D-283 browser checks for action-group availability and safe transitions."""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]
WEB_COMMON = ROOT.parent / "web"

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def translate_path(self, path):
        if path.startswith("/common/"):
            return str(WEB_COMMON / path.removeprefix("/common/"))
        return super().translate_path(path)

    def do_GET(self):
        if self.path == "/__d283_real_operations":
            body = """<!doctype html><html><head><meta charset='utf-8'></head><body>
              <ui-text id='shell-notice'></ui-text>
              <main><div class='surface-slot' data-slot='act'></div></main>
              <script type='module'>
                import {mountPanels} from '/src/hmi/dashboard/shell/mount.js';
                const panels = [
                  {id:'console.teleop', title:'수동 운전', slot:'act', action_group:'drive',
                   module:'/src/hmi/dashboard/panels/console/teleop.js', css:[], state:'available'},
                  {id:'console.docking', title:'도킹 운용', slot:'act', action_group:'docking',
                   module:'/src/hmi/dashboard/panels/console/docking.js', css:[], state:'available'},
                  {id:'console.line_follow', title:'차선 추종', slot:'act', action_group:'line_follow',
                   module:'/src/hmi/dashboard/panels/console/line-follow.js', css:[], state:'available'},
                ];
                window.__apiCalls = [];
                window.__deferred = [];
                window.__deferOps = false;
                const state = {mode:'MANUAL', evidence:{pose:{evidence:'fresh'},velocity:{evidence:'fresh'}}};
                const store = {poll(path, _interval, success) {
                  const data = path === '/api/v1/robot/state' ? state
                    : path === '/api/v1/system/capabilities' ? {teleop:true, navigation:{goal_navigation:true}}
                    : path === '/api/v1/safety/state' ? {estop:false}
                    : path === '/api/v1/line-follow' ? {mode:'OFF',state:'OFF'}
                    : path === '/api/v1/docking/status' ? {supported:true,state:'UNDOCKED'}
                    : path === '/api/v1/docking/docks' ? {docks:[{id:'dock-a',type:'test'}]} : {};
                  success(data); return () => {};
                }, stopAll() {}};
                window.__mounted = await mountPanels(document, panels, () => ({
                  role:'operator', store, api:async (path, options) => {
                    const body = options?.body ? JSON.parse(options.body) : null;
                    window.__apiCalls.push({path, method:options?.method, body});
                    if (window.__deferOps && (path === '/api/v1/line-follow/mode' || path.startsWith('/api/v1/docking/'))) {
                      return await new Promise((resolve) => window.__deferred.push({path, body, resolve}));
                    }
                    if (path === '/api/v1/line-follow/mode') return {mode:body.mode,state:body.mode === 'OFF' ? 'OFF' : 'WAITING'};
                    if (path === '/api/v1/docking/dock') return {state:'DOCKING'};
                    if (path === '/api/v1/docking/cancel') return {state:'UNDOCKED'};
                    return {};
                  },
                }));
              </script>
            </body></html>""".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/__d283":
            body = """<!doctype html><html><head><meta charset='utf-8'></head><body>
              <ui-text id='shell-notice'></ui-text>
              <main id='surface-main'><div id='surface-status' hidden></div>
                <div class='surface-slot' data-slot='act'></div>
              </main>
              <script type='module'>
                import {mountPanels} from '/src/hmi/dashboard/shell/mount.js';
                const panels = [
                  {id:'console.teleop', title:'수동 운전', slot:'act', order:30,
                   action_group:'drive', module:'/src/hmi/dashboard/panels/console/teleop.js',
                   css:[], state:'available'},
                  {id:'console.docking', title:'도킹 운용', slot:'act', order:40,
                   action_group:'docking', module:'/__stub.js', css:[], state:'available'},
                  {id:'console.line_follow', title:'차선 추종', slot:'act', order:50,
                   action_group:'line_follow', module:'/__stub.js', css:[], state:'available'},
                ];
                const state = {mode:'MANUAL', evidence:{pose:{evidence:'fresh'},velocity:{evidence:'fresh'}}};
                const store = {poll(path, _interval, success) {
                  const data = path === '/api/v1/robot/state' ? state
                    : path === '/api/v1/system/capabilities' ? {teleop:true}
                    : {estop:false};
                  success(data); return () => {};
                }, stopAll() {}};
                window.__timeline = [];
                new MutationObserver((records) => {
                  for (const record of records) for (const node of record.removedNodes) {
                    if (node.matches?.('[data-panel="console.teleop"]')
                        || node.querySelector?.('[data-panel="console.teleop"]')) window.__timeline.push({type:'teleop-unmount'});
                  }
                }).observe(document.querySelector('[data-slot="act"]'), {childList:true, subtree:true});
                window.__mounted = await mountPanels(document, panels, () => ({
                  role:'operator', store, api:async (path, options) => {
                    const body = options?.body ? JSON.parse(options.body) : null;
                    window.__timeline.push({type:'api', path, body});
                    if (window.__failZero && path === '/api/v1/teleop' && body?.linear === 0) throw new Error('offline');
                    return {};
                  },
                }));
              </script>
            </body></html>""".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/__stub.js":
            body = b"""export function mount(root) {
              root.textContent = 'Action controls';
              const panel = root.dataset.panel;
              return {
                beforeHide() {
                  if (window.__blocked?.[panel]) return {message: 'operation active'};
                  return true;
                },
                unmount() { window.__timeline.push({type: panel + '-unmount'}); },
              };
            }"""
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *_args):
        return


def test_group_switch_sends_terminal_zero_before_unmount_and_never_resumes_motion():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"http://127.0.0.1:{server.server_port}/__d283")
            page.wait_for_function("window.__mounted && document.querySelector('[data-panel=\"console.teleop\"]')")
            assert page.get_by_role("tab").count() == 3
            page.locator("[data-panel='console.teleop'] input[type=checkbox]").check()
            page.locator("[data-panel='console.teleop'] ui-button").first.dispatch_event("pointerdown")
            page.wait_for_function("window.__timeline.some((item) => item.path === '/api/v1/teleop' && item.body?.linear > 0)")
            page.get_by_role("tab", name="도킹").click()
            page.wait_for_selector("#action-group-docking:not([hidden])")
            after_dock = page.evaluate("""() => ({
              timeline: window.__timeline,
              teleopMounted: Boolean(document.querySelector('[data-panel="console.teleop"]')),
              selected: document.querySelector('[role=tab][aria-selected=true]')?.textContent,
            })""")
            zero_index = max(i for i, item in enumerate(after_dock["timeline"])
                             if item.get("path") == "/api/v1/teleop" and item["body"] == {"linear": 0, "angular": 0})
            unmount_index = next(i for i, item in enumerate(after_dock["timeline"]) if item["type"] == "teleop-unmount")
            page.get_by_role("tab", name="운전").click()
            page.wait_for_selector("#action-group-drive:not([hidden]) [data-panel='console.teleop']")
            calls_after_return = page.evaluate("window.__timeline.filter((item) => item.path === '/api/v1/teleop').length")
            page.wait_for_timeout(250)
            calls_later = page.evaluate("window.__timeline.filter((item) => item.path === '/api/v1/teleop').length")
            teleop_active = page.locator("[data-panel='console.teleop'] ui-button.active").count()
            new_stop_group = page.locator("[role='tab'][aria-selected='true']").inner_text()
            assert zero_index < unmount_index
            assert after_dock["timeline"][zero_index]["body"] == {"linear": 0, "angular": 0}
            assert after_dock["teleopMounted"] is False
            assert after_dock["selected"] == "도킹"
            assert new_stop_group == "운전"
            assert teleop_active == 0
            assert calls_after_return == calls_later
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_failed_terminal_zero_keeps_the_current_action_group_visible():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/__d283")
            page.wait_for_selector("#action-tab-drive")
            page.evaluate("window.__failZero = true")
            page.get_by_role("tab", name="도킹").click()
            page.wait_for_function("document.getElementById('shell-notice').textContent.includes('정지 확인')")
            assert page.locator("#action-group-drive").is_visible()
            assert page.locator("#action-group-docking").is_hidden()
            assert page.get_by_role("tab", name="운전").get_attribute("aria-selected") == "true"
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_active_group_operation_blocks_switch_until_terminal():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/__d283")
            page.wait_for_selector("#action-tab-drive")
            page.get_by_role("tab", name="도킹").click()
            page.wait_for_selector("#action-group-docking:not([hidden])")
            page.evaluate("window.__blocked = {'console.docking': true}")
            page.get_by_role("tab", name="차선 추종").click()
            page.wait_for_function("document.getElementById('shell-notice').textContent === 'operation active'")
            assert page.locator("#action-group-docking").is_visible()
            assert page.locator("#action-group-line_follow").is_hidden()
            page.evaluate("window.__blocked['console.docking'] = false")
            page.get_by_role("tab", name="차선 추종").click()
            page.wait_for_selector("#action-group-line_follow:not([hidden])")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unmount_all_keeps_action_group_when_terminal_zero_fails():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{server.server_port}/__d283")
            page.wait_for_selector("#action-group-drive [data-panel='console.teleop']")
            page.evaluate("window.__failZero = true")
            page.evaluate("window.__unmountFailed = window.__mounted.unmountAll().then(() => false, () => true)")
            assert page.evaluate("window.__unmountFailed") is True
            assert page.locator("#action-group-drive").is_visible()
            assert page.locator("[data-panel='console.teleop']").count() == 1
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_operation_panels_block_switch_during_start_and_while_active():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("dialog", lambda dialog: dialog.accept())
            page.goto(f"http://127.0.0.1:{server.server_port}/__d283_real_operations")
            page.wait_for_selector("#action-tab-drive")

            page.get_by_role("tab", name="차선 추종").click()
            page.wait_for_selector("#action-group-line_follow:not([hidden])")
            page.evaluate("window.__deferOps = true")
            page.locator("[data-panel='console.line_follow'] ui-button").filter(has_text="추종 시작").click()
            page.wait_for_function("window.__deferred.some((item) => item.path === '/api/v1/line-follow/mode')")
            page.get_by_role("tab", name="도킹").click()
            page.wait_for_function("document.getElementById('shell-notice').textContent.includes('요청이 처리 중')")
            assert page.locator("#action-group-line_follow").is_visible()
            page.evaluate("window.__deferred.find((item) => item.path === '/api/v1/line-follow/mode').resolve({mode:'IR_LINE',state:'WAITING'})")
            page.wait_for_function('document.querySelector(`[data-panel="console.line_follow"] dd`)?.textContent === "IR_LINE"')
            page.get_by_role("tab", name="도킹").click()
            page.wait_for_function("document.getElementById('shell-notice').textContent.includes('추종을 중지')")
            assert page.locator("#action-group-line_follow").is_visible()
            page.evaluate("window.__deferOps = false")
            page.locator("[data-panel='console.line_follow'] ui-button").filter(has_text="추종 중지").click()
            page.wait_for_function('document.querySelector(`[data-panel="console.line_follow"] dd`)?.textContent === "OFF"')
            page.get_by_role("tab", name="도킹").click()
            page.wait_for_selector("#action-group-docking:not([hidden])")

            page.evaluate("window.__deferOps = true")
            page.locator("[data-panel='console.docking'] ui-button").filter(has_text="도킹 시작").click()
            page.wait_for_function("window.__deferred.some((item) => item.path === '/api/v1/docking/dock')")
            page.get_by_role("tab", name="운전").click()
            page.wait_for_function("document.getElementById('shell-notice').textContent.includes('요청이 처리 중')")
            assert page.locator("#action-group-docking").is_visible()
            page.evaluate("window.__deferred.find((item) => item.path === '/api/v1/docking/dock').resolve({state:'DOCKING'})")
            page.wait_for_function('document.querySelectorAll(`[data-panel="console.docking"] dd`)[1]?.textContent === "DOCKING"')
            page.get_by_role("tab", name="운전").click()
            page.wait_for_function("document.getElementById('shell-notice').textContent.includes('도킹 작업이 끝나거나')")
            assert page.locator("#action-group-docking").is_visible()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
