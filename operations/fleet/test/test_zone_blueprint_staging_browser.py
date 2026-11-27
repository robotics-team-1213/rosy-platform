"""Real-Chromium Playwright tests for Zone Blueprint metric slot overlays & 2-click cell staging (PR 4)."""

from __future__ import annotations

import json

import pytest

from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 for Chromium",
)


def _confirm_dialog(page):
    dialog = page.locator("dialog.ui-confirm")
    dialog.wait_for(state="visible")
    dialog.get_by_role("button", name="요청 전송").click()
    dialog.wait_for(state="hidden")


def _wait_post(page, posts, path):
    page.wait_for_function("() => true")
    deadline = 50
    for _ in range(deadline):
        if any(p == path for p, _ in posts):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"POST {path} not observed in {posts!r}")


def _pr4_site_points():
    return {
        "vehicle_stops": [
            {"id": "S3", "name": "하역 S3", "kind": "stop", "port_role": "intake_dropoff",
             "pose": {"x": 0.745, "y": -0.207, "yaw": 3.14159}, "status": "verified", "dispatchable": True},
        ],
        "arm_zones": {
            "tier_height_mm": 32.4,
            "zones": [
                {
                    "id": "yard",
                    "label": "장치 야드",
                    "role": "보관",
                    "grid": {"rows": 3, "columns": 6, "tiers": 3},
                    "arms": ["arm_a", "arm_b"],
                    "status": "planned_unverified",
                    "slots": [
                        {
                            "id": "yard:r1-s1",
                            "label": "1행 1~3열",
                            "row": 1,
                            "slot": 1,
                            "columns": [1, 3],
                            "arms": ["arm_a", "arm_b"],
                            "status": "planned_unverified",
                            "tiers": [
                                {"tier": 1, "id": "yard:r1-s1-t1", "item": "ship-h2r0-l0"},
                                {"tier": 2, "id": "yard:r1-s1-t2", "item": "ship-h2r0-l1"},
                            ],
                        },
                    ],
                },
            ],
        },
        "handoffs": [],
    }


def _pr4_api():
    sp = _pr4_site_points()
    return {
        **API,
        "/api/fleet/site-map/active": {
            "version": 394,
            "map": {
                "map_id": "world_pr4",
                "places": [
                    {"id": "S3", "kind": "stop", "x": 0.745, "y": -0.207, "yaw": 3.14159},
                ],
                "edges": [],
            },
        },
        "/api/fleet/site-points": sp,
        "/api/fleet/site-points?view=full": sp,
        "/api/fleet/pipeline/station-zones": {
            "vehicle": {"front_m": 0.04205, "rear_m": -0.134, "half_width_m": 0.05655},
            "areas": [
                {
                    "id": "yard",
                    "name": "장치 야드",
                    "short_name": "배(야드)",
                    "kind": "cell_zone",
                    "zone_id": "yard",
                    "status": "cad_registered",
                    "polygon": [[0.73, 0.208], [0.86, 0.208], [0.86, 0.524], [0.73, 0.524]],
                },
                {
                    "id": "BELT",
                    "name": "컨베이어 벨트",
                    "short_name": "벨트",
                    "kind": "belt",
                    "status": "cad_registered",
                    "polygon": [[0.748, -0.103], [0.833, -0.103], [0.833, 0.197], [0.748, 0.197]],
                },
            ],
            "staging_bays": [],
            "export_stations": [],
        },
        "/api/fleet/pipeline/cell-tasks": {
            "tasks": [{
                "task_id": "cell-live-1",
                "status": "RUNNING",
                "src_site": "belt",
                "dst_site": "yard:r1-s1-t1",
                "arm_id": "arm_a",
                "cell_id": "cell_ab",
            }],
        },
        "/api/fleet/guide": {
            "robots": [{"robot_id": "rosy_01", "x": 0.745, "y": -0.207, "yaw": 3.14159, "moving": False, "place_id": "S3"}],
        },
    }


def test_zone_blueprint_renders_slot_overlays_and_dispatches_2click_cell_task(site):
    from playwright.sync_api import expect

    posts = []
    answers = {
        "/api/fleet/pipeline/cell-tasks": (422, {"detail": {"code": "INVALID_CELL_SITE"}}),
    }
    browser, page, errors = _open(None, site, _pr4_api(), posts, answers)
    try:
        open_btn = page.locator("#zone-blueprint-open")
        expect(open_btn).to_be_visible()
        open_btn.click()

        panel = page.locator("#zone-blueprint-panel")
        expect(panel).to_be_visible()

        belt_slot = panel.locator('[data-layer="arm-slots"] [data-slot-id="station:belt"]')
        yard_slot = panel.locator('[data-layer="arm-slots"] [data-slot-id="yard:r1-s1"]')
        expect(belt_slot).to_be_visible()
        expect(yard_slot).to_be_visible()
        expect(panel.locator('[data-layer="live-robots"] [data-robot-id="rosy_01"]')).to_be_visible()
        expect(panel.locator('[data-layer="live-tasks"] .zb-task-flow')).to_have_count(1)

        panel.locator("ui-button[data-zb-stage-toggle]").click()
        belt_slot.click()
        expect(belt_slot).to_have_attribute("data-stage-role", "src")
        yard_slot.click()
        expect(yard_slot).to_have_attribute("data-stage-role", "dst")

        panel.locator("select[data-zb-stage-tier]").select_option("2")
        submit = panel.locator("ui-button[data-zb-stage-submit]")
        expect(submit).not_to_be_disabled()

        # Refused 422 keeps selection and shows alert.
        submit.click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/pipeline/cell-tasks")
        expect(panel.locator('.zb-stage-result[role="alert"]')).to_contain_text("거절")

        # Happy 200 dispatches POST /api/fleet/pipeline/cell-tasks and clears selection.
        posts.clear()
        answers["/api/fleet/pipeline/cell-tasks"] = (200, {"ok": True, "task": {"task_id": "cell-staged-2"}})
        submit.click()
        _confirm_dialog(page)
        _wait_post(page, posts, "/api/fleet/pipeline/cell-tasks")
        assert json.loads(posts[-1][1]) == {
            "cell_id": "cell_ab",
            "src_site": "belt",
            "dst_site": "yard:r1-s1-t2",
            "tier": 2,
            "propose": False,
        }
        expect(panel.locator('.zb-stage-result[role="status"]')).to_contain_text("cell-staged-2")
        assert not errors
    finally:
        browser.close()
