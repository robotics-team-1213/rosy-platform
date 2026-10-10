"""Leader and follower appointment on the 관제 screen in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The real Fleet app with three fake CORE robots (fakes.FakeRobot) and the lane-traffic fake trip ports: every
press goes through the real Fleet routes, a named operator logs in with a password. Covers the 대형 (D-20)
leader/follower form, the 대열 (D-517 9) leader-first choice, the cards that say who leads and who follows,
and lane following shown in operator words (D-540 6: no raw enum on screen). No robot moves.
"""

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, launch_options, safe_listener

from fakes import FakeRelay, FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.site_map_store import SiteMapStore
from fleet.server.site_users import hash_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
from test_routing import demo_site
from test_trip_authority import AUTH, AuthFleet

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]
IDS = ("rosy_01", "rosy_02", "rosy_03")
PLACES = (("rosy_01", "east:fwd", 1.5), ("rosy_02", "east:fwd", 0.3), ("rosy_03", "west:fwd", 0.5))
# Raw protocol words an operator must not read (title and data-* may carry them).
RAW = re.compile(r"\b(?:[A-Z][A-Z0-9]*_[A-Z0-9_]+|IDLE|RUNNING|HOLDING|COLUMN|GRID|CIRCLE|TRAIL|TRACKING|WAITING)\b"
                 r"|line-follow|CORE motion")


class LaneRobot(FakeRobot):
    """A fake CORE whose line_follow follows the mode it was last sent."""

    async def line_follow_mode(self, mode):
        self._record("line_follow_mode", mode)
        self._state["line_follow"] = {"mode": mode, "state": "WAITING" if mode != "OFF" else "OFF"}
        return dict(self._state["line_follow"])


@pytest.fixture
def fleet_site(tmp_path):
    fleet = AuthFleet(IDS, {robot_id: AUTH for robot_id in IDS})
    fleet.advance(time.time() - fleet.now)
    store = SiteMapStore(tmp_path / "maps.sqlite")
    store.import_if_empty(demo_site(), source="test")
    graph = store.active()[2]
    robots = {}
    for robot_id, arc, s in PLACES:
        fleet.at(robot_id, graph.arcs[arc], s)
        x, y, yaw = graph.arcs[arc].point_at(s)
        robots[robot_id] = LaneRobot(robot_id, state={
            "robot_id": robot_id, "mode": "IDLE", "navigation": "IDLE", "map_id": "m1",
            "pose": {"x": x, "y": y, "yaw": yaw}, "safety": {"estop": False},
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}, "line_follow": {"mode": "OFF", "state": "OFF"}})
    console = FleetConsole([RobotEndpoint(r, f"http://127.0.0.1:81{i}0", "t") for i, r in enumerate(IDS)],
                           list(robots.values()),
                           relay_factory=lambda leader, followers, **kw: FakeRelay(leader, followers))
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, site_users={}, start_task_dispatcher=False,
                     site_logins={"kim": {"principal_id": "kim", "role": "operator",
                                          "password_scrypt": hash_password("pw-1234")}},
                     web_common=ROOT / "shared" / "web", site_maps=store, trip_caps_port=fleet.caps_for,
                     map_pose_port=fleet, lane_junction=fleet, traffic_authority=True)
    listener = safe_listener()
    origin = f"http://localhost:{listener.getsockname()[1]}"  # Secure session cookie on localhost
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    stop = threading.Event()

    def clock():  # the fake trip ports read their own clock; keep it on the wall clock
        while not stop.wait(0.5):
            fleet.advance(time.time() - fleet.now)
    threading.Thread(target=clock, daemon=True).start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        yield origin, robots
    finally:
        stop.set()
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def _login(playwright, origin):
    options = launch_options()
    options["args"] = [f"--explicitly-allowed-ports={urlparse(origin).port}"]
    browser = playwright.chromium.launch(**options)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors, posts = [], []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("request", lambda req: posts.append((urlparse(req.url).path, req.post_data))
            if req.method == "POST" and "/api/" in req.url else None)
    page.goto(origin + "/console")
    more = page.locator("#topbar-more")
    if more.is_visible() and more.get_attribute("aria-expanded") != "true":
        more.click()
    page.locator("#password-login [data-login=login]").fill("kim")
    page.locator("#password-login [data-login=password]").fill("pw-1234")
    page.locator("#password-login [data-login=submit]").click()
    page.locator("#user-role").filter(has_text="kim").wait_for(timeout=15000)
    if more.get_attribute("aria-expanded") == "true":
        more.click()
    return browser, page, errors, posts


