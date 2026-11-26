"""A supervised job from the actual Calibration page, with a fake arm process."""
import pytest

from browser_harness import browser_tests_enabled, open_page
from test_calibration_jobs_api import cell, screen, web  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1")


def test_arm_route_panels_show_only_the_requested_slots_and_preserve_both_results(screen):
    from playwright.sync_api import expect, sync_playwright

    url, account, calls, jobs, _ = screen
    account.callback = url + "/api/account/callback"
    account.apps = lambda cookie: []
    pairs = {"arm_a": ["tmp-a-1-l1", "ship-h1r0-l0"], "arm_b": ["tmp-b-2-l1", "ship-h1r2-l0"]}
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, 1200, 800, url=url)
        try:
            page.context.add_cookies([{"name": web.SESSION_COOKIE, "value": "valid", "url": url}])
            arms = {arm: {"sites": {}, "route_sites": pair} for arm, pair in pairs.items()}
            arms["arm_s"] = {"sites": {"pinky": {"place_xy_m": [0.2, 0.03], "surface_z": 0.01}}}
            page.route("**/api/calibration/status", lambda r: r.fulfill(json={"arms": arms,
                "fleet_cell_console_url": "https://fleet.example/cell"}))
            sent = []

            def handle(route):
                if route.request.method == "GET":
                    return route.fulfill(json={"jobs": [{"id": "unrelated-check", "arm": "arm_s", "step": "check",
                        "targets": ["floor:0.1,0.2"], "status": "done", "result": {"check": {"camera_issue": "foreign-result"}}}]})
                body = route.request.post_data_json
                sent.append(body)
                arm = body["arm"]
                if arm == "arm_s":
                    return route.fulfill(status=202, json={"id": "s-check", "arm": arm, "step": "check", "supply_route": True, "status": "done",
                        "result": {"check": {"camera_shift": {"ok": True}}, "todo": []}})
                route.fulfill(status=202, json={"id": arm + "-test", "arm": arm, "step": "check", "route": pairs[arm],
                    "task_id": body.get("task_id"),
                    "route_config": arm + ".json", "status": "done", "result": {"todo": ["remap"] if arm == "arm_a" else [],
                        "check": {"route": {"calibration_evidence": {"sites": {"source": {"top_roi": [1, 2, 3, 4]},
                            "destination": {}}, "reference_current": arm == "arm_b", "next_machine_action": "measure_named_xy"}}}}})

            page.route("**/api/calibration/jobs", handle)
            page.goto(url + "/?arm=arm_b")
            expect(page.get_by_role("link", name="연결된 셀 작업")).to_have_attribute("href", "https://fleet.example/cell")
            supply = page.locator("#routePanels article").filter(has_text="S팔 경로 점검")
            expect(supply).to_contain_text("pinky → belt")
            expect(supply).not_to_contain_text("foreign-result")
            supply.get_by_text("경로 사전 점검", exact=True).click()
            expect(supply).to_contain_text("카메라 · 기준 영상 확인")
            assert sent.pop() == {"arm": "arm_s", "step": "check", "supply_route": True}
            for arm, name in (("arm_a", "A"), ("arm_b", "B")):
                panel = page.locator("#routePanels article").filter(has_text=name + "팔 경로 점검")
                expect(panel.get_by_label("출발칸")).to_have_value(pairs[arm][0])
                expect(panel.get_by_label("도착칸")).to_have_value(pairs[arm][1])
                panel.get_by_text("경로 사전 점검", exact=True).click()
                expect(panel).to_contain_text("칸 중심 XY 실측")
                expect(panel).to_contain_text(arm + "-test")
            expect(page.locator("#routePanels article").nth(1)).to_contain_text("카메라 XY 맵 재측정 필요")
            expect(page.locator("#routePanels article").last).not_to_contain_text("카메라 XY 맵 재측정 필요")
            assert sent == [{"arm": arm, "step": "check", "route": pair} for arm, pair in pairs.items()]
            arms["arm_b"]["route_sites"] = [*pairs["arm_b"], "tmp-b-1-l0"]
            pairs["arm_b"] = ["tmp-b-1-l0", "ship-h1r2-l0"]
            link = "?arm=arm_b&src_site=tmp-b-1-l0&dst_site=ship-h1r2-l0&task_id=fleet%3A17"
            page.goto(url + "/" + link + "#route-arm_b")
            b = page.locator("#route-arm_b")
            expect(b.get_by_label("출발칸")).to_have_value("tmp-b-1-l0")
            expect(b).to_contain_text("연결된 Fleet 작업 · fleet:17")
            expect(page.locator("#account-login")).to_have_attribute("href", "/api/account/login" + link)
            assert len(sent) == 2
            b.get_by_text("경로 사전 점검", exact=True).click()
            expect(b).to_contain_text("점검 근거 · arm_b.json · Fleet fleet:17")
            assert sent[-1] == {"arm": "arm_b", "step": "check", "route": pairs["arm_b"], "task_id": "fleet:17"}
            page.goto(url + "/?arm=arm_s&src_site=unknown&dst_site=belt#route-arm_s")
            expect(supply.locator("ui-button[type=submit]")).to_be_disabled()
            expect(supply).to_contain_text("점검할 수 없는 Fleet 경로 링크")
            assert len(sent) == 3
            assert not calls["spawn"]
        finally:
            browser.close()


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
            page.locator("#jobRemeasure").check()
            page.locator("#jobStart").focus()
            page.keyboard.press("Enter")
            expect(page.locator("#jobProgress")).to_contain_text("종료", timeout=10000)
            assert len(calls["spawn"]) == 1 and "--remeasure-map" in calls["spawn"][0][0]
            expect(page.locator("#jobRemeasure")).not_to_be_checked()
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


def test_a_post_eval_saves_and_offers_the_escalated_step(screen):
    """2026-11-26 user: a visit saves what it measured, and the named next step is one click from the form."""
    import json as _json

    from playwright.sync_api import expect, sync_playwright

    url, account, calls, jobs, _ = screen
    account.callback = url + "/api/account/callback"
    account.apps = lambda cookie: []
    spawn = jobs.spawn

    def post_eval(argv, cwd, env, log):
        proc = spawn(argv, cwd, env, log)
        log.write_text(_json.dumps({"verdict": "drift", "applied": [{"site": "floor"}],
                                    "escalated": ["pivot-near floor:0.1,-0.2"]}) + "\n", encoding="utf-8")
        return proc

    jobs.spawn = post_eval
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, 390, 844, url=url)
        try:
            page.context.add_cookies([{"name": web.SESSION_COOKIE, "value": "valid", "url": url}])
            page.goto(url + "/?arm=arm_b")
            page.locator("#jobStep").select_option("post-eval")
            page.locator("#jobVisitSite").select_option("floor")
            page.locator("#jobSwitch").check()
            page.locator("#jobStart").click()
            expect(page.locator("#jobFollow")).to_contain_text("편차 보정값 1개를 저장했습니다", timeout=10000)
            assert "--apply" in calls["spawn"][0][0]
            page.locator("#jobFollow ui-button").click()
            expect(page.locator("#jobStep")).to_have_value("pivot-near")
            expect(page.locator("#jobTargets")).to_have_value("floor:0.1,-0.2")
            expect(page.locator("#jobSwitch")).not_to_be_checked()
            assert len(calls["spawn"]) == 1  # filling the form starts nothing
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
