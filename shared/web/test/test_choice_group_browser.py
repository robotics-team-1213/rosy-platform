"""G2 createChoiceGroup (single, toggle with master, check), G4 createTabs extension and S1 createSelection wiring."""

import pytest
from browser_harness import browser_tests_enabled
from gallery_fixture import gallery, selection_color  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
NO_FILL = "rgba(0, 0, 0, 0)"


def test_single_is_a_native_radio_fieldset_with_exactly_one_checked(gallery):
    from playwright.sync_api import expect
    page = gallery
    group = page.locator("#speed-step")
    assert group.evaluate("node => node.tagName") == "FIELDSET"
    expect(group.locator("legend")).to_have_text("재생 속도")
    radios = group.locator("input[type=radio]")
    assert radios.count() == 4 and group.locator("input:checked").count() == 1
    radios.first.focus()
    page.keyboard.press("ArrowRight")  # native: arrows move and choose
    expect(page.locator("#speed-step input:checked")).to_have_value("2")
    expect(page.locator("#choice-single-result")).to_have_text("2배속")
    assert group.locator("input:checked").count() == 1
    chip = group.locator(".choice-chip").nth(1)
    assert selection_color(page) in chip.evaluate("node => getComputedStyle(node).boxShadow")
    assert chip.evaluate("node => getComputedStyle(node).backgroundColor") == NO_FILL
    assert chip.locator(".choice-check").evaluate("node => getComputedStyle(node).visibility") == "visible"


def pressed(page, group):
    return page.locator(f"#{group} ui-button:not([data-master])").evaluate_all("nodes => nodes.map(node => node.getAttribute('aria-pressed'))")


