"""The Calibration header fits its navigation and Account controls at narrow widths."""
import pytest

from browser_harness import browser_tests_enabled, open_page
from test_calibration_web import account_screen, store  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1")


@pytest.mark.parametrize("width", [320, 390, 1440])
@pytest.mark.parametrize("signed_in", [False, True])
def test_calibration_header_controls_do_not_overlap(account_screen, width, signed_in):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    url, _ = account_screen
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, width, 900)
        try:
            if signed_in:
                page.route("**/api/account/session", lambda route: route.fulfill(json={
                    "enabled": True,
                    "authenticated": True,
                    "can_operate": True,
                    "account_id": "test-operator",
                    "profile": {
                        "account_id": "test-operator",
                        "display_name": "CalibrationOperatorWithALongDisplayName",
                    },
                    "profile_url": "https://account.test/console/profile",
                }))
            page.goto(url)
            if signed_in:
                expect(page.locator("[data-account-profile]")).to_be_visible()
                expect(page.locator("#account-logout")).to_be_visible()
            else:
                expect(page.locator("#account-login")).to_be_visible()
            expect(page.get_by_role("tab")).to_have_count(2)
            problems = page.evaluate("""() => {
              const header = document.querySelector('ui-topbar');
              const controls = [...header.querySelectorAll(
                'ui-brand, .cal-tabs > ui-button, #btnTheme, #mode-tag, #account-login, [data-account-profile], #account-logout'
              )].filter(node => node.getClientRects().length > 0);
              const bounds = controls.map(node => {
                const box = node.getBoundingClientRect();
                const range = document.createRange();
                range.selectNodeContents(node);
                const text = range.getBoundingClientRect();
                return { name: node.id || node.tagName,
                  left: Math.min(box.left, text.left), right: Math.max(box.right, text.right),
                  top: Math.min(box.top, text.top), bottom: Math.max(box.bottom, text.bottom) };
              });
              const failures = [];
              for (const [i, box] of bounds.entries()) {
                if (box.left < -1 || box.right > innerWidth + 1) failures.push(box.name + ' out of viewport');
                for (const other of bounds.slice(i + 1)) {
                  if (Math.min(box.right, other.right) - Math.max(box.left, other.left) > 1
                    && Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top) > 1) {
                    failures.push(box.name + ' overlaps ' + other.name);
                  }
                }
              }
              if (document.documentElement.scrollWidth > innerWidth + 1) failures.push('horizontal overflow');
              return failures;
            }""")
            assert not problems
            assert not errors
        finally:
            browser.close()
