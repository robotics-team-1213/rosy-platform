"""Waypoint capture follows server-judged pose evidence through state changes."""

from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright


REPO = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO), **kwargs)

    def translate_path(self, path):
        if path.startswith("/common/"):
            return str(REPO / "src/hmi/web" / path.removeprefix("/common/"))
        return super().translate_path(path)

    def log_message(self, _format, *_args):
        pass


def test_waypoint_save_tracks_fresh_pose_and_stays_blocked_after_disconnect():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.evaluate("""async () => {
              await import('/common/ui.js');
              const {mount} = await import('/src/hmi/dashboard/panels/setup/waypoints.js');
              const root = document.createElement('main'); document.body.append(root);
              const callbacks = {}; window.__callbacks = callbacks;
              const store = {poll(path, _interval, onData, onError) {
                callbacks[path] = {onData, onError}; return () => {};
              }};
              window.__calls = [];
              window.__resolve = null;
              window.__unmount = mount(root, {role:'operator', store, api: async (path, options) => {
                window.__calls.push({path, method:options.method});
                return await new Promise(resolve => { window.__resolve = resolve; });
              }});
              root.querySelector('input[name="name"]').value = 'dock approach';
            }""")
            save = page.locator("ui-button").filter(has_text="현재 위치 저장")
            assert save.is_disabled()
            page.evaluate("""() => window.__callbacks['/api/v1/robot/state'].onData({
              pose:{x:1.2,y:0.4,yaw:0},evidence:{pose:{evidence:'fresh'}}
            })""")
            assert save.is_enabled()
            page.evaluate("""() => window.__callbacks['/api/v1/robot/state'].onData({
              pose:{x:1.2,y:0.4,yaw:0},evidence:{pose:{evidence:'delayed',received_at:new Date(Date.now()-22000).toISOString()}}
            })""")
            assert save.is_disabled()
            assert "지연" in page.locator('[role="status"]').inner_text()
            page.locator("form").evaluate("form => form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            assert page.evaluate("window.__calls") == []
            page.evaluate("""() => window.__callbacks['/api/v1/robot/state'].onData({
              pose:{x:1.2,y:0.4,yaw:0},evidence:{pose:{evidence:'fresh'}}
            })""")
            page.locator("form").evaluate("form => form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            assert page.evaluate("window.__calls.length") == 1
            assert save.is_disabled()
            page.locator("form").evaluate("form => form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            assert page.evaluate("window.__calls.length") == 1
            page.evaluate("""() => window.__callbacks['/api/v1/robot/state'].onError(new Error('link down'))""")
            page.evaluate("window.__resolve({})")
            page.wait_for_timeout(50)
            assert save.is_disabled()
            assert page.evaluate("window.__calls.length") == 1
            assert errors == []
            page.evaluate("window.__unmount()")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
