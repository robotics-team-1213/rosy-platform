"""The camera alignment card: reference over live, arrows and a readout that says how far and which way (2026-11-27)."""
import json

import pytest

from browser_harness import browser_tests_enabled, open_page
from test_calibration_web import open_screen, store  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1")

def _png(w=64, h=48):
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG = _png()


@pytest.mark.parametrize("width", [390, 1280])
def test_the_align_card_overlays_and_says_how_far_to_move(open_screen, width):  # noqa: F811
    import base64

    from playwright.sync_api import expect, sync_playwright

    url = open_screen[0] if isinstance(open_screen, tuple) else open_screen
    report = {"ok": True, "aligned": False, "limit_px": 6.0, "max_px": 42.7, "median_px": 33.6, "shift_px": [33.2, -0.1],
              "rotation_deg": -2.17, "scale": 0.9519, "arrows": [[64, 48, 97, 48], [320, 240, 322, 241]],
              "live_image": base64.b64encode(PNG).decode("ascii")}
    calls = []
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, width, 900)
        try:
            page.route("**/api/calibration/v1/profiles", lambda r: r.fulfill(json={"configured": True, "profiles": [
                {"id": "arm_b", "arm_id": "arm_b", "label": "Arm B", "sites": {}, "camera_top": {}}]}))

            def align(route):
                calls.append(route.request.url)
                if "/align/reference" in route.request.url:
                    return route.fulfill(body=PNG, content_type="image/png")
                if "ref=" in route.request.url:
                    return route.fulfill(json=report)
                return route.fulfill(json={"references": [{"id": "current", "label": "11-26 13:26 · 현재 지도 기준"},
                                                          {"id": "generations/g1/reference-top.jpg", "label": "11-25 · generations/g1"}]})

            page.route(lambda u: "/api/calibration/v1/profiles/arm_b/align" in u, align)  # a glob "?" is one character
            page.goto(url + "/?arm=arm_b")
            expect(page.locator("#alignRef option")).to_have_count(2)
            page.locator("#alignRef").select_option("generations/g1/reference-top.jpg")
            page.locator("#alignStart").click()
            readout = page.locator("#alignReadout")
            expect(readout).to_contain_text("6 px 이내로 맞추세요", timeout=10000)
            expect(readout).to_contain_text("오른쪽 33.2")
            expect(readout).to_contain_text("반시계 방향 2.17° 회전")
            expect(page.locator("#alignTag")).to_have_text("어긋남 42.7 px")
            assert any("ref=generations%2Fg1%2Freference-top.jpg" in c for c in calls)
            report.update(aligned=True, max_px=3.1)
            expect(page.locator("#alignTag")).to_have_text("기준 안", timeout=10000)
            page.locator("#alignStart").click()
            expect(page.locator("#alignStart")).to_have_text("맞춤 보기 시작")
            assert page.evaluate("document.documentElement.scrollWidth") <= width
        finally:
            browser.close()
