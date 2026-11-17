"""Real Chromium test for per-task pause resume and human-safety hold clearing (Item I)."""

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")


def _cell_tasks_payload(*, hold=True, task_status="PAUSED_HUMAN", proposer="alice"):
    return {
        "tasks": [
            {
                "task_id": "t-pause-1",
                "cell_id": "cell_s",
                "arm_id": "arm_s",
                "status": task_status,
                "paused_by": "safety_watch",
                "paused_reason": "HUMAN_DETECTED_ESTOP" if hold else "HUMAN_CLEARED_AWAITING_RESUME",
                "paused_from_status": "RUNNING",
            }
        ],
        "cells": {
            "cell_s": {"gate": {"phase": "HUMAN_HOLD" if hold else "RELEASED", "paused_by": "safety_watch"}},
            "cell_ab": {"gate": {"phase": "RELEASED"}},
        },
        "human_safety": {
            "active_estop": hold,
            "human_detected": {"cell_s": hold, "cell_ab": False, "all": False},
        },
        "decision_proposals": [
            {"decision_id": "dec-1", "cell": "cell_s", "proposed_by": proposer},
        ],
    }


@pytest.mark.parametrize("size", [(1366, 768), (390, 844)])
def test_cell_hold_clear_keeps_task_paused_until_individual_resume(site, size):
    from playwright.sync_api import expect, sync_playwright

    state = {"hold": True, "task_status": "PAUSED_HUMAN", "proposer": "bob"}
    api = {
        **API,
        "/api/fleet/work": {
            "rows": [], "observed_at": "2026-10-12T00:00:00+00:00",
            "tasks_available": True, "missions_available": True, "truncated_sources": [],
        },
        "/api/fleet/channel-requests": {"rows": []},
    }
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, size=size)
        try:
            def cell_tasks(route):
                route.fulfill(json=_cell_tasks_payload(
                    hold=state["hold"], task_status=state["task_status"], proposer=state["proposer"],
                ))

            def clear_hold(route):
                posts.append(("/api/fleet/pipeline/human-safety-gate/clear", route.request.post_data_json))
                state["hold"] = False
                route.fulfill(json={"ok": True})

            def resume_task(route):
                posts.append(("/api/fleet/pipeline/cell-tasks/t-pause-1/resume", route.request.post_data))
                state["task_status"] = "RUNNING"
                route.fulfill(json={"ok": True})

            page.route("**/api/fleet/pipeline/cell-tasks", cell_tasks)
            page.route("**/api/fleet/pipeline/human-safety-gate/clear", clear_hold)
            page.route("**/api/fleet/pipeline/cell-tasks/t-pause-1/resume", resume_task)
            page.goto(site + "/console?view=work")
            page.clock.run_for(2000)
            for _ in range(25):
                if page.locator("#cell-resume-work").is_visible():
                    break
                page.clock.run_for(100)

            panel = page.locator("#cell-resume-work")
            expect(panel).to_be_visible()
            task_btn = panel.locator("[data-paused-task='t-pause-1'] ui-button")
            expect(task_btn).to_be_disabled()
            task_cause = panel.locator("[data-paused-task='t-pause-1'] ui-status")
            expect(task_cause).to_be_visible()
            expect(task_cause).to_contain_text("셀 홀드 활성 중 · 홀드 해제 후 재개할 수 있습니다")

            # Two-person lock prevents proposer (bob) from approving own decision proposal.
            dec_btn = panel.locator("[data-decision-proposal='dec-1'] ui-button")
            expect(dec_btn).to_be_disabled()
            dec_cause = panel.locator("[data-decision-proposal='dec-1'] ui-status")
            expect(dec_cause).to_be_visible()
            expect(dec_cause).to_contain_text("제안자는 자기 제안을 승인할 수 없습니다")

            # Clear hold does NOT auto-resume the task.
            hold_btn = panel.locator(".cell-hold-row[data-cell-id='cell_s'] ui-button")
            hold_btn.click()
            expect(page.locator("#cell-resume-status")).to_contain_text("홀드 해제됨 · 작업은 각각 재개")
            expect(panel.locator("[data-paused-task='t-pause-1']")).to_be_visible()
            expect(task_btn).to_be_enabled()

            # Resuming requires explicit confirmation and resumes only that task.
            task_btn.click()
            page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
            expect(panel.locator("[data-paused-task='t-pause-1']")).to_have_count(0)
            assert [p[0] for p in posts] == [
                "/api/fleet/pipeline/human-safety-gate/clear",
                "/api/fleet/pipeline/cell-tasks/t-pause-1/resume",
            ]
            assert posts[0][1] == {"cell_id": "cell_s"}
            assert errors == []
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            browser.close()
