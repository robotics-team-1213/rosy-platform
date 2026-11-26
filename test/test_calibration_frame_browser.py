"""Displayed pixels and geometry must belong to the same generation and live-frame registration."""
import base64
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
    tcp = {"x": 0.1, "y": 0.1, "z": 0.03, "yaw_deg": 0.0}
    # Fresh only by the server budget; arm_s carries the old wall-clock field alone and must not show a TCP.
    profiles[0]["robot_status"] = {"live": {"present": True, "stale": False, "age_ms": 100, "fresh_for_ms": 600000,
                                            "tcp": tcp, "tcp_pixel": [30, 30]}}
    profiles[1]["robot_status"] = {"live": {"present": True, "stale": False, "fresh_until": 4e9, "tcp": tcp}}
    profiles[0]["bias"] = {"regions": [{"site": "old", "bias_mm": [1, 2], "stale_map": True, "map_sha": "abc",
                                        "point_m": [0.1, 0.1], "map_point_m": [0.101, 0.102], "reach_mm": 30,
                                        "fk_pixel_z_view": [10, 10], "map_pixel_z_view": [20, 20]}]}
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
              window.armLabels = [];
              ctx.fillText = function(label, ...args) {
                if (this.canvas.id === 'topCanvas' && window.topLabels) window.topLabels.push(label);
                if (this.canvas.id === 'armCanvas') window.armLabels.push(label);
                return text.call(this, label, ...args);
              };
            """)
            page.route("**/api/calibration/v1/profiles", lambda r: r.fulfill(json={"profiles": profiles, "configured": True}))
            receipt = {"X-Rosy-Frame-Binding": "aligned", "X-Rosy-Frame-Generation": generation,
                       "X-Rosy-Frame-Reference-Sha256": reference, "X-Rosy-Frame-Lifetime-Ms": "2000",
                       "X-Rosy-Frame-Shift-Px": "0.0", "X-Rosy-Frame-Observed-At": "1795651503.2"}
            observation = {"fixtures": {"pallet": {"status": "partial", "segments": [
                {"kind": "image_edge", "points_px": [[4, 6], [21, 18]]}], "clipping_edges": ["bottom"]},
                "temp_plate_a": {"status": "partial", "placement_slots": {"status": "candidate", "revision": "v11",
                    "slots": {"R2": {"center_px": [28, 31], "uncertainty_px": 4.5}}}}}}
            def frame(route):
                if "fixture-frame+json" in route.request.headers.get("accept", ""):
                    route.fulfill(json={"media": "image/png", "image": base64.b64encode(encoded.getvalue()).decode(),
                                        "fixture_observation": observation}, headers=receipt)
                else:
                    route.fulfill(body=encoded.getvalue(), content_type="image/png", headers=receipt)
            page.route("**/frame/live", frame)
            page.goto(open_screen + "/?arm=arm_a")
            badge = page.locator("#frameBindTag")
            expect(badge).to_have_text("실시간 영상 정합 확인")
            assert page.evaluate("window.topLabels.includes('center_px')")
            assert page.evaluate("window.topLabels.includes('TCP')")
            assert page.evaluate("window.armLabels.some(l => l.startsWith('TCP ('))")
            # An old-map bias is quiet and dashed and says so in words, never in a severity colour.
            assert page.evaluate("window.topLabels.includes('bias 1,2mm · 지도 지연')")
            assert page.evaluate("window.armLabels.includes('bias(old) 1,2mm · 지도 지연')")
            expect(page.locator('#biasTableWrap td[data-evidence="delayed"]')).to_have_count(1)
            expect(page.locator('#biasTableWrap td[data-level="warn"]')).to_have_count(0)
            evidence = page.locator("#topEvidence")
            expect(evidence).to_have_text("지도 없음 · 관측 09:05:03 · 실시간 카메라")
            expect(evidence).to_have_attribute("title", "관측 UTC 2026-11-26T00:05:03.200Z")
            expect(page.locator("#fixtureDetails")).to_be_visible()
            assert page.evaluate("window.topLabels.includes('선박 외곽')")
            assert page.evaluate("window.topLabels.includes('R2 후보')")
            receipt["X-Rosy-Frame-Generation"] = "old-map"
            page.locator("#btnRefreshFrame").click()
            expect(badge).to_have_text("정합 미확인 · 오버레이 숨김")
            assert not page.evaluate("window.topLabels.includes('center_px')")
            expect(page.locator("#fixtureDetails")).to_be_hidden()
            assert not page.evaluate("window.topLabels.includes('R2 후보')")
            receipt.update({"X-Rosy-Frame-Generation": generation, "X-Rosy-Frame-Binding": "unverified",
                            "X-Rosy-Frame-Shift-Px": "124.6"})
            page.goto(open_screen + "/?arm=arm_s")
            expect(badge).to_have_attribute("title", "이동 124.6px")
            page.wait_for_function("window.armLabels.length > 0")
            assert not page.evaluate("window.armLabels.some(l => l.startsWith('TCP ('))")
            assert not page.evaluate("window.topLabels.includes('center_px')")
            assert not errors
        finally:
            browser.close()
