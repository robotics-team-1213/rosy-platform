"""Browser behavior of the D-204 device hardware panel."""

from __future__ import annotations

from pathlib import Path

import pytest

from browser_harness import open_page


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "hmi" / "dashboard"


def test_hardware_panel_marks_last_snapshot_stale_after_access_failure():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser, page, _errors = open_page(playwright, 720, 900)
        except Exception as error:
            pytest.skip(f"Playwright Chromium unavailable: {error}")

        page.route("http://rosy.test/panel-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body="<!doctype html><html><body></body></html>"))
        source = (WEB / "panels" / "host" / "hardware.js").read_text(encoding="utf-8")
        page.route("http://rosy.test/assets/panels/host/hardware.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=source))
        page.goto("http://rosy.test/panel-test", wait_until="domcontentloaded", timeout=5_000)
        page.evaluate("""async () => {
          const {mount} = await import('/assets/panels/host/hardware.js');
          const section = document.createElement('ui-section');
          section.id = 'hardware-test';
          document.body.append(section);
          const apiCalls = [];
          const store = {poll(_path, _interval, onData, onError) {
            window.__panelData = onData;
            window.__panelError = onError;
            return () => { window.__pollStopped = true; };
          }};
          const api = async (path, options) => {
            apiCalls.push({path, method: options.method || 'GET'});
            return {accepted: false, detail: '최근 요청이 있어 잠시 기다려 주세요.'};
          };
          window.__apiCalls = apiCalls;
          window.__unmount = mount(section, {role: 'administrator', api, store});
          window.__panelData({
            available: true,
            stale: false,
            measured_at: '2026-09-26T10:00:00+00:00',
            age_s: 7,
            devices: [
              {id: 'lidar', label: 'LiDAR', bus: 'UART', state: 'ok', evidence: '포트 응답'},
              {id: 'buzzer', label: '<img src=x>', bus: 'GPIO', state: 'no_response', evidence: '응답 없음'},
              {id: 'lamp', label: '표시등', bus: 'PWM', state: 'needs_human', evidence: '사람 확인 필요'}
            ]
          });
        }""")

        assert "LiDAR" in page.locator(".hardware-device").first.inner_text()
        assert page.locator(".hardware-device").first.locator(".hardware-device-state").get_attribute("data-status") == "OK"
        assert page.locator(".hardware-device").nth(1).get_attribute("data-state") == "no_response"
        assert page.locator(".hardware-device").nth(1).locator(".hardware-device-state").get_attribute("data-status") == "ERROR"
        assert page.locator(".hardware-device").nth(2).locator(".hardware-device-state").get_attribute("data-status") is None
        assert page.locator(".hardware-device-identity img").count() == 0
        page.locator("ui-button.hardware-refresh").click()
        assert "최근 요청" in page.locator(".hardware-note").inner_text()
        assert page.evaluate("window.__apiCalls") == [{
            "path": "/api/v1/host/hardware/refresh", "method": "POST",
        }]

        page.evaluate("window.__panelError({status: 403, message: 'Forbidden'})")
        assert page.locator(".hardware-facts").get_attribute("data-stale") == "true"
        assert "권한이 없습니다" in page.locator(".hardware-note").inner_text()

        page.evaluate("window.__unmount()")
        assert page.evaluate("window.__pollStopped") is True
        browser.close()
