"""D-540 3 / 7 queue decisions, one scroll and folded cards in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The real Fleet app serves the console and its asset allowlist; every /api call is a fake answer: rosy_01 is
stuck and asks, rosy_02's trip waits at a place for a changed route, rosy_03 is nominal, rosy_04 is offline.
No robot moves. ROSY_SHOT_DIR keeps the screenshots.
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
from fleet.swarm.robots import RobotEndpoint

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]
WIDE = [(1920, 1080), (1440, 900), (1024, 768)]
DECISIONS = ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"]


def _robot(robot_id, online=True, safety=None, **extra):
    battery = {"evidence": "fresh", "sample_age_s": 0.2, "stale_after_s": 5, "percent": 80, "level": "ok",
               "charging_state": "unknown"}
    row = {"robot_id": robot_id, "online": online, "goal": None, "queued": None, "yielding": None, "error": None,
           "power_health_age_s": 0.3, "power_health": {"battery": battery},
           "state": {"robot_id": robot_id, "mode": "LINE_FOLLOW", "navigation": "IDLE",
                     "pose": {"x": 1.0, "y": 1.0, "yaw": 0.0}, "battery": {"percent": 80},
                     "safety": {"estop": False} if safety is None else safety}}
    row.update(extra)
    return row


STUCK = {"robot_id": "rosy_01", "stuck_id": "stuck-abc", "cause": "obstacle_ahead", "phase": "ASKING",
         "held_s": 4.0, "attempts": 0, "max_attempts": 2, "local_enabled": True, "ask_remaining_s": 11.0,
         "front_clearance_m": 0.12, "rear_clearance_m": 0.31, "turn_clearance_m": 0.09, "preview_seq": 812,
         "robot_online": True, "observed_age_s": 0.0, "fleet_answer": None}
HELD = {"trip_id": "t-rosy_02", "plan_id": "t-rosy_02", "robot_id": "rosy_02", "state": "running", "reason": None,
        "detail": {}, "map_version": None, "segment_index": 0, "lap": 1,
        "plan": {"segments": [], "places": [], "actions": []},
        "hold": {"reason": "replan", "map_version": 4, "length_m": 3.2, "eta_s": 40,
                 "plan": {"segments": [], "places": ["a", "b"], "actions": []}}}
OFFLINE = _robot("rosy_04", online=False, error={"reachable": False, "code": "ConnectError"})
OFFLINE["state"] = None
API = {
    "/api/fleet/session": {"principal_id": "bob", "role": "operator"},
    "/api/fleet/state": {"fleet": {"name": "site", "online": 3, "total": 4}, "ts": 0.0,
                         "robots": [_robot("rosy_01", line_stuck=STUCK), _robot("rosy_02"), _robot("rosy_03"),
                                    OFFLINE]},
    "/api/fleet/traffic": {"map_version": None, "block_length_m": {}, "units": [], "loop_capacity": [],
                           "wait_cycle": None, "robots": [{"robot_id": "rosy_02", "authority_end_m": 0.5,
                                                           "waiting_for": [], "lap": 1, "trip_state": "running"}]},
    "/api/fleet/trips": {"running": HELD, "trips": [HELD], "open": [HELD]},
    "/api/fleet/formation": {"active": False, "state": "IDLE", "leader": None, "formation": None, "spacing": None,
                             "assignment": {}, "reason": None, "pending_triggers": [], "stream_evidence": {},
                             "relay": None},
}

# Elements that scroll on their own right now (the document is reported separately).
SCROLLERS = """() => [...document.querySelectorAll('body *')].filter((node) => {
  const y = getComputedStyle(node).overflowY;
  return (y === 'auto' || y === 'scroll') && node.scrollHeight > node.clientHeight + 1;
}).map((node) => node.id || node.className)"""


@pytest.fixture
def site():
    robot = FakeRobot("rosy_01")
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [robot])
    app = create_app(console, console_token="operator-token", web_common=ROOT / "shared" / "web")
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


def _open(playwright, origin, api, posts, answers=None, size=(1440, 900)):
    options = launch_options()
    options["args"] = [f"--explicitly-allowed-ports={urlparse(origin).port}"]
    browser = playwright.chromium.launch(**options)
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    def serve(route):
        request = route.request
        path = urlparse(request.url).path
        if request.method != "GET":
            posts.append((path, request.post_data))
            status, body = (answers or {}).get(path, (404, {"detail": "no such api"}))
            route.fulfill(status=status, json=body)
        elif path in api:
            route.fulfill(json=api[path])
        else:
            route.fulfill(status=404, json={"detail": "no such api"})

    page.route("**/api/**", serve)
    page.clock.install()
    page.goto(origin + "/console")
    page.clock.run_for(2500)  # state, traffic and trips polls
    return browser, page, errors


def _shot(page, name):
    if out := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(out) / name))


def test_decision_buttons_show_at_rail_scroll_zero_and_the_rail_is_the_one_scroll(site):
    """D-540 7: at 1920, 1440 and 1024 the open stuck row's five answers are on screen with the rail at
    scroll 0, the document does not scroll and the queue and roster have no scroll of their own. 390 is one
    column: the document scrolls, nothing inside it does. Queue text is never cut (wrapping is fine)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, [])
        for width, height in [*WIDE, (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1500)
            _shot(page, f"console-{width}x{height}.png")
            slot = page.locator('[data-decision-slot="rosy_01|stuck"]')
            assert slot.is_visible(), width
            if width >= 1024:
                assert page.evaluate("document.querySelector('.console-secondary').scrollTop") == 0
                assert page.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), width
                for decision in DECISIONS:
                    box = slot.locator(f'ui-button[data-decision="{decision}"]').bounding_box()
                    assert box and box["y"] >= 0 and box["y"] + box["height"] <= height, (width, decision, box)
                assert set(page.evaluate(SCROLLERS)) <= {"console-primary", "console-secondary"}, (width, page.evaluate(SCROLLERS))
            else:
                assert page.evaluate(SCROLLERS) == [], page.evaluate(SCROLLERS)
            assert page.evaluate("""() => [...document.querySelectorAll('.issue-list li, .queue-row')]
              .every((node) => node.scrollWidth <= node.clientWidth + 1)"""), width
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["y"] >= 0 and stop["y"] + stop["height"] <= height, width
        assert page.locator("#stuck-panel").count() == 0 and page.locator("#roster-toggle").count() == 0
        assert not errors
        browser.close()


