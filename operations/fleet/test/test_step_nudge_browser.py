"""Forward/back 0.10 m step buttons in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1)."""

import copy
import json

from test_console_queue_inline_browser import API, _open, _robot, site  # noqa: F401

from browser_harness import browser_tests_enabled
import pytest

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


def test_step_nudge_blocks_second_post_while_running_and_ignores_hold(site):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    r1 = _robot("rosy_01")
    r1["localization"] = {"state": "LOCALIZED", "reporting": True}
    api = copy.deepcopy(API)
    api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 1, "total": 1}, "ts": 0.0, "robots": [r1]}
    step_posts = []
    loc_state = {"mission": {"kind": "nudge_forward", "state": "running"}}

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            def handle_step(route):
                step_posts.append(json.loads(route.request.post_data or "{}"))
                route.fulfill(status=202, content_type="application/json", body=json.dumps({"accepted": True}))

            def handle_loc(route):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(loc_state))

            page.route("**/api/fleet/robots/*/step", handle_step)
            page.route("**/api/fleet/robots/*/localization", handle_loc)

            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="rosy_01"]').click()
            fwd = page.locator('[data-step-nudge="forward"]')
            bwd = page.locator('[data-step-nudge="backward"]')
            expect(fwd).to_be_enabled()

            # Hold pointer down for 400 ms then release: only 1 POST
            fwd.scroll_into_view_if_needed()
            box = fwd.bounding_box()
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.down()
            page.wait_for_timeout(400)
            page.mouse.up()

            expect(fwd).to_be_disabled()
            expect(bwd).to_be_disabled()
            # Attempting a second click while running does not send a second POST
            bwd.click(force=True)
            page.wait_for_timeout(150)
            assert len(step_posts) == 1
            assert step_posts[0] == {"direction": "forward", "distance_m": 0.1}

            loc_state["mission"] = {"kind": "nudge_forward", "state": "done"}
            expect(fwd).to_be_enabled(timeout=3000)
            expect(bwd).to_be_enabled()
        finally:
            browser.close()
        assert errors == []


def test_step_nudge_shows_disabled_reason_when_reporting_is_off(site):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    r1 = _robot("rosy_01")
    r1["localization"] = None
    api = copy.deepcopy(API)
    api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 1, "total": 1}, "ts": 0.0, "robots": [r1]}

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="rosy_01"]').click()
            fwd = page.locator('[data-step-nudge="forward"]')
            bwd = page.locator('[data-step-nudge="backward"]')
            expect(fwd).to_be_disabled()
            expect(bwd).to_be_disabled()
            expect(page.locator(".step-nudge [data-cause]")).to_contain_text("위치 보고가 꺼져 있음")
        finally:
            browser.close()
        assert errors == []
