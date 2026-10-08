"""D-517 9 M3 / 10 convoy view in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The traffic browser fakes (test_traffic_view_browser) with rosy_02 following rosy_01: one thin line
from rosy_01 to rosy_02 on the console map, the card line "대열 · rosy_01 뒤 0.5 m", and the site map
운행 panel's leader choice. ROSY_SHOT_DIR keeps the screenshots (1920x1080, 1280x800, 390x844).
"""

import copy
import json

import pytest
from browser_harness import browser_tests_enabled

import test_traffic_view_browser as base
from test_traffic_view_browser import OPEN, TRAFFIC, _open, _shots, site  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

CONVOY = copy.deepcopy(TRAFFIC)
CONVOY["units"] = [{**unit, "waiting": []} for unit in CONVOY["units"]]
CONVOY["robots"][0].update(front_d_m=0.9, convoy=None)
CONVOY["robots"][1].update(front_d_m=1.7, waiting_for=["rosy_01"],
                           convoy={"leader": "rosy_01", "follows": "rosy_01", "gap_m": 0.5})
TRIPS = [{**OPEN[0], "convoy": None}, {**OPEN[1], "convoy": {"leader": "rosy_01"}}]


@pytest.fixture
def convoy_api(monkeypatch):
    monkeypatch.setitem(base.API, "/api/fleet/traffic", CONVOY)
    monkeypatch.setitem(base.API, "/api/fleet/trips", {"running": TRIPS[1], "trips": TRIPS, "open": TRIPS})


def test_console_draws_the_convoy_line_and_card(site, convoy_api):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, "/console", posts)
        try:
            expect(page.locator("#user-role")).to_contain_text("bob")
            page.clock.run_for(1500)
            page.wait_for_function("() => window.__trafficLayer?.convoys === 1", timeout=15000)
            page.clock.run_for(5000)  # the roster redraws on its state poll with the traffic it holds
            page.get_by_role("button", name="전체 로봇 보기").click()  # healthy robots are folded away
            expect(page.locator('#roster article[data-robot-id="rosy_02"] .trip-line')).to_have_text(
                "반복 운행 1바퀴째 · 대열 · rosy_01 뒤 0.5 m")
            _shots(page, "console-convoy", fits=True)
            assert not posts, posts
            assert not errors, errors
        finally:
            browser.close()


def test_site_map_starts_a_follower_behind_the_chosen_leader(site, convoy_api, monkeypatch):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.setitem(base.API, "/api/fleet/trips", {"running": TRIPS[0], "trips": TRIPS[:1], "open": TRIPS[:1]})
    started = {**TRIPS[1], "robot_id": "rosy_02", "trip_id": "p-9", "state": "started"}
    plan = {"plan_id": "p-9", "map_version": 4, "segments": [], "places": [], "actions": [], "length_m": 0, "eta_s": 0}
    answers = {"/api/fleet/robots/rosy_02/trip": (200, plan), "/api/fleet/trips/p-9/start": (200, started)}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, "/console/site-map", posts, answers)
        try:
            page.locator("#credential input").fill("operator-token")
            page.locator("#connect").click()
            expect(page.locator("#session")).to_contain_text("bob")
            page.clock.run_for(1500)
            page.locator("#trip-robot").select_option("rosy_02")
            page.locator("#trip-start-place").select_option("start_s")
            page.clock.run_for(1500)
            expect(page.locator("#trip-leader option")).to_have_text(["대열 없음 · 혼자 반복 운행", "rosy_01 뒤를 따라감"])
            page.locator("#trip-leader").select_option("rosy_01")
            _shots(page, "site-map-convoy")
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.locator("#trip-repeat").click()
            expect(page.locator("#notice")).to_contain_text("rosy_01 뒤 대열")
            body = {"to": "start_s", "via": ["start_n"], "repeat": True, "convoy": {"leader": "rosy_01"}}
            assert json.loads(posts[0][1]) == body
            assert not errors, errors
        finally:
            browser.close()
