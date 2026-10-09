"""D-540 2·7 — the one header on the four Fleet documents, measured in real Chromium.

The development-mode case fakes /api/fleet/state, traffic, trips and site-map/active (rosy_01 on a trip,
rosy_02 stuck, rosy_03 offline, as the 2026-10-09 audit) and, with ROSY_SHOT_DIR set, saves one capture
per document and viewport. The paired case has no development sessions: the E-stop locks only after the
session is refused and unlocks with the shared token.
"""

import copy
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, launch_options, open_token_access, safe_listener

from fakes import FakeRobot
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.development_session import DevelopmentSessions
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore
from fleet.swarm.robots import RobotEndpoint
import test_traffic_view_browser as tv

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]
DOCS = [("console", "/console"), ("install", "/console/install"),
        ("site-map", "/console/site-map"), ("cell", "/console/cell")]
SIZES = [(1920, 1080), (1440, 900), (1024, 768), (390, 844), (320, 700)]
STUCK = {"stuck_id": "stuck-abc", "cause": "obstacle_ahead", "phase": "ASKING", "held_s": 41.0,
         "attempts": 1, "max_attempts": 2, "local_enabled": True, "ask_remaining_s": 9.0,
         "last_answer": None, "decisions": ["WAIT", "RESUME", "BACK_AND_RETRY", "MANUAL", "ABORT"],
         "front_clearance_m": 0.12, "rear_clearance_m": 0.31, "rear_state": "clear",
         "turn_clearance_m": 0.09, "preview_seq": 812, "opened_event": True, "robot_online": True}

# Header rows: visible topbar children grouped by vertical overlap. The E-stop's own box and the
# one-shot facts the contract names (D-540 7: same size, same place, first screen, no sideways scroll).
PROBE = """() => {
  const boxes = [...document.querySelector('ui-topbar').children]
    .map(node => node.getBoundingClientRect()).filter(box => box.width > 0 && box.height > 0)
    .sort((a, b) => a.top - b.top);
  let rows = 0, bottom = -1;
  for (const box of boxes) { if (box.top >= bottom - 1) { rows += 1; bottom = box.bottom; } else bottom = Math.max(bottom, box.bottom); }
  const stop = document.querySelector('#estop').getBoundingClientRect();
  return {rows, header: document.querySelector('ui-topbar').getBoundingClientRect().height,
    stop: [Math.round(stop.x), Math.round(stop.y), Math.round(stop.width), Math.round(stop.height)],
    overflow: document.documentElement.scrollWidth - innerWidth,
    overflowNodes: [...document.querySelectorAll('body *')].filter(node => node.getBoundingClientRect().right > innerWidth + 1)
      .slice(0, 8).map(node => [node.tagName, node.id, node.textContent.slice(0, 30), Math.round(node.getBoundingClientRect().right)]),
    ids: [...document.querySelectorAll('ui-topbar [id]')].map(node => node.id)};
}"""


