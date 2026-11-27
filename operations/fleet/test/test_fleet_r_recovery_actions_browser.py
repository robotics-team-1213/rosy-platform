"""Fleet R recovery and direct command browser flows in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1)."""

import json

import pytest
from browser_harness import browser_tests_enabled
from fleet_cockpit_browser import select_robot
from test_console_queue_inline_browser import API, _open, _robot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

RUN_ID = "11111111-2222-3333-4444-555555555555"
MAP_SHA = "a" * 64


def _confirm_dialog(page):
    dialog = page.locator("dialog.ui-confirm")
    dialog.wait_for(state="visible", timeout=3000)
    dialog.locator('ui-button[kind="irreversible"]').click()


def _wait_post(page, posts, expected_path):
    for _ in range(50):
        page.clock.run_for(100)
        if any(path == expected_path for path, _ in posts):
            return
    raise AssertionError(f"POST {expected_path} not observed in {posts}")


def test_custody_release_happy_and_refused(site):
    from playwright.sync_api import expect

    custody = {
        "reservation_id": "res-101",
        "age_s": 4.0,
        "missing_proof": "CORE standstill",
        "motion_refused_site_wide": True,
        "operator_action": "현장 정지 확인 후 해제",
    }
    state = {"fleet": {"name": "site", "online": 1, "total": 1}, "ts": 0.0,
             "robots": [_robot("rosy_01", named_stop_custody=custody)]}
    api = {**API, "/api/fleet/state": state, "/api/fleet/trips": {"running": None, "trips": [], "open": []}}
    posts = []
    answers = {
        "/api/fleet/robots/rosy_01/named-stop-custody/release": (409, {"detail": {"code": "CUSTODY_STILL_MOVING"}}),
    }
    browser, page, errors = _open(None, site, api, posts, answers)
    try:
        page.locator("#fleet-inbox").click()
        row = page.locator('li[data-key="rosy_01|custody"] > .queue-row')
        expect(row).to_be_visible()
        row.click()
        slot = page.locator('[data-decision-slot="rosy_01|custody"]')
        expect(slot).to_be_visible()

        # Canceled confirmation sends nothing.
        slot.locator('ui-button[data-named-stop-action="release"]').click()
        page.locator('dialog.ui-confirm ui-button[kind="quiet"]').click()
        page.clock.run_for(200)
        assert not posts

        # Refused (409) shows error banner without claiming success.
        slot.locator('ui-button[data-named-stop-action="release"]').click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/robots/rosy_01/named-stop-custody/release")
        expect(slot.locator('[role="alert"]')).to_contain_text("거절")

        # Happy release (200) sends reservation_id and reason, then terminal readback removes the row.
        posts.clear()
        answers["/api/fleet/robots/rosy_01/named-stop-custody/release"] = (200, {"released": True})
        slot.locator('ui-button[data-named-stop-action="release"]').click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/robots/rosy_01/named-stop-custody/release")
        sent = json.loads(posts[-1][1])
        assert sent == {"reservation_id": "res-101", "reason": "현장 정지 확인 완료"}
        expect(slot.locator('[role="status"]')).to_contain_text("해제를 완료")

        state["robots"] = [_robot("rosy_01")]
        page.clock.run_for(1500)
        expect(page.locator('li[data-key="rosy_01|custody"]')).to_have_count(0)
        assert not errors
    finally:
        browser.close()


def test_step_nudge_happy_and_refused(site):
    from playwright.sync_api import expect

    api = {
        **API,
        "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1}, "ts": 0.0, "robots": [_robot("rosy_01")]},
        "/api/fleet/trips": {"running": None, "trips": [], "open": []},
        "/api/fleet/dispatch-control": {"dispatch_enabled": True, "generation": 1},
    }
    posts = []
    answers = {"/api/fleet/robots/rosy_01/step": (409, {"detail": {"code": "STEP_CABLE_INHIBITED", "message": "cable hold"}})}
    browser, page, errors = _open(None, site, api, posts, answers)
    try:
        select_robot(page, "rosy_01")
        page.clock.run_for(400)
        manual_summary = page.locator('#robot-panel details[data-section="manual"] > summary')
        if manual_summary.count():
            manual_summary.click()
            page.clock.run_for(200)
        fwd = page.locator('#robot-panel ui-button[data-manual-step="forward"]')
        expect(fwd).to_be_visible()
        assert fwd.get_attribute("disabled") is None

        # Refused 409 shows refusal in manual banner.
        fwd.click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/robots/rosy_01/step")
        expect(page.locator("#fleet-manual-reason")).to_contain_text("STEP_CABLE_INHIBITED")

        # Happy 200 sends robot-frame forward 0.1m without requiring MANUAL mode.
        posts.clear()
        answers["/api/fleet/robots/rosy_01/step"] = (200, {"state": "SUCCEEDED"})
        fwd.click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/robots/rosy_01/step")
        assert json.loads(posts[-1][1]) == {"direction": "forward", "distance_m": 0.1}
        expect(page.locator("#fleet-manual-reason")).to_contain_text("완료")
        assert not errors
    finally:
        browser.close()


