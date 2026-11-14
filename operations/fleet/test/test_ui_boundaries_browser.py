"""Compare roster layout across ownership changes using the real served Console."""

import json
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
from test_console_card_trips_browser import API, _open_form
from test_console_queue_inline_browser import _open, site  # noqa: F401


pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


@pytest.mark.parametrize("width,height", [(320, 844), (390, 844), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_roster_layout_keeps_safety_and_trip_controls(site, width, height, theme):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        posts = []
        browser, page, errors = _open(pw, site, API, posts, size=(width, height))
        page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
        form = _open_form(page, "rosy_02")
        expect(form).to_be_visible()
        expect(page.locator("#estop")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        robots = page.locator("#roster > article.robot-summary:not(.omx-summary)[data-robot-id]")
        cells = page.locator("#roster > article.robot-summary.omx-summary[data-robot-id]")
        order = robots.evaluate_all("cards => cards.map(card => card.dataset.robotId)")
        assert set(order) == {
            "rosy_01", "rosy_02", "rosy_03", "rosy_04"}
        assert set(cells.evaluate_all("cards => cards.map(card => card.dataset.robotId)")) == {
            "arm_a", "arm_b", "arm_s"}
        assert order.index("rosy_04") < order.index("rosy_01")
        expect(page.locator('#roster > article[data-robot-id="rosy_04"]')).to_be_visible()
        snapshot = page.evaluate("""() => {
          const rules = {};
          for (const selector of ['.roster-block', '.robot-summary', '.robot-summary.selected',
            '#robot-workspace .robot', '#robot-workspace .facts', '#robot-workspace .card-trip']) {
            const node = document.querySelector(selector), style = getComputedStyle(node);
            rules[selector] = Object.fromEntries(['display', 'grid-template-columns', 'gap', 'padding',
              'border-left-width', 'border-left-style', 'background-color', 'color', 'font-family', 'font-size']
              .map(key => [key, style.getPropertyValue(key)]));
          }
          return rules;
        }""")
        assert snapshot['#robot-workspace .robot']['display'] == 'flex'
        assert snapshot['#robot-workspace .card-trip']['display'] == 'grid'
        if output := os.environ.get("ROSY_SHOT_DIR"):
            folder = Path(output)
            folder.mkdir(parents=True, exist_ok=True)
            stem = f"roster-{theme}-{width}x{height}"
            (folder / (stem + ".json")).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf8")
            page.evaluate("document.fonts.ready")
            page.locator("#robot-workspace").screenshot(path=str(folder / (stem + ".png")))
        expect(page.locator('#robot-choice option[value="rosy_04"]')).to_have_count(1)
        page.locator('#roster ui-button[data-select-robot-id="rosy_04"]').click()
        expect(page.locator('#robot-workspace article[data-robot-id="rosy_04"]')).to_be_visible()
        expect(page.locator('#robot-workspace ui-button[data-goal-robot-id="rosy_04"]')).to_be_disabled()
        assert not posts and not errors
        browser.close()
