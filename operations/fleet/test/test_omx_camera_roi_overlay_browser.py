"""Real-Chromium Playwright test for OMX camera pixel ROI SVG overlay & toggle (PR 5)."""

from __future__ import annotations

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium",
)


def _pr5_api():
    cameras = {
        "schema": "rosy.cell-site-pixels.v1",
        "image_size_px": [640, 480],
        "status": "cell_local_reference",
        "arm_s_top": {
            "pinky_tray": {"label": "S3 짐칸 ROI", "top_roi_px": [10, 40, 260, 240]},
            "belt_center": {"label": "벨트 인입 중앙", "top_roi_px": [240, 90, 460, 270]},
        },
        "arm_ab_top": {
            "belt_pickup": {"label": "벨트 픽업", "top_px": [341, 112]},
            "outbound_stand": {"label": "반출대 적재", "top_roi_px": [410, 30, 570, 125]},
        },
    }
    return {
        **API,
        "/api/fleet/charge-bays": {
            "thresholds": {"go_percent": 15, "leave_percent": 80},
            "bays": [{"bay": "C1", "x": -0.414, "y": 0.47, "state": "free", "robot_id": None}],
            "actions": [],
            "omx_cells": {
                "cell_s": {"station": {"station_place": "S3"}, "gate": {"phase": "IDLE", "robot_id": "rosy_01"}},
                "cell_ab": {"station": {"station_place": "S5"}, "gate": {"phase": "IDLE"}},
            },
        },
        "/api/fleet/site-points": {"cameras": cameras},
        "/api/fleet/site-points?view=full": {"cameras": cameras},
    }


def test_omx_inspector_renders_pixel_roi_svg_and_toggles_visibility(site):
    from playwright.sync_api import expect

    posts = []
    browser, page, errors = _open(None, site, _pr5_api(), posts, {})
    try:
        inspector = page.locator("#omx-right-inspector")
        expect(inspector).to_be_visible()
        summary = inspector.locator("details.omx-pipeline-disclosure > summary")
        summary.click()

        roi_toggle = inspector.locator('ui-button[data-roi-toggle="true"]')
        expect(roi_toggle).to_be_visible()
        expect(roi_toggle).to_have_attribute("aria-pressed", "true")

        svg = inspector.locator(".omx-inspector-single-wrap svg.omx-cam-roi-overlay")
        expect(svg).to_have_count(0)

        inspector.get_by_role("button", name="S3 상단 카메라 선택").click()
        expect(svg).to_be_visible()
        expect(svg).to_have_attribute("viewBox", "0 0 640 480")
        expect(svg).to_have_attribute("preserveAspectRatio", "xMidYMid slice")
        expect(svg.locator('rect[data-roi-key="pinky_tray"]')).to_have_count(1)
        expect(svg.locator('rect[data-roi-key="belt_center"]')).to_have_count(1)

        zoom_btn = inspector.locator(".omx-inspector-zoom")
        zoom_btn.click()
        expect(svg).to_have_attribute("preserveAspectRatio", "xMidYMid meet")
        zoom_btn.click()
        expect(svg).to_have_attribute("preserveAspectRatio", "xMidYMid slice")

        roi_toggle.click()
        expect(roi_toggle).to_have_attribute("aria-pressed", "false")
        expect(svg).to_have_count(0)

        roi_toggle.click()
        expect(svg).to_have_count(1)
        assert not errors
    finally:
        browser.close()
