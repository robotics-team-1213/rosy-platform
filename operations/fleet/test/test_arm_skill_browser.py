"""Real Chromium arm-skill seats (B3, plan 2026-11-14-rosy-vla-decision-ai-command.md 6.2 R3-R5).

The robot row, #detail-skill and the 3D facts line read the same C20 table (skill-state.js); every /api call is faked at
the harness and no robot moves. The AI arm proposal view (B1/B2) is kept on branch feat/arm-proposal-view until the real
C3 route exists, so its tests are not here.
"""

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


# C20 표 그대로: (수명주기, 로봇 행·상세에 들어갈 글자, 조용한 정상인가)
NINE_STATES = [
    ("proposed", "승인 대기", True),                       # 막지 않는 제안됨·대기는 태그가 없다
    ("waiting_approval", "승인 대기", False),              # 로봇을 막는 대기는 주의
    ("approved", "승인됨 · 시작 대기", True),
    ("running", "실행 중 3/5", True),
    ("measured_success", "측정 성공", True),
    ("measured_failure", "측정 실패", False),
    ("stopped", "정지 · HOLD", False),
    ("timed_out", "시간 초과 · HOLD", False),
    ("fallback_proposed", "대체 제안됨 · 승인 필요", False),
]


@pytest.mark.parametrize("lifecycle,words,quiet", NINE_STATES)
def test_nine_skill_states_reach_the_robot_row_the_detail_slot_and_the_3d_facts(site, lifecycle, words, quiet):
    """B3 (계획 6.2 R3·R4·R5): 아홉 수명주기가 같은 C20 표로 로봇 행 글자와 #detail-skill에 오고,
    정상 진행에는 태그가 하나도 없다. 3D 상태 줄은 실행기·단계 글자만 늘린다(그림은 그대로)."""
    from playwright.sync_api import expect, sync_playwright

    from test_console_queue_inline_browser import _robot

    arm_skill = {"sample": True, "lifecycle": lifecycle, "executor": "ik_chunk", "guard": "ok"}
    if lifecycle == "running":
        arm_skill["step"] = {"n": 3, "of": 5}
    if lifecycle == "measured_success":
        arm_skill["measured"] = "verify_placed"
    if lifecycle == "stopped":
        arm_skill["guard"] = "estop"
    if lifecycle == "waiting_approval":
        arm_skill["blocking"] = True
    robot = _robot("arm_a")
    robot["kind"] = "arm"
    robot["state"]["arm_skill"] = arm_skill
    api = {**API, "/api/fleet/state": {**API["/api/fleet/state"], "robots": [robot]}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            page.locator(".doc-tabs").get_by_role("link", name="작업", exact=True).click()
            row = page.locator("#roster .robot-row").filter(has_text="arm_a")
            expect(row).to_have_count(1)
            expect(row.locator('[data-col="task"]')).to_contain_text(words)
            row.locator("[data-select-robot-id]").click()  # 행 선택 → 상세 카드
            detail = page.locator("#detail-skill")
            expect(detail.locator(".detail-skill-line")).to_contain_text(words)
            expect(detail.locator(".detail-skill-line")).to_contain_text("스킬")
            expect(detail.locator("[data-sample]")).to_have_count(1)  # 샘플 상태는 이름을 밝힌다
            readout = detail.locator(".detail-skill-readout")
            expect(readout).to_contain_text("규칙 운반")
            if lifecycle == "running":
                expect(readout).to_contain_text("3/5")
            if quiet:
                assert detail.locator(".detail-skill-line ui-tag[data-state]").count() == 0, lifecycle
                assert row.locator('[data-col="alarm"] ui-tag').count() == 0, lifecycle
            else:
                expect(detail.locator(".detail-skill-line ui-tag[data-state]")).to_have_count(1)
                expect(row.locator('[data-col="alarm"] ui-tag')).to_have_count(1)
            # 3D 상태 줄: 실행기(·단계) 글자만, 제안 목표를 그리지 않는다.
            expect(page.locator(".robot-detail-3d .robot-view")).to_have_count(1)
            facts = page.locator(".robot-view .robot-view-facts")
            if lifecycle == "running":
                expect(facts).to_contain_text("규칙 운반")
                expect(facts).to_contain_text("3/5")
            assert not errors
        finally:
            browser.close()
