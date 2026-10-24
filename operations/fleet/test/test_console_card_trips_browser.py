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
    # D-763 9 (v1.237): 새 작업 shows only the kinds the server lists
    "/api/fleet/work": {"rows": [], "observed_at": "2026-10-15T00:00:00+00:00", "tasks_available": True,
                        "missions_available": True, "cell_jobs_available": True, "truncated_sources": [],
                        "kinds": ["trip"]},
}
PLAN = {"segments": [{"edge_id": "e1"}], "places": [], "actions": [], "length_m": 2.1, "eta_s": 14,
        "map_version": 4, "expires_at": 4e9}


def _card(page, robot_id):
    page.locator('[data-context-tab="status"]').click()
    page.locator("#robot-choice").select_option(robot_id)
    return page.locator(f'#robot-workspace article[data-robot-id="{robot_id}"]')


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
    card.locator(f'ui-button[data-trip-open="{robot_id}"]').click()
    return card.locator(".card-trip")


def _settle(page, posts, path, count=1):
    for _ in range(50):  # answers land on the real network clock
        page.clock.run_for(100)
        if sum(1 for post in posts if post[0] == path) >= count:
            return


def test_unknown_site_pose_blocks_plan_without_hiding_inspection(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = {**API, "/api/fleet/guide": {"map_version": 4, "robots": [{"robot_id": "rosy_02", "online": True, "body_radius_m": 0.085, "pose": None}]}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts)
        form = _open_form(page, "rosy_02")
        preview = form.get_by_role("button", name="경로 보기", exact=True)
        assert preview.evaluate("node => node.disabled")
        assert "위치" in preview.get_attribute("reason")
        api["/api/fleet/guide"]["robots"][0]["pose"] = {
            "state": "LOCALIZED", "x": 0, "y": 0, "yaw": 0, "u_m": 0.12, "source": "operator_pin"}
        # Blur the form through its tab, rather than clicking a panel centre that can hit an action.
        page.locator('[data-context-tab="status"]').click()
        page.clock.run_for(1500)
        expect(form.get_by_role("button", name="경로 보기", exact=True)).to_be_enabled()
        assert not posts and not errors
        browser.close()


@pytest.mark.parametrize("change", ["expired", "estop", "pose"])
def test_retained_trip_button_rechecks_current_evidence_before_start(site, change):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    plan_path, start_path = "/api/fleet/robots/rosy_02/trip", "/api/fleet/trips/p2/start"
    api = {**API, "/api/fleet/guide": {"map_version": 4, "robots": [{"robot_id": "rosy_02", "online": True, "body_radius_m": 0.085, "pose": {
        "state": "LOCALIZED", "x": 0, "y": 0, "yaw": 0, "u_m": 0.12, "source": "operator_pin"}}]}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, {plan_path: (200, {
            **PLAN, "plan_id": "p2", "expires_at": time.time() + 30})})
        form = _open_form(page, "rosy_02")
        form.get_by_role("button", name="경로 보기", exact=True).click()
        _settle(page, posts, plan_path)
        go = form.locator('[data-trip-start="rosy_02"]')
        expect(go).to_be_enabled()
        form.get_by_role("combobox", name="목적지", exact=True).focus()
        if change == "estop":
            rows = [json.loads(json.dumps(row)) for row in API["/api/fleet/state"]["robots"]]
            next(row for row in rows if row["robot_id"] == "rosy_02")["state"]["safety"]["estop"] = True
            api["/api/fleet/state"] = {**API["/api/fleet/state"], "robots": rows}
        elif change == "pose":
            api["/api/fleet/guide"]["robots"][0]["pose"] = None
        page.clock.run_for(31000 if change == "expired" else 1500)
        # The focused picker preserves the old DOM; dispatch without changing focus first.
        go.evaluate("node => node.dispatchEvent(new MouseEvent('click', {bubbles: true}))")
        page.clock.run_for(500)
        assert not any(path == start_path for path, _ in posts)
        expect(form).to_contain_text("운행 거절")
        assert not errors
        browser.close()


def test_delayed_plan_for_previous_destination_is_not_adopted(site):
    from playwright.sync_api import expect, sync_playwright

    posts, pending = [], []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, posts)
        path = "/api/fleet/robots/rosy_02/trip"
        page.route("**" + path, lambda route: pending.append(route))
        form = _open_form(page, "rosy_02")
        destination = form.get_by_role("combobox", name="목적지", exact=True)
        destination.select_option("A")
        form.get_by_role("button", name="경로 보기", exact=True).click()
        page.wait_for_function("document.querySelector('.card-trip') !== null")
        for _ in range(50):
            page.clock.run_for(100)
            if pending:
                break
        assert len(pending) == 1
        destination.select_option("B")
        pending[0].fulfill(json={**PLAN, "plan_id": "previous-A"})
        page.clock.run_for(500)
        go = form.locator('[data-trip-start="rosy_02"]')
        expect(go).to_be_disabled()
        assert destination.input_value() == "B"
        assert not any(path.endswith("/start") for path, _ in posts)
        assert not errors
        browser.close()


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_robot_selection_only_inspects_and_all_offline_safety_evidence_stays_visible(site, role):
    """Inspection is open to viewers too, sends no POST and never arms the map; offline movement stays off."""
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = {**API, "/api/fleet/session": {"principal_id": "bob", "role": role}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts)
        expect(page.locator("#roster .robot-summary")).to_have_count(4)
        assert page.locator("#roster [data-goal-robot-id], #roster [data-trip-open]").count() == 0
        offline = page.locator('#roster [data-robot-id="rosy_04"]')
        expect(offline).to_contain_text("오프라인")
        expect(offline).to_contain_text("접속 실패")
        expect(page.locator("#robot-workspace article")).to_have_count(0)
        page.locator('#roster [data-robot-id="rosy_03"]').focus()
        page.keyboard.press("Enter")
        expect(page.locator('#robot-workspace article[data-robot-id="rosy_03"]')).to_have_count(1)
        if role == "operator":
            for width, height in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                _shot(page, f"workspace-selected-{width}x{height}.png", full_page=True)
        assert page.locator("#map-canvas").get_attribute("tabindex") == "-1"
        assert page.locator("#map-canvas").evaluate("node => node.classList.contains('idle')")
        card = _card(page, "rosy_04")
        expect(page.locator("#robot-workspace article")).to_have_count(1)
        assert card.locator("[data-goal-robot-id]").evaluate("node => node.disabled")
        assert card.locator("[data-trip-open]").evaluate("node => node.disabled")
        expect(offline).to_contain_text("접속 실패")
        if role == "operator":
            rows = [_robot(row["robot_id"], online=False, error={"reachable": False, "code": "ConnectError"})
                    for row in API["/api/fleet/state"]["robots"]]
            api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 0, "total": 4}, "ts": 0.0, "robots": rows}
            page.clock.run_for(1500)
            expect(page.locator("#roster .robot-summary")).to_have_count(4)
            for row in rows:
                expect(page.locator(f'#roster [data-robot-id="{row["robot_id"]}"]')).to_contain_text("접속 실패")
            for width, height in [(1440, 1000), (390, 844)]:
                page.set_viewport_size({"width": width, "height": height})
                _shot(page, f"workspace-offline-{width}x{height}.png", full_page=True)
        assert not posts and not errors
        browser.close()


