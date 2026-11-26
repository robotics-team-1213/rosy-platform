"""Browser contract for pre-auth Vision 401 suppression and single signed-out CTA."""

import pytest
from browser_harness import browser_tests_enabled, open_token_access
from test_fleet_header_browser import _fleet

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")

LEASE = {
    "source_id": "ceiling_north",
    "lease": "test-lease",
    "frame_path": "/api/vision/sources/ceiling_north/frame",
    "expires_in_s": 60,
}
FRAME = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#556070"/></svg>'


def test_signed_out_console_defers_protected_vision_and_uses_single_cta(tmp_path):
    """Signed-out boot suppresses protected Vision fetches, shows neutral auth status, and avoids double CTA."""
    from playwright.sync_api import expect

    with _fleet(tmp_path, console_token="header-token") as (browser, origin):
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        vision_requests = []
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.on("request", lambda req: vision_requests.append(req.url) if "/api/fleet/vision/" in req.url else None)
        vision_mode = "ok"

        def handle_sources(route):
            if vision_mode == "drop":
                route.abort()
            elif vision_mode == "503":
                route.fulfill(status=503, json={"detail": "vision unavailable"})
            else:
                route.fulfill(status=200, json={"sources": ["ceiling_north"]})

        page.route("**/api/fleet/vision/sources", handle_sources)
        page.route("**/api/fleet/vision/lease", lambda route: route.fulfill(json=LEASE))
        page.route(
            "**/api/vision/sources/ceiling_north/frame",
            lambda route: route.fulfill(
                content_type="image/svg+xml",
                body=FRAME,
                headers={"X-Frame-Rectified": "false", "X-Frame-Seq": "42", "X-Frame-Age-Ms": "20"},
            ),
        )
        try:
            page.goto(origin + "/console")
            expect(page.locator("#user-role")).to_have_text("인증 필요", timeout=15000)
            expect(page.locator("#site-path-summary")).to_have_text("인증 필요")
            expect(page.locator("#site-path-summary")).to_have_attribute("data-kind", "neutral")
            expect(page.locator("#connection-guide")).to_be_hidden()
            expect(page.locator("#map-empty")).to_be_visible()
            expect(page.locator("#connection-guide-action")).to_be_visible()
            page.wait_for_timeout(1600)
            assert vision_requests == [], f"Unexpected pre-auth Vision fetches: {vision_requests}"

            open_token_access(page)
            page.locator("#console-token").fill("header-token")
            page.locator("#token-save").click()
            expect(page.locator("#user-role")).to_contain_text("운영자", timeout=15000)
            expect(page.locator("#connection-guide")).to_be_hidden()
            expect(page.locator("#connection-guide-action")).to_be_hidden()
            expect(page.locator("#site-path-summary")).to_have_text("모두 정상", timeout=10000)
            expect(page.locator("#site-path-summary")).to_have_attribute("data-kind", "good")
            assert len(vision_requests) >= 1

            page.locator("#context-tools-tab").click()
            expect(page.locator("#vision-refresh")).to_be_visible(timeout=10000)
            vision_mode = "503"
            page.locator("#vision-refresh").click()
            expect(page.locator("#site-path-summary")).to_have_text("Vision 응답 503", timeout=10000)
            expect(page.locator("#site-path-summary")).to_have_attribute("data-kind", "warn")
            # 끊김은 warn이다. crit은 실제 운용 위험만(콘셉트 표, 대열 relay 끊김) 쓴다.
            vision_mode = "drop"
            page.locator("#vision-refresh").click()
            expect(page.locator("#site-path-summary")).to_have_text("Vision 끊김", timeout=10000)
            expect(page.locator("#site-path-summary")).to_have_attribute("data-kind", "warn")

            open_token_access(page)
            page.locator("#console-token").fill("")
            page.locator("#token-save").click()
            expect(page.locator("#user-role")).to_have_text("인증 필요", timeout=15000)
            expect(page.locator("#site-path-summary")).to_have_text("인증 필요")
            expect(page.locator("#site-path-summary")).to_have_attribute("data-kind", "neutral")
            expect(page.locator("#connection-guide")).to_be_hidden()
            expect(page.locator("#connection-guide-action")).to_be_visible()
            after_lock = len(vision_requests)
            page.wait_for_timeout(1600)
            assert len(vision_requests) == after_lock
            assert not errors
        finally:
            page.close()
