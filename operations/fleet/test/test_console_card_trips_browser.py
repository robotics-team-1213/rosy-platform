"""D-540 (d) trips from the 관제 robot card and the 대형·대열 convoy in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The real Fleet app serves the console; every /api call is a fake answer. rosy_01 laps a repeat trip (the
convoy leader), rosy_02 is nominal with camera lane driving on, rosy_03's last trip stopped because the
robot screen took it over (D-541 lease_lost), rosy_04 is offline. No robot moves. ROSY_SHOT_DIR keeps
the screenshots.
"""

import json
import time

import pytest

from test_console_queue_inline_browser import OFFLINE, SCROLLERS, _open, _robot, _shot, site  # noqa: F401
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
NAMED = "이름 있는 운영자 로그인이 필요합니다"
PLACES = [{"id": "A", "name": "북", "kind": "start", "x": 0.0, "y": 0.0, "yaw": 0.0},
          {"id": "B", "name": "남", "kind": "start", "x": 1.0, "y": 0.0, "yaw": 0.0},
          {"id": "X", "name": "교차", "kind": "junction", "x": 0.5, "y": 0.5}]
ACTIVE = {"version": 4, "activated_by": "kim", "map": {"map_id": "m", "places": PLACES, "edges": []}}
LEAD = {"trip_id": "t-1", "plan_id": "t-1", "robot_id": "rosy_01", "state": "running", "reason": None, "detail": {},
        "map_version": 4, "repeat": True, "lap": 2, "convoy": None, "hold": None,
        "plan": {"segments": [], "places": [], "actions": []}}
LOST = {"trip_id": "t-0", "plan_id": "t-0", "robot_id": "rosy_03", "state": "stopped", "reason": "lease_lost",
        "detail": {"lease_reason": "taken_over", "lease_by": "kim-tablet"}, "map_version": 4, "hold": None}
LANE = _robot("rosy_02")
LANE["state"]["line_follow"] = {"mode": "CAMERA_LINE", "state": "TRACKING"}
API = {
    "/api/fleet/session": {"principal_id": "bob", "role": "operator"},
    "/api/fleet/state": {"fleet": {"name": "site", "online": 3, "total": 4}, "ts": 0.0,
                         "robots": [_robot("rosy_01"), LANE, _robot("rosy_03"), OFFLINE]},
    "/api/fleet/site-map/active": ACTIVE,
    "/api/fleet/traffic": {"map_version": 4, "block_length_m": {}, "units": [], "wait_cycle": None,
                           "loop_capacity": [{"edges": ["e1"], "capacity": 3, "robots": ["rosy_01"]}],
                           "robots": [{"robot_id": "rosy_01", "authority_end_m": 0.5, "waiting_for": [], "lap": 2,
                                       "trip_state": "running"}]},
    "/api/fleet/trips": {"running": LEAD, "trips": [LEAD, LOST], "open": [LEAD]},
    "/api/fleet/formation": {"active": False, "state": "IDLE", "leader": None, "formation": None, "spacing": None,
                             "assignment": {}, "reason": None, "pending_triggers": [], "stream_evidence": {},
                             "relay": None},
}
PLAN = {"segments": [{"edge_id": "e1"}], "places": [], "actions": [], "length_m": 2.1, "eta_s": 14,
        "map_version": 4, "expires_at": 4e9}


def _card(page, robot_id):
    return page.locator(f'#roster article[data-robot-id="{robot_id}"]')


def test_running_trip_shows_and_clears_ai_route_warning_without_deadlock(site):
    from playwright.sync_api import expect, sync_playwright

    fact = {"kind": "trip_route_check", "robot_ids": ["rosy_01"], "observed_at": time.time(),
            "ttl_s": 5, "confidence": 0.8, "value": {"status": "OFF_ROUTE", "offset_m": 0.05, "limit_m": 0.03},
            "evidence": {"trip_id": LEAD["trip_id"], "map_version": LEAD["map_version"]}}
    api = {**API, "/api/fleet/ai": {"facts": [fact]}}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts)
        warning = page.locator("#warning-list li").filter(has_text="AI 경로 편차 관찰")
        expect(warning).to_have_count(1)
        expect(warning).to_contain_text("rosy_01")
        expect(warning).to_contain_text("허용 경계보다 2 cm 밖")
        # The real polling request reads the new judgement; no operator action is required.
        api["/api/fleet/ai"] = {"facts": [{**fact, "observed_at": page.evaluate("Date.now() / 1000"),
                                         "value": {"status": "ON_ROUTE"}}]}
        page.clock.run_for(1500)
        expect(warning).to_have_count(0)
        assert not posts and not errors
        browser.close()


