"""D-908: known neutral trip proposal handoff over fixture APIs; no robot, lease or execution owner."""
import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
PATH = "/api/fleet/trip-proposals/trip-prop-example"
LINK = "/console?view=work&trip_proposal=trip-prop-example"


def fixture_api(actor="independent", role="operator"):
    proposal = {"proposal_id": "trip-prop-example", "proposal_principal_id": "application-proposer",
                "request_key": "harbor/move-1", "request_digest": "b" * 64, "proposal_digest": "a" * 64,
                "candidate_robot_ids": ["rosy_01"], "steps": [{"to": "B", "via": ["A"]}], "status": "PROPOSED",
                "dispatch_generation": None, "approved_by": None, "mission_id": None}
    api = {**API, "/api/fleet/session": {"principal_id": actor, "role": role}, PATH: {"proposal": proposal},
           "/api/fleet/dispatch-control": {"dispatch_enabled": True, "generation": 7},
           "/api/fleet/work": {"rows": [], "observed_at": "2026-10-28T00:00:00Z",
                               "tasks_available": True, "missions_available": True, "truncated_sources": []}}
    return api, proposal


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
def test_deep_link_reads_and_explicit_confirmation_admits_the_saved_proposal(site, size):
    from playwright.sync_api import expect, sync_playwright
    api, proposal = fixture_api()
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            page.goto(site + LINK)
            admit = page.locator("#trip-proposal-admit")
            expect(admit).to_be_visible()
            expect(admit).to_be_enabled()
            assert not posts
            expect(page.locator("#trip-proposal-work")).to_contain_text("rosy_01")
            admit.click()
            page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
            assert not posts

            def accept(route):
                body = route.request.post_data_json
                assert body == {"expected_proposal_digest": "a" * 64, "expected_generation": 7}
                posts.append((PATH + "/admit", body))
                proposal.update(status="ADMITTED", approved_by="independent", dispatch_generation=7, mission_id="m-1")
                route.fulfill(json={"proposal": proposal})
            page.route("**" + PATH + "/admit", accept)
            admit.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator("#trip-proposal-state")).to_contain_text("승인 응답")
            expect(admit).to_be_disabled()
            page.locator("#trip-proposal-read").click()
            expect(page.locator("#trip-proposal-state")).to_contain_text("작업 생성")
            assert len(posts) == 1 and not errors
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            browser.close()


@pytest.mark.parametrize("status", [403, 409, 503])
def test_rejection_and_unknown_response_require_read_without_automatic_retry(site, status):
    from playwright.sync_api import expect, sync_playwright
    api, _ = fixture_api()
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts,
                                      answers={PATH + "/admit": (status, {"detail": "rejected or unknown"})})
        try:
            page.goto(site + LINK)
            admit = page.locator("#trip-proposal-admit")
            expect(admit).to_be_enabled()
            admit.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator("#trip-proposal-state")).to_contain_text("자동 재전송하지 않았습니다")
            expect(admit).to_be_disabled()
            page.clock.run_for(4000)
            assert len(posts) == 1 and not errors
        finally:
            browser.close()


@pytest.mark.parametrize("actor,role", [("application-proposer", "operator"), ("independent", "viewer")])
def test_self_admission_or_viewer_is_read_only(site, actor, role):
    from playwright.sync_api import expect, sync_playwright
    api, _ = fixture_api(actor, role)
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts)
        try:
            page.goto(site + LINK)
            expect(page.locator("#trip-proposal-work")).to_contain_text("rosy_01")
            expect(page.locator("#trip-proposal-admit")).to_be_disabled()
            assert not posts and not errors
        finally:
            browser.close()
