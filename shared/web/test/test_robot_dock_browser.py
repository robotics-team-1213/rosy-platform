"""C23 robot dock on the served gallery: buttons, abnormal-only marks, aria-pressed, selection sync, and 390 layout."""

import pytest
from browser_harness import browser_tests_enabled
from gallery_fixture import gallery  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


def _demo(page):
    section = page.locator("#robot-dock")
    section.evaluate("el => el.scrollIntoView({block: 'start'})")
    return page.locator("#robot-dock-demo")


def test_dock_buttons_and_abnormal_only_marks(gallery):
    from playwright.sync_api import expect

    page = gallery
    demo = _demo(page)
    buttons = demo.locator(".robot-dock .robot-dock-btn")
    expect(buttons).to_have_count(6)

    meta = buttons.evaluate_all(
        "els => els.map(el => ({id: el.dataset.robotId, tag: el.tagName, label: el.getAttribute('aria-label'), "
        "short: el.querySelector('.robot-dock-id')?.textContent}))"
    )
    assert [m["id"] for m in meta] == ["rosy_42", "rosy_45", "rosy_46", "arm_s", "arm_a", "arm_b"]
    assert [m["short"] for m in meta] == ["42", "45", "46", "S", "A", "B"]
    for item in meta:
        assert item["tag"] == "BUTTON"
        assert item["label"] and item["label"].strip()

    expected_marks = {
        "rosy_42": [("alarm", "caution")],
        "rosy_45": [("link", "delayed")],
        "rosy_46": [],
        "arm_s": [("alarm", "caution")],
        "arm_a": [],
        "arm_b": [("link", "disconnected")],
    }
    for robot_id, expected in expected_marks.items():
        marks = demo.locator(f'.robot-dock-btn[data-robot-id="{robot_id}"] .robot-dock-mark')
        actual = marks.evaluate_all("els => els.map(el => [el.dataset.markKind, el.dataset.state])")
        assert actual == [list(pair) for pair in expected], f"{robot_id}: expected marks {expected}, got {actual}"
        if expected:
            assert marks.locator("svg.ui-icon").count() == len(expected)


def test_dock_selection_and_pressed_state(gallery):
    from playwright.sync_api import expect

    page = gallery
    demo = _demo(page)
    panel = demo.locator(".robot-panel")
    expect(panel).to_be_hidden()
    expect(demo.locator('.robot-dock-btn[aria-pressed="true"]')).to_have_count(0)

    # Map click while closed selects without opening the panel.
    demo.locator('[data-demo-map-robot="rosy_45"]').click()
    expect(panel).to_be_hidden()
    expect(demo.locator('.robot-dock-btn[aria-pressed="true"]')).to_have_count(0)
    expect(demo.locator(".robot-dock-btn[data-selected]")).to_have_attribute("data-robot-id", "rosy_45")

    # Dock click opens the panel and moves both pressed and selection.
    demo.locator('.robot-dock-btn[data-robot-id="rosy_42"]').click()
    expect(panel).to_be_visible()
    expect(panel.locator(".robot-panel-title")).to_have_text("rosy_42")
    expect(demo.locator('.robot-dock-btn[aria-pressed="true"]')).to_have_count(1)
    expect(demo.locator('.robot-dock-btn[aria-pressed="true"]')).to_have_attribute("data-robot-id", "rosy_42")
    expect(demo.locator(".robot-dock-btn[data-selected]")).to_have_attribute("data-robot-id", "rosy_42")

    if page.wide:
        # Map click while open moves selection and panel follows without extra pressed buttons.
        demo.locator('[data-demo-map-robot="rosy_46"]').click()
        expect(panel).to_be_visible()
        expect(panel.locator(".robot-panel-title")).to_have_text("rosy_46")
        expect(demo.locator(".robot-dock-btn[data-selected]")).to_have_attribute("data-robot-id", "rosy_46")
        expect(demo.locator('.robot-dock-btn[aria-pressed="true"]')).to_have_count(1)

        # Switching via another dock button keeps exactly one aria-pressed="true".
        demo.locator('.robot-dock-btn[data-robot-id="arm_s"]').click()
        expect(panel).to_be_visible()
        expect(panel.locator(".robot-panel-title")).to_have_text("arm_s")
        expect(demo.locator('.robot-dock-btn[aria-pressed="true"]')).to_have_count(1)
        expect(demo.locator('.robot-dock-btn[aria-pressed="true"]')).to_have_attribute("data-robot-id", "arm_s")
        expect(demo.locator(".robot-dock-btn[data-selected]")).to_have_attribute("data-robot-id", "arm_s")


def test_dock_narrow_layout_has_no_overflow_and_44px_targets(gallery):
    from playwright.sync_api import expect

    page = gallery
    if page.wide:
        pytest.skip("390 only")
    demo = _demo(page)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")

    buttons = demo.locator(".robot-dock .robot-dock-btn")
    expect(buttons).to_have_count(6)
    for i in range(6):
        btn = buttons.nth(i)
        box = btn.bounding_box()
        assert box is not None
        assert box["width"] >= 44 and box["height"] >= 44, f"button {i} box {box} < 44px"
        id_el = btn.locator(".robot-dock-id")
        expect(id_el).to_be_visible()
        id_box = id_el.bounding_box()
        assert id_box is not None and id_box["width"] > 0 and id_box["height"] > 0
