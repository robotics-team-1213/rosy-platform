"""Displayed pixels and geometry must belong to the same generation and live-frame registration."""
from io import BytesIO

import pytest

from browser_harness import browser_tests_enabled, open_page
from test_calibration_web import open_screen, store  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1")


def test_exact_frame_gate_follows_the_image_and_generation(open_screen):  # noqa: F811
    from PIL import Image
    from playwright.sync_api import expect, sync_playwright

    encoded = BytesIO()
    Image.new("RGB", (64, 48), color=(80, 60, 40)).save(encoded, "PNG")
    generation, reference = "1" * 12, "2" * 64
    profiles = [{"id": arm, "arm_id": arm, "sites": {}, "camera_top": {
        "generation": generation, "reference_sha256": reference, "has_reference": True,
        "frame_size": [64, 48], "center_px": [20, 16], "height_m": 0.6,
    }} for arm in ("arm_a", "arm_s")]
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 1200, 900)
        try:
            page.add_init_script("""
              const ctx = CanvasRenderingContext2D.prototype;
              const draw = ctx.drawImage, text = ctx.fillText;
              ctx.drawImage = function(...args) {
                if (this.canvas.id === 'topCanvas') window.topLabels = [];
                return draw.apply(this, args);
              };
              ctx.fillText = function(label, ...args) {
                if (this.canvas.id === 'topCanvas' && window.topLabels) window.topLabels.push(label);
                return text.call(this, label, ...args);
              };
            """)
            page.route("**/api/calibration/v1/profiles", lambda r: r.fulfill(json={"profiles": profiles, "configured": True}))
            receipt = {"X-Rosy-Frame-Binding": "aligned", "X-Rosy-Frame-Generation": generation,
                       "X-Rosy-Frame-Reference-Sha256": reference, "X-Rosy-Frame-Lifetime-Ms": "2000",
                       "X-Rosy-Frame-Shift-Px": "0.0"}
            page.route("**/frame/live", lambda r: r.fulfill(body=encoded.getvalue(), content_type="image/png", headers=receipt))
            page.goto(open_screen + "/?arm=arm_a")
            badge = page.locator("#frameBindTag")
            expect(badge).to_have_text("실시간 영상 정합 확인")
            assert page.evaluate("window.topLabels.includes('center_px')")
            receipt["X-Rosy-Frame-Generation"] = "old-map"
            page.locator("#btnRefreshFrame").click()
            expect(badge).to_have_text("정합 미확인 · 오버레이 숨김")
            assert not page.evaluate("window.topLabels.includes('center_px')")
            receipt.update({"X-Rosy-Frame-Generation": generation, "X-Rosy-Frame-Binding": "unverified",
                            "X-Rosy-Frame-Shift-Px": "124.6"})
            page.goto(open_screen + "/?arm=arm_s")
            expect(badge).to_have_attribute("title", "이동 124.6px")
            assert not page.evaluate("window.topLabels.includes('center_px')")
            assert not errors
        finally:
            browser.close()
