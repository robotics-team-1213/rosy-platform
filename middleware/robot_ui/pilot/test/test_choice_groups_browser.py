"""Pilot pickers are createChoiceGroup radios: one value per group, arrow keys move it, the stores agree (S5)."""
import pytest
from browser_harness import browser_tests_enabled
from test_pilot_browser import _enter_drive, _tools

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="browser opt-in")


def _checked(page, group):
    return page.locator(f"{group} input:checked").evaluate_all("els => els.map(e => e.value)")


def test_speed_preset_is_one_group_with_exactly_one_checked_and_arrow_keys_move_it(tablet_page):
    origin, page, errors = tablet_page
    _enter_drive(page, origin)
    assert page.locator("[data-drive-preset-row]").evaluate("e => e.tagName === 'FIELDSET'")
    first = _checked(page, "[data-drive-preset-row]")
    assert len(first) == 1
    page.locator("[data-drive-preset-row] input:checked").focus()
    page.keyboard.press("ArrowRight")
    after = _checked(page, "[data-drive-preset-row]")
    assert len(after) == 1 and after != first
    # the same value reaches the store the cap reads, and the input panel no longer carries a second picker
    assert page.evaluate("JSON.parse(localStorage.getItem('rosy.pilot.input') ?? '{}').preset") == after[0]
    _tools(page)
    page.click("[data-drive-inputs]")
    page.wait_for_selector("[data-inputs-panel] input[type=range]")
    assert page.locator("[data-inputs-panel] [name=input-preset], [data-inputs-panel] [data-preset]").count() == 0
    assert errors == [], errors


def test_fit_fill_are_two_commands_not_a_choice(tablet_page):
    """Panel 11-14: zoom has in-between stops, so fit/fill are K20 buttons (no aria-pressed, no radios) and always work."""
    origin, page, errors = tablet_page
    _enter_drive(page, origin)
    _tools(page)
    assert page.locator("[data-drive-fit][aria-pressed], [data-drive-fill][aria-pressed]").count() == 0
    page.click("[data-drive-zoom]")   # 1.2x: neither fit nor fill
    page.click("[data-drive-fit]")    # must still act from an in-between zoom
    page.wait_for_function("document.querySelector('[data-screen=drive]').dataset.viewMode === 'fit'")
    page.click("[data-drive-fill]")
    page.wait_for_function("document.querySelector('[data-screen=drive]').dataset.viewMode === 'full'")
    assert errors == [], errors


def test_drive_mode_group_keeps_manual_checked_and_arrow_keys_are_native(tablet_page):
    origin, page, errors = tablet_page
    _enter_drive(page, origin)
    modes = "[data-drive-modes]"
    assert _checked(page, modes) == ["manual"]
    if page.locator("[data-drive-auto]").count():
        page.locator(f"{modes} input:checked").focus()
        page.keyboard.press("ArrowRight")
        assert _checked(page, modes) == ["auto"]
        assert page.evaluate("document.querySelector('[data-screen=drive]').dataset.autoMode") == "on"
        page.keyboard.press("ArrowLeft")
        assert _checked(page, modes) == ["manual"]
        assert page.evaluate("document.querySelector('[data-screen=drive]').dataset.autoMode") == "off"
    assert errors == [], errors


def test_arrows_on_a_focused_chip_move_the_chip_and_never_drive_but_the_body_drives(tablet_page):
    """Decision 11-14: drive keys are ignored on any form control (APG arrows move chips); with focus on the page they drive."""
    origin, page, errors = tablet_page
    _enter_drive(page, origin)
    log = f"{origin}/__test__/teleop"
    page.click("[data-drive-preset-row] label:has(input[value=mid])")
    before = _checked(page, "[data-drive-preset-row]")
    n = len(page.request.get(log).json())
    for key in ("ArrowRight", "KeyW"):
        page.keyboard.down(key); page.wait_for_timeout(400); page.keyboard.up(key)
    assert _checked(page, "[data-drive-preset-row]") != before   # the arrow moved the chip
    assert all(c["linear"] == 0 and c["angular"] == 0 for c in page.request.get(log).json()[n:]), "a focused chip must not drive"
    page.evaluate("() => document.activeElement.blur()")
    page.keyboard.down("KeyW"); page.wait_for_timeout(500); page.keyboard.up("KeyW")
    assert any(c["linear"] > 0 for c in page.request.get(log).json()), "W 로 전진 명령이 나가야 한다"
    assert errors == [], errors


def test_drive_keys_do_not_fire_while_typing_in_a_contenteditable(tablet_page):
    """Safety review 11-14: text entry of any kind (contenteditable) never drives."""
    origin, page, errors = tablet_page
    _enter_drive(page, origin)
    page.evaluate("() => { const n = document.createElement('div'); n.contentEditable = 'true'; n.id = 'ce'; document.body.append(n); }")
    log = f"{origin}/__test__/teleop"
    before = len(page.request.get(log).json())
    page.focus("#ce")
    page.keyboard.down("KeyW")
    page.wait_for_timeout(500)
    page.keyboard.up("KeyW")
    assert all(c["linear"] == 0 for c in page.request.get(log).json()[before:])
    assert errors == [], errors
