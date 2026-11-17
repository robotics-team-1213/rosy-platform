"""S0b: choice-group allowEmpty, createTabs (veto, disabled reason, icon-only, automatic), poll-safe set/setItems, status text,
compact chips and the radio hit target, all on the served gallery at 1440 and 390."""

import pytest
from browser_harness import browser_tests_enabled
from gallery_fixture import gallery, selection_color  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
TABS = "#choice-tabs2-mount [role=tab]"
BAR = "#choice-tabs2-mount [role=tablist]"


def checked(page, group):
    return page.locator(f"#{group} input:checked").evaluate_all("nodes => nodes.map(node => node.value)")


def test_allow_empty_starts_with_no_radio_checked_and_arrows_check_one(gallery):
    from playwright.sync_api import expect
    page = gallery
    assert checked(page, "fit-mode") == []
    radios = page.locator("#fit-mode input[type=radio]")
    radios.first.focus()  # Tab enters the group on the first radio; focus alone checks nothing (APG)
    assert checked(page, "fit-mode") == []
    page.keyboard.press("ArrowRight")
    assert checked(page, "fit-mode") == ["fill"]
    expect(page.locator("#choice-empty-result")).to_have_text("맞춤 방식 fill")
    page.locator("#choice-empty-clear").click()  # only the owner returns to none, silently
    assert checked(page, "fit-mode") == []
    expect(page.locator("#choice-empty-result")).to_have_text("값 없음(화면이 비움)")
    assert page.locator("#fit-mode .choice-chip .choice-check").first.evaluate("node => getComputedStyle(node).visibility") == "hidden"


def test_the_radio_is_the_hit_target_so_a_locator_can_check_it_directly(gallery):
    page = gallery
    radio = page.get_by_role("radio", name="맞춤")
    radio.check()  # no label click needed
    assert checked(page, "fit-mode") == ["fit"]
    box, chip = radio.bounding_box(), page.locator("#fit-mode .choice-chip").first.bounding_box()
    assert box["width"] >= chip["width"] - 3 and box["height"] >= chip["height"] - 3  # the chip border is 1px each side
    assert chip["height"] >= 44  # a touch target


def test_tabs_automatic_arrows_activate_skip_the_disabled_tab_and_icon_only_tabs_have_names(gallery):
    from playwright.sync_api import expect
    page = gallery
    tabs = page.locator(TABS)
    mount = page.locator("#choice-tabs2-mount")
    assert mount.get_by_role("tab", name="기록").count() == 1 and mount.get_by_role("tab", name="근거").count() == 1
    expect(tabs.nth(0)).to_have_attribute("data-icon-only", "")
    assert tabs.nth(0).locator("svg").count() == 1
    cause = page.locator("#tabs2-cause")
    expect(cause).to_have_text("정지 중에는 도구를 쓸 수 없습니다")
    assert "tabs2-cause" in tabs.nth(1).get_attribute("aria-describedby")
    assert tabs.nth(1).get_attribute("aria-disabled") == "true"
    tabs.nth(1).click(force=True)  # a disabled tab never activates
    expect(tabs.nth(0)).to_have_attribute("aria-selected", "true")
    tabs.nth(0).focus()
    page.keyboard.press("ArrowRight")  # automatic: focus moves AND activates; the disabled one is skipped
    expect(tabs.nth(2)).to_be_focused()
    expect(tabs.nth(2)).to_have_attribute("aria-selected", "true")
    expect(page.locator("#choice-tabs2-result")).to_have_text("탭 evidence")
    page.keyboard.press("Home")
    expect(tabs.nth(0)).to_have_attribute("aria-selected", "true")
    page.keyboard.press("End")
    expect(tabs.nth(2)).to_have_attribute("aria-selected", "true")
    assert page.locator("#tab2-evidence").is_visible() and not page.locator("#tab2-history").is_visible()


