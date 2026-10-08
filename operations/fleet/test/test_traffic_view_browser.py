"""D-517 10 (M1b) traffic view in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The real Fleet app serves the pages and the asset allowlist; every /api call is a fake answer:
two robots on a square loop, one junction zone held by rosy_01 and rosy_02 waiting at its entry.
No robot moves. ROSY_SHOT_DIR keeps the screenshots (1920x1080, 1280x800, 390x844).
"""

import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, launch_options, safe_listener

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]
SIZES = [(1920, 1080), (1280, 800), (390, 844)]

PLACES = [{"id": "j_sw", "name": "남서", "x": 0, "y": 0, "kind": "junction"},
          {"id": "j_se", "name": "남동", "x": 2, "y": 0, "kind": "junction"},
          {"id": "j_ne", "name": "북동", "x": 2, "y": 1.2, "kind": "junction"},
          {"id": "j_nw", "name": "북서", "x": 0, "y": 1.2, "kind": "junction"},
          {"id": "start_s", "name": "출발-남", "x": 0.5, "y": 0, "yaw": 0, "kind": "start"},
          {"id": "start_n", "name": "출발-북", "x": 1.5, "y": 1.2, "yaw": 3.14159, "kind": "start"}]
EDGES = [{"id": eid, "from": a, "to": b, "polyline": line, "direction": "one_way", "drive_mode": "lane",
          "width_m": 0.2, "speed_cap_mps": 0.2}
         for eid, a, b, line in (("east", "j_sw", "j_se", [[0, 0], [2, 0]]),
                                 ("ring_e", "j_se", "j_ne", [[2, 0], [2, 1.2]]),
                                 ("west", "j_ne", "j_nw", [[2, 1.2], [0, 1.2]]),
                                 ("ring_w", "j_nw", "j_sw", [[0, 1.2], [0, 0]]))]
ACTIVE = {"version": 4, "activated_by": "bob", "activated_at": 0,
          "map": {"schema": "rosy.site_map/1", "map_id": "demo", "places": PLACES, "edges": EDGES, "view_turn_deg": 0}}


def _unit(uid, state="FREE", holders=(), waiting=(), zone=False):
    return {"id": uid, "capacity": 1, "zone": zone, "two_way": False, "state": state,
            "holders": list(holders), "waiting": list(waiting)}


TRAFFIC = {
    "map_version": 4,
    "block_length_m": {"east": 0.667, "ring_e": 1.2, "west": 0.667, "ring_w": 1.2},
    "units": [_unit("east#0"), _unit("east#1", "OCCUPIED", ["rosy_02"]), _unit("east#2", "OCCUPIED", ["rosy_02"]),
              _unit("ring", "OCCUPIED", ["rosy_01"], ["rosy_02"], zone=True),
              _unit("west#0", "GRANTED", ["rosy_01"]), _unit("west#1"), _unit("west#2"), _unit("ring_w#0")],
    "robots": [{"robot_id": "rosy_01", "authority_end_m": 1.867, "waiting_for": [], "lap": 3, "trip_state": "running"},
               {"robot_id": "rosy_02", "authority_end_m": 1.95, "waiting_for": ["rosy_01"], "lap": 1,
                "trip_state": "running"}],
    "loop_capacity": [{"edges": ["east", "ring_e", "ring_w", "west"], "capacity": 3, "robots": ["rosy_01", "rosy_02"]}],
    "wait_cycle": None,
}


def _trip(robot_id, segments):
    return {"trip_id": f"t-{robot_id}", "plan_id": f"t-{robot_id}", "robot_id": robot_id, "state": "running",
            "reason": None, "detail": {}, "map_version": 4, "hold": None, "repeat": True, "lap": 1,
            "plan": {"segments": segments, "places": [], "actions": []}, "segment_index": 0,
            "pose": {"state": "LOCALIZED", "source": "sighting"}, "created_at": 0, "updated_at": 0}