def _card(page, robot_id):
    card = page.locator(f'#roster article[data-robot-id="{robot_id}"]')
    if card.get_attribute("data-collapsed") is not None:
        card.locator(".robot-line").first.click()
    return card


def _raw_words(page):
    return sorted(set(RAW.findall(page.locator("main").inner_text())))


def test_formation_appoints_a_leader_and_its_followers(fleet_site):
    """대형: the follower boxes leave the leader out; unticking one sends only the ticked followers; the
    cards then say 대형 리더 / 대형 팔로워; buttons say what they are, and a held-off button says 위 사유."""
    from playwright.sync_api import expect, sync_playwright

    origin, robots = fleet_site
    with sync_playwright() as playwright:
        browser, page, errors, posts = _login(playwright, origin)
        page.locator(".formation-form-wrap > summary").click()
        page.locator("#formation-leader").select_option("rosy_02")
        boxes = page.locator("#formation-members input")
        expect(boxes).to_have_count(2)
        assert [box.get_attribute("value") for box in boxes.all()] == ["rosy_01", "rosy_03"]
        buttons = page.locator("#formation-start, #formation-reform, #formation-resume, #formation-stop")
        assert [b.evaluate("n => [...n.childNodes].filter(c => c.nodeType === 3).map(c => c.textContent).join('').trim()")
                for b in buttons.all()] == ["대형 시작", "대형 변경", "대형 재개", "대형 해제"]
        assert [b.get_attribute("reason") for b in buttons.all()] == [None, "위 사유", "위 사유", "위 사유"]
        expect(page.locator("#formation-why")).to_contain_text("대형을 시작한 뒤에")
        page.locator('#formation-members input[value="rosy_03"]').uncheck()
        expect(page.locator("#formation-detail")).to_contain_text("리더 rosy_02 · 팔로워 1대(rosy_01) · 종대")
        assert _raw_words(page) == []
        page.locator("#formation-start").click()
        expect(page.locator("#formation-state")).to_have_text("진행 중")
        start = [json.loads(body) for path, body in posts if path == "/api/fleet/formation/start"]
        assert start == [{"leader": "rosy_02", "formation": "COLUMN", "spacing": 0.6, "members": ["rosy_02", "rosy_01"]}]
        assert [c[0] for c in robots["rosy_01"].calls if c[0] == "follow"] == ["follow"]
        assert not any(c[0] == "follow" for c in robots["rosy_03"].calls)
        expect(_card(page, "rosy_02").locator('[data-formation-role="leader"]')).to_have_text("대형 리더")
        expect(_card(page, "rosy_01").locator('[data-formation-role="follower"]')).to_have_text("대형 팔로워")
        assert _card(page, "rosy_03").locator("[data-formation-role]").count() == 0
        # 대형 변경 sends the shape on screen: the form stays reachable while the formation runs.
        expect(page.locator("#formation-shape")).to_be_enabled()
        expect(page.locator("#formation-leader")).to_be_disabled()
        page.locator("#formation-shape").select_option("LINE")
        page.locator("#formation-reform").click()
        expect(page.locator("#formation-detail")).to_contain_text("횡대")
        expect(page.locator("#formation-resume")).to_have_attribute("reason", "위 사유")
        expect(page.locator("#formation-why")).to_contain_text("멈췄을 때만")
        assert _raw_words(page) == []
        page.locator("#formation-stop").click()
        expect(page.locator("#formation-state")).to_have_text("해제됨")
        assert page.locator("[data-formation-role]").count() == 0
        assert not errors
        browser.close()


