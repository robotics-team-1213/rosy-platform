"""C20/C21/A3 on the served gallery: skill states, source-separated evidence lines, sample tag, refused self-approval, 3D skill text."""

import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
from gallery_fixture import gallery  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


def test_skill_states_use_the_table_words_and_icons(gallery):
    from playwright.sync_api import expect
    page = gallery
    case = lambda name: page.locator(f'#skill-states [data-skill-case="{name}"]')  # noqa: E731
    expect(case("s1")).to_contain_text("승인 대기")
    assert case("s1").locator("ui-tag").count() == 0, "a calm waiting proposal has no tag"
    expect(case("s2").locator("ui-tag")).to_have_attribute("data-state", "caution")
    for name in ("s3", "s4", "s5", "s6"):
        assert case(name).locator("ui-tag").count() == 0, f"{name}: normal states are quiet"
    expect(case("s4")).to_contain_text("실행 중 2/5")
    expect(case("s5")).to_contain_text("act-pick@01234567")
    expect(case("s5")).not_to_contain_text("가드")
    expect(case("s8").locator("ui-tag")).to_have_attribute("data-state", "danger")
    assert case("s8").locator("ui-tag svg, ui-tag .ui-icon").count() >= 1
    assert case("s8").locator("ui-tag").inner_html() != case("s9").locator("ui-tag").inner_html(), "E-stop and owner HOLD use different icons"
    expect(case("s10").locator("ui-tag")).to_have_attribute("data-state", "caution")
    expect(case("s11")).to_contain_text("대체 제안됨 · 승인 필요")
    expect(case("s12")).to_contain_text("정보 없음")
    expect(case("s12").locator("ui-tag")).to_have_attribute("data-state", "unknown")


def test_evidence_lines_never_show_a_model_value_as_a_measurement(gallery):
    from playwright.sync_api import expect
    page = gallery
    first = page.locator('[data-evidence-case="측정이 앞, 모델 값은 뒤"] .evidence-line')
    assert first.locator("> span").evaluate_all("els => els.map(e => e.dataset.source)") == ["ledger", "measured", "model"]
    expect(first.locator('[data-source=model]')).to_contain_text("모델 자체 값")
    expect(first.locator('[data-source=model]')).to_contain_text("(측정 아님)")
    expect(first.locator('[data-source=model] b')).not_to_have_text("측정")
    assert first.locator("ui-tag").count() == 0, "a fresh line is quiet"
    stale = page.locator('[data-evidence-case="낡은 근거"] .evidence-line')
    expect(stale.locator("ui-tag")).to_have_attribute("data-state", "delayed")
    expect(stale.locator("ui-tag")).to_contain_text("지연 · 42초 전")
    unknown = page.locator('[data-evidence-case="값 없음·출처 없음"] .evidence-line')
    expect(unknown.locator("ui-tag")).to_have_attribute("data-state", "unknown")
    expect(unknown.locator('[data-source=unknown]')).to_contain_text("출처 정보 없음")
    assert "측정" not in unknown.inner_text()


def test_every_sample_area_says_sample_data_and_self_approval_is_refused(gallery):
    from playwright.sync_api import expect
    page = gallery
    for card in ("#skill-states-card", "#evidence-lines-card", "#self-approval-card", "#ai-skill-3d"):
        expect(page.locator(f"{card} ui-tag[data-sample], article:has({card}) ui-tag[data-sample]").first).to_have_text("샘플 데이터")
    button = page.locator("#self-approval-mount ui-button")
    assert button.evaluate("el => el.disabled || el.hasAttribute('disabled')")
    expect(page.locator("#self-approval-mount ui-tag")).to_have_attribute("data-state", "locked")
    expect(page.locator("#self-approval-mount [data-cause]")).to_contain_text("제안자는 자기 제안을 승인할 수 없습니다")


def test_skill_text_reaches_only_the_3d_facts_line_and_layout_holds(gallery):
    from playwright.sync_api import expect
    page = gallery
    page.locator("#robot-3d").scroll_into_view_if_needed()
    expect(page.locator("#robot-3d-mount")).to_have_attribute("data-drawn", "all", timeout=20000)
    expect(page.locator("#view-arm-skill .robot-view-facts")).to_contain_text("규칙 운반 · 2/5")
    expect(page.locator("#view-arm .robot-view-facts")).not_to_contain_text("규칙 운반")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        Path(output).mkdir(parents=True, exist_ok=True)
        theme = os.environ.get("ROSY_SHOT_THEME", "light")
        page.evaluate("t => document.documentElement.dataset.theme = t", theme)
        page.locator("#ai-skill").screenshot(path=str(Path(output) / f"ai-skill-{theme}-{page.viewport_size['width']}.png"))