def test_workspace_goal_keeps_confirmation_target_and_selection_change_withdraws_the_arm(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    goal = "/api/fleet/robots/rosy_03/goal"
    grid = {"map_id": "mock:1", "width": 40, "height": 40, "resolution": 0.05,
            "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "data": [20] * 1600}
    api = {**API, "/api/fleet/map": grid}
    answers = {goal: (200, {"accepted": True, "task": {"task_id": "selected-goal", "status": "ACCEPTED"}})}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, posts, answers)
        card = _card(page, "rosy_03")
        card.locator("[data-goal-robot-id]").click()
        assert page.locator("#map-canvas").get_attribute("tabindex") == "0"
        _card(page, "rosy_01")
        assert page.locator("#map-canvas").get_attribute("tabindex") == "-1"
        assert page.locator("#map-canvas").evaluate("node => node.classList.contains('idle')")
        assert not posts
        card = _card(page, "rosy_03")
        card.locator("[data-goal-robot-id]").click()
        page.keyboard.press("Enter")
        dialog = page.locator("dialog.ui-confirm")
        expect(dialog).to_contain_text("rosy_03")
        assert not posts
        dialog.locator("ui-button[kind=irreversible]").click()
        _settle(page, posts, goal)
        assert sum(path == goal for path, _ in posts) == 1
        expect(page.locator("#log")).to_contain_text("미션 하달")
        assert page.evaluate("document.activeElement?.dataset.goalRobotId") == "rosy_03"
        assert not errors
        browser.close()


def test_workspace_trip_picker_shows_one_mode_and_keeps_destination_across_polls(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, posts)
        form = _open_form(page, "rosy_02")
        for width, height in [(1440, 1000), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            _shot(page, f"workspace-form-{width}x{height}.png", full_page=True)
        kind = form.get_by_role("combobox", name="작업 종류", exact=True)
        assert kind.input_value() == "route"
        destination = form.get_by_role("combobox", name="목적지", exact=True)
        destination.select_option("B")
        page.clock.run_for(1500)
        assert destination.input_value() == "B"
        expect(form.locator(".trip-mode:not([hidden])")).to_have_count(1)
        kind.select_option("lap")
        expect(form.get_by_role("combobox", name="한 바퀴 출발·복귀", exact=True)).to_be_visible()
        expect(destination).not_to_be_visible()
        kind.select_option("repeat")
        expect(form.get_by_role("combobox", name="반복 출발 자리", exact=True)).to_be_visible()
        expect(form.locator(".trip-mode:not([hidden])")).to_have_count(1)
        kind.select_option("route")
        assert destination.input_value() == "B"
        _card(page, "rosy_03")
        expect(page.locator("#robot-workspace .card-trip")).to_have_count(0)
        assert not posts and not errors
        browser.close()


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
        form.get_by_role("combobox", name="목적지", exact=True).select_option("B")
        go = form.locator('ui-button[data-trip-start="rosy_02"]')
        assert go.get_attribute("reason") == "먼저 경로를 계산하세요"
        form.get_by_role("button", name="경로 보기", exact=True).click()
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
        form.get_by_role("combobox", name="작업 종류", exact=True).select_option("repeat")
        form.get_by_role("combobox", name="반복 출발 자리", exact=True).select_option("B")
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
        page.get_by_role("tab", name="운영 도구").click()
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
        assert lead.get_attribute("data-collapsed") is None
        assert "반복 운행 2바퀴째" in lead.inner_text()
        lost = _card(page, "rosy_03")
        assert lost.get_attribute("data-collapsed") is None
        assert "운행 멈춤 · 로봇 화면·Pilot에서 넘겨받음(kim-tablet)" in lost.locator(".trip-line").inner_text()
        assert "운행 멈춤" in page.locator("#warning-list").inner_text()

        stop = _card(page, "rosy_01").locator('ui-button[data-cancel-scope="trip"]')
        assert stop.get_attribute("kind") == "quiet" and stop.inner_text().strip() == "운행 취소"
        stop.click()
        _settle(page, posts, "/api/fleet/trips/t-1/cancel")
        assert ("/api/fleet/trips/t-1/cancel", None) in posts
        assert not any(path == "/api/fleet/robots/rosy_01/cancel" for path, _ in posts)

        lane = _card(page, "rosy_02")
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
        trip = card.locator('ui-button[data-trip-open="rosy_02"]')
        assert trip.get_attribute("reason") == NAMED and trip.evaluate("node => node.disabled")
        assert not card.locator('ui-button[data-cancel-scope="goal-lane"]').evaluate("node => node.disabled")
        page.get_by_role("tab", name="운영 도구").click()
        page.locator(".convoy-form-wrap > summary").click()
        page.locator("#convoy-follower").select_option("rosy_02")
        page.clock.run_for(1100)
        assert page.locator("#convoy-go").get_attribute("reason") == NAMED
        assert not errors
        browser.close()


def test_the_open_form_fits_every_viewport_without_rail_overflow(site):  # noqa: F811
    """D-540 7 with the card form open: no horizontal overflow of the rail or the document, button words on
    one line, tall wide windows keep the map in one frame, short windows flow, E-stop on the first screen."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, API, [])
        _open_form(page, "rosy_02")
        for width, height in [(1920, 1080), (1440, 900), (1024, 768), (1366, 600), (390, 844), (320, 568)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1500)
            form = _card(page, "rosy_02").locator(".card-trip")
            assert form.count() == 1, width
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            assert page.evaluate("""() => { const rail = document.querySelector('.console-secondary');
              return rail.scrollWidth <= rail.clientWidth + 1; }"""), width
            assert page.evaluate("""() => [...document.querySelectorAll('.card-trip ui-button, .card-trip select')]
              .filter((node) => node.getBoundingClientRect().height > 0)
              .every((node) => node.scrollWidth <= node.clientWidth + 1 && node.getBoundingClientRect().height < 80)"""), width
            if width >= 1024 and height >= 640:
                assert set(page.evaluate(SCROLLERS)) <= {"console-primary", "console-secondary"}, (width, page.evaluate(SCROLLERS))
                assert page.evaluate("""() => { const primary = document.querySelector('.console-primary');
                  const stage = document.querySelector('#map-stage').getBoundingClientRect();
                  return primary.scrollHeight <= primary.clientHeight + 1 && stage.height >= 200;
                }"""), (width, height, page.evaluate("""() => {
                  const primary = document.querySelector('.console-primary');
                  return {scroll: primary.scrollHeight, client: primary.clientHeight,
                    stage: document.querySelector('#map-stage').getBoundingClientRect().height};
                }"""))
            elif width >= 1024:
                assert page.evaluate("document.querySelector('ui-shell').getBoundingClientRect().height > innerHeight")
            assert page.evaluate("""() => [...document.querySelectorAll('.map-head > *')]
              .filter((node) => node.offsetParent).every((node) => {
                const child = node.getBoundingClientRect(), head = node.parentElement.getBoundingClientRect();
                return child.left >= head.left - 1 && child.right <= head.right + 1;
              })"""), (width, height)
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["y"] >= 0 and stop["y"] + stop["height"] <= height, width
            # One atomic scroll: a 1 s poll may rebuild the card between a locator's resolve and its action.
            page.evaluate("document.querySelector('#robot-workspace article[data-robot-id=\"rosy_02\"] .card-trip')"
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
        page.get_by_role("tab", name="운영 도구").click()
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


def test_a_regulation_wait_reads_on_the_card_and_past_its_bound_in_the_queue(site):  # noqa: F811
    """D-763 8 (v1.232): the card line shows Fleet's wait; past its bound a warn row, never 개입 (rev 2 Q7)."""
    from playwright.sync_api import expect, sync_playwright

    waiting = {**LEAD, "wait": {"reason": "crosswalk_look", "since": 0.0, "bound_s": 15.0, "over_bound": False,
                                "waiting": True}}
    api = {**API, "/api/fleet/trips": {"running": waiting, "trips": [waiting, LOST], "open": [waiting]}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        for width, height in [(1366, 600), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1500)
            expect(_card(page, "rosy_01").locator(".trip-line")).to_have_text("대기 · 횡단보도")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["y"] >= 0 and stop["y"] + stop["height"] <= height, width
        assert "대기 상한" not in page.locator(".queues-panel").inner_text()
        over = {**waiting, "wait": {**waiting["wait"], "reason": "signal", "over_bound": True, "waiting": False}}
        api["/api/fleet/trips"] = {"running": over, "trips": [over, LOST], "open": [over]}
        page.clock.run_for(1500)
        expect(page.locator("#warning-list")).to_contain_text("대기 상한 넘음 · 신호")
        expect(_card(page, "rosy_01").locator(".trip-line")).to_have_text("대기 상한 넘음 · 신호")
        assert "대기 상한" not in page.locator("#critical-list").inner_text()
        assert not errors
        browser.close()


def test_new_work_move_sends_the_card_requests_and_shows_the_same_refusal(site):  # noqa: F811
    """D-763 6: 작업 › 새 작업의 이동은 로봇 카드의 운행 폼 그대로다. 같은 계획·시작 요청을 보내고, 바쁜 로봇에는
    카드와 같은 거절(TRIP_ROBOT_BUSY)을 보인다."""
    from urllib.parse import urlparse
    from playwright.sync_api import expect, sync_playwright

    plan_path, start_path = "/api/fleet/robots/rosy_02/trip", "/api/fleet/trips/p2/start"
    started = (200, {**LEAD, "trip_id": "p2", "robot_id": "rosy_02", "repeat": False})
    busy = (409, {"detail": {"code": "TRIP_ROBOT_BUSY", "message": "robot busy"}})
    answers = {plan_path: (200, {"plan_id": "p2", **PLAN}), start_path: started}

    def trip(page, form, posts, count):
        form.get_by_role("combobox", name="목적지", exact=True).select_option("B")
        form.get_by_role("button", name="경로 보기", exact=True).click()
        _settle(page, posts, plan_path, count)
        expect(form).to_contain_text("1개 차로 · 2.10 m · 약 14 s · 지도 v4 · 실행하지 않음")
        form.locator('ui-button[data-trip-start="rosy_02"]').click()
        _settle(page, posts, start_path, count)

    with sync_playwright() as playwright:
        posts, sent, seat = [], {"card": [], "work": []}, ["card"]
        browser, page, errors = _open(playwright, site, API, posts, answers)
        page.on("request", lambda r: r.method != "GET" and "/api/" in r.url and sent[seat[0]].append(
            (r.method, urlparse(r.url).path, r.post_data, r.headers.get("content-type"))))
        trip(page, _open_form(page, "rosy_02"), posts, 1)
        page.clock.run_for(1500)  # the next poll drops the trip the start answer opened
        answers[start_path] = busy
        form = _open_form(page, "rosy_02")
        trip(page, form, posts, 2)
        expect(form.locator(".stuck-result")).to_contain_text("운행 거절 · 이 로봇은 운행 중입니다")
        card_refusal = form.locator(".stuck-result").inner_text()

        answers[start_path], seat[0] = started, "work"
        page.goto(site + "/console?view=work&show=new")
        page.clock.run_for(2500)
        screens = page.get_by_role("navigation", name="작업 화면", exact=True)
        assert screens.locator('a[aria-current="page"]').all_inner_texts() == ["새 작업"]
        page.locator("#work-new-move").click()
        page.locator("#work-move-robot").select_option("rosy_02")
        form = page.locator("#work-move .card-trip")
        trip(page, form, posts, 3)
        page.clock.run_for(1500)
        answers[start_path] = busy
        trip(page, form, posts, 4)
        expect(form.locator(".stuck-result")).to_contain_text("운행 거절")
        assert form.locator(".stuck-result").inner_text() == card_refusal
        assert len(sent["card"]) == 4 and sent["work"] == sent["card"], sent
        assert not errors
        browser.close()


def test_new_work_trip_picker_keeps_focus_and_destination_across_poll(site):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        posts = []
        browser, page, errors = _open(playwright, site, API, posts)
        page.goto(site + "/console?view=work&show=new")
        page.clock.run_for(2500)
        page.locator("#work-new-move").click()
        page.locator("#work-move-robot").select_option("rosy_02")
        form = page.locator("#work-move .card-trip")
        destination = form.get_by_role("combobox", name="목적지", exact=True)
        destination.select_option("B")
        destination.focus()
        page.clock.run_for(2500)
        expect(destination).to_be_focused()
        expect(destination).to_have_value("B")
        page.locator("#work-move-robot").focus()
        page.locator("#work-move-robot").select_option("rosy_03")
        expect(form).to_have_attribute("aria-label", "rosy_03 운행")
        expect(form.get_by_role("combobox", name="목적지", exact=True)).to_have_value("A")
        assert not posts and not errors
        browser.close()


def test_a_viewer_switches_robots_in_new_work_and_reads_each_reason(site):  # noqa: F811
    """Review P2: the 이동 robot picker is a read control; a viewer switches robots and sees each card's reason,
    while the start controls stay locked."""
    from playwright.sync_api import expect, sync_playwright

    api = {**API, "/api/fleet/session": {"principal_id": "eve", "role": "viewer"}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        page.goto(site + "/console?view=work&show=new")
        page.clock.run_for(2500)
        page.locator("#work-new-move").click()
        pick = page.locator("#work-move-robot")
        for robot_id in ("rosy_02", "rosy_04"):
            expect(pick).to_be_enabled()
            pick.select_option(robot_id)
            page.clock.run_for(1500)
            go = page.locator(f'#work-move ui-button[data-trip-start="{robot_id}"]')
            expect(go).to_have_count(1)
            assert go.evaluate("node => node.disabled") and go.get_attribute("reason"), robot_id
        assert not errors
        browser.close()


def test_new_work_shows_only_kinds_that_run_and_the_move_form_fits(site):  # noqa: F811
    """D-763 9 (v1.237): 새 작업은 서버의 종류 목록(`kinds`)만 보인다. 목록에 없는 종류는 꺼진 단추도 아니고 없다.
    Cell 적재는 /console/cell로 간다. 1366·390에서 이동 폼은 넘치지 않고 비상 정지는 첫 화면에 있다."""
    from playwright.sync_api import expect, sync_playwright

    api = {**API, "/api/fleet/work": {**API["/api/fleet/work"], "kinds": []}}
    with sync_playwright() as playwright:
        browser, page, errors = _open(playwright, site, api, [])
        page.goto(site + "/console?view=work&show=new")
        page.clock.run_for(2500)
        kinds = page.get_by_role("list", name="새 작업 종류", exact=True)
        cell = kinds.get_by_role("link", name="Cell 적재", exact=True)
        assert page.locator("#work-new-move-item").is_hidden() and page.locator("#work-move").is_hidden()
        assert page.locator("#work-new-cell-item").is_hidden()  # places and robots in the browser do not decide
        assert not page.locator("#work-list").is_visible() and not page.locator("#work-context").is_visible()
        api["/api/fleet/work"] = {**API["/api/fleet/work"], "kinds": ["trip", "CELL_TRANSFER"]}
        page.clock.run_for(5000)  # the work poll (MAP_MS)
        expect(cell).to_be_visible()
        assert cell.get_attribute("href") == "/console/cell"
        expect(page.locator("#work-new-move")).to_be_visible()
        # One row look for every kind: the Cell link once drew as a small underlined box beside a full-width 이동.
        move_box, cell_box = page.locator("#work-new-move").bounding_box(), cell.bounding_box()
        assert all(abs(move_box[key] - cell_box[key]) <= 1 for key in ("x", "width", "height")), (move_box, cell_box)
        assert cell.evaluate("node => getComputedStyle(node).textDecorationLine") == "none"
        page.locator("#work-new-move").click()
        page.locator("#work-move-robot").select_option("rosy_02")
        for width, height in [(1366, 768), (390, 844)]:
            page.set_viewport_size({"width": width, "height": height})
            page.clock.run_for(1500)
            assert page.locator("#work-move .card-trip").count() == 1, width
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
            assert page.evaluate("""() => [...document.querySelectorAll('#work-move ui-button, #work-move select')]
              .filter((node) => node.getBoundingClientRect().height > 0)
              .every((node) => node.scrollWidth <= node.clientWidth + 1)"""), width
            stop = page.locator("#estop").bounding_box()
            assert stop and stop["y"] >= 0 and stop["y"] + stop["height"] <= height, width
            if width < 1024:
                assert page.locator("#work-new").bounding_box()["y"] < page.locator("#work-move").bounding_box()["y"]
            page.evaluate("document.querySelector('#work-move')?.scrollIntoView({block: 'nearest'})")
            _shot(page, f"work-new-move-{width}x{height}.png")
            page.evaluate("window.scrollTo(0, 0); document.querySelector('.console-secondary').scrollTop = 0")
        page.set_viewport_size({"width": 1366, "height": 768})
        api["/api/fleet/work"] = {**API["/api/fleet/work"], "kinds": ["CELL_TRANSFER"]}
        page.clock.run_for(5000)  # the work poll (MAP_MS)
        assert page.locator("#work-new-move-item").is_hidden() and page.locator("#work-move").is_hidden()
        page.route("**/api/fleet/work", lambda route: route.fulfill(status=503, json={"detail": "offline"}))
        page.clock.run_for(5000)  # the work poll (MAP_MS)
        assert page.locator("#work-new-cell-item").is_hidden()  # no answer: no kind
        page.unroute("**/api/fleet/work")
        page.clock.run_for(5000)  # the work poll (MAP_MS)
        cell.click()
        page.wait_for_url("**/console/cell")
        screens = page.get_by_role("navigation", name="작업 화면", exact=True)
        assert screens.locator('a[aria-current="page"]').all_inner_texts() == ["새 작업"]
        assert not errors
        browser.close()