def _open_form(page, robot_id):
    card = _card(page, robot_id)
    if card.get_attribute("data-collapsed") is not None:
        card.locator(".robot-line").click()
    card.locator(f'ui-button[data-trip-open="{robot_id}"]').click()
    return card.locator(".card-trip")


def _settle(page, posts, path, count=1):
    for _ in range(50):  # answers land on the real network clock
        page.clock.run_for(100)
        if sum(1 for post in posts if post[0] == path) >= count:
            return


def test_a_trip_and_a_repeat_start_from_the_card(site):  # noqa: F811
    """`운행…` opens the form on the card: destination → `경로 보기` (a preview) → `운행 시작` starts that
    plan; `반복 운행 시작` plans the lap over the start places and starts it. Both use the D-494 routes."""
    from playwright.sync_api import expect, sync_playwright

    posts = []
    answers = {"/api/fleet/robots/rosy_02/trip": (200, {"plan_id": "p2", **PLAN}),
               "/api/fleet/trips/p2/start": (200, {**LEAD, "trip_id": "p2", "robot_id": "rosy_02", "repeat": False})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, posts, answers)
        form = _open_form(page, "rosy_02")
        assert "고리 1/3대" in form.inner_text()
        form.locator("select").first.select_option("B")
        go = form.locator('ui-button[data-trip-start="rosy_02"]')
        assert go.get_attribute("reason") == "먼저 경로를 계산하세요"
        form.locator("ui-button", has_text="경로 보기").click()
        _settle(page, posts, "/api/fleet/robots/rosy_02/trip")
        assert ("/api/fleet/robots/rosy_02/trip", json.dumps({"to": "B"}, separators=(",", ":"))) in posts
        expect(form).to_contain_text("1개 차로 · 2.10 m · 약 14 s · 지도 v4 · 실행하지 않음")
        _shot(page, "card-trip-preview-1440x900.png")
        go.click()
        _settle(page, posts, "/api/fleet/trips/p2/start")
        assert ("/api/fleet/trips/p2/start", None) in posts
        page.clock.run_for(1500)  # the next poll: rosy_02 has no open trip in the fake, the form is closed
        assert _card(page, "rosy_02").locator(".card-trip").count() == 0

        form = _open_form(page, "rosy_02")
        form.locator("select").nth(1).select_option("B")
        form.locator('ui-button[data-trip-repeat="rosy_02"]').click()
        _settle(page, posts, "/api/fleet/trips/p2/start", 2)
        body = [json.loads(data) for path, data in posts if path == "/api/fleet/robots/rosy_02/trip"][-1]
        assert body == {"to": "B", "via": ["A"], "repeat": True}
        assert not errors
        browser.close()


def test_convoy_follows_the_leader_from_the_formation_block(site):  # noqa: F811
    """D-540 3 `대형·대열`: the follower laps behind rosy_01's open repeat trip (`convoy.leader`)."""
    from playwright.sync_api import sync_playwright

    posts = []
    answers = {"/api/fleet/robots/rosy_02/trip": (200, {"plan_id": "p3", **PLAN}),
               "/api/fleet/trips/p3/start": (200, {**LEAD, "trip_id": "p3", "robot_id": "rosy_02",
                                                   "convoy": {"leader": "rosy_01"}})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, posts, answers)
        assert page.locator("#formation-heading").inner_text() == "대형·대열"
        page.locator(".convoy-form-wrap > summary").click()
        # Leader first: only a robot on an open repeat trip; the follower list leaves out robots on a trip.
        assert page.locator("#convoy-leader").input_value() == "rosy_01"
        followers = page.locator("#convoy-follower option").all_inner_texts()
        assert "rosy_01" not in followers and "rosy_02" in followers
        page.locator("#convoy-follower").select_option("rosy_02")
        page.locator("#convoy-start").select_option("A")
        page.clock.run_for(1100)
        _shot(page, "convoy-1440x900.png")
        page.locator("#convoy-go").click()
        _settle(page, posts, "/api/fleet/trips/p3/start")
        body = [json.loads(data) for path, data in posts if path == "/api/fleet/robots/rosy_02/trip"][-1]
        assert body == {"to": "A", "via": ["B"], "repeat": True, "convoy": {"leader": "rosy_01"}}
        assert ("/api/fleet/trips/p3/start", None) in posts
        assert not errors
        browser.close()


