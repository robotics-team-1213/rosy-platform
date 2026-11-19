"""D-1005: the Fleet manual pad drives at the robot's own manual limit and lets an operator raise or lower it."""

import pytest

from browser_harness import browser_tests_enabled
from console_browser_site import console_url  # noqa: F401
from test_fleet_console_browser import _open_cards, _open_console
from test_fleet_manual_control_browser import _api

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium",
)

LIMITS = {"manual_linear": 0.12, "manual_angular": 0.5, "set_linear": 0.12, "set_angular": 0.5,
          "approved_linear": None, "approved_angular": None, "max_linear": 0.2, "max_angular": 0.8}


def _api_with(limits):
    api = _api()
    for robot in api["/api/fleet/state"]["robots"]:
        robot["state"]["speed_limits"] = dict(limits)
    return api


def test_the_pad_sends_the_robots_live_limit_and_says_it(console_url):
    from playwright.sync_api import expect, sync_playwright

    sent = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api_with(LIMITS))
        page.route("**/api/fleet/do", lambda route: (sent.append(route.request.post_data_json), route.fulfill(json={"accepted": True})))
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        expect(page.locator("[data-manual-reason]")).to_contain_text("전후진 0.12m/s · 회전 0.5rad/s")
        page.locator('[data-manual-direction="backward"]').hover()
        page.mouse.down()
        page.wait_for_timeout(300)
        page.mouse.up()
        page.wait_for_timeout(250)
        assert any(row["linear"] == -0.12 and row["angular"] == 0 for row in sent), sent
        page.locator('[data-manual-direction="left"]').hover()
        page.mouse.down()
        page.wait_for_timeout(300)
        page.mouse.up()
        page.wait_for_timeout(250)
        assert any(row["linear"] == 0 and row["angular"] == 0.5 for row in sent), sent
        assert sent[-1] == {"do": "move", "robot": "rosy_45", "linear": 0, "angular": 0}
        assert not errors
        browser.close()


def test_a_sealed_measured_speed_is_what_the_pad_shows_and_sends(console_url):
    from playwright.sync_api import expect, sync_playwright

    limits = {**LIMITS, "manual_linear": 0.02, "manual_angular": 0.07, "approved_linear": 0.02, "approved_angular": 0.07}
    sent = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api_with(limits))
        page.route("**/api/fleet/do", lambda route: (sent.append(route.request.post_data_json), route.fulfill(json={"accepted": True})))
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        expect(page.locator("[data-manual-reason]")).to_contain_text("측정 봉인 0.02·0.07로 제한")
        page.locator('[data-manual-direction="forward"]').hover()
        page.mouse.down()
        page.wait_for_timeout(300)
        page.mouse.up()
        page.wait_for_timeout(250)
        assert any(row["linear"] == 0.02 for row in sent) and all(abs(row["linear"]) <= 0.02 for row in sent), sent
        browser.close()


def test_an_operator_raises_and_lowers_the_manual_speed_in_steps(console_url):
    from playwright.sync_api import expect, sync_playwright

    puts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api_with(LIMITS))

        def speed(route):
            puts.append(route.request.post_data_json)
            route.fulfill(json={"robot_id": "rosy_45", "limits": {}})

        page.route("**/api/fleet/robots/rosy_45/speed-limits", speed)
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        faster = page.locator('[data-manual-speed="faster"]')
        expect(faster).to_be_enabled()
        faster.click()
        expect(faster).to_be_enabled()
        page.locator('[data-manual-speed="slower"]').click()
        page.wait_for_timeout(200)
        assert puts == [{"manual_linear": 0.13, "manual_angular": 0.55},
                        {"manual_linear": 0.11, "manual_angular": 0.45}], puts
        assert not errors
        browser.close()


def test_the_pad_cannot_raise_past_the_signed_ceiling(console_url):
    from playwright.sync_api import expect, sync_playwright

    top = {**LIMITS, "manual_linear": 0.2, "set_linear": 0.2, "manual_angular": 0.8, "set_angular": 0.8}
    puts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api_with(top))
        page.route("**/api/fleet/robots/rosy_45/speed-limits",
                   lambda route: (puts.append(route.request.post_data_json), route.fulfill(json={"limits": {}})))
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        expect(page.locator('[data-manual-speed="faster"]')).to_be_enabled()
        page.locator('[data-manual-speed="faster"]').click()
        page.wait_for_timeout(200)
        assert puts == [{"manual_linear": 0.2, "manual_angular": 0.8}], puts
        browser.close()


def test_a_robot_that_reports_no_limit_keeps_the_old_pad_speed_and_has_no_speed_control(console_url):
    from playwright.sync_api import expect, sync_playwright

    sent = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api())
        page.route("**/api/fleet/do", lambda route: (sent.append(route.request.post_data_json), route.fulfill(json={"accepted": True})))
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        expect(page.locator("[data-manual-reason]")).to_contain_text("전후진 0.03m/s · 회전 0.1rad/s")
        expect(page.locator('[data-manual-speed="faster"]')).to_be_disabled()
        browser.close()