def _api():
    api = copy.deepcopy(tv.API)
    api.pop("/api/fleet/session")  # the real development session answers
    r1 = tv._robot("rosy_01", 2.0, 0.6, 1.57)
    r2 = tv._robot("rosy_02", 1.6, 0.0, 0.0)
    r2["line_stuck"] = STUCK
    r2["state"]["line_follow"] = {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": STUCK}
    r3 = tv._robot("rosy_03", 0.0, 1.2, 3.14)
    r3.update(online=False, error="robot unreachable: ConnectError", power_health=None, power_health_age_s=None)
    api["/api/fleet/state"] = {"fleet": {"name": "site", "online": 2, "total": 3}, "ts": 0.0, "robots": [r1, r2, r3]}
    return api


@contextmanager
def _fleet(tmp_path, **options):
    console = FleetConsole([RobotEndpoint("rosy_01", "http://127.0.0.1:8080", "t")], [FakeRobot("rosy_01")])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "fleet.sqlite3"), robot_ids=console.robot_ids)
    app = create_app(console, task_service=tasks, web_common=ROOT / "shared" / "web",
                     start_task_dispatcher=False, **options)
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
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            launch = launch_options()
            launch["args"] = [f"--explicitly-allowed-ports={urlparse(origin).port}"]
            browser = playwright.chromium.launch(**launch)
            try:
                yield browser, origin
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def test_four_documents_draw_one_header_and_one_estop(tmp_path):
    from playwright.sync_api import expect

    api = _api()
    shots = os.environ.get("ROSY_SHOT_DIR")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
    measured = {}
    with _fleet(tmp_path, console_token="registry-only", development_sessions=DevelopmentSessions()) as (browser, origin):
        for name, path in DOCS:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda exc, e=errors: e.append(str(exc)))

            def serve(route):
                p = urlparse(route.request.url).path
                if route.request.method == "GET" and p in api:
                    route.fulfill(json=api[p])
                elif route.request.method != "GET" and "/auth/" not in p:
                    route.fulfill(status=409, json={"detail": "header test: no writes"})
                else:
                    route.continue_()

            page.route("**/api/**", serve)
            page.goto(origin + path)
            role = page.locator("#user-role")
            expect(role).to_have_text("운영자", timeout=15000)  # D-540 2: Korean role, principal id in title
            expect(page.locator("#development-badge")).to_be_visible()
            expect(page.locator("#online-pill")).to_have_text("2/3 연결", timeout=15000)
            expect(page.locator("#estop")).to_be_enabled()
            expect(page.locator("#clock")).not_to_have_text("--:--:--")
            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(400)
                fact = page.evaluate(PROBE)
                measured[(name, width)] = fact
                x, y, w, h = fact["stop"]
                assert fact["overflow"] <= 0, (name, width, fact["overflowNodes"])
                assert x + w <= width and y + h <= height and y < 0.2 * height, (name, width, fact)
                assert width - (x + w) <= 32, (name, width, fact)  # right top corner
                if width <= 390:
                    more = page.get_by_role("button", name="접속과 화면 표시")
                    expect(more).to_be_visible()
                    if width == 390:
                        expect(more).to_contain_text("접속")
                    more.click()
                    expect(page.locator("#theme-choice-label")).to_be_visible()
                    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0, (name, width)
                    more.click()
                if width >= 1440:
                    assert fact["rows"] == 1, (name, width, fact)
                elif width >= 1024:
                    assert fact["rows"] <= 2, (name, width, fact)
                else:
                    assert fact["header"] <= 0.2 * height, (name, width, fact)
                if shots:
                    page.screenshot(path=str(Path(shots) / f"{name}-{width}x{height}.png"))
            assert not errors, (name, errors)
            page.close()
    for width, _height in SIZES:
        first = measured[("console", width)]
        for name, _path in DOCS:
            fact = measured[(name, width)]
            assert fact["ids"] == first["ids"], (name, width)
            # Same size and place on every document (a scrollbar may shift x by its width).
            assert fact["stop"][2:] == first["stop"][2:], (name, width, fact["stop"], first["stop"])
            assert abs(fact["stop"][1] - first["stop"][1]) <= 1, (name, width, fact["stop"], first["stop"])


def test_estop_locks_only_after_the_session_is_refused(tmp_path):
    from playwright.sync_api import expect

    with _fleet(tmp_path, console_token="header-token") as (browser, origin):
        for name, path in DOCS:
            for width, height in ((1440, 900), (390, 844)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(origin + path)
                stop = page.locator("#estop")
                expect(page.locator("#user-role")).to_have_text("인증 필요", timeout=15000)
                expect(stop).to_be_disabled()
                expect(stop).to_have_attribute("reason", "접속이 필요합니다")
                expect(stop).to_be_visible()
                open_token_access(page)
                page.locator("#console-token").fill("header-token")
                page.locator("#token-save").click()
                expect(page.locator("#user-role")).to_contain_text("운영자", timeout=15000)
                expect(stop).to_be_enabled()
                assert stop.get_attribute("reason") is None
                page.close()
