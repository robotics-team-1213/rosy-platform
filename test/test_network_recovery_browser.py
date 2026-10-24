"""Real Chromium recovery flow; intercepted HTTPS isolates UI from physical radios."""
from pathlib import Path

import pytest

from browser_harness import browser_tests_enabled, launch_options, save_temp_screenshot
from test_network_recovery import modules, rig  # noqa: F401 - shared isolated authority fixtures

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in required")


@pytest.mark.parametrize("width,height", [(320, 568), (390, 844), (1366, 768)])
def test_recovery_keyboard_confirmation_disconnect_and_reconnect(rig, width, height):
    playwright = pytest.importorskip("playwright.sync_api")
    _, http, _, _, calls, coordinator, code = rig
    assets = Path(__file__).resolve().parents[1] / "shared/web"
    app = http.RecoveryHTTP(coordinator, fingerprint="AB:" * 31 + "AB", assets_dir=assets)
    connection_lost = [False]
    terminal = [False]
    def network(command, payload):
        calls.append((command, payload))
        return {"job_id": payload.get("request_id", "job-1"),
                "state": "committed" if terminal[0] else "prepared"}
    coordinator.network_call = network
    with playwright.sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(**launch_options())
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        def intercept(route):
            request = route.request
            if connection_lost[0] and "/network/" in request.url:
                route.abort("internetdisconnected")
                return
            headers = {name.title(): value for name, value in request.all_headers().items()}
            headers["Host"] = "10.42.0.1:8443"
            status, response_headers, body = app.response(request.method,
                request.url.removeprefix("https://10.42.0.1:8443"), headers,
                request.post_data_buffer or b"")
            after_response = app.after_response
            route.fulfill(status=status, headers=response_headers, body=body)
            if after_response:
                after_response()
        page.route("https://10.42.0.1:8443/**", intercept)
        try:
            page.goto("https://10.42.0.1:8443/")
            page.get_by_label("물리 화면과 전체 지문", exact=False).check()
            page.get_by_label("화면에 표시된 복구 코드", exact=True).fill("WRONG123")
            page.get_by_role("button", name="복구 코드 확인", exact=True).click()
            page.get_by_text("복구 코드가 맞지 않습니다.", exact=False).wait_for()
            assert page.locator("#message").evaluate("el => el === document.activeElement")
            page.locator("#code").fill(code)
            page.locator("#code").press("Enter")
            page.locator("#network").wait_for(state="visible")
            page.get_by_label("현장 Wi-Fi 이름 (SSID)", exact=True).fill("site")
            page.get_by_label("Wi-Fi 비밀번호", exact=True).fill("password")
            page.locator("#psk").press("Enter")
            assert page.locator("#apply").evaluate("el => el === document.activeElement")
            page.get_by_role("button", name="Wi-Fi 연결 적용", exact=True).click()
            page.get_by_text("작업 접수됨 · 연결 적용 대기", exact=True).wait_for()
            assert page.locator("#psk").input_value() == ""
            assert "password" not in page.locator("body").inner_text()
            assert [call[0] for call in calls] == ["network.connect", "network.start"]
            connection_lost[0] = True
            page.get_by_role("button", name="결과 다시 확인", exact=True).click()
            page.get_by_text("연결이 끊겼습니다.", exact=False).wait_for()
            connection_lost[0] = False
            terminal[0] = True
            page.reload()
            page.get_by_text("연결 저장 완료", exact=True).wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            save_temp_screenshot(page, f"network-recovery-{width}.png")
            assert errors == []
        finally:
            browser.close()
