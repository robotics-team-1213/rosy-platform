"""Account authorization and Fleet login keep their own coherent identity."""
from urllib.parse import urlencode

import pytest

from browser_harness import browser_tests_enabled
from test_fleet_account_browser import account_backend, account_page  # noqa: F401


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


@pytest.mark.parametrize("width", [320, 1366])
@pytest.mark.parametrize("central", [False, True])
@pytest.mark.parametrize("text_scale", [1, 2, 4])
def test_login_identity_matches_heading_form_and_return_context(account_page, width, central, text_scale):
    from playwright.sync_api import expect

    page, origin = account_page
    page.set_viewport_size({"width": width, "height": 844})
    target = "/console?view=work&show=pending"
    if central:
        target = "/api/fleet/auth/authorize?" + urlencode({
            "response_type": "code", "client_id": "learning", "redirect_uri": "https://learning.test/callback",
            "scope": "project:one", "state": "test-state", "code_challenge": "x" * 43,
            "code_challenge_method": "S256"})
    page.goto(origin + "/console/login?" + urlencode({"return": target}))
    expect(page.locator("[data-login=login]")).to_be_visible()
    page.evaluate('(scale) => document.documentElement.style.fontSize = `${scale * 100}%`', text_scale)
    expect(page.locator("ui-brand b")).to_have_text("Rosy Account" if central else "Rosy Fleet")
    expect(page.locator("[data-login=form]")).to_have_attribute("aria-label", "Rosy Account 로그인" if central else "관제 로그인")
    if central:
        expect(page.locator("#login-intro")).to_have_text("Rosy Account로 로그인해 원래 앱의 작업을 이어가세요.")
        expect(page.locator("ui-brand small")).to_have_text("공용 계정")
    expect(page.locator("#login-back")).to_have_attribute("href", target)
    if central:
        expect(page.locator("#login-back")).to_be_hidden()
    else:
        expect(page.locator("#login-back")).to_be_visible()
    expect(page.locator("[data-login=login]")).to_have_attribute("autocomplete", "username")
    expect(page.locator("[data-login=password]")).to_have_attribute("autocomplete", "current-password")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