OPEN = [_trip("rosy_01", [{"edge_id": "ring_e", "forward": True, "s_from": 0.6, "s_to": 1.2},
                          {"edge_id": "west", "forward": True, "s_from": 0, "s_to": 2}]),
        _trip("rosy_02", [{"edge_id": "east", "forward": True, "s_from": 0.5, "s_to": 2},
                          {"edge_id": "ring_e", "forward": True, "s_from": 0, "s_to": 1.2}])]


def _robot(robot_id, x, y, yaw):
    battery = {"evidence": "fresh", "sample_age_s": 0.2, "stale_after_s": 5, "percent": 80, "level": "ok",
               "charging_state": "unknown"}
    return {"robot_id": robot_id, "online": True, "goal": None, "queued": None, "yielding": None, "error": None,
            "power_health_age_s": 0.3, "power_health": {"battery": battery},
            "state": {"robot_id": robot_id, "mode": "LINE_FOLLOW", "navigation": "IDLE",
                      "pose": {"x": x, "y": y, "yaw": yaw}, "battery": {"percent": 80}, "safety": {"estop": False}}}


API = {
    "/api/fleet/session": {"principal_id": "bob", "role": "operator"},
    "/api/fleet/state": {"fleet": {"name": "site", "online": 2, "total": 2}, "ts": 0.0,
                         "robots": [_robot("rosy_01", 2.0, 0.6, 1.57), _robot("rosy_02", 1.6, 0.0, 0.0)]},
    "/api/fleet/site-map": {"maps": [{"map_id": "demo", "polygon_m": [[-0.3, -0.3], [2.3, -0.3], [2.3, 1.5], [-0.3, 1.5]],
                                      "bounds_m": {"min_x": -0.3, "max_x": 2.3, "min_y": -0.3, "max_y": 1.5},
                                      "sources": [{"source_id": "cam-1"}]}]},
    "/api/fleet/site-map/active": ACTIVE,
    "/api/fleet/site-map/draft": {"map": None, "revision": None},
    "/api/fleet/calibrations": {"calibrations": []},
    "/api/fleet/traffic": TRAFFIC,
    "/api/fleet/trips": {"running": OPEN[1], "trips": OPEN, "open": OPEN},
    "/api/fleet/formation": {"active": False, "state": "IDLE", "leader": None, "formation": None, "spacing": None,
                             "assignment": {}, "reason": None, "pending_triggers": [], "stream_evidence": {},
                             "relay": None},
}


@pytest.fixture
def site(tmp_path):
    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, console_token="operator-token", task_service=tasks,
                     web_common=ROOT / "shared" / "web", start_task_dispatcher=False)
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        yield origin
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def _open(playwright, origin, path, posts, answers=None):
    options = launch_options()
    options["args"] = [f"--explicitly-allowed-ports={urlparse(origin).port}"]
    browser = playwright.chromium.launch(**options)
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    def serve(route):
        request = route.request
        api = urlparse(request.url).path
        if request.method != "GET":
            posts.append((api, request.post_data))
            status, body = (answers or {}).get(api, (404, {"detail": "no such api"}))
            route.fulfill(status=status, json=body)
        elif api in API:
            route.fulfill(json=API[api])
        else:
            route.fulfill(status=404, json={"detail": "no such api"})

    page.route("**/api/**", serve)
    page.clock.install()
    page.goto(origin + path)
    return browser, page, errors


