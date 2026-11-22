"""Product adoption tests verifying C18/C23/C24 cockpit dock+panel and wrapped actions."""

import copy
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (390, 844), (320, 568)])
def test_cockpit_dock_and_panel_replace_legacy_robot_selector(site, width, height):
    from playwright.sync_api import expect, sync_playwright

    api = copy.deepcopy(API)
    api["/api/fleet/site-map"] = {
        "maps": [{
            "map_id": "site",
            "polygon_m": [[-1, -1], [1.5, -1], [1.5, 1], [-1, 1]],
            "bounds_m": {"min_x": -1, "min_y": -1, "max_x": 1.5, "max_y": 1},
            "places": [],
        }],
    }
    api["/api/fleet/tracking"] = {
        "lease_s": 10,
        "sources": [{"source_id": "ceiling_north", "status": "OK", "age_ms": 20}],
        "robots": [],
        "unknown": [],
        "anchors": [{
            "target_id": "arm_a",
            "kind": "omx_ai",
            "label": "OMX A",
            "base_x": 0.55,
            "base_y": 0.36,
            "cell_status": "READY",
            "live": True,
        }],
    }

    with sync_playwright() as pw:
        posts = []
        browser, page, errors = _open(pw, site, api, posts, size=(width, height))

        # C23 right-dock + C24 stage & panel mount cleanly; retired legacy selectors stay absent.
        stage = page.locator("#" + "robot-stage")
        dock = page.locator("#" + "robot-dock")
        panel = page.locator("#" + "robot-panel")
        expect(stage).to_be_visible()
        expect(dock).to_be_visible()
        expect(panel).to_be_hidden()

        for retired in (
            "#robot-choice",
            "#focus-robot-choice",
            ".workspace-heading",
            "#robot-workspace-empty",
            "[data-select-robot-id]",
        ):
            assert page.locator(retired).count() == 0, f"retired selector still in DOM: {retired}"
        assert "/api/fleet/pipeline/" not in page.content()

        buttons = dock.locator(".robot-dock-btn")
        assert buttons.count() >= 2
        boxes = buttons.evaluate_all("nodes => nodes.map(n => n.getBoundingClientRect().toJSON())")
        if width >= 1024:
            assert all(b["width"] >= 48 and b["height"] >= 44 for b in boxes)
        else:
            assert all(b["height"] >= 44 and b["width"] >= 44 for b in boxes)

        # Open a mobile robot from C23 dock -> C24 panel shows workspace card with collapsed manual controls.
        mobile_btn = dock.locator('.robot-dock-btn[data-kind="mobile"]').first
        mobile_id = mobile_btn.get_attribute("data-robot-id")
        mobile_btn.click()
        expect(panel).to_be_visible()
        expect(panel).to_have_attribute("data-robot-id", mobile_id)
        expect(panel.locator(".robot-panel-twin .robot-view")).to_have_count(1)
        expect(page.locator(f'#robot-workspace article[data-robot-id="{mobile_id}"]')).to_be_visible()
        manual_details = panel.locator('details[data-section="manual"]')
        expect(manual_details).to_have_count(1)
        assert manual_details.evaluate("node => !node.open")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")

        # Switching to observed OMX arm via dock hides mobile jog and links to /console/cell.
        arm_btn = dock.locator('.robot-dock-btn[data-robot-id="arm_a"]')
        expect(arm_btn).to_be_visible()
        arm_btn.click()
        expect(panel).to_have_attribute("data-robot-id", "arm_a")
        expect(panel).to_have_attribute("data-kind", "arm")
        expect(panel.locator(".robot-panel-twin .robot-view")).to_have_count(1)
        assert panel.locator('details[data-section="manual"]').count() == 0
        expect(panel.locator('a[href="/console/cell"]')).to_have_count(1)

        if output := os.environ.get("ROSY_SHOT_DIR"):
            Path(output).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(output) / f"fleet-cockpit-{width}.png"))

        panel.locator(".robot-panel-close").click()
        expect(panel).to_be_hidden()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert not posts and not errors
        browser.close()


@pytest.mark.parametrize("width", [320, 390])
def test_long_intervention_action_wraps_and_keeps_confirmation(site, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, API, [], size=(width, 844))
        page.locator("#fleet-inbox").click()
        button = page.locator('[data-decision="BACK_AND_RETRY"]').first
        assert button.inner_text().rstrip().endswith("…")
        button.evaluate("node => node.firstChild.textContent = '뒤쪽 공간을 확인한 뒤 후진하여 다시 시도하기…'")
        assert button.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        assert not errors
        browser.close()
