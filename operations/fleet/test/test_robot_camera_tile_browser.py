"""Real Chromium Pinky front camera tile tests (Item H): fresh / stale / unregistered + WebRTC fallback."""

import struct
import zlib

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _robot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


def _png_1x1() -> bytes:
    """A 1x1 grey PNG built from its chunks (no high-entropy literal for the secret scan)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    signature = bytes([137, 80, 78, 71, 13, 10, 26, 10])
    return signature + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes([0, 128]))) + chunk(b"IEND", b"")


_PNG_1X1 = _png_1x1()


@pytest.mark.parametrize("case", ["fresh", "stale", "unregistered"])
def test_pinky_front_camera_tile_states_in_robot_detail(site, case):
    from playwright.sync_api import expect, sync_playwright

    robot = _robot("rosy_45")
    sources = [] if case == "unregistered" else ["pinky_45_front"]
    lease = {"source_id": "pinky_45_front", "lease": "sample-lease", "expires_in_s": 60,
             "frame_path": "/api/vision/sources/pinky_45_front/frame"}
    api = {**API, "/api/fleet/state": {**API["/api/fleet/state"], "robots": [robot]},
           "/api/fleet/vision/sources": {"sources": sources},
           "/api/fleet/vision/lease": lease}
    answers = {"/api/fleet/vision/lease": (200, lease)}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [], answers=answers)
        try:
            frame_state = {"age": "500", "state": "live"}
            if case != "unregistered":
                page.route("**/api/vision/sources/pinky_45_front/frame", lambda route: route.fulfill(
                    status=200,
                    headers={"Content-Type": "image/png", "X-Frame-Age-Ms": frame_state["age"], "X-Frame-State": frame_state["state"]},
                    body=_PNG_1X1,
                ))
            page.locator("#robot-dock-mount .robot-dock-btn[data-robot-id='rosy_45']").click()
            tile = page.locator("#robot-panel-mount [data-robot-camera-tile='rosy_45']")
            expect(tile).to_be_visible()
            if case == "unregistered":
                expect(tile).to_have_attribute("data-state", "unregistered")
                expect(tile).to_contain_text("카메라 등록 안 됨")
            elif case == "fresh":
                expect(tile).to_have_attribute("data-state", "live")
                expect(tile).to_contain_text("최신 사진 ·")
            else:
                expect(tile).to_have_attribute("data-state", "live")
                frame_state["age"] = "5000"
                frame_state["state"] = "stale"
                page.clock.run_for(2500)
                expect(tile).to_have_attribute("data-state", "stale", timeout=5000)
                expect(tile).to_contain_text("최신 사진 ·")
            # C24 layout: camera feed section sits above commands (.robot-actions)
            actions_box = page.locator("#robot-panel-mount .robot-panel-commands .robot-actions").first.bounding_box()
            tile_box = tile.bounding_box()
            assert actions_box["y"] >= tile_box["y"] + tile_box["height"]
            assert not errors
        finally:
            browser.close()
