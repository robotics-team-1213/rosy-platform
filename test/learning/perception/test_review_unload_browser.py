"""Object review warns before leaving while a save has not reached the server."""

import pytest

from browser_harness import browser_tests_enabled
from test_review_flow_browser import browser_workspace  # noqa: F401

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium",
)

LEAVE = """()=>{const event=new Event('beforeunload',{cancelable:true});
    window.dispatchEvent(event);return event.defaultPrevented;}"""


def test_failed_save_warns_on_leave_until_a_save_succeeds(browser_workspace):
    page, _store, expect = browser_workspace
    expect(page.locator("#status")).not_to_be_empty()
    assert not page.evaluate(LEAVE)

    def refuse(route):
        if route.request.method == "POST":
            route.fulfill(status=500, json={"detail": "down"})
        else:
            route.continue_()

    page.route("**/api/frames/*", refuse)
    page.evaluate("() => document.getElementById('exclude').click()")
    expect(page.locator("#save-status")).to_contain_text("저장 실패")
    assert page.evaluate(LEAVE)

    page.unroute("**/api/frames/*")
    page.evaluate("() => document.getElementById('exclude').click()")
    expect(page.locator("#save-status")).to_contain_text("서버 저장됨")
    assert not page.evaluate(LEAVE)
