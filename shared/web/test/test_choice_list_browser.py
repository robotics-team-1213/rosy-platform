"""G1 createChoiceList on the served gallery: APG listbox keyboard, ARIA, no interactive children, focus kept on refresh."""

import pytest
from browser_harness import browser_tests_enabled
from gallery_fixture import gallery, selection_color  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
LIST = "#frame-list"
OPTIONS = f"{LIST} [role=option]"


def selected_ids(page):
    return page.locator(f"{OPTIONS}[aria-selected=true]").evaluate_all("nodes => nodes.map(node => node.dataset.id)")


def test_listbox_aria_and_no_interactive_children(gallery):
    from playwright.sync_api import expect
    page = gallery
    box = page.locator(f"{LIST} [role=listbox]")
    expect(box).to_have_attribute("aria-labelledby", "frame-list-label")
    expect(page.locator("#frame-list-label")).to_have_text("프레임 후보")
    assert page.locator(OPTIONS).count() == 6
    assert page.locator(f"{OPTIONS} :is(button, a, input, select, textarea, ui-button)").count() == 0
    assert page.locator(f"{OPTIONS}[tabindex='0']").count() == 1  # one Tab stop (roving)
    assert selected_ids(page) == []


def test_arrows_move_focus_but_only_enter_or_space_selects(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator(OPTIONS).first.focus()
    page.keyboard.press("ArrowDown")
    expect(page.locator(OPTIONS).nth(1)).to_be_focused()
    assert selected_ids(page) == []  # focus is not selection
    page.keyboard.press("Enter")
    assert selected_ids(page) == ["frame-2"]
    expect(page.locator("#choice-list-result")).to_have_text("선택 frame-2")
    page.keyboard.press("End")
    expect(page.locator(OPTIONS).nth(5)).to_be_focused()
    page.keyboard.press("Enter")  # the last option is disabled: focusable, not choosable
    assert selected_ids(page) == ["frame-2"]
    page.keyboard.press("Home")
    expect(page.locator(OPTIONS).first).to_be_focused()
    page.keyboard.press("Space")
    assert selected_ids(page) == ["frame-1"]  # exactly one at a time


def test_typeahead_jumps_to_the_next_label_with_that_letter(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator(OPTIONS).first.focus()
    page.evaluate("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: '프', bubbles: true}))")  # press() cannot send Hangul
    expect(page.locator(OPTIONS).nth(1)).to_be_focused()


def test_click_selects_and_the_mark_is_edge_plus_check_never_a_fill(gallery):
    page = gallery
    page.locator(OPTIONS).nth(2).click()
    page.mouse.move(0, 0)  # no hover fill under the pointer
    assert selected_ids(page) == ["frame-3"]
    option = page.locator(OPTIONS).nth(2)
    assert option.get_attribute("data-selected") is not None
    assert selection_color(page) in option.evaluate("node => getComputedStyle(node).boxShadow")
    assert option.evaluate("node => getComputedStyle(node).backgroundColor") == "rgba(0, 0, 0, 0)"
    assert option.locator(".choice-check").evaluate("node => getComputedStyle(node).visibility") == "visible"
    assert page.locator(OPTIONS).nth(0).locator(".choice-check").evaluate("node => getComputedStyle(node).visibility") == "hidden"


def test_refresh_keeps_the_value_and_the_focused_item(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator(OPTIONS).nth(1).click()
    page.locator(OPTIONS).nth(3).focus()
    page.evaluate("document.getElementById('choice-list-refresh').click()")  # rebuilds every option
    expect(page.locator(OPTIONS).nth(3)).to_be_focused()
    assert selected_ids(page) == ["frame-2"]
    assert page.locator(OPTIONS).nth(3).inner_text().count("검출") == 1
