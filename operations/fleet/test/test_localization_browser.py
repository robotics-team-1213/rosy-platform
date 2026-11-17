"""Real Chromium C19 localization tests (Item E): loc-1..loc-14, queue, confirm gate, viewer lock, revoked gate."""

import json
from pathlib import Path

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _robot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

LOC_FIXTURE = Path(__file__).resolve().parents[3] / "applications" / "fleet" / "dev" / "sample" / "fixtures" / "localization.json"


def _loc_robots():
    raw = json.loads(LOC_FIXTURE.read_text(encoding="utf-8"))
    return raw["robots"]


def test_viewer_sees_no_relocalize_and_candidate_is_never_drawn_as_pose(site):
    from playwright.sync_api import expect, sync_playwright

    loc4 = next(r for r in _loc_robots() if r["id"] == "loc-4")
    robot = _robot("loc-4")
    api = {
        **API,
        "/api/fleet/session": {"role": "viewer", "principal_id": "viewer-1", "authenticated": True},
        "/api/fleet/state": {**API["/api/fleet/state"], "robots": [robot]},
        "/api/fleet/auto-locate": {"robots": []},
        "/api/fleet/robots/loc-4/localization": {
            "localization": loc4["localization"],
            "candidates": loc4["candidates"],
            "ladder": loc4["ladder"],
            "motion_allowed": False,
            "last_operator_request": None,
        },
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            page.locator(".doc-tabs").get_by_role("link", name="작업", exact=True).click()
            row = page.locator("#roster .robot-row").filter(has_text="loc-4")
            expect(row).to_be_visible()
            expect(row.locator('[data-loc-action="relocalize"]')).to_have_count(0)
            expect(row.locator("[data-localization]")).not_to_contain_text("확정")
            row.locator("[data-select-robot-id]").click()
            expect(page.locator('#detail-localization [data-loc-action="relocalize"]')).to_have_count(0)
            assert not errors
        finally:
            browser.close()


def test_stale_candidate_refused_with_nothing_sent_to_confirm(site):
    from playwright.sync_api import expect, sync_playwright

    loc4 = next(r for r in _loc_robots() if r["id"] == "loc-4")
    robot = _robot("loc-4")
    confirm_posts = []
    reads = [0]
    api = {
        **API,
        "/api/fleet/state": {**API["/api/fleet/state"], "robots": [robot]},
        "/api/fleet/auto-locate": {"robots": []},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            def handle_loc(route):
                reads[0] += 1
                cands = dict(loc4["candidates"])
                if reads[0] > 1:
                    cands["request_id"] = "req-loc-4-newer"
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "localization": loc4["localization"],
                    "candidates": cands,
                    "ladder": loc4["ladder"],
                    "motion_allowed": False,
                    "last_operator_request": None,
                }))

            page.route("**/api/fleet/robots/loc-4/localization", handle_loc)
            page.route("**/api/fleet/robots/loc-4/localization/confirm", lambda route: (confirm_posts.append(1), route.fulfill(status=200, body="{}")))
            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="loc-4"]').click()
            btn = page.locator('#detail-localization [data-loc-confirm="0"]')
            expect(btn).to_be_visible()
            btn.click()
            expect(page.locator("#detail-localization")).to_contain_text("후보가 바뀌었습니다")
            assert confirm_posts == []
            assert not errors
        finally:
            browser.close()


def test_revoked_gate_shows_requester_and_offers_relocalize_without_auto_retry(site):
    from playwright.sync_api import expect, sync_playwright

    loc9 = next(r for r in _loc_robots() if r["id"] == "loc-9")
    robot = _robot("loc-9")
    reloc_posts = []
    api = {
        **API,
        "/api/fleet/state": {**API["/api/fleet/state"], "robots": [robot]},
        "/api/fleet/auto-locate": {"robots": []},
        "/api/fleet/robots/loc-9/localization": {
            "localization": loc9["localization"],
            "candidates": None,
            "ladder": loc9["ladder"],
            "motion_allowed": False,
            "last_operator_request": loc9["motion"]["last_operator_request"],
        },
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            page.route("**/api/fleet/robots/loc-9/relocalize", lambda route: (reloc_posts.append(1), route.fulfill(status=200, body="{}")))
            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="loc-9"]').click()
            detail = page.locator("#detail-localization")
            expect(detail).to_contain_text("회전 권한 닫힘")
            expect(detail.locator('[data-loc-action="relocalize"]')).to_be_visible()
            assert reloc_posts == []
            assert not errors
        finally:
            browser.close()
