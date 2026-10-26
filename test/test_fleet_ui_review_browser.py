"""Screen-review regressions: reachable mobile status and readable critical text."""
import re
import os
from pathlib import Path

import pytest

from browser_harness import browser_tests_enabled
from console_browser_site import console_url  # noqa: F401
from test_fleet_console_browser import MAP_GRID, SNAPSHOT, _open_console

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


def luminance(color):
    channels = [int(value) / 255 for value in re.findall(r"\d+", color)[:3]]
    return sum(weight * (value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
               for weight, value in zip((0.2126, 0.7152, 0.0722), channels))


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
            foreground, background = sorted(map(luminance, colors))
            assert (background + 0.05) / (foreground + 0.05) >= 4.5, colors
            if output := os.environ.get("ROSY_SHOT_DIR"):
                Path(output).mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(Path(output) / f"fleet-status-{theme}-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator('#robot-choice').select_option('rosy_01')
            page.locator('#robot-workspace article').wait_for()
            selected = page.locator('#robot-workspace').bounding_box()
            assert selected['y'] < page.locator('.robot-list-details').bounding_box()['y']
            assert selected['y'] < 844
            assert not errors
        finally:
            browser.close()