def test_tabs_async_veto_keeps_the_tab_and_a_confirmed_switch_commits_once(gallery):
    from playwright.sync_api import expect
    page = gallery
    tabs = page.locator(TABS)
    page.locator("#choice-tabs2-veto").check()
    tabs.nth(2).click()
    expect(page.locator(BAR)).not_to_have_attribute("aria-busy", "true")  # the veto settled (the busy window is proven without a race below)
    expect(tabs.nth(0)).to_have_attribute("aria-selected", "true")
    expect(page.locator("#choice-tabs2-result")).to_have_text("탭 상태")  # no onChange for a veto
    page.locator("#choice-tabs2-veto").uncheck()
    tabs.nth(2).click()
    expect(tabs.nth(2)).to_have_attribute("aria-selected", "true")
    expect(page.locator("#choice-tabs2-result")).to_have_text("탭 evidence")


def test_tabs_edge_cases_run_in_the_page(gallery):
    page = gallery
    result = page.evaluate("""async () => {
      const {createTabs} = await import('/common/interaction-controls.js');
      const {createChoiceGroup} = await import('/common/choice-group.js');
      const p = () => document.createElement('p');
      const two = id => [{label: 'A', content: p(), id: 'a'}, {label: 'B', content: p(), id: 'b'}];
      const empty = createTabs({id: 'none', tabs: []});
      const noPanel = createTabs({id: 'np', tabs: [{label: 'A', content: p()}, {label: 'B', content: p()}]});
      document.body.append(noPanel.element);
      const all = createTabs({id: 'all', tabs: [{label: 'A', content: p(), disabled: true}, {label: 'B', content: p(), reason: 'no'}]});
      document.body.append(all.element);
      const seen = [];
      const veto = createTabs({id: 'sy', tabs: two(), beforeChange: () => false, onChange: k => seen.push(k)});
      document.body.append(veto.element); veto.element.querySelectorAll('[role=tab]')[1].click();
      const throws = createTabs({id: 'th', tabs: two(), beforeChange: () => { throw new Error('x'); }, onChange: k => seen.push(k)});
      document.body.append(throws.element); throws.element.querySelectorAll('[role=tab]')[1].click();
      const late = createTabs({id: 'la', tabs: two(), beforeChange: () => new Promise(r => setTimeout(() => r(true), 30)), onChange: k => seen.push('late-' + k)});
      document.body.append(late.element); late.element.querySelectorAll('[role=tab]')[1].click(); late.dispose();
      await new Promise(r => setTimeout(r, 80));
      const pendingSeen = [];
      let release; const gate = new Promise(r => { release = r; });
      const slow = createTabs({id: 'pe', tabs: [...two(), {label: 'C', content: p(), id: 'c'}], beforeChange: () => gate, onChange: k => pendingSeen.push(k)});
      document.body.append(slow.element);
      const slowTabs = slow.element.querySelectorAll('[role=tab]'), slowBar = slow.element.querySelector('[role=tablist]');
      slowTabs[1].click();
      const busy = slowBar.getAttribute('aria-busy');
      slowTabs[2].click();  // ignored while pending
      slow.setDisabled('b', 'locked meanwhile');  // the target is disabled while the question is open
      release(true); await new Promise(r => setTimeout(r, 20));
      const afterDisabled = {value: slow.value, seen: [...pendingSeen], busyAfter: slowBar.getAttribute('aria-busy')};
      slow.setDisabled('b', '');
      const reenabled = !slowTabs[1].disabled && slow.element.querySelector('[data-cause]').hidden;
      const rej = createTabs({id: 'rj', tabs: two(), beforeChange: () => Promise.reject(new Error('no')), onChange: k => pendingSeen.push('rej-' + k)});
      document.body.append(rej.element); rej.element.querySelectorAll('[role=tab]')[1].click(); await new Promise(r => setTimeout(r, 20));
      let unlock; const lock = new Promise(r => { unlock = r; });
      const mid = createTabs({id: 'mi', tabs: two(), beforeChange: () => lock, onChange: k => pendingSeen.push('mid-' + k)});
      document.body.append(mid.element); mid.element.querySelectorAll('[role=tab]')[1].click();
      mid.select('b'); const midBusy = mid.element.querySelector('[role=tablist]').getAttribute('aria-busy');
      unlock(true); await new Promise(r => setTimeout(r, 20));
      const emptyGroup = createChoiceGroup({id: 'em', label: 'x', mode: 'single', allowEmpty: true, items: [{value: 'a', label: 'A'}, {value: 'b', label: 'B'}], value: 'a'});
      document.body.append(emptyGroup.element); emptyGroup.setItems([{value: 'b', label: 'B'}]);
      let bad = null; try { createTabs({id: 'x', tabs: [], activation: 'sometimes'}); } catch (e) { bad = e.name; }
      return {emptyValue: empty.value, controls: noPanel.element.querySelector('[role=tab]').getAttribute('aria-controls'), panelTab: noPanel.element.querySelector('[role=tabpanel]').tabIndex,
        allValue: all.value, allSelected: all.element.querySelectorAll('[aria-selected=true]').length, seen, bad, busy, afterDisabled, reenabled, pendingSeen, midBusy, emptyValue2: emptyGroup.value,
        selectDisabled: (() => { all.select('all-panel-0'); all.select('all-panel-1'); return all.value; })()};
    }""")
    assert result == {"emptyValue": None, "controls": "np-panel-0", "panelTab": 0, "allValue": None, "allSelected": 0, "seen": [], "bad": "RangeError", "selectDisabled": None,
                      "busy": "true", "afterDisabled": {"value": "a", "seen": [], "busyAfter": None}, "reenabled": True,
                      "pendingSeen": [], "midBusy": None, "emptyValue2": None}


