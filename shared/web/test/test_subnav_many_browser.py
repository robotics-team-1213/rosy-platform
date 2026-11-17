"""Sub-navigation with many links: below 64rem seven or more links stay one scrolling row of real anchors; fewer wrap."""

import pytest
from browser_harness import browser_tests_enabled
from test_component_kit_browser import gallery  # noqa: F401  (served shared gallery fixture)

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


def test_many_links_are_one_scrolling_row_and_still_clickable(gallery):  # noqa: F811
    from playwright.sync_api import expect
    page = gallery
    nav = page.locator("#subnav-many-example .ui-subnav-nav")
    page.set_viewport_size({"width": 390, "height": 844})
    expect(nav).to_have_attribute("data-many", "")
    assert nav.evaluate("n => getComputedStyle(n).flexWrap === 'nowrap' && getComputedStyle(n).overflowX === 'auto'")
    tops = nav.locator("a").evaluate_all("nodes => new Set(nodes.map(n => Math.round(n.getBoundingClientRect().top))).size")
    assert tops == 1, "all links share one row"
    nav.locator("a").nth(7).click()  # Playwright scrolls the last link into view and clicks it
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
