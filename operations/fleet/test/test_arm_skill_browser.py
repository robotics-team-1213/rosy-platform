"""Real Chromium arm-skill seats (B1-B3, plan 2026-11-14-rosy-vla-decision-ai-command.md 6.2 R1-R4).

The ten dev-sample cases (applications/fleet/dev/sample/fixtures/arm-ai.json) drive the real console with every
/api call faked at the harness; no robot moves. The exception queue takes only blocking waits and skill exceptions;
the robot row, #detail-skill and the 3D facts line read the same C20 table (skill-state.js); the proposer can never
approve their own proposal, and an approval always carries the CURRENT digest·generation (never an in-place swap).
"""

import json
from pathlib import Path

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, ON_TOP, _open, _shot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

FIXTURE = Path(__file__).resolve().parents[3] / "applications" / "fleet" / "dev" / "sample" / "fixtures" / "arm-ai.json"


def arm_cases(overrides=None):
    """The dev-sample case set plus the digest·generation the served read carries (arm_ai.py)._"""
    out = []
    for index, case in enumerate(json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]):
        row = {**case, "digest": f"{index:016x}", "generation": 1}
        row.update((overrides or {}).get(row["id"], {}))
        out.append(row)
    return out


def arm_api(cases, **extra):
    return {**API, "/api/fleet/arm-proposals": {"sample": True, "label": "샘플 데이터", "cases": cases}, **extra}