def test_one_queue_row_open_at_a_time_and_the_replan_confirm_round_trips(site):
    """D-540 3: the most urgent decision opens first; opening the replan row closes it; `바뀐 경로로 계속`
    posts confirm-replan for that trip and the stuck answers send unchanged values."""
    from playwright.sync_api import sync_playwright

    posts = []
    answers = {"/api/fleet/trips/t-rosy_02/confirm-replan": (200, {**HELD, "hold": None}),
               "/api/fleet/robots/rosy_01/line-stuck/claim": (200, {"ok": True}),
               "/api/fleet/robots/rosy_01/line-stuck/decision": (200, {"result": {"outcome": "hold"}})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, posts, answers)
        stuck_row = page.locator('li[data-key="rosy_01|stuck"] > .queue-row')
        replan_row = page.locator('li[data-key="rosy_02|replan"] > .queue-row')
        assert stuck_row.get_attribute("aria-expanded") == "true"
        assert replan_row.get_attribute("aria-expanded") == "false"
        page.locator('[data-decision-slot="rosy_01|stuck"] ui-button[data-decision="WAIT"]').click()
        page.clock.run_for(300)
        assert ("/api/fleet/robots/rosy_01/line-stuck/decision",
                json.dumps({"stuck_id": "stuck-abc", "decision": "WAIT"}, separators=(",", ":"))) in posts

        replan_row.click()
        page.clock.run_for(1500)  # the choice survives a poll
        assert replan_row.get_attribute("aria-expanded") == "true"
        assert stuck_row.get_attribute("aria-expanded") == "false"
        slot = page.locator('[data-decision-slot="rosy_02|replan"]')
        assert "바뀐 경로 3.2 m" in slot.inner_text()
        _shot(page, "console-replan-1440x900.png")
        slot.locator('ui-button[data-replan="confirm"]').click()
        for _ in range(50):  # the answer lands on the real network clock
            page.clock.run_for(100)
            if "바뀐 경로로 계속합니다" in slot.inner_text():
                break
        assert ("/api/fleet/trips/t-rosy_02/confirm-replan", None) in posts
        assert "바뀐 경로로 계속합니다" in slot.inner_text()
        assert not errors
        browser.close()


def test_cards_fold_when_nominal_and_the_four_must_expand_states_stay_open(site):
    """D-540 3: a nominal card is one line (name, trip line, battery) and opens on click; offline, latched
    E-stop, safety not nominal and calibration in progress stay open with no fold control."""
    from playwright.sync_api import sync_playwright

    api = {**API, "/api/fleet/trips": {"running": None, "trips": [], "open": []},
           "/api/fleet/state": {"fleet": {"name": "site", "online": 4, "total": 5}, "ts": 0.0, "robots": [
               _robot("nominal"), OFFLINE, _robot("latched", safety={"estop": True}),
               _robot("unknown", safety={}), _robot("calib", calibration={"label": "카메라 보정", "holder": "kim"})]}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        card = page.locator('#roster article[data-robot-id="nominal"]')
        assert card.get_attribute("data-collapsed") == ""
        assert "80%" in card.inner_text()
        for robot_id in ("rosy_04", "latched", "unknown", "calib"):
            must = page.locator(f'#roster article[data-robot-id="{robot_id}"]')
            assert must.get_attribute("data-collapsed") is None, robot_id
            assert must.locator(".robot-fold").count() == 0, robot_id
        card.locator(".robot-line").click()
        page.clock.run_for(1500)
        assert card.get_attribute("data-collapsed") is None
        card.locator(".robot-fold").click()
        assert card.get_attribute("data-collapsed") == ""
        _shot(page, "console-cards-1440x900.png")
        assert not errors
        browser.close()


def test_the_open_stuck_row_shows_its_evidence_picture_below_the_answers(site):
    """D-577 8: the stuck row carries the one camera picture Fleet holds for that stuck, with its frame and
    age; the five answers stay on screen at rail scroll 0 (D-540 7) because the picture sits below them."""
    from playwright.sync_api import sync_playwright

    preview = {"robot_id": "rosy_01", "stuck_id": "stuck-abc", "sequence": 812, "source": "front",
               "media_type": "image/jpeg", "age_s": 0.4, "jpeg_base64": "/9j/2Q=="}
    api = {**API, "/api/fleet/robots/rosy_01/line-stuck/evidence": preview}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [], size=(1024, 768))
        page.clock.run_for(1500)
        slot = page.locator('[data-decision-slot="rosy_01|stuck"]')
        image = slot.locator(".stuck-evidence img")
        assert image.get_attribute("src").startswith("data:image/jpeg;base64,")
        assert "앞 카메라 #812" in slot.locator(".stuck-evidence figcaption").inner_text()
        for decision in DECISIONS:
            box = slot.locator(f'ui-button[data-decision="{decision}"]').bounding_box()
            assert box and box["y"] + box["height"] <= 768, (decision, box)
        _shot(page, "console-stuck-evidence-1024x768.png")
        assert not errors
        browser.close()