def test_convoy_picks_the_leader_first_and_both_cards_name_their_role(fleet_site):
    """대열: the leader list holds only robots on an open repeat trip, the follower list only robots without
    a trip; after 대열 시작 the follower card says whom it follows and the leader card who follows it."""
    from playwright.sync_api import expect, sync_playwright

    origin, _robots = fleet_site
    with sync_playwright() as playwright:
        browser, page, errors, posts = _login(playwright, origin)
        page.locator(".convoy-form-wrap > summary").click()
        expect(page.locator("#convoy-go")).to_have_attribute("reason", re.compile("^반복 운행 중인 리더가 없습니다"))
        lead = _card(page, "rosy_01")
        lead.locator('ui-button[data-trip-open="rosy_01"]').click()
        lead.locator(".card-trip select").nth(1).select_option("start_n")
        lead.locator('ui-button[data-trip-repeat="rosy_01"]').click()
        expect(lead.locator(".trip-line")).to_contain_text("반복 운행", timeout=10000)
        expect(page.locator("#convoy-leader")).to_have_value("rosy_01", timeout=5000)
        assert page.locator("#convoy-follower option").all_inner_texts() == ["rosy_02", "rosy_03"]
        page.locator("#convoy-follower").select_option("rosy_02")
        page.locator("#convoy-start").select_option("start_n")
        expect(page.locator("#convoy-detail")).to_have_text("팔로워 rosy_02 · 리더 rosy_01 뒤에서 반복 운행 · 출발 start_n")
        page.locator("#convoy-go").click()
        body = None
        for _ in range(50):
            sent = [json.loads(b) for p, b in posts if p == "/api/fleet/robots/rosy_02/trip"]
            if sent:
                body = sent[-1]
                break
            page.wait_for_timeout(100)
        assert body == {"to": "start_n", "via": ["start_s"], "repeat": True, "convoy": {"leader": "rosy_01"}}
        expect(_card(page, "rosy_02").locator(".trip-line")).to_contain_text("대열 · rosy_01", timeout=10000)
        expect(_card(page, "rosy_01").locator(".trip-line")).to_contain_text("대열 리더 · rosy_02 따라옴")
        assert _raw_words(page) == []
        assert not errors
        browser.close()


def test_lane_following_reads_as_one_operator_word(fleet_site):
    """추종: the card's mode tag names the lane-follow mode (CORE's IDLE is not the robot's story while lane
    following drives it), the enum stays in title, and the IR fallback buttons say 차선 추종."""
    from playwright.sync_api import expect, sync_playwright

    origin, robots = fleet_site
    robots["rosy_03"]._state["line_follow"] = {"mode": "CAMERA_LINE", "state": "TRACKING"}
    with sync_playwright() as playwright:
        browser, page, errors, posts = _login(playwright, origin)
        card = _card(page, "rosy_03")
        mode = card.locator("[data-line-follow]")
        expect(mode).to_have_text("카메라 차선 추종 · 추종 중")
        assert "CAMERA_LINE" in mode.get_attribute("title")
        expect(card).to_contain_text("차선 추종 중에는 목표를 받지 않습니다")
        expect(card.locator("ui-button[data-goal-robot-id]")).to_have_attribute("reason", re.compile("."))
        robots["rosy_03"]._state["line_follow"] = {"mode": "CAMERA_LINE", "state": "LOST",
                                                    "reason": "camera_reselection_required"}
        card.locator("ui-button", has_text="IR 차선 추종으로 전환…").click()
        page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
        expect(card.locator("[data-line-follow]")).to_have_text("IR 차선 추종 · 선 찾는 중", timeout=10000)
        assert ("/api/fleet/robots/rosy_03/line-follow", '{"mode":"IR_LINE"}') in posts
        card.locator("ui-button", has_text="IR 차선 추종 끄기").click()
        expect(card.locator("[data-line-follow]")).to_have_count(0, timeout=10000)
        expect(page.locator("#log")).to_contain_text("IR 차선 추종 끔 · 꺼짐")
        assert _raw_words(page) == []
        assert not errors
        browser.close()