def _shots(page, name, fits=False):
    out = os.environ.get("ROSY_SHOT_DIR")
    for width, height in SIZES:
        page.set_viewport_size({"width": width, "height": height})
        page.clock.run_for(1500)  # a poll and a redraw at this size
        if out:
            page.screenshot(path=str(Path(out) / f"{name}-{width}x{height}.png"), full_page=True)
        if fits and (width, height) == (1920, 1080):  # D-517 10: the console never scrolls at 1920x1080
            fit = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll(
                '.console-secondary > *, .console-primary > *')].map((n) => [n.className || n.tagName,
                Math.round(n.getBoundingClientRect().height)]))""")
            overflow = page.evaluate("document.documentElement.scrollHeight - innerHeight")
            assert overflow <= 1, f"1920x1080 scrolls {overflow}px: {fit}"


def test_console_traffic_layer_card_line_and_queue_row(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, "/console", posts)
        try:
            expect(page.locator("#user-role")).to_contain_text("bob")
            page.clock.run_for(1500)  # the first 1 s traffic poll
            expect(page.locator("#traffic-toggle")).to_be_visible(timeout=15000)
            page.wait_for_function("() => window.__trafficLayer?.zones === 1", timeout=15000)
            assert page.evaluate("window.__trafficLayer") == {"bands": 4, "zones": 1, "ticks": 2, "convoys": 0}
            expect(page.locator("#legend-traffic")).to_be_visible()
            # The merge wait becomes a 주의 row after merge_max_wait_s (20 s); a block wait alone is no row.
            expect(page.locator("#warning-list")).not_to_contain_text("합류 대기")
            page.clock.run_for(22000)
            expect(page.locator("#warning-list")).to_contain_text("rosy_02: 합류 대기")
            expect(page.locator('#roster article[data-robot-id="rosy_02"] .trip-line')).to_have_text(
                "반복 운행 1바퀴째 · 교차로 대기 · rosy_01 통과 중")
            _shots(page, "console-traffic", fits=True)
            page.set_viewport_size({"width": 1920, "height": 1080})
            before = page.locator("#map-canvas").evaluate("c => c.toDataURL()")
            page.locator("#traffic-toggle").click()
            expect(page.locator("#traffic-toggle")).to_have_attribute("aria-pressed", "false")
            expect(page.locator("#traffic-toggle")).to_have_text("교통 끔")
            expect(page.locator("#legend-traffic")).to_be_hidden()
            assert page.locator("#map-canvas").evaluate("c => c.toDataURL()") != before
            page.locator("#traffic-toggle").click()
            expect(page.locator("#legend-traffic")).to_be_visible()
            assert not posts, posts
            assert not errors, errors
        finally:
            browser.close()


def test_site_map_repeat_start_pairs_robot_and_start_place(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    loop_full = {"code": "TRIP_LOOP_FULL", "detail": {"robots": 4, "capacity": 3, "held_per_robot": 3}}
    answers = {"/api/fleet/robots/rosy_02/trip": (200, {"plan_id": "p-9", "map_version": 4, "segments": [],
                                                       "places": [], "actions": [], "length_m": 0, "eta_s": 0}),
               "/api/fleet/trips/p-9/start": (422, {"detail": loop_full})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, "/console/site-map", posts, answers)
        try:
            page.locator("#credential input").fill("operator-token")
            page.locator("#connect").click()
            expect(page.locator("#session")).to_contain_text("bob")
            page.clock.run_for(1500)
            expect(page.locator("#trip-loop")).to_have_text("고리 2/3대")
            page.locator("#trip-robot").select_option("rosy_01")
            expect(page.locator("#trip-repeat")).to_be_disabled()  # rosy_01 already runs its trip
            assert page.locator("#trip-repeat").get_attribute("reason") == "이 로봇은 이미 운행 중입니다"
            # The running line names the selected robot's trip; a third robot is not in this fake.
            page.locator("#trip-robot").select_option("rosy_02")
            page.locator("#trip-start-place").select_option("start_s")
            _shots(page, "site-map-run")
            page.set_viewport_size({"width": 1920, "height": 1080})
            api_open = {"running": None, "trips": [], "open": [OPEN[0]]}
            page.route("**/api/fleet/trips", lambda route: route.fulfill(json=api_open))
            page.clock.run_for(1500)
            expect(page.locator("#trip-repeat")).to_be_enabled()
            page.locator("#trip-repeat").click()
            expect(page.locator("#notice")).to_contain_text("운행 거절")
            expect(page.locator("#notice")).to_contain_text("고리 4/3대")
            assert [path for path, _ in posts] == ["/api/fleet/robots/rosy_02/trip", "/api/fleet/trips/p-9/start"]
            assert json.loads(posts[0][1]) == {"to": "start_s", "via": ["start_n"], "repeat": True}
            assert not errors, errors
        finally:
            browser.close()
