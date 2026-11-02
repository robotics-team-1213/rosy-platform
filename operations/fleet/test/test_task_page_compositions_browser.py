"""Fleet task documents reuse shared geometry without losing safety or navigation."""
import re

import pytest

from browser_harness import browser_tests_enabled
from test_fleet_account_browser import account_backend, account_page, _credentials  # noqa: F401


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


@pytest.mark.parametrize("width", [320, 1366])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_fleet_task_documents_share_composition_and_keep_live_stop(account_page, width, theme):
    from playwright.sync_api import expect

    page, origin = account_page
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(origin + "/console/login")
    _credentials(page)
    page.locator("[data-login=submit]").click()
    expect(page.locator("#user-role")).to_have_attribute("title", "alice · operator")
    for target in ["/console/profile", "/console/accounts", "/console/install", "/console/site-map",
                   "/console/cell", "/console/policy", "/console/learning"]:
        page.goto(origin + target, wait_until="domcontentloaded")
        page.evaluate("theme => window.RosyTheme.set(theme)", theme)
        expect(page.locator("main")).to_have_class(re.compile(r"\bui-task-page\b"))
        expect(page.locator("h1")).to_have_count(1)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), target
        if page.locator("#estop").count():
            expect(page.locator("#estop")).to_be_visible()
        for link in page.locator("a.ui-action-link:visible").all():
            assert link.get_attribute("data-kind") in ("primary", "quiet"), target
            assert link.bounding_box()["height"] >= 48, (target, link.inner_text())