def test_toggle_syncs_aria_pressed_and_master_goes_mixed_true_false(gallery):
    from playwright.sync_api import expect
    page = gallery
    group = page.locator("#map-layers")
    assert group.get_attribute("role") == "group" and group.get_attribute("aria-labelledby") == "map-layers-label"
    master = group.locator("[data-master]")
    expect(master).to_have_attribute("aria-pressed", "mixed")
    assert pressed(page, "map-layers") == ["true", "true", "false", "true", "false"]
    group.locator("ui-button[data-value=grid]").focus()
    page.keyboard.press("Space")
    expect(group.locator("ui-button[data-value=grid]")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#choice-toggle-result")).to_have_text("겹 4개 켬")
    master.click()
    assert set(pressed(page, "map-layers")) == {"true"}
    expect(master).to_have_attribute("aria-pressed", "true")
    master.click()
    assert set(pressed(page, "map-layers")) == {"false"}  # all off is allowed for toggle
    expect(master).to_have_attribute("aria-pressed", "false")
    on = group.locator("ui-button[data-value=route]")
    on.click()
    page.mouse.move(0, 0)
    assert selection_color(page) in on.evaluate("node => getComputedStyle(node).boxShadow")
    assert on.locator(".choice-check").evaluate("node => getComputedStyle(node).visibility") == "visible"
    assert on.evaluate("node => getComputedStyle(node).backgroundColor") == NO_FILL


def test_max_blocks_the_rest_with_a_visible_reason_and_frees_them_again(gallery):
    from playwright.sync_api import expect
    page = gallery
    group = page.locator("#robot-filter")
    for value in ("arm_a", "arm_b"):
        group.locator(f"ui-button[data-value={value}]").click()
    blocked = group.locator("ui-button[data-value=rosy_40]")
    expect(blocked).to_have_attribute("disabled", "")
    expect(blocked).to_contain_text("최대 2개까지 고를 수 있습니다")
    group.locator("ui-button[data-value=arm_a]").click()
    assert blocked.get_attribute("disabled") is None


def test_check_is_a_legend_fieldset_of_native_checkboxes_with_a_reason_for_disabled(gallery):
    from playwright.sync_api import expect
    page = gallery
    group = page.locator("#data-kinds")
    expect(group.locator("legend")).to_have_text("자료 종류")
    boxes = group.locator("input[type=checkbox]")
    assert boxes.count() == 4 and group.locator("input:checked").count() == 2
    assert boxes.nth(3).is_disabled()
    expect(group).to_contain_text("권한 없음")
    boxes.nth(2).check()
    expect(page.locator("#choice-check-result")).to_have_text("자료 종류 3개")
    for at in range(3):
        boxes.nth(at).uncheck()
    assert group.locator("input:checked").count() == 0  # none is allowed for check


def test_tabs_arrows_focus_enter_activates_onchange_and_silent_select(gallery):
    from playwright.sync_api import expect
    page = gallery
    tabs = page.locator("#choice-tabs-mount [role=tab]")
    assert page.locator("#choice-tabs-mount [role=tablist]").get_attribute("aria-label") == "견본 맥락"
    tabs.first.focus()
    page.keyboard.press("ArrowRight")
    expect(tabs.nth(1)).to_be_focused()
    expect(tabs.nth(1)).to_have_attribute("aria-selected", "false")  # manual activation
    page.keyboard.press("End")
    expect(tabs.nth(2)).to_be_focused()
    page.keyboard.press("Home")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    expect(tabs.nth(1)).to_have_attribute("aria-selected", "true")
    expect(page.locator("#choice-tabs-result")).to_have_text("탭 evidence")
    assert page.locator("#choice-tab-evidence").is_visible() and not page.locator("#choice-tab-state").is_visible()
    tabs.first.click()
    expect(page.locator("#choice-tabs-result")).to_have_text("탭 state")
    page.evaluate("document.getElementById('choice-tabs-select').click()")
    expect(tabs.nth(1)).to_have_attribute("aria-selected", "true")
    expect(page.locator("#choice-tabs-result")).to_contain_text("알림 없음")  # select() never calls onChange


def test_one_selection_store_drives_roster_pick_markers_and_detail(gallery):
    from playwright.sync_api import expect
    page = gallery
    expect(page.locator("#selection-detail")).to_have_text("선택: rosy_40")

    def state():
        return page.evaluate("""() => ({
          markers: [...document.querySelectorAll('#selection-markers li[data-selected]')].map(li => li.dataset.markerId),
          rows: [...document.querySelectorAll('#selection-roster-mount li.robot-row[data-selected]')].map(li => li.dataset.robotId),
          pressed: [...document.querySelectorAll('#selection-roster-mount [data-select-robot-id][aria-pressed=true]')].map(b => b.dataset.selectRobotId),
          pick: document.getElementById('robot-pick').value})""")
    assert state() == {"markers": ["rosy_40"], "rows": ["rosy_40"], "pressed": ["rosy_40"], "pick": "rosy_40"}
    page.locator("#selection-markers [data-marker-id]").nth(0).click()  # a map marker chooses
    expect(page.locator("#selection-detail")).to_have_text("선택: OMX-AI A")
    assert state() == {"markers": ["arm_a"], "rows": ["arm_a"], "pressed": ["arm_a"], "pick": "arm_a"}
    if page.wide:
        button = page.locator("#selection-roster-mount li[data-robot-id=rosy_41] [data-select-robot-id]")
        button.click()
        expect(button).to_have_text("선택됨")
    else:  # S2: narrow shows the select, not the roster
        assert not page.locator("#selection-roster-mount").is_visible() and page.locator("#robot-pick").is_visible()
        page.locator("#robot-pick").select_option("rosy_41")
    assert state() == {"markers": ["rosy_41"], "rows": ["rosy_41"], "pressed": ["rosy_41"], "pick": "rosy_41"}
    # the same mark on a marker and a row: the --selection edge and no fill; the button says 선택됨 (not colour alone)
    marker = page.locator("#selection-markers li[data-selected]")
    assert "선택됨" in marker.inner_text()
    lines = [marker] + ([page.locator("#selection-roster-mount li[data-selected]")] if page.wide else [])
    for li in lines:
        assert selection_color(page) in li.evaluate("node => getComputedStyle(node).boxShadow")
        assert li.evaluate("node => getComputedStyle(node).backgroundColor") == NO_FILL
