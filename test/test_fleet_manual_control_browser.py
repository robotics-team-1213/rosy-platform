"""Selected Fleet manual control: real pointer lifetime and terminal stop requests."""

import pytest

from browser_harness import browser_tests_enabled
from console_browser_site import console_url  # noqa: F401
from test_fleet_console_browser import MAP_GRID, _open_cards, _open_console, _robot

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium",
)


def _api():
    robots = [_robot(rid, {"x": 0, "y": 0, "yaw": 0}) for rid in ("rosy_45", "rosy_46")]
    for robot in robots:
        robot.update(state_age_s=0.05, capabilities={"teleop": True, "runtime": {"mode": "motor"}})
        robot["state"].update(mode="MANUAL", navigation="IDLE", velocity={"linear": 0, "angular": 0},
                              evidence={key: {"evidence": "fresh"} for key in ("pose", "velocity")})
    return {
        "/api/fleet/state": {"fleet": {"name": "site", "online": 2, "total": 2}, "robots": robots},
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }


@pytest.mark.parametrize("ending", ["release", "blur", "selection", "timeout", "keyboard", "cancel", "hidden", "pagehide"])
def test_selected_robot_hold_ends_with_zero(console_url, ending):
    from playwright.sync_api import expect, sync_playwright

    sent = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api())

        def move(route):
            sent.append(route.request.post_data_json)
            route.fulfill(status=200, json={"accepted": True})

        page.route("**/api/fleet/do", move)
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        button = page.locator('[data-manual-direction="forward"]')
        expect(button).to_be_enabled()
        button.hover()
        if ending == "keyboard":
            button.focus()
            page.keyboard.down("Space")
        else:
            page.mouse.down()
        page.wait_for_function("() => document.querySelector('[data-manual-direction=forward]').getAttribute('aria-pressed') === 'true'")
        page.wait_for_timeout(250)
        assert any(row == {"do": "move", "robot": "rosy_45", "linear": 0.03, "angular": 0} for row in sent)
        if ending == "release":
            page.mouse.up()
        elif ending == "blur":
            page.evaluate("window.dispatchEvent(new Event('blur'))")
        elif ending == "selection":
            page.locator("#robot-choice").select_option("rosy_46")
        elif ending == "keyboard":
            page.keyboard.up("Space")
        elif ending == "cancel":
            button.dispatch_event("pointercancel")
        elif ending == "hidden":
            page.evaluate("Object.defineProperty(document, 'hidden', {get: () => true}); document.dispatchEvent(new Event('visibilitychange'))")
        elif ending == "pagehide":
            page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
        else:
            page.wait_for_timeout(2100)
        expect(button).to_have_attribute("aria-pressed", "false")
        page.wait_for_timeout(250)
        assert sent[-1] == {"do": "move", "robot": "rosy_45", "linear": 0, "angular": 0}
        assert all(row["robot"] == "rosy_45" for row in sent)
        assert all(abs(row["linear"]) <= 0.03 and abs(row["angular"]) <= 0.10 for row in sent)
        page.mouse.up()
        assert not errors
        browser.close()


def test_rejected_zero_stays_visible_after_polling(console_url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api())

        def move(route):
            row = route.request.post_data_json
            route.fulfill(status=200, json={"accepted": bool(row["linear"] or row["angular"])})

        page.route("**/api/fleet/do", move)
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        button = page.locator('[data-manual-direction="forward"]')
        expect(button).to_be_enabled()
        button.hover()
        page.mouse.down()
        page.wait_for_timeout(250)
        page.mouse.up()
        page.wait_for_timeout(500)
        expect(page.locator("[data-manual-reason]")).to_contain_text("정지 명령 전달 실패")
        assert not errors
        browser.close()


def test_late_drive_response_is_followed_by_zero_for_original_robot(console_url):
    from playwright.sync_api import expect, sync_playwright

    held, sent = [], []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api())

        def move(route):
            row = route.request.post_data_json
            sent.append(row)
            if row["linear"]:
                held.append(route)
            else:
                route.fulfill(status=200, json={"accepted": True})

        page.route("**/api/fleet/do", move)
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        button = page.locator('[data-manual-direction="forward"]')
        expect(button).to_be_enabled()
        button.hover()
        page.mouse.down()
        page.wait_for_timeout(250)
        assert len(held) == 1
        page.locator("#robot-choice").select_option("rosy_46")
        page.wait_for_timeout(150)
        assert sent[-1]["robot"] == "rosy_45" and sent[-1]["linear"] == 0
        zeros = sum(row["linear"] == 0 for row in sent)
        held.pop().fulfill(status=200, json={"accepted": True})
        page.wait_for_timeout(250)
        assert sum(row["linear"] == 0 for row in sent) > zeros
        assert all(row["robot"] == "rosy_45" for row in sent)
        page.mouse.up()
        assert not errors
        browser.close()


def test_stale_or_stopped_robot_cannot_be_driven(console_url):
    from playwright.sync_api import expect, sync_playwright

    api = _api()
    api["/api/fleet/state"]["robots"][0]["state_age_s"] = 20
    api["/api/fleet/state"]["robots"][1]["state"]["safety"]["estop"] = True
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        button = page.locator('[data-manual-direction="forward"]')
        expect(button).to_be_disabled()
        expect(page.locator("[data-manual-reason]")).to_contain_text("오래")
        _open_cards(page, "rosy_46")
        expect(button).to_be_disabled()
        expect(page.locator("[data-manual-reason]")).to_contain_text("비상정지")
        assert not errors
        browser.close()