def test_poll_driven_set_and_setitems_rebuild_nothing_when_nothing_changed(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#frame-list [role=option]").nth(3).focus()
    page.evaluate("window.__option = document.querySelectorAll('#frame-list [role=option]')[3]")
    page.evaluate("document.getElementById('choice-list-poll').click()")
    assert page.evaluate("window.__option.isConnected")
    expect(page.locator("#frame-list [role=option]").nth(3)).to_be_focused()
    page.evaluate("document.getElementById('choice-list-refresh').click()")  # a real change rebuilds and still keeps focus
    assert not page.evaluate("window.__option.isConnected")
    expect(page.locator("#frame-list [role=option]").nth(3)).to_be_focused()
    page.evaluate("window.__chip = document.querySelectorAll('#speed-step .choice-chip')[1]")
    page.locator("#speed-step input").nth(1).focus()
    page.evaluate("document.getElementById('choice-single-poll').click()")
    assert page.evaluate("window.__chip.isConnected")
    expect(page.locator("#speed-step input").nth(1)).to_be_focused()


def test_group_setitems_keeps_the_focused_control_when_it_really_rebuilds(gallery):
    page = gallery
    held = page.evaluate("""async () => {
      const {createChoiceGroup} = await import('/common/choice-group.js');
      const items = label => [{value: 'a', label}, {value: 'b', label: 'B'}];
      const group = createChoiceGroup({id: 'rb', label: '다시 짓기', mode: 'toggle', items: items('A'), master: {label: '전체'}});
      document.body.append(group.element);
      group.element.querySelector('ui-button[data-value=b]').focus();
      group.setItems(items('A2'));
      const after = document.activeElement.dataset.value;
      group.element.querySelector('[data-master]').focus(); group.setItems(items('A3'));
      const master = document.activeElement.hasAttribute('data-master');
      group.dispose(); group.setItems([{value: 'z', label: 'Z'}]);
      return {after, master, still: group.element.querySelectorAll('ui-button[data-value]').length};
    }""")
    assert held == {"after": "b", "master": True, "still": 2}


def test_item_status_carries_its_own_text_and_icon(gallery):
    page = gallery
    late = page.locator("#frame-list [role=option]").nth(2).locator("ui-tag")
    assert late.inner_text().strip() == "14초 늦음" and late.locator("svg").count() == 1
    promoted = page.locator("#frame-list [role=option]").nth(5).locator("ui-tag")
    assert promoted.inner_text().strip() == "승격됨" and promoted.get_attribute("data-state") == "locked"
    assert page.locator("#frame-list [role=option]").nth(4).locator("ui-tag").inner_text().strip() == "주의"  # a plain string keeps the default


def test_chips_give_the_unselected_tick_back_only_on_compact_widths(gallery):
    page = gallery
    chips = page.locator("#speed-step .choice-chip")
    probe = "node => ({display: getComputedStyle(node).display, visibility: getComputedStyle(node).visibility})"
    selected = chips.nth(0).locator(".choice-check").evaluate(probe)
    unselected = chips.nth(1).locator(".choice-check").evaluate(probe)
    assert selected["visibility"] == "visible" and selected["display"] != "none"
    assert unselected["visibility"] == "hidden"
    assert (unselected["display"] != "none") if page.wide else (unselected["display"] == "none")
    assert selection_color(page) in chips.nth(0).evaluate("node => getComputedStyle(node).boxShadow")  # the edge stays on both widths
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if not page.wide:
        tops = chips.evaluate_all("nodes => new Set(nodes.map(node => Math.round(node.getBoundingClientRect().top))).size")
        assert tops == 1, "four short chips fit one line at 390"


def test_a_disabled_current_value_keeps_its_selection_edge_and_tick_muted_with_its_reason(gallery):
    page = gallery
    assert checked(page, "drive-mode") == ["auto"]
    radio = page.locator("#drive-mode input[value=auto]")
    assert radio.is_disabled()
    chip = page.locator("#drive-mode .choice-chip").nth(0)
    assert selection_color(page) in chip.evaluate("node => getComputedStyle(node).boxShadow")  # the edge
    assert chip.locator(".choice-check").evaluate("node => getComputedStyle(node).visibility") == "visible"  # the tick
    assert float(chip.evaluate("node => getComputedStyle(node).opacity")) < 1  # muted, not hidden
    assert "정지 중에는 바꿀 수 없습니다" in chip.inner_text()  # the reason stays on the chip
    other = page.locator("#drive-mode .choice-chip").nth(1)
    assert other.locator(".choice-check").evaluate("node => getComputedStyle(node).visibility") == "hidden"
    page.locator("#drive-mode input[value=manual]").evaluate("node => node.click()")  # a disabled radio cannot be chosen
    assert checked(page, "drive-mode") == ["auto"]


def test_k20_current_value_button_is_bold_underlined_and_not_faded(gallery):
    page = gallery
    buttons = page.locator("#k20-current ui-button")
    probe = """node => { const s = getComputedStyle(node);
      return {opacity: parseFloat(s.opacity), weight: parseInt(s.fontWeight, 10),
        shadow: s.boxShadow, outlineStyle: s.outlineStyle, outlineWidth: s.outlineWidth}; }"""
    sibling = buttons.nth(0).evaluate(probe)
    current = buttons.nth(1).evaluate(probe)
    selected_shadow = page.locator("#speed-step .choice-chip").nth(0).evaluate("node => getComputedStyle(node).boxShadow")
    assert current["opacity"] == 1
    assert current["weight"] >= 600 and current["weight"] > sibling["weight"]
    assert current["shadow"] and current["shadow"] != "none"
    assert "inset" in current["shadow"] and current["shadow"] != selected_shadow
    assert current["outlineStyle"] == "none" or current["outlineWidth"] == "0px"
    assert sibling["weight"] != current["weight"] and sibling["shadow"] != current["shadow"]
