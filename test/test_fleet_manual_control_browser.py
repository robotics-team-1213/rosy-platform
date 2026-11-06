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
        "/api/fleet/dispatch-control": {"dispatch_enabled": True, "generation": 7,
                                        "queued_tasks": 0, "unresolved_actions": 0},
    }


def test_viewer_manual_controls_stay_locked_and_send_no_move(console_url):
    from playwright.sync_api import expect, sync_playwright

    api, sent = _api(), []
    api["/api/fleet/session"] = {"principal_id": "test-viewer", "role": "viewer"}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        try:
            def move(route):
                sent.append(route.request.post_data_json)
                route.fulfill(status=403, json={"detail": "operator required"})

            page.route("**/api/fleet/do", move)
            page.goto(console_url, wait_until="load")
            expect(page.locator("#user-role")).to_contain_text("보기 전용")
            _open_cards(page, "rosy_45")
            page.wait_for_timeout(250)
            controls = page.locator("[data-manual-direction]")
            expect(controls).to_have_count(4)
            for button in controls.all():
                expect(button).to_be_disabled()
                expect(button).to_have_attribute("reason", "위 사유")
            expect(page.locator("[data-manual-reason]")).to_contain_text("운영자 권한이 필요합니다")
            button = page.locator('[data-manual-direction="forward"]')
            button.hover()
            page.mouse.down()
            page.wait_for_timeout(250)
            page.mouse.up()
            page.keyboard.press("Tab")
            for control in controls.all():
                expect(control).not_to_be_focused()
            page.keyboard.down("Space")
            page.wait_for_timeout(250)
            page.keyboard.up("Space")
            expect(button).to_have_attribute("aria-pressed", "false")
            assert sent == []
            assert not errors
        finally:
            browser.close()


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


def test_manual_mode_is_confirmed_for_one_robot_and_waits_for_readback(console_url):
    from playwright.sync_api import expect, sync_playwright

    api, sent = _api(), []
    api["/api/fleet/state"]["robots"][0]["state"]["mode"] = "IDLE"
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        def request(route):
            sent.append(route.request.post_data_json)
            route.fulfill(status=200, json={"accepted": True})
        page.route("**/api/fleet/do", request)
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        switch = page.locator('[data-manual-mode]')
        expect(switch).to_be_enabled()
        switch.click()
        assert sent == []
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
        page.wait_for_timeout(150)
        assert sent == [{"do": "manual", "robot": "rosy_45"}]
        expect(page.locator('[data-manual-direction=forward]')).to_be_disabled()
        api["/api/fleet/state"]["robots"][0]["state"]["mode"] = "MANUAL"
        expect(page.locator('[data-manual-direction=forward]')).to_be_enabled()
        assert not errors
        browser.close()


@pytest.mark.parametrize("changed", ["selection", "generation", "stale", "estop"])
def test_manual_confirmation_rechecks_target_and_safety(console_url, changed):
    from playwright.sync_api import expect, sync_playwright

    api, sent = _api(), []
    api["/api/fleet/state"]["robots"][0]["state"]["mode"] = "IDLE"
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.route("**/api/fleet/do", lambda route: (sent.append(route.request.post_data_json),
                   route.fulfill(status=200, json={"accepted": True})))
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        page.locator('[data-manual-mode]').click()
        dialog = page.locator('dialog.ui-confirm')
        expect(dialog).to_have_count(1)
        if changed == "selection":
            page.locator('#robot-choice').select_option('rosy_46')
            expect(dialog).to_have_count(0)
        else:
            if changed == "generation":
                api['/api/fleet/dispatch-control']['generation'] = 8
                page.wait_for_function('document.querySelector("#dispatch-control-detail").textContent.includes("8")')
            elif changed == "stale":
                api['/api/fleet/state']['robots'][0]['state_age_s'] = 20
                expect(page.locator('[data-manual-mode]')).to_be_disabled()
            else:
                api['/api/fleet/state']['robots'][0]['state']['safety']['estop'] = True
                expect(page.locator('[data-manual-mode]')).to_be_disabled()
            dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_timeout(150)
        assert sent == []
        assert not errors
        browser.close()


@pytest.mark.parametrize("changed", ["closed", "generation"])
def test_dispatch_change_stops_hold_with_terminal_zero(console_url, changed):
    from playwright.sync_api import expect, sync_playwright

    api, sent = _api(), []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.route("**/api/fleet/do", lambda route: (sent.append(route.request.post_data_json),
                   route.fulfill(status=200, json={"accepted": True})))
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        button = page.locator('[data-manual-direction=forward]')
        expect(button).to_be_enabled()
        button.hover()
        page.mouse.down()
        page.wait_for_timeout(250)
        if changed == "closed":
            api['/api/fleet/dispatch-control']['dispatch_enabled'] = False
            expect(button).to_be_disabled()
        else:
            api['/api/fleet/dispatch-control']['generation'] = 8
            page.wait_for_function('document.querySelector("#dispatch-control-detail").textContent.includes("8")')
        page.wait_for_timeout(150)
        assert sent[-1] == {"do": "move", "robot": "rosy_45", "linear": 0, "angular": 0}
        count = len(sent)
        page.wait_for_timeout(250)
        assert len(sent) == count
        assert not errors
        page.mouse.up()
        browser.close()


def test_panel_separates_missing_from_old_and_names_the_stale_evidence(console_url):
    from playwright.sync_api import expect, sync_playwright

    api = _api()
    robots = api["/api/fleet/state"]["robots"]
    del robots[0]["state_age_s"]
    robots[1]["state"]["evidence"]["pose"] = {"evidence": "delayed"}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        reason = page.locator("[data-manual-reason]")
        expect(reason).to_contain_text("시각을 받지 못했습니다")
        _open_cards(page, "rosy_46")
        expect(reason).to_contain_text("위치 지연 · 최신 관측을 기다립니다")
        expect(page.locator("[data-manual-pose]")).to_contain_text("위치 관측 지연")
        expect(page.locator('[data-manual-direction="forward"]')).to_have_attribute("reason", "위 사유")
        assert not errors
        browser.close()


def test_two_second_limit_says_why_and_the_pad_is_a_first_screen_square(console_url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _api())
        page.set_viewport_size({"width": 1366, "height": 768})
        page.goto(console_url, wait_until="load")
        _open_cards(page, "rosy_45")
        forward = page.locator('[data-manual-direction="forward"]')
        expect(forward).to_be_enabled()
        expect(page.locator("[data-manual-pose]")).to_contain_text("위치 관측 최신")
        rects = page.locator("[data-manual-direction]").evaluate_all("nodes => nodes.map(n => n.getBoundingClientRect().toJSON())")
        assert {round(rect["width"]) for rect in rects} == {round(rects[0]["width"])}, rects
        assert len({round(rect["y"]) for rect in rects}) == 2, rects  # 2×2, never 3+1
        assert max(rect["bottom"] for rect in rects) <= 768, rects
        forward.hover()
        page.mouse.down()
        expect(page.locator("[data-manual-reason]")).to_contain_text("2초 한도로 멈췄습니다", timeout=5000)
        page.mouse.up()
        assert not errors
        browser.close()