def test_cancel_stops_the_trip_else_the_goal_and_the_lane(site):  # noqa: F811
    """D-540 1: one `운행 취소` per card, quiet, no confirm: the open trip if there is one, else the goal plus
    lane driving that is on. A stopped trip opens its card with the lease end reason (D-541 7)."""
    from playwright.sync_api import sync_playwright

    posts = []
    answers = {"/api/fleet/trips/t-1/cancel": (200, {**LEAD, "state": "canceled"}),
               "/api/fleet/robots/rosy_02/cancel": (200, {"ok": True}),
               "/api/fleet/robots/rosy_02/line-follow": (200, {"result": {"state": "OFF"}})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, posts, answers)
        lead = _card(page, "rosy_01")
        assert lead.get_attribute("data-collapsed") == ""
        assert "반복 운행 2바퀴째" in lead.inner_text()
        lost = _card(page, "rosy_03")
        assert lost.get_attribute("data-collapsed") is None
        assert "운행 멈춤 · 로봇 화면·Pilot에서 넘겨받음(kim-tablet)" in lost.locator(".trip-line").inner_text()
        assert "운행 멈춤" in page.locator("#warning-list").inner_text()

        lead.locator(".robot-line").click()
        stop = lead.locator('ui-button[data-cancel-scope="trip"]')
        assert stop.get_attribute("kind") == "quiet" and stop.inner_text().strip() == "운행 취소"
        stop.click()
        _settle(page, posts, "/api/fleet/trips/t-1/cancel")
        assert ("/api/fleet/trips/t-1/cancel", None) in posts
        assert not any(path == "/api/fleet/robots/rosy_01/cancel" for path, _ in posts)

        lane = _card(page, "rosy_02")
        lane.locator(".robot-line").click()
        lane.locator('ui-button[data-cancel-scope="goal-lane"]').click()
        _settle(page, posts, "/api/fleet/robots/rosy_02/line-follow")
        assert ("/api/fleet/robots/rosy_02/cancel", None) in posts
        assert ("/api/fleet/robots/rosy_02/line-follow", '{"mode":"OFF"}') in posts
        assert not errors
        browser.close()


