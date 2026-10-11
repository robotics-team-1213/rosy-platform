"""Real Chromium mixed-work view over fixture APIs; never dispatches to devices."""

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _shot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


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
           "/api/fleet/tasks/same": {"task": rows[0], "history": []},
           "/api/fleet/missions/same": {"mission": rows[1], "history": []}}
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
            page.locator("#work-list ui-button").filter(has_text="팔 작업").click()
            assert page.locator("#work-detail").inner_text().find("packing") >= 0
            assert page.locator("#work-detail").inner_text().find("목표 확인 대기") >= 0
            page.locator("#work-filter").select_option("task")
            assert page.locator("#work-list ui-button").count() == 1
            page.locator("#work-list ui-button").click()
            assert "CORE" in page.locator("#work-detail").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#work-filter").select_option("all")
            _shot(page, f"mixed-work-{role}-{size[0]}.png", full_page=True)
            page.route("**/api/fleet/work", lambda route: route.fulfill(status=503, json={"detail": "offline"}))
            page.locator("#work-refresh").click()
            page.wait_for_function("() => document.getElementById('work-list').childElementCount === 0")
            assert "조회 실패" in page.locator("#work-state").inner_text()
            assert not posts and not errors
        finally:
            browser.close()
