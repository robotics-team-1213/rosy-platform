"""Wave 4 S2: pre-confirm server planTrip preview on the Fleet console map in real Chromium."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_console_queue_inline_browser import API, _open, _robot, _shot, site  # noqa: E402,F401
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

SITE_MAP = {
    "maps": [{
        "map_id": "site_a",
        "polygon_m": [[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]],
        "bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 2.0, "max_y": 1.0},
    }],
}
ACTIVE_MAP = {
    "version": 4,
    "activated_by": "bob",
    "map": {
        "map_id": "site_a",
        "places": [
            {"id": "A", "name": "출발", "kind": "start", "x": 0.0, "y": 0.0},
            {"id": "B", "name": "도착", "kind": "stop", "x": 1.5, "y": 0.5},
        ],
        "edges": [
            {"id": "e1", "from": "A", "to": "B", "direction": "two_way", "polyline": [[0.0, 0.0], [1.5, 0.5]]},
        ],
    },
}
GUIDE = {
    "map_version": 4,
    "robots": [{
        "robot_id": "rosy_01",
        "online": True,
        "body_radius_m": 0.085,
        "pose": {"state": "LOCALIZED", "x": 0.0, "y": 0.0, "yaw": 0.0, "u_m": 0.05, "source": "operator_pin"},
    }],
}
PLAN = {
    "plan_id": "plan-b2",
    "map_version": 4,
    "length_m": 1.58,
    "eta_s": 11,
    "places": ["A", "B"],
    "segments": [{"edge_id": "e1", "forward": True, "s_from": 0.0, "s_to": 1.58}],
    "actions": [],
    "expires_at": 4e9,
    "start_check": {"code": None},
}


def test_site_goal_previews_server_plan_before_confirm_and_cancels_without_start(site):
    """Clicking a place on viaTrip calls POST /trip BEFORE confirm, shows server metrics in dialog,
    canceling posts 0 /start, and confirming posts /start once with no duplicate /trip."""
    from playwright.sync_api import expect, sync_playwright

    robot = _robot("rosy_01")
    robot["state"]["map_id"] = "slam_local"
    robot["state"]["pose"] = {"x": 0.0, "y": 0.0, "yaw": 0.0}
    api = {
        **API,
        "/api/fleet/state": {"fleet": {"name": "site", "online": 1, "total": 1}, "ts": 0.0, "robots": [robot]},
        "/api/fleet/site-map": SITE_MAP,
        "/api/fleet/site-map/active": ACTIVE_MAP,
        "/api/fleet/guide": GUIDE,
        "/api/fleet/traffic": {"map_version": 4, "block_length_m": {}, "units": [],
                               "wait_cycle": None, "loop_capacity": [], "robots": []},
        "/api/fleet/trips": {"running": None, "trips": [], "open": []},
    }
    posts = []
    answers = {
        "/api/fleet/robots/rosy_01/trip": (200, PLAN),
        "/api/fleet/trips/plan-b2/start": (200, {
            "trip_id": "trip-b2", "plan_id": "plan-b2", "robot_id": "rosy_01", "state": "running", "hold": None}),
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers)
        expect(page.locator("#map-stage")).to_have_attribute("data-map-state", "site", timeout=10000)
        page.clock.run_for(1500)
        page.locator('[data-context-tab="status"]').click()
        page.locator("#robot-choice").select_option("rosy_01")
        goal_btn = page.locator('ui-button[data-goal-robot-id="rosy_01"]')
        expect(goal_btn).to_be_enabled(timeout=10000)

        pos = page.evaluate("""async () => {
          const { siteBounds, fitTransform, project } = await import('/console/assets/site-layer.js');
          const r = document.querySelector('#map-canvas').getBoundingClientRect();
          const b = siteBounds({ maps: [{ map_id: 'site_a', polygon_m: [[0,0],[2,0],[2,1],[0,1]] }] });
          return project(fitTransform(b, r.width, r.height, 32), 1.5, 0.5);
        }""")

        goal_btn.click()
        page.locator("#map-canvas").click(position={"x": pos["px"], "y": pos["py"]})
        dialog = page.locator("dialog.ui-confirm")
        for _ in range(50):
            page.clock.run_for(100)
            if dialog.count() == 1:
                break
        expect(dialog).to_have_count(1)
        expect(dialog).to_contain_text("1.58 m")
        expect(dialog).to_contain_text("11 s")
        assert posts == [("/api/fleet/robots/rosy_01/trip", json.dumps({"to": "B"}, separators=(",", ":")))]
        _shot(page, "console-s2-plan-preview-1440x900.png")

        # Canceling never calls /start.
        dialog.locator('ui-button[kind="quiet"]').click()
        expect(dialog).to_have_count(0)
        assert not any(path.endswith("/start") for path, _ in posts)

        # Confirming starts the pre-planned trip with no duplicate POST /trip inside confirm.
        page.locator("#map-canvas").click(position={"x": pos["px"], "y": pos["py"]})
        for _ in range(50):
            page.clock.run_for(100)
            if dialog.count() == 1:
                break
        expect(dialog).to_have_count(1)
        assert [path for path, _ in posts] == [
            "/api/fleet/robots/rosy_01/trip",
            "/api/fleet/robots/rosy_01/trip",
        ]
        page.clock.run_for(5500)
        dialog.locator('ui-button[kind="irreversible"]').click()
        for _ in range(50):
            page.clock.run_for(100)
            if any(path.endswith("/start") for path, _ in posts):
                break
        assert [path for path, _ in posts] == [
            "/api/fleet/robots/rosy_01/trip",
            "/api/fleet/robots/rosy_01/trip",
            "/api/fleet/trips/plan-b2/start",
        ]
        expect(page.locator("#log")).to_contain_text("차로 주행 시작")
        assert not errors
        browser.close()
