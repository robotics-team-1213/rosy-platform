"""C24 robot panel on the served gallery: focus, Esc/close, switching, stop rules, 390 sheet, and zero motion."""

import re

import pytest
from browser_harness import browser_tests_enabled
from gallery_fixture import gallery  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


def _demo(page):
    section = page.locator("#robot-dock")
    section.evaluate("el => el.scrollIntoView({block: 'start'})")
    return page.locator("#robot-dock-demo")


def test_panel_open_focus_esc_close_and_switching(gallery):
    from playwright.sync_api import expect

    page = gallery
    demo = _demo(page)
    panel = demo.locator(".robot-panel")
    title = panel.locator(".robot-panel-title")
    btn_42 = demo.locator('.robot-dock-btn[data-robot-id="rosy_42"]')
    btn_45 = demo.locator('.robot-dock-btn[data-robot-id="rosy_45"]')

    # Opens on click and focuses the title.
    btn_42.click()
    expect(panel).to_be_visible()
    expect(title).to_have_text("rosy_42")
    assert title.evaluate("el => document.activeElement === el")

    # Esc closes and returns focus to the opening dock button.
    page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    assert btn_42.evaluate("el => document.activeElement === el")

    # Close button closes and returns focus to the opening dock button.
    btn_45.click()
    expect(panel).to_be_visible()
    expect(title).to_have_text("rosy_45")
    panel.locator(".robot-panel-close").click()
    expect(panel).to_be_hidden()
    assert btn_45.evaluate("el => document.activeElement === el")

    # Map click while closed does not open the panel.
    demo.locator('[data-demo-map-robot="arm_a"]').click()
    expect(panel).to_be_hidden()

    if page.wide:
        # Clicking another icon while open switches content with a single visible panel.
        btn_42.click()
        expect(panel).to_be_visible()
        expect(title).to_have_text("rosy_42")
        btn_45.click()
        expect(demo.locator(".robot-panel:not([hidden])")).to_have_count(1)
        expect(title).to_have_text("rosy_45")

        # Map click while open switches content to that robot.
        demo.locator('[data-demo-map-robot="arm_s"]').click()
        expect(demo.locator(".robot-panel:not([hidden])")).to_have_count(1)
        expect(title).to_have_text("arm_s")

        # Clicking the currently open dock icon closes it.
        demo.locator('.robot-dock-btn[data-robot-id="rosy_45"]').click()
        expect(panel).to_be_hidden()


def test_panel_stop_rules_and_zero_animation(gallery):
    from playwright.sync_api import expect

    page = gallery
    demo = _demo(page)
    panel = demo.locator(".robot-panel")

    # Pinky panel: live stop button inside viewport, enabled, data-always-live, no overflow.
    demo.locator('.robot-dock-btn[data-robot-id="rosy_42"]').click()
    expect(panel).to_be_visible()
    demo.locator(".robot-stage").evaluate("el => el.scrollIntoView({block: 'start'})")
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

    stop_btn = panel.locator(".robot-panel-stop")
    expect(stop_btn).to_be_visible()
    expect(stop_btn).to_have_attribute("data-always-live", "")
    assert not stop_btn.evaluate("el => el.disabled || el.hasAttribute('disabled')")
    stop_box = stop_btn.bounding_box()
    vp = page.viewport_size
    assert stop_box is not None
    assert stop_box["x"] >= 0 and stop_box["y"] >= 0
    assert stop_box["x"] + stop_box["width"] <= vp["width"]
    assert stop_box["y"] + stop_box["height"] <= vp["height"]

    # Zero transition/animation on dock buttons and the panel (D-220).
    dock_motion = demo.locator(".robot-dock-btn").evaluate_all(
        "els => els.map(el => { const s = getComputedStyle(el); return [s.transitionDuration, s.animationName]; })"
    )
    panel_motion = panel.evaluate(
        "el => { const s = getComputedStyle(el); return [s.transitionDuration, s.animationName]; }"
    )
    for dur, anim in [*dock_motion, panel_motion]:
        assert all(part.strip() in ("0s", "0ms") for part in dur.split(",")), f"unexpected transitionDuration: {dur}"
        assert anim == "none", f"unexpected animationName: {anim}"

    if not page.wide:
        panel.locator(".robot-panel-close").click()
        expect(panel).to_be_hidden()

    # Arm panel: note instead of stop button, no stop/torque/power/hold-clear buttons, no overflow.
    demo.locator('.robot-dock-btn[data-robot-id="arm_s"]').click()
    expect(panel).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    expect(panel.locator(".robot-panel-stop")).to_have_count(0)
    expect(panel.locator(".robot-panel-stop-note")).to_be_visible()

    btn_labels = panel.locator("button, ui-button").evaluate_all(
        "els => els.map(el => (el.getAttribute('aria-label') || el.textContent || '').trim())"
    )
    forbidden = re.compile(r"정지|토크|전원|홀드\s*해제")
    assert not [label for label in btn_labels if forbidden.search(label)], f"forbidden arm panel buttons: {btn_labels}"


def test_narrow_panel_keeps_header_stop_visible_and_clickable(gallery):
    from playwright.sync_api import expect

    page = gallery
    if page.wide:
        pytest.skip("390 only")
    demo = _demo(page)
    demo.locator('.robot-dock-btn[data-robot-id="rosy_42"]').click()
    panel = demo.locator(".robot-panel")
    expect(panel).to_be_visible()

    topbar_box = page.locator("ui-topbar").bounding_box()
    panel_box = panel.bounding_box()
    assert topbar_box is not None and panel_box is not None
    assert panel_box["y"] >= topbar_box["y"] + topbar_box["height"] - 1

    header_stop = page.locator("#gallery-stop")
    expect(header_stop).to_be_visible()
    stop_box = header_stop.bounding_box()
    assert stop_box is not None
    cx = stop_box["x"] + stop_box["width"] / 2
    cy = stop_box["y"] + stop_box["height"] / 2
    hit_stop = page.evaluate(
        "([x, y]) => { const el = document.elementFromPoint(x, y); const s = document.getElementById('gallery-stop'); "
        "return Boolean(el && s && (el === s || s.contains(el))); }",
        [cx, cy],
    )
    assert hit_stop, "header #gallery-stop must remain uncovered at 390 when panel sheet is open"

    header_stop.click()
    expect(page.locator("#stop-result")).not_to_have_text("")