def test_an_unnamed_operator_sees_why_moves_are_off_and_can_still_cancel(site):  # noqa: F811
    """D-540 9: the shared console token moves nothing; `운행 취소` stays open."""
    from playwright.sync_api import sync_playwright

    api = {**API, "/api/fleet/session": {"principal_id": "site-console", "role": "operator"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        card = _card(page, "rosy_02")
        card.locator(".robot-line").click()
        trip = card.locator('ui-button[data-trip-open="rosy_02"]')
        assert trip.get_attribute("reason") == NAMED and trip.evaluate("node => node.disabled")
        assert not card.locator('ui-button[data-cancel-scope="goal-lane"]').evaluate("node => node.disabled")
        page.locator(".convoy-form-wrap > summary").click()
        page.locator("#convoy-follower").select_option("rosy_02")
        page.clock.run_for(1100)
        assert page.locator("#convoy-go").get_attribute("reason") == NAMED
        assert not errors
        browser.close()


def test_the_open_form_fits_every_viewport_without_rail_overflow(site):  # noqa: F811
    """D-540 7 with the card form open: no horizontal overflow of the rail or the document, button words on
    one line, the rail is still the one scroll at 1024 and up, E-stop on the first screen."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, [])
        _open_form(page, "rosy_02")
        for width, height in [(1920, 1080), (1440, 900), (1024, 768), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1500)
            form = _card(page, "rosy_02").locator(".card-trip")
            assert form.count() == 1, width
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            assert page.evaluate("""() => { const rail = document.querySelector('.console-secondary');
              return rail.scrollWidth <= rail.clientWidth + 1; }"""), width
            assert page.evaluate("""() => [...document.querySelectorAll('.card-trip ui-button, .card-trip select')]
              .every((node) => node.scrollWidth <= node.clientWidth + 1 && node.getBoundingClientRect().height < 80)"""), width
            if width >= 1024:
                assert set(page.evaluate(SCROLLERS)) <= {"console-primary", "console-secondary"}, (width, page.evaluate(SCROLLERS))
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["y"] >= 0 and stop["y"] + stop["height"] <= height, width
            # One atomic scroll: a 1 s poll may rebuild the card between a locator's resolve and its action.
            page.evaluate("document.querySelector('#roster article[data-robot-id=\"rosy_02\"] .card-trip')"
                          "?.scrollIntoView({block: 'nearest'})")
            _shot(page, f"card-trip-{width}x{height}.png")
            page.evaluate("window.scrollTo(0, 0); document.querySelector('.console-secondary').scrollTop = 0")
        assert not errors
        browser.close()


def test_a_failed_trip_cancel_still_stops_lane_driving(site):  # noqa: F811
    """Review 1: if the trip cancel fails, the fallback also turns lane driving OFF (Fleet's trip guard then
    ends the open trip), not only the goal cancel."""
    from playwright.sync_api import sync_playwright

    lead = _robot("rosy_01")
    lead["state"]["line_follow"] = {"mode": "CAMERA_LINE", "state": "TRACKING"}
    api = {**API, "/api/fleet/state": {**API["/api/fleet/state"], "robots": [lead, LANE, _robot("rosy_03"), OFFLINE]}}
    posts = []
    answers = {"/api/fleet/trips/t-1/cancel": (503, {"detail": "busy"}),
               "/api/fleet/robots/rosy_01/cancel": (200, {"ok": True}),
               "/api/fleet/robots/rosy_01/line-follow": (200, {"result": {"state": "OFF"}})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers)
        card = _card(page, "rosy_01")
        card.locator(".robot-line").click()
        card.locator('ui-button[data-cancel-scope="trip"]').click()
        _settle(page, posts, "/api/fleet/robots/rosy_01/line-follow")
        assert ("/api/fleet/trips/t-1/cancel", None) in posts
        assert ("/api/fleet/robots/rosy_01/cancel", None) in posts
        assert ("/api/fleet/robots/rosy_01/line-follow", '{"mode":"OFF"}') in posts
        assert not errors
        browser.close()


def test_a_kept_card_cancels_the_trip_that_opened_after_it_was_drawn(site):  # noqa: F811
    """Review 2: a card kept across polls (its picker has focus) decides what 운행 취소 stops at click time."""
    from playwright.sync_api import sync_playwright

    api = {**API}
    posts = []
    answers = {"/api/fleet/trips/t-2/cancel": (200, {"state": "canceled"})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers)
        form = _open_form(page, "rosy_02")
        form.locator("select").first.focus()
        late = {**LEAD, "trip_id": "t-2", "plan_id": "t-2", "robot_id": "rosy_02", "repeat": False}
        api["/api/fleet/trips"] = {"running": late, "trips": [late, LEAD, LOST], "open": [LEAD, late]}
        page.clock.run_for(1500)
        _card(page, "rosy_02").locator("ui-button[data-cancel-scope]").click()
        _settle(page, posts, "/api/fleet/trips/t-2/cancel")
        assert ("/api/fleet/trips/t-2/cancel", None) in posts
        assert not any(path == "/api/fleet/robots/rosy_02/cancel" for path, _ in posts)
        assert not errors
        browser.close()


def test_rail_panels_do_not_overlap(site):  # noqa: F811
    """Review 3: the rail rows size to their content, so the camera panel never runs under the next panel."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, [])
        page.locator(".convoy-form-wrap > summary").click()  # the audit scene: the ops block grows
        for width, height in [(1440, 900), (1024, 768)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1500)
            boxes = page.evaluate("""() => [...document.querySelector('.console-secondary').children]
              .filter((node) => node.offsetParent && getComputedStyle(node).position !== 'absolute')
              .map((node) => { const r = node.getBoundingClientRect();
                return [node.className, r.top, r.top + Math.max(r.height, node.scrollHeight)]; })
              .filter(([, top, bottom]) => bottom > top)""")
            for (a, _, bottom), (b, top, _) in zip(boxes, boxes[1:]):
                assert top >= bottom - 1, (width, a, bottom, b, top)
            _shot(page, f"rail-{width}x{height}.png")
        assert not errors
        browser.close()


def test_cancel_all_goes_at_once_for_any_operator(site):  # noqa: F811
    """D-540 6 (user decision 2026-10-10): 전체 주행 취소 is a stop — quiet, no confirm dialog, open to the shared
    console token too (D-540 9), and the line beside it says at once that it was sent and to how many robots."""
    from playwright.sync_api import expect, sync_playwright

    posts = []
    result = {"cancelled": 3, "total": 3, "evidence": "CORE_REPLY_ONLY", "formation": None,
              "robots": [{"robot_id": r, "result": "cancelled", "steps": {}, "tasks": {"awaiting_core_result": []}}
                         for r in ("rosy_01", "rosy_02", "rosy_03")],
              "tasks": {"canceled": [], "error": None}}
    api = {**API, "/api/fleet/session": {"principal_id": "site-console", "role": "operator"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, {"/api/fleet/cancel-all": (200, result)})
        button = page.locator("#cancel-all")
        assert button.get_attribute("kind") == "quiet" and not button.evaluate("node => node.disabled")
        button.click()
        assert page.locator("dialog.ui-confirm").count() == 0
        _settle(page, posts, "/api/fleet/cancel-all")
        assert ("/api/fleet/cancel-all", None) in posts
        expect(page.locator("#cancel-all-result")).to_contain_text("전체 주행 취소를 보냈습니다 · 3대")
        assert not any(path == "/api/fleet/estop" for path, _ in posts)
        assert not errors
        browser.close()
