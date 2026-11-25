"""A supervised job from the actual Calibration page, with a fake arm process."""
import pytest

from browser_harness import browser_tests_enabled, open_page
from test_calibration_jobs_api import cell, screen, web  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1")


def test_operator_starts_job_and_recovers_its_result_after_reload(screen):
    from playwright.sync_api import expect, sync_playwright

    url, account, calls, jobs, _ = screen
    account.callback = url + "/api/account/callback"
    account.apps = lambda cookie: []
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, 390, 844, url=url)
        try:
            page.context.add_cookies([{"name": web.SESSION_COOKIE, "value": "valid", "url": url}])
            page.goto(url + "/?arm=arm_b")
            expect(page.locator("#jobArm")).to_have_value("arm_b")
            assert page.locator("#jobForm").evaluate(
                "form => [...form.querySelectorAll('select, ui-button')].filter(el => el.checkVisibility())"
                ".every(el => el.getBoundingClientRect().left >= 0 && el.getBoundingClientRect().right <= innerWidth)"
            )
            page.locator("#jobStep").select_option("remap")
            page.locator("#jobStart").focus()
            page.keyboard.press("Enter")
            assert not calls["spawn"]
            page.locator("#jobSwitch").check()
            page.locator("#jobStart").focus()
            page.keyboard.press("Enter")
            expect(page.locator("#jobProgress")).to_contain_text("종료", timeout=10000)
            assert len(calls["spawn"]) == 1
            progress = page.locator("#jobProgress").inner_text()
            assert "arm_b" in progress and " · " in progress
            expect(page.locator("#recentJobsWrap")).to_contain_text("종료")
            expect(page.locator("#jobSwitch")).not_to_be_checked()
            page.reload()
            expect(page.locator("#jobProgress")).to_have_text(progress)
            page.locator("#jobDetail summary").click()
            expect(page.locator("#jobOutput")).to_contain_text('"ok": true')
            jobs.lease().claim("arm_b", "other-job", "calibration", 60)
            with page.expect_response(lambda r: r.url.endswith("/api/calibration/jobs") and r.request.method == "POST") as refusal:
                page.locator("#jobStart").click()
            assert refusal.value.status == 409
            expect(page.locator("#jobActionNote")).to_contain_text("other-job")
            page.route("**/api/calibration/status", lambda route: route.fulfill(status=503, json={"error": "offline"}))
            page.locator("#btnReloadSnapshot").click()
            expect(page.locator("#jobStatusBody")).to_be_hidden()
            page.unroute("**/api/calibration/status")
            page.locator("#btnReloadSnapshot").click()
            expect(page.locator("#jobStatusBody")).to_be_visible()
            expect(page.locator("#jobActionNote")).to_contain_text("other-job")
            account.operate = False
            page.reload()
            expect(page.locator("#jobProgress")).to_have_text(progress)
            expect(page.locator("#jobForm")).to_be_hidden()
            account.operate = True
            page.goto(url + "/?arm=arm_s")
            expect(page.locator("#jobStart")).to_be_disabled()
            expect(page.locator("#jobArm")).to_have_value("")
        finally:
            browser.close()


def test_named_surface_requires_fresh_switch_and_clear_sweep_acknowledgement(screen):
    from playwright.sync_api import expect, sync_playwright

    url, account, calls, _, _ = screen
    account.callback = url + "/api/account/callback"
    account.apps = lambda cookie: []
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, 390, 844, url=url)
        try:
            page.context.add_cookies([{"name": web.SESSION_COOKIE, "value": "valid", "url": url}])
            page.goto(url + "/?arm=arm_b")
            page.locator("#jobStep").select_option("surface")
            page.locator("#jobSwitch").check()
            page.locator("#jobStart").click()
            assert not calls["spawn"]
            page.locator("#jobSurface").select_option("floor")
            expect(page.locator("#jobSwitch")).not_to_be_checked()
            expect(page.locator("#jobSwitchLabel")).to_contain_text("이동 경로")
            assert page.locator("#jobSurface option[value=belt]").count() == 0
            page.locator("#jobStart").click()
            assert not calls["spawn"]
            page.locator("#jobSwitch").check()
            with page.expect_response(lambda r: r.url.endswith("/api/calibration/jobs") and r.request.method == "POST") as reply:
                page.locator("#jobStart").click()
            assert reply.value.status == 202
            assert reply.value.request.post_data_json == {"arm": "arm_b", "step": "surface", "site": "floor",
                                                          "person_at_switch": True, "surface_clear": True}
            assert "--remeasure-surface" in calls["spawn"][0][0]
        finally:
            browser.close()
