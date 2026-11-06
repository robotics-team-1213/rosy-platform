"""Selected robot's fact row: the safety value stays readable inside its card."""

import pytest

from browser_harness import browser_tests_enabled
from console_browser_site import console_url  # noqa: F401
from test_fleet_console_browser import MAP_GRID, _open_cards, _open_console, _robot

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(), reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium",
)


def test_emergency_stop_chip_stays_inside_the_robot_card(console_url):
    from playwright.sync_api import sync_playwright

    robot = _robot("rosy_01", {"x": 0.5, "y": 0.5, "yaw": 0.0})
    robot["state"]["safety"] = {"estop": True}
    api = {
        "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1}, "robots": [robot], "ts": 0.0},
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        _open_cards(page)
        card = page.locator("#robot-workspace article").filter(has_text="rosy_01")
        safety = card.locator('[data-fact="safety"]')
        assert "비상 정지" in safety.inner_text()
        measured = safety.evaluate("""node => {
          const card = node.closest('article').getBoundingClientRect();
          return {card: card.right, right: Math.max(...[node, ...node.querySelectorAll('*')]
            .map(part => part.getBoundingClientRect().right))};
        }""")
        assert measured["right"] <= measured["card"], measured
        assert not errors
        browser.close()
