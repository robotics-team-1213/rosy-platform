"""Compat console pickers (K1/K5) and the login tabs (K9) are shared parts (ui-regions R1, S5)."""
from __future__ import annotations

import pytest

from test_dashboard_browser import _launch_page, pytestmark  # noqa: F401
from test_dashboard_browser_part2 import _open_dashboard, NO_TOKEN_INIT


def test_compat_pickers_are_choice_groups_one_value_each_and_the_same_value_as_the_panel():
    """S5: view switch (K1) and map layers (K5) are createChoiceGroup; mode and line sensor are K20 buttons that mirror the robot."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _launch_page(playwright, width=1366, height=768)
        page.goto("http://rosy.test/dashboard#compatibility")
        page.wait_for_function("document.querySelector('#robot-mode').textContent==='수동'")
        checked = lambda group: page.locator(f"{group} input:checked").evaluate_all("els => els.map(e => e.value)")
        # view switch: exactly one checked, arrow keys move it (native radios), the panel follows
        assert checked("#view-choice") == ["operate"]
        page.locator("#view-operate").focus()
        page.keyboard.press("ArrowRight")
        assert checked("#view-choice") == ["inspect"]
        expect(page.locator("#view-inspect-panel")).to_be_visible()
        page.keyboard.press("ArrowLeft")
        expect(page.locator("#view-operate-panel")).to_be_visible()
        # mode (K20, panel 11-14): the robot says 수동; a declined pick sends nothing
        current = lambda group: page.locator(f"{group} [aria-current=true]").evaluate_all("els => els.map(e => e.dataset.mode || e.dataset.lineMode)")
        assert current("#mode-choice") == ["MANUAL"]
        page.locator("[data-mode=IDLE]").click()
        dialog = page.locator("dialog.ui-confirm")
        expect(dialog).to_have_count(1)
        dialog.locator("ui-button[kind=quiet]").click()
        assert current("#mode-choice") == ["MANUAL"]
        assert page.evaluate("__apiCalls.filter(c=>c.path==='/api/v1/mode').length") == 0
        # line sensor: 꺼짐 is current and is the always-live stop of line following
        assert current("#line-choice") == ["OFF"]
        expect(page.locator("[data-line-mode=OFF]")).to_have_attribute("data-always-live", "")
        expect(page.locator("[data-line-mode=OFF]")).to_be_enabled()
        # Escape is the always-live stop (focus on the view radio is not text entry)
        page.locator("#view-operate").focus()
        page.keyboard.press("Escape")
        page.wait_for_function("__apiCalls.filter(c=>c.path==='/api/v1/safety/stop').length===1")
        # decision 11-14: Escape stops from every focus (checkbox, text field); only IME composition is exempt
        page.evaluate("() => { for (const t of ['checkbox', 'text']) { const i = document.createElement('input'); i.type = t; i.id = 'esc-' + t; document.body.append(i); } }")
        page.locator("#esc-checkbox").focus()
        page.keyboard.press("Escape")
        page.wait_for_function("__apiCalls.filter(c=>c.path==='/api/v1/safety/stop').length===2")
        page.locator("#esc-text").focus()
        page.keyboard.press("Escape")
        page.wait_for_function("__apiCalls.filter(c=>c.path==='/api/v1/safety/stop').length===3")
        # map layers: independent flags with aria-pressed (K5)
        layers = page.locator("#map-layers ui-button[data-map-layer]")
        assert layers.evaluate_all("els => els.map(e => e.getAttribute('aria-pressed'))") == ["true", "true", "true"]
        layers.nth(1).click()
        assert layers.evaluate_all("els => els.map(e => e.getAttribute('aria-pressed'))") == ["true", "false", "true"]
        browser.close()


def test_auth_drawer_tabs_are_createtabs_with_manual_activation():
    """K9: the login method tabs are createTabs: arrows move focus only, Enter or Space activates, one tab stop."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright, expect
    with sync_playwright() as playwright:
        browser, page = _open_dashboard(playwright, NO_TOKEN_INIT)
        page.wait_for_selector("#auth-drawer.open")
        tabs = page.locator("[data-auth-tabs] [role=tab]")
        assert tabs.count() == 2
        assert tabs.evaluate_all("els => els.map(e => e.getAttribute('aria-selected'))") == ["true", "false"]
        assert page.locator("[data-auth-tabs] [role=tab][tabindex='0']").count() == 1
        tabs.nth(0).focus()
        page.keyboard.press("ArrowRight")
        assert tabs.evaluate_all("els => els.map(e => e.getAttribute('aria-selected'))") == ["true", "false"]
        page.keyboard.press("Enter")
        assert tabs.evaluate_all("els => els.map(e => e.getAttribute('aria-selected'))") == ["false", "true"]
        expect(page.locator("#auth-form")).to_be_visible()
        expect(page.locator("#code-form")).to_be_hidden()
        expect(page.locator("#token-input")).to_be_focused()
        browser.close()
