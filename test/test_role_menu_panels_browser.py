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


def test_setup_docking_never_sends_motion_without_supported_capability():
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
        page.route("http://rosy.test/assets/panels/setup/docking.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
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
          window.confirm = () => true;
          root.querySelector('[data-dock-id="dock-a"] ui-button:last-child').click();
          root.querySelectorAll('.surface-actions ui-button').forEach(button => button.click());
        }""")
        assert "동작을 막았습니다" in page.locator("[role=status]").inner_text()
        assert page.locator("[data-dock-id='dock-a'] ui-button:last-child").evaluate("node => node.disabled === true")
        assert page.evaluate("window.__apiCalls") == []
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
