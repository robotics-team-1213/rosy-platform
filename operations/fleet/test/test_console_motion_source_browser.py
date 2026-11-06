"""Robot card motion source in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

Fake /api answers only; no robot moves. Each robot carries one proving fact (or none): the card names the
source, a stale or unknown state says 확인 불가, and a robot moving with no known owner raises an attention row.
"""

import copy

from test_console_queue_inline_browser import API, _open, _robot, site  # noqa: F401

from browser_harness import browser_tests_enabled
import pytest

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

FRESH = {"velocity": {"evidence": "fresh", "stale_after_s": 0.5}}


def _moving(robot_id, linear=0.0, mode="IDLE", **state):
    row = _robot(robot_id)
    row["state_age_s"] = 0.3
    row["state"].update({"mode": mode, "velocity": {"linear": linear, "angular": 0.0}, "evidence": FRESH, **state})
    return row


def test_card_names_the_motion_source_and_flags_the_unowned_mover(site):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    stale = _moving("rosy_05", 0.1, "MANUAL")
    stale["state_age_s"] = 30.0
    robots = [
        _moving("rosy_01", 0.1, "NAVIGATION", trip_lease={"lease_id": "l", "trip_id": "t", "holder": "fleet",
                                                           "operator_name": "kim", "since": "x", "expires_in_s": 9}),
        _moving("rosy_02"),  # the shared API fixture holds an open Fleet trip for it
        _moving("rosy_03", 0.05),
        _moving("rosy_04", 0.0, "MANUAL"),
        stale,
        _moving("rosy_06", 0.0, docking={"state": "DOCKING"}),
        _moving("rosy_07"),
    ]
    api = copy.deepcopy(API)
    api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 7, "total": 7}, "ts": 0.0, "robots": robots}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        try:
            def chip(robot_id):
                return page.locator(f'article.robot-summary[data-robot-id="{robot_id}"] [data-motion-source]')
            expect(chip("rosy_01")).to_have_text("배차 운행 · kim")
            expect(chip("rosy_02")).to_have_text("배차 운행")
            expect(chip("rosy_07")).to_have_text("정지 · 대기")
            expect(chip("rosy_03")).to_have_text("원인 불명 이동")
            expect(chip("rosy_04")).to_have_text("수동 모드 · 조종 주체 확인 불가")
            expect(chip("rosy_05")).to_contain_text("이동 출처 확인 불가 · 상태")
            expect(chip("rosy_05")).to_contain_text("초 전 값")
            expect(chip("rosy_06")).to_have_text("도킹 동작 (충전 복귀)")
            summary = lambda rid: page.locator(f'article.robot-summary[data-robot-id="{rid}"]')  # noqa: E731
            expect(summary("rosy_03")).to_contain_text("원인 불명 이동 — Fleet이 모르는 이동입니다")
            expect(summary("rosy_01")).not_to_contain_text("Fleet이 모르는 이동")
            expect(summary("rosy_05")).not_to_contain_text("Fleet이 모르는 이동")  # stale is never promoted to live
            assert not errors, errors
        finally:
            browser.close()