def test_a_hundred_robots_stay_usable(tmp_path):
    """The robot count must not matter: 100 fake COREs (5 stuck, 10 offline). Exceptions lead the queue and the
    cards, nominal cards fold to one line, no horizontal overflow at 1440x900 and 1024x768, no long main-thread
    task over 250 ms across polls, and the robot finder narrows the 99 follower boxes."""
    from playwright.sync_api import sync_playwright
    from test_server_gather_source import _health

    ids = [f"rosy_{i:03d}" for i in range(1, 101)]
    robots = []
    for i, robot_id in enumerate(ids):
        lane = {"mode": "CAMERA_LINE", "state": "TRACKING"}
        if i % 20 == 7:
            lane = {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": {
                "stuck_id": f"s-{robot_id}", "cause": "obstacle_ahead", "phase": "ASKING", "held_s": 4.0, "attempts": 0,
                "max_attempts": 2, "local_enabled": True, "ask_remaining_s": 60.0}}
        robot = LaneRobot(robot_id, state={
            "robot_id": robot_id, "mode": "IDLE", "navigation": "IDLE", "map_id": "m1",
            "pose": {"x": (i % 10) * 0.3, "y": (i // 10) * 0.3, "yaw": 0.0}, "safety": {"estop": False},
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}, "line_follow": lane})
        robot.power_health_value = _health(time.monotonic)
        if i % 10 == 9:
            robot.state_error = ConnectionError("down")
        robots.append(robot)
    console = FleetConsole([RobotEndpoint(r.robot_id, f"http://127.0.0.1:{9000 + i}", "t") for i, r in enumerate(robots)],
                           robots, relay_factory=lambda leader, followers, **kw: FakeRelay(leader, followers))
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, site_users={}, start_task_dispatcher=False,
                     site_logins={"kim": {"principal_id": "kim", "role": "operator",
                                          "password_scrypt": hash_password("pw-1234")}},
                     web_common=ROOT / "shared" / "web")
    listener = safe_listener()
    origin = f"http://localhost:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as playwright:
            browser, page, errors, _posts = _login(playwright, origin)
            # The first gathers fill power evidence; nominal cards fold once it is fresh.
            page.wait_for_function("() => document.querySelectorAll('#roster article[data-collapsed]').length >= 80",
                                   timeout=30000)
            page.evaluate("""() => { window.__lt = []; new PerformanceObserver((list) =>
              window.__lt.push(...list.getEntries().map((e) => e.duration))).observe({type: 'longtask'}); }""")
            page.wait_for_timeout(6000)  # several 1 s polls of 100 robots
            longest = page.evaluate("Math.max(0, ...window.__lt)")
            assert longest < 250, longest
            assert page.evaluate("document.getElementsByTagName('*').length") < 12000
            cards = page.locator("#roster article")
            assert cards.count() == 100
            first = [cards.nth(i).get_attribute("data-robot-id") for i in range(15)]
            exceptions = {robot_id for i, robot_id in enumerate(ids) if i % 20 == 7 or i % 10 == 9}
            assert set(first) == exceptions, first  # the 15 exception cards come first, open
            assert page.locator("#critical-list li").first.inner_text().split(":")[0] in exceptions
            head = page.locator("#critical-head small").inner_text() + page.locator("#warning-head small").inner_text()
            assert "외" in head or len(head) < 120, head  # a group head never lists every name
            for width, height in [(1440, 900), (1024, 768)]:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(1200)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                assert page.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), width
            page.locator(".formation-form-wrap > summary").click()
            members = page.locator("#formation-members")
            assert members.bounding_box()["height"] <= 12 * 16 + 1  # a bounded list, not 99 rows of boxes
            page.locator("#formation-filter").fill("05")
            visible = page.locator("#formation-members label:not([hidden])").all_inner_texts()
            assert visible and all("05" in robot_id for robot_id in visible), visible
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def test_map_labels_declutter_and_one_cause_is_one_queue_row(tmp_path):
    """Ten robots on a robot grid: every map marker gets its short id unless the spot is taken (five robots on
    one spot show one label; the stuck one always shows). Eight robots with the same warn cause are one queue
    row "… · 8대 (…)", the stuck robot's 최우선 row stays its own and first, and no head repeats the names."""
    from playwright.sync_api import expect, sync_playwright
    from test_server_gather_source import _health

    grid = {"map_id": "m1", "width": 160, "height": 120, "resolution": 0.025,
            "origin": {"x": -2.0, "y": -1.5, "yaw": 0.0}, "data": [0] * (160 * 120)}
    ids = [f"rosy_{i:03d}" for i in range(1, 11)]
    robots = []
    for i, robot_id in enumerate(ids):
        spot = (0.0, 0.0) if i < 5 else (-1.4 + 0.5 * (i - 5), 1.0)  # five share one spot
        lane = {"mode": "CAMERA_LINE", "state": "TRACKING"}
        if robot_id == "rosy_003":
            lane = {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": {
                "stuck_id": "s-3", "cause": "obstacle_ahead", "phase": "ASKING", "held_s": 4.0, "attempts": 0,
                "max_attempts": 2, "local_enabled": True, "ask_remaining_s": 60.0}}
        robot = LaneRobot(robot_id, map=grid, state={
            "robot_id": robot_id, "mode": "IDLE", "navigation": "IDLE", "map_id": "m1",
            "pose": {"x": spot[0], "y": spot[1], "yaw": 0.0}, "safety": {"estop": False},
            "localization": {"state": "LOCALIZED", "pose_frame": "map"}, "line_follow": lane})
        if i >= 2:  # eight robots whose power answer fails the schema: one warn cause on eight robots
            robot.power_health_value = {"battery": {"percent": 80}}
        else:
            robot.power_health_value = _health(time.monotonic)
        robots.append(robot)
    console = FleetConsole([RobotEndpoint(r.robot_id, f"http://127.0.0.1:{9100 + i}", "t") for i, r in enumerate(robots)],
                           robots, relay_factory=lambda leader, followers, **kw: FakeRelay(leader, followers))
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, site_users={}, start_task_dispatcher=False,
                     site_logins={"kim": {"principal_id": "kim", "role": "operator",
                                          "password_scrypt": hash_password("pw-1234")}},
                     web_common=ROOT / "shared" / "web")
    listener = safe_listener()
    origin = f"http://localhost:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as playwright:
            browser, page, errors, _posts = _login(playwright, origin)
            group = page.locator("#warning-list li[data-group] summary")
            expect(group).to_have_count(1, timeout=20000)
            expect(group).to_contain_text("· 8대 (rosy_003")
            expect(page.locator("#critical-list li").first).to_contain_text("rosy_003")
            assert page.locator("#critical-head small").inner_text() == ""
            assert page.locator("#warning-head small").inner_text() == ""
            group.click()
            expect(page.locator("#warning-list li[data-group] p")).to_contain_text("rosy_010")
            page.wait_for_function("() => (window.__mapMarkers || []).length === 10", timeout=20000)
            labels = page.evaluate("(window.__mapChips || []).map((chip) => chip.text)")
            assert "003" in labels, labels                      # the stuck robot always has its label
            assert {"006", "007", "008", "009", "010"} <= set(labels), labels  # apart: every one shows
            shared = [label for label in labels if label in {"001", "002", "003", "004", "005"}]
            assert len(shared) <= 2, labels                     # one spot: the rest hide instead of stacking
            assert page.evaluate("window.__mapChipsHidden") >= 3
            assert not errors
            browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