def test_only_blocking_waits_and_skill_exceptions_reach_the_exception_queue(site):
    """B1 (계획 6.2 R1): 로봇을 막는 대기 제안과 스킬 이상만 L1에 오른다. 정상·막지 않는 대기는 못 오른다."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, arm_api(arm_cases()), [])
        try:
            queues = page.locator(".queues-panel")
            expect(queues).to_be_visible()
            # 막는 승인 대기(arm-ai-2)만 제안 행으로 오르고, 막지 않는 대기(arm-ai-1)는 오르지 않는다.
            expect(page.locator("#warning-list")).to_contain_text("AI 팔 제안 · 승인 대기 — 하역 셔틀 비우기 · 승인 대기, 로봇을 막음")
            assert "적재 2단 · 승인 대기, 로봇 안 막음" not in queues.inner_text()
            # 스킬 이상: 측정 실패·시간 초과는 주의, 정지는 위험(심각도 축).
            expect(page.locator("#warning-list")).to_contain_text("팔 스킬 · 측정 실패 — 적재 3단 · 측정 실패")
            expect(page.locator("#warning-list")).to_contain_text("팔 스킬 · 시간 초과 · HOLD — 적재 2단 · 시간 초과")
            expect(page.locator("#critical-list")).to_contain_text("팔 스킬 · 정지 · HOLD — 적재 2단 · 비상 정지")
            # 정상 수명주기(승인됨·실행 중·측정 성공)와 막지 않는 대체 제안은 예외가 아니다.
            for absent in ["적재 1단 · 승인됨", "규칙 운반 실행 중", "측정 성공", "대체 제안(근거 낡음)"]:
                assert absent not in queues.inner_text(), absent
            # 제안 행은 펼쳐지면 작업 큐의 같은 제안으로 간다(승인은 L2 자리에서만).
            row = page.locator("#warning-list li").filter(has_text="AI 팔 제안 · 승인 대기")
            expect(row).to_have_count(1)
            row.locator(".queue-row").click()
            link = row.locator("a.ui-disclosure-row")
            expect(link).to_be_visible()
            expect(link).to_have_attribute("href", "/console?view=work&show=pending")
            assert not errors
        finally:
            browser.close()


def test_proposer_can_never_approve_and_an_admit_carries_the_current_digest(site):
    """B2 (계획 6.2 R2, 사용자 결정 1·4): 제안자는 잠긴 단추와 함께 승인하지 못하고, 승인은 현재
    digest·세대를 실어 보낸다. 바뀐 제안은 새 제안 확인으로만 풀린다(자동 재전송 금지)."""
    from playwright.sync_api import expect, sync_playwright

    cases = arm_cases({"arm-ai-1": {"requested_by": "bob"}})  # 로그인한 bob이 요청한 건
    work = {"rows": [], "observed_at": "2026-10-12T00:00:00+00:00", "tasks_available": True,
            "missions_available": True, "truncated_sources": []}
    api = arm_api(cases, **{"/api/fleet/session": {"principal_id": "bob", "role": "operator"},
                            "/api/fleet/work": work})
    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, api, posts)
        try:
            page.goto(site + "/console?view=work")
            for _ in range(80):  # 작업 화면 첫 갱신(5초 주기)까지 시계를 앞으로 민다
                page.clock.run_for(100)
                if page.locator("#work-list ui-button").count() == 10:
                    break
            # 샘플 행마다 샘플 태그가 붙고, 정상 수명주기 행에는 상태 태그가 없다(C22·C20).
            expect(page.locator("#work-list li [data-sample]")).to_have_count(10)
            quiet = page.locator("#work-list li").filter(has_text="적재 2단 · 규칙 운반 실행 중")
            assert quiet.locator("ui-tag[data-state]").count() == 0

            # 제안자 본인(bob)의 건: 잠긴 승인, 이유가 원인 줄에 보이고, 눌러도 아무것도 가지 않는다.
            page.locator('#work-list [data-work-key="arm|arm-ai-1"]').click()
            panel = page.locator("#arm-proposal")
            expect(panel).to_be_visible()
            admit = page.locator("#arm-proposal-admit")
            expect(admit).to_be_disabled()
            reason = "제안자는 자기 제안을 승인할 수 없습니다"
            described = admit.get_attribute("aria-describedby")
            assert reason in page.locator(f"#{described}").inner_text()
            expect(page.locator("#arm-proposal ui-tag[data-state=locked]")).to_be_visible()
            admit.click(force=True)
            assert not posts

            # 남의 건은 기명 승인으로만: 확인 대화상자를 지나 현재 digest·세대를 실어 보낸다.
            page.locator("#work-list ui-button").filter(has_text="arm-ai-2").click()
            expect(admit).to_be_enabled()
            admit.click()
            page.locator("dialog.ui-confirm ui-button[kind=quiet]").click()  # 취소는 아무것도 보내지 않는다
            assert not posts

            def admit_route(route):
                body = route.request.post_data_json
                wanted = next(item for item in cases if item["id"] == "arm-ai-2")
                assert body == {"expected_proposal_digest": wanted["digest"], "expected_generation": wanted["generation"]}
                posts.append(("admit", body))
                wanted.update(lifecycle="approved", digest="f" * 16, generation=2)  # 승인 뒤 세대가 지난다
                route.fulfill(json=wanted)
            page.route("**/api/fleet/arm-proposals/arm-ai-2/admit", admit_route)
            admit.click()
            page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            for _ in range(50):
                page.clock.run_for(100)
                if posts:
                    break
            assert len(posts) == 1, posts
            page.clock.run_for(2000)  # 갱신 폴링이 승인된 상태를 다시 그린다
            expect(page.locator("#arm-proposal-state")).to_contain_text("승인됨 · 시작 대기")
            expect(admit).to_be_hidden()  # 승인 대기가 아니면 승인할 것이 없다

            # 바뀐 제안(409): 사유를 적고 자동으로 다시 보내지 않는다.
            page.locator("#work-list ui-button").filter(has_text="arm-ai-10").click()
            expect(admit).to_be_visible()  # 대체 제안은 새 승인이 필요한 새 줄이다
            expect(page.locator("#arm-proposal-facts")).to_contain_text("arm-ai-9의 대체 제안 · 새 승인이 필요합니다")

            def changed(route):
                posts.append(("changed", route.request.post_data_json))
                route.fulfill(status=409, json={"detail": {"code": "PROPOSAL_CHANGED"}})
            page.route("**/api/fleet/arm-proposals/arm-ai-10/admit", changed)
            admit.click()
            page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
            for _ in range(50):
                page.clock.run_for(100)
                if len(posts) == 2:
                    break
            expect(admit).to_be_disabled()
            described = admit.get_attribute("aria-describedby")
            assert "제안이 바뀌었습니다 · 새 제안을 다시 확인하세요" in page.locator(f"#{described}").inner_text()
            admit.click(force=True)
            assert len(posts) == 2, posts
            assert not errors
        finally:
            browser.close()


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
            expect(page.locator(".robot-view")).to_have_count(1)
            facts = page.locator(".robot-view .robot-view-facts")
            if lifecycle == "running":
                expect(facts).to_contain_text("규칙 운반")
                expect(facts).to_contain_text("3/5")
            assert not errors
        finally:
            browser.close()
