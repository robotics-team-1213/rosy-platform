"""Shared action layout and a direct mobile path to the existing robot selector."""

import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


@pytest.mark.parametrize("width", [320, 390])
def test_mobile_robot_choice_jump_changes_no_command(site, width):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as pw:
        posts = []
        browser, page, errors = _open(pw, site, API, posts, size=(width, 844))
        page.get_by_role("button", name="로봇 선택으로 이동", exact=True).click()
        expect(page.locator("#robot-choice")).to_be_focused()
        expect(page.locator("#robot-choice")).to_be_in_viewport()
        page.clock.run_for(1500)
        expect(page.locator("#robot-choice")).to_be_focused()
        if output := os.environ.get("ROSY_SHOT_DIR"):
            Path(output).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(output) / f"fleet-robot-choice-{width}.png"))
        assert not posts and not errors
        browser.close()


@pytest.mark.parametrize("width", [320, 390])
def test_long_intervention_action_wraps_and_keeps_confirmation(site, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, API, [], size=(width, 844))
        button = page.locator('[data-decision="BACK_AND_RETRY"]').first
        assert button.inner_text().rstrip().endswith("…")
        button.evaluate("node => node.firstChild.textContent = '뒤쪽 공간을 확인한 뒤 후진하여 다시 시도하기…'")
        assert button.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        assert not errors
        browser.close()
