"""C1 cause line, C2 busy scope, C4 value text: real behaviour on the served gallery.

Carries over the behaviour expectations of uiux/account-cal-mon-rule-fixes (A2/A3/A8) as component
tests: a locked region restores each control exactly, stop stays live, typed drafts survive, and a
background refresh never swallows a user action or overwrites what the action read.
"""

import pytest
from browser_harness import browser_tests_enabled
from test_component_kit_browser import gallery  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


def _disabled(expect, locator, on):
    if on:
        expect(locator).to_have_attribute("disabled", "")
    else:
        expect(locator).not_to_have_attribute("disabled", "")


def test_busy_scope_locks_region_restores_exactly_and_keeps_stop_live(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#busy-draft").fill("작성 중")
    page.locator("#busy-save").focus()
    page.keyboard.press("Enter")
    region = page.locator("#busy-region")
    expect(region).to_have_attribute("aria-busy", "true")
    expect(page.locator("#busy-status")).to_have_text("저장 결과를 확인하고 있습니다.")
    _disabled(expect, page.locator("#busy-save"), True)
    _disabled(expect, page.locator("#busy-stop"), False)  # stop and [data-always-live] are never locked
    expect(page.locator("#busy-stop")).to_have_attribute("aria-disabled", "false")
    expect(page.locator("#busy-stop")).to_be_visible()  # invariant: no owner hides the stop (nothing repairs it)
    expect(page.locator("#busy-off")).to_have_attribute("aria-describedby", "busy-status")
    expect(page.locator("#busy-draft")).to_have_js_property("readOnly", True)
    page.locator("#busy-stop").click(trial=True)  # actionable (enabled, receives the click) while busy; no focus move
    page.evaluate("document.getElementById('busy-finish').click()")  # a script click keeps focus where it is
    expect(page.locator("#busy-status")).to_have_text("저장 견본 완료")
    expect(region).not_to_have_attribute("aria-busy", "true")
    _disabled(expect, page.locator("#busy-save"), False)
    _disabled(expect, page.locator("#busy-off"), True)  # locked before, still locked after: exact restore
    expect(page.locator("#busy-off")).not_to_have_attribute("aria-describedby", "busy-status")
    expect(page.locator("#busy-draft")).to_have_value("작성 중")
    expect(page.locator("#busy-draft")).to_have_js_property("readOnly", False)
    expect(page.locator("#busy-save")).to_be_focused()  # focus lost to <body> returns to the opener


def test_busy_scope_ignores_a_second_start_while_busy(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#busy-save").click()
    page.locator("#busy-save").dispatch_event("click")  # disabled, but force the event anyway
    page.locator("#busy-finish").click()
    expect(page.locator("#busy-status")).to_have_text("저장 견본 완료")
    _disabled(expect, page.locator("#busy-save"), False)


def test_background_refresh_never_locks_and_a_save_during_it_runs(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#refresh-start").click()
    _disabled(expect, page.locator("#busy-save"), False)  # a refresh in flight blocks nothing
    page.locator("#busy-save").click()  # the user action starts and is not swallowed
    expect(page.locator("#busy-region")).to_have_attribute("aria-busy", "true")
    page.locator("#refresh-finish").click()  # the older refresh result is dropped, it must not render
    page.locator("#busy-finish").click()
    expect(page.locator("#busy-status")).to_have_text("저장 견본 완료")
    expect(page.locator("#refresh-status")).to_have_text("")


def test_background_refresh_applies_when_nothing_else_runs_and_is_skipped_while_busy(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#refresh-start").click()
    page.locator("#refresh-finish").click()
    expect(page.locator("#refresh-status")).to_have_text("배경 조회 결과 적용")
    page.locator("#busy-save").click()
    page.locator("#refresh-start").click()  # not started while an action runs
    page.locator("#refresh-finish").click()
    page.locator("#busy-finish").click()
    expect(page.locator("#busy-status")).to_have_text("저장 견본 완료")


def test_cause_line_tracks_every_lock_change(gallery):
    from playwright.sync_api import expect
    page = gallery
    line = page.locator("#cause-group [data-cause]")
    expect(line).to_be_hidden()  # empty: hidden by the shared [hidden] rule
    page.locator("#cause-lock").click()
    expect(line).to_be_visible()
    expect(line).to_have_text("합성 견본: 아직 권한을 확인하지 못했습니다")  # one line, one reason for two controls
    line_id = line.get_attribute("id")
    for control in ("#cause-a", "#cause-b"):
        _disabled(expect, page.locator(control), True)
        expect(page.locator(control)).to_have_attribute("aria-describedby", line_id)
    page.locator("#cause-open-b").click()  # someone else enables B: B stops pointing at the line, A still does
    expect(page.locator("#cause-b")).not_to_have_attribute("aria-describedby", line_id)
    expect(page.locator("#cause-a")).to_have_attribute("aria-describedby", line_id)
    expect(line).to_be_visible()
    page.locator("#cause-clear").click()
    expect(line).to_be_hidden()
    for control in ("#cause-a", "#cause-b"):
        _disabled(expect, page.locator(control), False)
        expect(page.locator(control)).not_to_have_attribute("aria-describedby", line_id)


def test_unknown_values_show_the_evidence_label_not_a_default(gallery):
    from playwright.sync_api import expect
    page = gallery
    expect(page.locator("#value-missing")).to_have_text("정보 없음")
    expect(page.locator("#value-zero")).to_have_text("0%")
    expect(page.locator("#value-stale")).to_have_text("42% · 12초 전")
    expect(page.locator("#value-stale")).to_have_attribute("data-state", "delayed")
    expect(page.locator("#value-down")).to_have_text("연결 끊김")
    text = page.locator("#locks .ui-readout").inner_text()
    assert not any(word in text for word in ("undefined", "NaN", "null", "100%", "정상"))


def test_a_cause_set_during_a_run_is_applied_when_it_ends_and_nothing_opens_early(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#bc-run").click()
    expect(page.locator("#bc-region")).to_have_attribute("aria-busy", "true")
    _disabled(expect, page.locator("#bc-b"), True)  # cause.set(b, "") asked to enable it; the run still owns it
    _disabled(expect, page.locator("#bc-a"), True)
    page.locator("#bc-finish").click()
    expect(page.locator("#bc-region")).not_to_have_attribute("aria-busy", "true")
    _disabled(expect, page.locator("#bc-b"), False)  # the recorded target, not the pre-run snapshot
    _disabled(expect, page.locator("#bc-input"), False)  # same for a control locked via `readonly`, not disabled
    expect(page.locator("#bc-input")).to_have_value("초안")
    expect(page.locator("#bc-input")).to_have_js_property("readOnly", False)
    _disabled(expect, page.locator("#bc-a"), True)   # disabled by its cause, not restored to enabled
    line = page.locator("#bc-region [data-cause]")
    expect(line).to_have_text("합성 사유: 처리가 끝나도 A는 닫혀 있습니다")
    expect(page.locator("#bc-a")).to_have_attribute("aria-describedby", line.get_attribute("id"))
    expect(page.locator("#bc-b")).not_to_have_attribute("aria-describedby", line.get_attribute("id"))


def test_cause_line_forgets_controls_that_left_the_document(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#cause-lock").click()
    expect(page.locator("#cause-count")).to_have_text("추적 2개")
    page.locator("#cause-rebuild").click()  # B is replaced by a new element; the old one is gone
    expect(page.locator("#cause-count")).to_have_text("추적 2개")  # not 3: the detached B was pruned
    line = page.locator("#cause-group [data-cause]")
    expect(page.locator("#cause-b")).to_have_attribute("aria-describedby", line.get_attribute("id"))
