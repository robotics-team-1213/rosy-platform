"""Synthetic UI fixture; real Chromium checks local approval and uncertain results."""

import json
import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _shot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_control_unit_approval_uses_current_revision_and_stale_read_blocks_actions(site, size, theme, tmp_path, monkeypatch):
    from playwright.sync_api import expect, sync_playwright
    reply = {"unit_id": "A1", "config_revision": "v1", "stale": False, "delegation": {
        "origin_id": "R", "delegation_id": "job-1", "request": {"target_unit": "A1", "robot_id": "a1",
        "goal": {"x": 1.0, "y": 2.0, "yaw": 0.0}}, "owner_unit": "A1", "status": "PENDING",
        "revision": 7, "local_actor": None, "local_task_id": None, "cancel_requested": False,
        "updated_at": "2026-10-23T00:00:00Z", "result": {}}}
    prefix = "/api/fleet/control-unit"
    api = {**API, prefix: {"unit_id": "A1", "config_revision": "v1", "parent": "A",
                           "children": [], "resources": ["robot:a1"]},
           prefix + "/delegations": {"delegations": [reply]},
           "/api/fleet/work": {"rows": [], "kinds": [], "observed_at": "2026-10-23T00:00:00Z",
                               "tasks_available": True, "missions_available": False, "truncated_sources": []}}
    with sync_playwright() as playwright:
        monkeypatch.setenv("ROSY_SHOT_DIR", str(tmp_path))
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size,
            answers={prefix + "/delegations/R/job-1/approve": (200, reply)})
        try:
            page.goto(site + "/console?view=work")
            page.evaluate("theme => window.RosyTheme.set(theme)", theme)
            page.clock.run_for(2000)
            panel = page.locator("#control-unit-work")
            expect(panel).to_be_visible()
            expect(panel).to_contain_text("상위 관제 A")
            expect(panel).to_contain_text("목표 X 1 m · Y 2 m · 방향 0 rad")
            expect(panel).to_contain_text("위임 R / job-1")
            _shot(page, f"control-unit-fresh-{size[0]}-{theme}.png", full_page=True)
            approve = panel.get_by_role("button", name="이 관제에서 승인", exact=True)
            expect(approve).to_be_enabled()
            approve.focus()
            page.locator("#work-refresh").evaluate("node => node.click()")
            page.clock.run_for(1500)
            expect(panel.get_by_role("button", name="이 관제에서 승인", exact=True)).to_be_focused()
            approve.click()
            assert posts[-1][0] == prefix + "/delegations/R/job-1/approve"
            assert json.loads(posts[-1][1]) == {"expected_revision": 7}
            reply["stale"] = True
            page.locator("#work-refresh").click()
            page.clock.run_for(1500)
            approve = panel.get_by_role("button", name="이 관제에서 승인", exact=True)
            expect(approve).to_be_disabled()
            expect(panel).to_contain_text("소유 관제 연결을 확인하세요")
            expect(panel).to_contain_text("실제 정지 확인과 별개")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            _shot(page, f"control-unit-stale-{size[0]}-{theme}.png", full_page=True)
            print("CONTROL_UNIT_SHOTS=" + str(tmp_path))
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("outcome", ["unknown", "rejected"])
def test_unknown_submission_keeps_its_body_and_identity_across_reload(site, outcome):
    from playwright.sync_api import expect, sync_playwright
    prefix = "/api/fleet/control-unit"
    api = {**API, prefix: {"unit_id": "R", "config_revision": "v1", "parent": None,
                          "children": ["A"], "resources": []}, prefix + "/delegations": {"delegations": []},
           "/api/fleet/work": {"rows": [], "kinds": [], "observed_at": "2026-10-23T00:00:00Z",
                               "tasks_available": True, "missions_available": False, "truncated_sources": []}}
    with sync_playwright() as playwright:
        posts = []
        refusal = (409, {"detail": {"code": "CONTROL_UNIT_RESOURCE_OUTSIDE_SCOPE"}})
        browser, page, errors = _open(playwright, site, api, posts,
            answers={prefix + "/delegations": refusal if outcome == "rejected" else
                     (503, {"detail": {"code": "UNAVAILABLE"}})})
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(1500)
            page.locator("#control-unit-work summary").click()
            page.locator("#control-unit-target_unit").fill("A")
            page.locator("#control-unit-robot_id").fill("a")
            page.locator("#control-unit-x").fill("1")
            page.locator("#control-unit-y").fill("2")
            page.locator("#control-unit-yaw").fill("0")
            send = page.get_by_text("대상 관제에 요청", exact=True)
            send.click()
            expect(page.locator("#control-unit-work")).to_contain_text("접수 전에 거절" if outcome == "rejected" else "요청 결과 미확인")
            first = posts[-1]
            if outcome == "rejected":
                fresh = page.get_by_role("button", name="새 요청 작성", exact=True)
                expect(fresh).to_be_enabled()
                fresh.click()
                expect(page.locator("#control-unit-target_unit")).to_be_editable()
                assert len(posts) == 1
                return
            page.reload()
            page.clock.run_for(1500)
            page.locator("#control-unit-work summary").click()
            expect(page.locator("#control-unit-target_unit")).to_have_value("A")
            expect(page.locator("#control-unit-x")).to_have_value("1")
            expect(page.get_by_role("button", name="새 요청 작성", exact=True)).to_be_disabled()
            page.get_by_text("대상 관제에 요청", exact=True).click()
            expect(page.locator("#control-unit-work")).to_contain_text("요청 결과 미확인")
            assert posts[-1] == first
            assert not errors
        finally:
            browser.close()
