"""Real Chromium mixed-work view over fixture APIs; never dispatches to devices."""

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _shot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
def test_channel_review_keeps_candidate_separate_from_execution(site, size):
    from playwright.sync_api import expect, sync_playwright

    request_id, digest = "a" * 24, "b" * 64
    path = f"/api/fleet/channel-requests/{request_id}/review"
    receipt = {"content": "<script>unsafe()</script> 이동 요청", "request_id": request_id,
               "content_hash": digest, "received_at": "2026-10-12T00:00:00+00:00"}
    review = {"request_id": request_id, "content_hash": digest, "revision": 0, "state": "REQUESTED",
              "candidate": None, "reason": None, "work_id": None, "work_kind": None, "work_status": None,
              "request_key": "discord-" + request_id}
    api = {**API, "/api/fleet/work": {"rows": [], "observed_at": receipt["received_at"],
           "tasks_available": True, "missions_available": True, "truncated_sources": []},
           "/api/fleet/channel-requests": {"rows": [receipt]}, path: review}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(2000)
            page.locator("#channel-requests ui-button").click()
            expect(page.locator("#channel-review")).to_be_visible()
            page.locator("#channel-review-reason").fill("목표 위치 확인 필요")

            def save(route):
                body = route.request.post_data_json
                posts.append((path, body))
                assert body["expected_hash"] == digest and body["expected_revision"] == review["revision"]
                review.update(state=body["state"], reason=body["reason"], candidate=body["candidate"],
                              revision=review["revision"] + 1)
                route.fulfill(json=review)

            page.route("**" + path, lambda route: save(route) if route.request.method == "PUT"
                       else route.fulfill(json=review))
            page.locator("#channel-review-hold").click()
            expect(page.locator("#channel-review-state")).to_contain_text("HOLD")
            assert review["candidate"] is None and posts[-1][1]["state"] == "HOLD"
            page.locator("#channel-review-robot").select_option("rosy_03")
            page.locator("#channel-review-x").fill("1.25")
            page.locator("#channel-review-y").fill("2.5")
            page.locator("#channel-review-ready").click()
            expect(page.locator("#channel-review-state")).to_contain_text("READY")
            assert review["candidate"] == {"robot_id": "rosy_03", "x": 1.25, "y": 2.5, "yaw": 0}
            assert all(item[0] == path for item in posts)
            submit = page.locator("#channel-review-submit")
            submit.click()
            page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
            assert all(item[0] == path for item in posts)

            def goal(route):
                assert route.request.headers["idempotency-key"] == review["request_key"]
                assert route.request.post_data_json == {"x": 1.25, "y": 2.5, "yaw": 0}
                posts.append(("goal", route.request.post_data_json))
                route.fulfill(json={"task": {"task_id": "task-one", "status": "QUEUED"}})

            def link(route):
                body = route.request.post_data_json
                assert body == {"task_id": "task-one", "expected_hash": digest, "expected_revision": 2}
                posts.append(("link", body))
                review.update(state="LINKED", work_id="task-one", work_kind="task", work_status="QUEUED", revision=3)
                route.fulfill(json=review)

            page.route("**/api/fleet/robots/rosy_03/goal", goal)
            page.route(f"**/api/fleet/channel-requests/{request_id}/task", link)
            submit.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator("#channel-review-state")).to_contain_text("LINKED")
            assert [item[0] for item in posts] == [path, path, "goal", "link"]
            expect(submit).not_to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            _shot(page, f"channel-review-{size[0]}.png", full_page=True)
            page.route("**/api/fleet/channel-requests", lambda route: route.fulfill(status=403, json={"detail": "revoked"}))
            page.locator("#work-refresh").click()
            expect(page.locator("#channel-review")).not_to_be_visible()
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_mixed_work_selection_filter_refresh_failure_and_accessibility(site, size, role):
    from playwright.sync_api import sync_playwright

    rows = [{"source": source, "source_id": "same", "action_kind": kind,
             "status": state, "device_id": device, "workcell_id": cell, "reason": None,
             "updated_at": "2026-10-11T12:00:00+00:00"}
            for source, kind, state, device, cell in (
                ("task", "navigate", "RUNNING", "rosy_01", None),
                ("mission", "PICK_PLACE", "ACTION_SUCCEEDED", "omx_control", "packing"))]
    api = {**API, "/api/fleet/session": {"principal_id": "bob", "role": role},
           "/api/fleet/work": {"rows": rows, "observed_at": "2026-10-11T12:00:01+00:00",
                               "tasks_available": True, "missions_available": True, "truncated_sources": []},
           "/api/fleet/tasks/same": {"task": {**rows[0], "source": "console", "task_id": "same"}, "history": []},
           "/api/fleet/missions/same": {"mission": rows[1], "history": []}}
    if role == "operator":
        api["/api/fleet/channel-requests"] = {"rows": [{"content": "<script>window.intakeXss=true</script>" + "x" * 1000,
            "received_at": "2026-10-12T00:00:00+00:00", "request_id": "request-1"}]}
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            page.goto(site + "/console?view=work")
            page.clock.run_for(2000)
            page.wait_for_function("() => document.querySelectorAll('#work-list ui-button').length === 2")
            assert page.locator("#work-overview").is_visible()
            assert not page.locator('[aria-labelledby="map-heading"]').is_visible()
            assert page.locator('.doc-tabs a[href="/console?view=work"]').get_attribute("aria-current") == "page"
            assert page.evaluate("() => document.querySelector('.console-context').compareDocumentPosition(document.querySelector('.queues-panel')) & Node.DOCUMENT_POSITION_FOLLOWING")
            if size[0] < 1024:
                assert page.locator("#work-overview").bounding_box()["y"] < page.locator(".console-context").bounding_box()["y"] < page.locator(".queues-panel").bounding_box()["y"]
            page.locator("#work-list ui-button").filter(has_text="팔 작업").click()
            assert page.locator("#work-detail").inner_text().find("packing") >= 0
            assert page.locator("#work-detail").inner_text().find("목표 확인 대기") >= 0
            page.locator("#work-filter").select_option("task")
            assert page.locator("#work-list ui-button").count() == 1
            page.locator("#work-list ui-button").click()
            assert "CORE" in page.locator("#work-detail").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if role == "operator":
                assert page.locator("#channel-requests").inner_text().find("<script>") >= 0
                assert page.evaluate("window.intakeXss === undefined")
                page.route("**/api/fleet/channel-requests", lambda route: route.fulfill(status=403, json={"detail": "revoked"}))
                page.locator("#work-refresh").click()
                page.wait_for_function("() => document.getElementById('channel-requests').childElementCount === 0")
                assert "기명 운영자" in page.locator("#channel-requests-state").inner_text()
            page.locator("#work-filter").select_option("all")
            _shot(page, f"mixed-work-{role}-{size[0]}.png", full_page=True)
            page.route("**/api/fleet/work", lambda route: route.fulfill(status=503, json={"detail": "offline"}))
            page.locator("#work-refresh").click()
            page.wait_for_function("() => document.getElementById('work-list').childElementCount === 0")
            assert "조회 실패" in page.locator("#work-state").inner_text()
            assert not posts and not errors
        finally:
            browser.close()
