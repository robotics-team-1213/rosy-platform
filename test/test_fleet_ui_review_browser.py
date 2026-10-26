"""Screen-review regressions: reachable mobile status and readable critical text."""
import re

import pytest

from browser_harness import browser_tests_enabled
from console_browser_site import console_url  # noqa: F401
from test_console_palette import contrast
from test_fleet_console_browser import MAP_GRID, SNAPSHOT, _open_console

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


@pytest.mark.parametrize("width", [320, 390])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_mobile_robot_status_precedes_map_and_critical_text_is_readable(console_url, width, theme):
    from playwright.sync_api import sync_playwright

    api = {"/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID,
           "/api/fleet/formation": {"active": False, "state": "IDLE"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        try:
            page.set_viewport_size({"width": width, "height": 844})
            page.goto(console_url, wait_until="networkidle")
            page.evaluate("theme => window.RosyTheme.set(theme)", theme)
            page.locator("#roster article").first.wait_for()
            choice = page.locator("#robot-choice").bounding_box()
            roster = page.locator(".robot-list-details").bounding_box()
            map_panel = page.locator('[aria-labelledby="map-heading"]').bounding_box()
            assert choice["y"] + choice["height"] < 844
            assert roster["y"] < map_panel["y"]
            colors = page.locator("#site-path-summary").evaluate("""node => {
                node.dataset.kind = 'crit'; node.textContent = 'Vision 끊김';
                const style = getComputedStyle(node);
                return [style.color, style.backgroundColor];
            }""")
            foreground, background = ["#" + "".join(f"{int(v):02x}" for v in re.findall(r"\d+", color)[:3])
                                      for color in colors]
            assert contrast(foreground, background) >= 4.5, colors
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()
