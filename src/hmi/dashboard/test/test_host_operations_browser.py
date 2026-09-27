"""Device procedure feedback stays visible beside its action."""

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
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO), **kwargs)

    def log_message(self, _format, *_args):
        pass


def test_network_action_reports_rejection_and_success_beside_controls():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.evaluate("""async () => {
              const {mount} = await import('/src/hmi/dashboard/panels/host/operations.js');
              const root = document.createElement('main'); document.body.append(root);
              const callbacks = {};
              window.__callbacks = callbacks;
              const store = {poll(path, _interval, onData, onError) {
                callbacks[path] = {onData, onError}; return () => {};
              }};
              window.__result = {available: true, ok: false, detail: '프로파일이 거부되었습니다.'};
              window.__calls = [];
              window.__unmount = mount(root, {role:'administrator', store,
                api: async (path, options) => {
                  window.__calls.push({path, method: options.method}); return window.__result;
                }});
              callbacks['/api/v1/host/network'].onData({available:true,ok:true,data:{mode:'SITE_STA'}});
              window.confirm = () => true;
              root.querySelector('input[aria-label="네트워크 프로파일 ID"]').value = 'site-a';
            }""")
            page.locator("form").filter(has=page.locator('input[aria-label="네트워크 프로파일 ID"]')).evaluate(
                "form => form.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
            )
            network = page.locator("section.ui-readback").filter(has_text="네트워크").first
            result = network.locator("ui-status").last
            assert "프로파일이 거부되었습니다" in result.inner_text()
            assert result.is_visible()
            assert page.evaluate("window.__calls.length") == 1

            page.evaluate("window.__result = {available:true,ok:true}")
            page.locator("form").filter(has=page.locator('input[aria-label="네트워크 프로파일 ID"]')).evaluate(
                "form => form.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
            )
            assert "프로파일 적용을 요청했습니다" in result.inner_text()
            assert result.is_visible()
            assert page.evaluate("window.__calls.length") == 2

            page.evaluate("""() => {
              window.__result = {available:true,ok:false,detail:'이전 릴리스가 거부되었습니다.'};
              window.__callbacks['/api/v1/host/release'].onData({
                available:true,ok:true,data:{state:'IDLE',previous:'r1'}
              });
            }""")
            page.get_by_text("이전 릴리스로 복귀", exact=True).click()
            release = page.locator("section.ui-readback").filter(has_text="릴리스").first
            release_result = release.locator("ui-status").last
            assert "이전 릴리스가 거부되었습니다" in release_result.inner_text()
            assert release_result.is_visible()

            page.evaluate("""() => {
              window.confirm = () => false;
              document.querySelector('input[aria-label="Wi-Fi SSID"]').value = 'site';
              document.querySelector('input[aria-label="Wi-Fi 암호"]').value = 'password123';
            }""")
            page.locator("form").filter(has=page.locator('input[aria-label="Wi-Fi SSID"]')).evaluate(
                "form => form.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))"
            )
            page.wait_for_timeout(100)
            assert page.evaluate("window.__calls.length") == 3
            assert errors == []
            page.evaluate("window.__unmount()")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
