"""The Calibration screen's steps used together, as an operator walks them (2026-11-26).

check -> fill the suggested pivot-near -> a failed run shows why -> post-eval saves and names the next step ->
forced remap. One fake engine answers by argv; nothing moves. ROSY_FLOW_SHOTS=<dir> keeps a screenshot per step.
"""
import json
import os
from pathlib import Path

import pytest

from browser_harness import browser_tests_enabled, open_page
from test_calibration_jobs_api import FakeProc, cell, screen, web  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1")

ANSWERS = {  # argv marker -> (exit code, log)
    "check": (0, {"check": {"bias_coverage_gaps": [{"site": "floor", "suggested_pivot": [0.1, -0.2]}]}, "todo": []}),
    "pivot-near": (1, "remap stopped at goto above_pick for [0.1, -0.2]: contact in goto above_pick: shoulder_lift lag"),
    "cell_post_eval.py": (0, {"verdict": "drift", "applied": [{"site": "floor"}], "escalated": ["remap"]}),
    "remap": (0, {"done": [{"remap": {"max": 2.9, "mean": 1.7}}]}),
}


def answer(argv):
    if any(str(a).endswith("cell_post_eval.py") for a in argv):
        return ANSWERS["cell_post_eval.py"]
    only = argv[argv.index("--only") + 1] if "--only" in argv else "check"
    return ANSWERS[only]


@pytest.mark.parametrize("width", [390, 1280])
def test_an_operator_walks_check_pivot_post_eval_and_forced_remap(screen, width):
    from playwright.sync_api import expect, sync_playwright

    url, account, calls, jobs, _ = screen
    account.callback = url + "/api/account/callback"
    account.apps = lambda cookie: []
    shots = Path(os.environ["ROSY_FLOW_SHOTS"]) if os.environ.get("ROSY_FLOW_SHOTS") else None

    def spawn(argv, cwd, env, log):
        calls["spawn"].append((argv, cwd, env))
        code, out = answer(argv)
        log.write_text("session up\n" + (out if isinstance(out, str) else json.dumps(out)) + "\n", encoding="utf-8")
        proc = FakeProc.__new__(FakeProc)
        proc.code = code
        return proc

    jobs.spawn = spawn
    with sync_playwright() as pw:
        browser, page, _ = open_page(pw, width, 900, url=url)

        def shot(name):
            if shots:
                shots.mkdir(parents=True, exist_ok=True)
                page.locator("#jobForm").scroll_into_view_if_needed()
                page.screenshot(path=str(shots / f"{width}-{name}.png"), full_page=True)

        try:
            page.context.add_cookies([{"name": web.SESSION_COOKIE, "value": "valid", "url": url}])
            page.goto(url + "/?arm=arm_b")
            start, switch, follow = page.locator("#jobStart"), page.locator("#jobSwitch"), page.locator("#jobFollow")

            # 1. check: no switch needed, the gap becomes a button that only fills the form
            page.locator("#jobStep").select_option("check")
            start.click()
            expect(follow).to_contain_text("점검이 권하는 다음 작업", timeout=10000)
            shot("1-check")
            follow.locator("ui-button").click()
            expect(page.locator("#jobStep")).to_have_value("pivot-near")
            expect(page.locator("#jobTargets")).to_have_value("floor:0.1,-0.2")
            expect(switch).not_to_be_checked()
            start.click()
            assert len(calls["spawn"]) == 1  # a moving step waits for the switch

            # 2. the pivot-near fails: the reason is on the progress line and in the recent jobs table
            switch.check()
            start.click()
            expect(page.locator("#jobProgress")).to_contain_text("contact in goto above_pick", timeout=10000)
            expect(page.locator("#recentJobsWrap")).to_contain_text("실패 · remap stopped")
            argv = calls["spawn"][1][0]
            assert argv[argv.index("--only") + 1] == "pivot-near" and argv[argv.index("--targets") + 1] == "floor:0.1,-0.2"
            shot("2-failed")

            # 3. post-eval saves what it measured and offers the remap it escalated
            page.locator("#jobStep").select_option("post-eval")
            page.locator("#jobVisitSite").select_option("floor")
            switch.check()
            start.click()
            expect(follow).to_contain_text("편차 보정값 1개를 저장했습니다", timeout=10000)
            assert "--apply" in calls["spawn"][2][0]
            shot("3-post-eval")

            # 4. the offered remap, forced: the checkbox shows only for remap and resets after the start
            follow.locator("ui-button").click()
            expect(page.locator("#jobStep")).to_have_value("remap")
            expect(page.locator("#jobRemeasureLabel")).to_be_visible()
            page.locator("#jobRemeasure").check()
            switch.check()
            start.click()
            # the progress line still reads the post-eval's "종료" until the new job shows; wait for the remap row
            expect(page.locator("#recentJobsWrap tbody tr").first).to_contain_text("재매핑", timeout=10000)
            expect(page.locator("#jobProgress")).to_contain_text("종료", timeout=10000)
            assert "--remeasure-map" in calls["spawn"][3][0]
            expect(page.locator("#jobRemeasure")).not_to_be_checked()
            expect(follow).to_be_hidden()
            shot("4-remap")
            assert len(calls["spawn"]) == 4
            # nothing on the form leaves the page sideways at this width
            assert page.evaluate("document.documentElement.scrollWidth") <= width
        finally:
            browser.close()