def test_correction_clearance_and_trip_resume_flows(site):
    from playwright.sync_api import expect

    corr_trip = {
        "trip_id": "t-corr",
        "plan_id": "t-corr",
        "robot_id": "rosy_02",
        "state": "running",
        "reason": None,
        "hold": None,
        "detail": {
            "named_stop_operation": {"run_id": RUN_ID},
            "named_stop_dispatch": {"place": "S3", "map_sha256": MAP_SHA},
            "named_stop_precision": {"decision": "HOLD", "reason": "camera_disagrees_with_pose", "forward_m": 0.04, "site_end": [0.745, -0.207]},
        },
    }
    paused_trip = {
        "trip_id": "t-pause",
        "plan_id": "t-pause",
        "robot_id": "rosy_01",
        "state": "running",
        "reason": None,
        "detail": {},
        "hold": {"reason": "fleet_hold", "stop": {"confirmed": True}},
    }
    trips = {"running": corr_trip, "trips": [corr_trip, paused_trip], "open": [corr_trip, paused_trip]}
    api = {
        **API,
        "/api/fleet/state": {"fleet": {"name": "site", "online": 2, "total": 2}, "ts": 0.0,
                             "robots": [_robot("rosy_01"), _robot("rosy_02")]},
        "/api/fleet/trips": trips,
    }
    posts = []
    answers = {
        "/api/fleet/trips/t-corr/correction-clearance": (409, {"detail": {"code": "NAMED_STOP_CORRECTION_SCOPE_CHANGED"}}),
        "/api/fleet/trips/t-corr/cancel": (200, {**corr_trip, "state": "canceled"}),
        "/api/fleet/trips/t-pause/resume": (409, {"detail": {"code": "TRIP_PAUSE_STOP_UNCONFIRMED"}}),
    }
    browser, page, errors = _open(None, site, api, posts, answers)
    try:
        page.locator("#fleet-inbox").click()
        corr_row = page.locator('li[data-key="rosy_02|correction"] > .queue-row')
        corr_row.click()
        slot = page.locator('[data-decision-slot="rosy_02|correction"]')
        corr_btn = slot.locator('ui-button[data-named-stop-action="correction"]')
        expect(corr_btn).to_be_disabled()

        slot.locator('input[data-named-stop-clear="check"]').check()
        expect(corr_btn).not_to_be_disabled()

        # Refused 409 shows alert.
        corr_btn.click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/trips/t-corr/correction-clearance")
        expect(slot.locator('[role="alert"]')).to_contain_text("거절")

        # Happy 202 posts exact CorrectionClearance body.
        posts.clear()
        answers["/api/fleet/trips/t-corr/correction-clearance"] = (202, {"accepted": True})
        corr_btn.click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/trips/t-corr/correction-clearance")
        assert json.loads(posts[-1][1]) == {
            "nav_run_id": RUN_ID,
            "map_sha256": MAP_SHA,
            "forward_m": 0.04,
            "site_end": [0.745, -0.207],
            "cable_and_path_clear": True,
        }
        expect(slot.locator('[role="status"]')).to_contain_text("보냈습니다")

        # Resume refused then happy.
        page.locator('li[data-key="rosy_01|replan"] > .queue-row').click()
        replan_slot = page.locator('[data-decision-slot="rosy_01|replan"]')
        replan_slot.locator('ui-button[data-replan="confirm"]').click()
        if page.locator("dialog.ui-confirm").is_visible():
            _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/trips/t-pause/resume")
        expect(replan_slot.locator('[role="alert"]')).to_contain_text("거절")

        posts.clear()
        answers["/api/fleet/trips/t-pause/resume"] = (200, {**paused_trip, "hold": None})
        replan_slot.locator('ui-button[data-replan="confirm"]').click()
        if page.locator("dialog.ui-confirm").is_visible():
            _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/trips/t-pause/resume")
        expect(replan_slot.locator('[role="status"]')).to_contain_text("재개")

        # Terminal 1-click cancel from correction row (no confirm).
        corr_row.click()
        slot.locator('ui-button[data-named-stop-action="cancel"]').click()
        _wait_post(page, posts, "/api/fleet/trips/t-corr/cancel")
        trips["trips"] = []
        trips["open"] = []
        trips["running"] = None
        page.clock.run_for(1500)
        expect(page.locator('li[data-key="rosy_02|correction"]')).to_have_count(0)
        assert not errors
    finally:
        browser.close()
