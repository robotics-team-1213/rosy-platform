"""Input settings keep keyboard context while updating the existing control values."""
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
from playwright.sync_api import expect
from test_pilot_browser import _enter_drive

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason='opt-in Chromium input settings')


def open_inputs(page, origin):
    _enter_drive(page, origin)
    page.locator('[data-drive-tools]').focus()
    page.keyboard.press('Enter')
    page.locator('[data-drive-inputs]').focus()
    page.keyboard.press('Enter')
    return page.locator('[data-inputs-panel]')


def test_opening_input_settings_moves_focus_inside_and_escape_returns_to_tools(tablet_page):
    origin, page, errors = tablet_page
    panel = open_inputs(page, origin)
    assert panel.evaluate('n => n.contains(document.activeElement)')
    page.keyboard.press('Escape')
    expect(panel).to_have_count(0)
    expect(page.locator('[data-drive-tools]')).to_be_focused()
    assert not errors


@pytest.mark.parametrize('width', [320, 768, 1440])
@pytest.mark.parametrize('label', ['빠름', '중앙 섬세', '반전 꺼짐'])
def test_input_setting_changes_preserve_the_same_focused_control(tablet_page, width, label):
    origin, page, errors = tablet_page
    page.set_viewport_size({'width': width, 'height': 900})
    panel = open_inputs(page, origin)
    button = panel.get_by_role('button', name=label, exact=True)
    button.focus()
    handle = button.element_handle()
    page.keyboard.press('Space')
    assert handle.evaluate('n => n.isConnected && n === document.activeElement')
    assert handle.get_attribute('aria-pressed') == 'true'
    if value := os.environ.get('ROSY_SHOT_DIR'):
        root = Path(value).expanduser(); root.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(root / f'inputs-{width}-{label}.png'))
    page.keyboard.press('Escape')
    expect(panel).to_have_count(0)
    expect(page.locator('[data-drive-tools]')).to_be_focused()
    assert not errors