def test_the_deadlock_row_shows_fleet_and_ai_and_acts_only_through_the_trip_routes(site):
    """D-577 (d): a wait-cycle row opens on Fleet's resolver decision and the AI facts (shadow). `바뀐 경로로 계속`
    posts confirm-replan, `운행 취소` posts cancel (no confirm step), `로봇 카드 열기` opens the card and posts
    nothing. No other route is called."""
    from playwright.sync_api import sync_playwright

    running = {**HELD, "trip_id": "t-rosy_03", "plan_id": "t-rosy_03", "robot_id": "rosy_03", "hold": None}
    cycle = ["rosy_02", "rosy_03"]
    api = {**API,
           "/api/fleet/traffic": {**API["/api/fleet/traffic"], "wait_cycle": cycle, "resolver": [
               {"robot_id": "rosy_02", "trigger": "wait_cycle", "decision": "replan", "cycle": cycle,
                "blocked_edges": ["e1"]},
               {"robot_id": "rosy_03", "trigger": "wait_cycle", "decision": "wait", "cycle": cycle}]},
           "/api/fleet/trips": {"running": HELD, "trips": [HELD, running], "open": [HELD, running]},
           "/api/fleet/ai": {"status": {"state": "present"}, "proposals": [], "facts": [
               {"kind": "wait_cycle_confirmed", "robot_ids": cycle, "value": {"held_s": 4.0}, "confidence": 0.9,
                "evidence": {}, "source": "analyzer:traffic_watch@1", "observed_at": 0, "ttl_s": 3,
                "stage": "shadow"}]}}
    posts = []
    answers = {"/api/fleet/trips/t-rosy_02/confirm-replan": (200, {**HELD, "hold": None}),
               "/api/fleet/trips/t-rosy_03/cancel": (200, {**running, "state": "canceled"})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers)
        page.clock.run_for(1500)

        def slot_of(robot_id):
            page.locator(f'li[data-key="{robot_id}|deadlock"] > .queue-row').click()
            page.clock.run_for(300)
            return page.locator(f'[data-decision-slot="{robot_id}|deadlock"]')

        slot = slot_of("rosy_02")
        text = slot.inner_text()
        assert "rosy_02 · 해결기 다른 길 계획" in text and "rosy_03 · 해결기 다른 로봇 대기" in text
        assert "AI 참고 · 교착 확인 (모두 멈춤) · rosy_02, rosy_03 · 신뢰도 90%" in text
        _shot(page, "console-deadlock-1440x900.png")
        slot.locator('ui-button[data-replan="confirm"]').click()
        for _ in range(50):
            page.clock.run_for(100)
            if ("/api/fleet/trips/t-rosy_02/confirm-replan", None) in posts:
                break
        assert ("/api/fleet/trips/t-rosy_02/confirm-replan", None) in posts

        card = page.locator('#roster article[data-robot-id="rosy_03"]')
        card.locator(".robot-fold").click()
        assert card.get_attribute("data-collapsed") == ""
        slot = slot_of("rosy_03")
        assert slot.locator('ui-button[data-replan="confirm"]').get_attribute("reason") == "확인할 바뀐 경로가 없습니다"
        slot.locator('ui-button[data-replan="cancel"]').click()
        for _ in range(50):
            page.clock.run_for(100)
            if ("/api/fleet/trips/t-rosy_03/cancel", None) in posts:
                break
        assert ("/api/fleet/trips/t-rosy_03/cancel", None) in posts
        before = list(posts)
        page.locator('[data-decision-slot="rosy_03|deadlock"] ui-button[data-replan="card"]').click()
        page.clock.run_for(300)
        assert card.get_attribute("data-collapsed") is None
        assert posts == before
        assert {path for path, _ in posts} <= {"/api/fleet/trips/t-rosy_02/confirm-replan",
                                                "/api/fleet/trips/t-rosy_03/cancel"}
        assert not errors
        browser.close()
