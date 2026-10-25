"""Known neutral ARM handoff over fixture APIs; no device or execution owner."""
import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, _shot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
PATH = "/api/fleet/arm-transfers/jobs/arm-example"


def fixture_api(actor="independent", role="operator"):
    job = {"mission_id": "arm-example", "action_kind": "ARM_TRANSFER", "status": "PROPOSED",
           "proposal_principal_id": "application-proposer", "proposal_digest": "a" * 64,
           "dispatch_generation": None, "approved_by": None, "reason": None,
           "transfer": {"workcell_id": "cell", "instance_id": "arm", "object_ref": "object-1",
                        "source": "source-1", "target": "target-1"}}
    api = {**API, "/api/fleet/session": {"principal_id": actor, "role": role}, PATH: {"job": job},
           "/api/fleet/dispatch-control": {"dispatch_enabled": True, "generation": 7},
           "/api/fleet/work": {"rows": [], "observed_at": "2026-10-25T00:00:00Z",
                               "tasks_available": True, "missions_available": True, "truncated_sources": []}}
    return api, job


@pytest.mark.parametrize("size", [(1366, 768), (320, 568)])
def test_deep_link_reads_and_explicit_confirmation_admits_saved_contract(site, size):
    from playwright.sync_api import expect, sync_playwright
    api, job = fixture_api()
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            page.goto(site + "/console?view=work&arm_transfer=arm-example")
            admit = page.locator("#arm-transfer-admit")
            expect(admit).to_be_enabled()
            assert not posts
            expect(page.locator("#arm-transfer-work")).to_contain_text("object-1")
            admit.click()
            page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
            assert not posts

            def accept(route):
                body = route.request.post_data_json
                assert body == {"expected_proposal_digest": "a" * 64, "expected_generation": 7}
                posts.append((PATH + "/admit", body))
                job.update(status="READY", approved_by="independent", dispatch_generation=7)
                route.fulfill(json={"job": job})
            page.route("**" + PATH + "/admit", accept)
            admit.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator("#arm-transfer-state")).to_contain_text("승인 응답")
            expect(admit).to_be_disabled()
            assert len(posts) == 1
            page.locator("#arm-transfer-read").click()
            expect(page.locator("#arm-transfer-state")).to_contain_text("실행 준비")
            assert len(posts) == 1 and not errors
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            _shot(page, "arm-transfer-handoff", size[0])
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
            page.goto(site + "/console?view=work&arm_transfer=arm-example")
            admit = page.locator("#arm-transfer-admit")
            expect(admit).to_be_enabled()
            admit.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(page.locator("#arm-transfer-state")).to_contain_text("자동 재전송하지 않았습니다")
            expect(admit).to_be_disabled()
            page.clock.run_for(4000)
            assert len(posts) == 1 and not errors
            api["/api/fleet/dispatch-control"]["generation"] = 8
            page.locator("#arm-transfer-read").click()
            expect(admit).to_be_enabled()
            expect(page.locator("#arm-transfer-work")).to_contain_text("8")
            assert len(posts) == 1
        finally:
            browser.close()


@pytest.mark.parametrize("actor,role", [("application-proposer", "operator"), ("independent", "viewer")])
def test_self_approval_or_viewer_is_read_only(site, actor, role):
    from playwright.sync_api import expect, sync_playwright
    api, _ = fixture_api(actor, role)
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts)
        try:
            page.goto(site + "/console?view=work&arm_transfer=arm-example")
            expect(page.locator("#arm-transfer-work")).to_contain_text("object-1")
            expect(page.locator("#arm-transfer-admit")).to_be_disabled()
            assert not posts and not errors
        finally:
            browser.close()
