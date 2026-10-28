"""D-540 2·7 — the one header on the four Fleet documents, measured in real Chromium.

The development-mode case fakes /api/fleet/state, traffic, trips and site-map/active (rosy_01 on a trip,
rosy_02 stuck, rosy_03 offline, as the 2026-10-09 audit) and, with ROSY_SHOT_DIR set, saves one capture
per document and viewport. The paired case has no development sessions: the E-stop locks only after the
session is refused and unlocks with the shared token.
"""

import copy
import os
import re
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
SIZES = [(1920, 1080), (1366, 768), (1440, 900), (1024, 768), (768, 1024), (390, 844), (320, 568)]
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
    // UiButton's generated reason descriptions vary with each document's current state.
    ids: [...document.querySelectorAll('ui-topbar [id]:not([data-reason])')].map(node => node.id)};
}"""


def _api():
    api = copy.deepcopy(tv.API)
    api.pop("/api/fleet/session")  # the real development session answers
    r1 = tv._robot("rosy_01", 2.0, 0.6, 1.57)
    r2 = tv._robot("rosy_02", 1.6, 0.0, 0.0)
    r2["line_stuck"] = STUCK
    r2["state"]["line_follow"] = {"mode": "CAMERA_LINE", "state": "HOLD", "stuck": STUCK}
    r3 = tv._robot("rosy_03", 0.0, 1.2, 3.14)
    # The shape console_view._error_of sends; a bare string drew "닿지 않음: undefined" on the card.
    r3.update(online=False, error={"reachable": False, "code": "ConnectError", "message": "ConnectError"},
              power_health=None, power_health_age_s=None)
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
            if name == "console":
                count = page.locator('main [aria-labelledby="map-heading"] #online-pill')
                expect(count).to_have_text("2/3", timeout=15000)
                offline = page.locator('article.robot-summary[data-robot-id="rosy_03"]').first
                expect(offline).to_contain_text("닿지 않음: 접속 실패")
                assert "undefined" not in page.locator("main").inner_text(), name
            else:
                expect(page.locator("#online-pill")).to_have_count(0)
            expect(page.locator("#estop")).to_be_enabled()
            expect(page.locator("#clock")).not_to_have_text("--:--:--")
            expect(page.locator("#link-state")).to_have_text("실시간", timeout=15000)
            for width, height in SIZES:
                page.set_viewport_size({"width": width, "height": height})
                page.wait_for_timeout(400)
                fact = page.evaluate(PROBE)
                assert page.locator('ui-topbar [data-header-region]').count() == 4
                for region in ("identity", "actions", "safety"):
                    expect(page.locator(f'[data-header-region="{region}"]')).to_be_visible()
                if width >= 768:  # 48rem 아래의 연결 자리는 평상시 비어 있다
                    expect(page.locator('[data-header-region="status"]')).to_be_visible()
                assert page.locator('[data-header-region="status"] ui-button').count() == 0
                assert page.locator('[data-header-region="actions"] > #fleet-inbox').count() == 1
                assert page.locator('[data-header-region="actions"] > #topbar-more').count() == 1
                assert page.locator('#topbar-more ui-button').count() == 0
                expect(page.locator('#topbar-more #user-role')).to_have_text("운영자")
                if width >= 480:
                    expect(page.locator('#topbar-more #user-role')).to_be_visible()
                else:  # 30rem 아래: 역할 글은 접히고 아래 줄의 접근 이름이 역할을 말한다
                    expect(page.locator('#topbar-more #user-role')).to_be_hidden()
                    expect(page.locator('#topbar-more [data-action-icon="account"]')).to_be_visible()
                expect(page.locator('#topbar-more #development-badge')).to_have_text("개발")
                expect(page.locator('#topbar-more')).to_have_attribute(
                    "aria-label", re.compile("계정과 접속.*운영자.*개발 연결 모드"))
                for value in page.locator('#topbar-more ui-tag').all():
                    expect(value).to_have_css("border-width", "0px")
                    expect(value).to_have_css("background-color", "rgba(0, 0, 0, 0)")
                assert page.locator('[data-header-region="safety"] #estop').count() == 1
                more = page.locator("#topbar-more")
                expect(page.locator('#topbar-extra')).not_to_be_visible()
                expect(page.locator("#fleet-theme")).to_be_hidden()  # 화면 표시는 계정 단추 아래에 있다
                more.click()
                expect(more).to_have_attribute("aria-expanded", "true")
                theme = page.locator("#topbar-extra #fleet-theme")
                expect(theme).to_be_visible()
                expect(theme).to_be_enabled()
                assert theme.locator(".ui-icon-label").count() == 0
                expect(theme).to_have_attribute("data-ui-tooltip", re.compile("테마:"))
                assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0, (name, width)
                preference = page.evaluate("RosyTheme.get()")
                for _ in range(3):
                    theme.click()
                assert page.evaluate("RosyTheme.get()") == preference
                theme.focus()
                page.keyboard.press("Escape")
                expect(more).to_be_focused()
                expect(more).to_have_attribute("aria-expanded", "false")

                measured[(name, width)] = fact
                nav = page.locator(".doc-tabs").bounding_box()
                main = page.locator("main").bounding_box()
                expect(page.get_by_role("contentinfo")).to_have_count(0)
                expect(page.locator('[data-header-region="status"] #clock')).not_to_have_text("--:--:--")
                if width >= 768:
                    expect(page.locator("#clock")).to_be_visible()
                    expect(page.locator("#link-state")).to_be_visible()
                else:  # 48rem 아래: 시계와 평상(실시간) 글은 접힌다
                    expect(page.locator("#clock")).to_be_hidden()
                    expect(page.locator("#link-state")).to_be_hidden()
                expect(page.get_by_role("banner")).to_have_count(1)
                assert page.locator(".doc-tabs a[aria-current=page]").count() == 1
                labels = []
                for link in page.locator(".doc-tabs a").all():
                    box = link.bounding_box()
                    assert box["height"] == 56 and 55 <= box["width"] <= 56, (name, width, box)
                    if width >= 1024:  # the vertical rail: inside the track's padding (8 + 8) and 1px rule
                        assert box["width"] <= nav["width"] - 17, (name, width, box, nav)
                    label, icon = link.locator(".ui-icon-label"), link.locator(".ui-icon").bounding_box()
                    expect(label).to_be_visible()
                    assert label.bounding_box()["y"] >= icon["y"] + icon["height"] - 1, (name, width)
                    assert link.get_attribute("data-ui-tooltip") is None, (name, width)
                    labels.append(label.text_content().strip())
                assert labels == ["관제", "작업", "기록", "지도", "설치"], (name, width)
                rail = page.locator(".doc-tabs")
                expect(rail.get_by_role("link", name="설치·보정", exact=True)).to_have_count(1)
                expect(rail.get_by_role("link", name="현장 지도", exact=True)).to_have_count(1)
                expect(page.locator("#fleet-inbox")).to_be_visible()
                inbox_text = page.locator("#fleet-inbox").text_content().strip()
                assert not inbox_text or inbox_text.isdecimal(), inbox_text
                expect(page.locator("#fleet-inbox")).to_have_attribute("aria-label", re.compile("알림 창"))
                for tab in page.locator(".context-tabs [role=tab]").all():
                    assert tab.locator(".ui-icon-label").bounding_box()["width"] <= 1
                    assert tab.bounding_box()["height"] == 48
                    expect(tab).to_have_attribute("data-ui-tooltip", tab.text_content().strip())
                if width >= 1024:
                    assert nav["x"] + nav["width"] <= main["x"] + 1, (name, width, nav, main)
                else:
                    assert nav["y"] + nav["height"] <= main["y"] + 1, (name, width, nav, main)
                x, y, w, h = fact["stop"]
                assert fact["overflow"] <= 0, (name, width, fact["overflowNodes"])
                assert page.locator("#development-badge").evaluate(
                    "node => node.scrollWidth <= node.clientWidth + 1"), (name, width)
                inbox = page.locator("#fleet-inbox").bounding_box()
                assert inbox and inbox["height"] >= 48 and inbox["y"] + inbox["height"] <= height
                assert h == inbox["height"] == 48 and w >= 48, (name, width, fact)
                assert page.locator("#estop").evaluate("""node => {
                  const style = getComputedStyle(node);
                  return style.fontSize === '14px' && style.paddingLeft === '12px' &&
                    style.paddingRight === '12px' &&
                    [...node.querySelectorAll('span:not(.sr-only)')].every(
                      label => getComputedStyle(label).fontSize === '14px');
                }"""), (name, width)
                assert x + w <= width and y + h <= height and y < 0.2 * height, (name, width, fact)
                assert width - (x + w) <= 32, (name, width, fact)  # right top corner
                expect(more).to_be_visible()
                # D-741 5: 앱 바는 320px까지 한 줄이고 높이는 --appbar-height(64px)다.
                assert fact["rows"] == 1, (name, width, fact)
                assert fact["header"] <= 64 + 1, (name, width, fact)
                assert fact["header"] <= 0.2 * height, (name, width, fact)
                if shots:
                    page.screenshot(path=str(Path(shots) / f"{name}-{width}x{height}.png"))
            page.locator("#fleet-inbox").click()
            expect(page.locator("#context-inbox")).to_be_visible()
            expect(page.locator("#context-inbox-tab")).to_have_attribute("aria-selected", "true")
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


@pytest.mark.parametrize('name,path', DOCS)
@pytest.mark.parametrize('width', [320, 390, 768, 1440])
def test_authenticated_account_refresh_does_not_reveal_token_or_collapse_layout(tmp_path, name, path, width):
    from playwright.sync_api import expect
    with _fleet(tmp_path, console_token='header-token') as (browser, origin):
        page = browser.new_page(viewport={'width': width, 'height': 1000})
        page.goto(origin+path)
        expect(page.locator('#user-role')).to_have_text('인증 필요')
        open_token_access(page)
        page.locator('#console-token').fill('header-token')
        page.locator('#token-save').click()
        expect(page.locator('#fleet-login')).to_be_hidden()
        page.locator('#topbar-more').click()
        expect(page.locator('#topbar-extra')).to_be_visible()
        expect(page.locator('#token-access')).to_be_hidden()
        before = page.locator('ui-topbar').bounding_box()
        page.evaluate("""async()=>{
          const header=await import('/console/assets/fleet-header.js');
          const response=await fetch('/api/fleet/session',{headers:{Authorization:'Bearer header-token'}});
          header.showSession(await response.json());
        }""")
        expect(page.locator('#topbar-more')).to_have_attribute('aria-expanded', 'true')
        assert abs(page.locator('ui-topbar').bounding_box()['height']-before['height'])<=1
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#fleet-theme').focus()
        page.keyboard.press('Escape')
        expect(page.locator('#topbar-more')).to_be_focused()
        if shots := os.environ.get('ROSY_SHOT_DIR'):
            target=Path(shots).expanduser();target.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(target/f'account-stable-{name}-{width}.png'))
        page.close()


@pytest.mark.parametrize('width', [320, 390, 768, 1440])
def test_canonical_chrome_is_in_first_response_without_page_javascript(tmp_path, width):
    from playwright.sync_api import expect
    with _fleet(tmp_path, console_token='header-token') as (browser, origin):
        for name, path in DOCS:
            page = browser.new_page(viewport={'width': width, 'height': 1000}, java_script_enabled=False)
            response = page.goto(origin+path)
            assert '<!-- fleet:header:start -->' in response.text()
            assert '<!-- fleet:nav:start -->' in response.text()
            expect(page.locator('ui-topbar')).to_have_count(1)
            expect(page.locator('#estop')).to_be_visible()
            expect(page.locator('#estop')).to_have_attribute('data-always-live', '')
            expect(page.locator('.doc-tabs a')).to_have_count(5)
            expect(page.locator('.doc-tabs + .ui-subnav')).to_have_count(1)
            expect(page.locator('#topbar-extra')).to_be_hidden()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), name
            box = page.locator('#estop').bounding_box()
            assert box['x']>=0 and box['x']+box['width']<=width+1 and box['y']+box['height']<=1000, (name,box)
            page.close()


@pytest.mark.parametrize('width', [320, 390, 768, 1440])
def test_task_layout_and_feedback_share_role_geometry(tmp_path, width):
    from playwright.sync_api import expect
    with _fleet(tmp_path, console_token='registry-only', development_sessions=DevelopmentSessions()) as (browser, origin):
        for name, path in DOCS:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.goto(origin+path)
            expect(page.locator('#user-role')).to_have_text('운영자')
            page.evaluate("""async()=>{
              const header=await import('/console/assets/fleet-header.js');
              header.stopNotice('Layout feedback fixture');header.noteLink({status:503});
            }""")
            expect(page.locator('#estop-feedback')).to_be_visible()
            geometry = page.evaluate("""()=>{
              const main=document.querySelector('main'),css=getComputedStyle(main),root=getComputedStyle(document.documentElement);
              const box=main.getBoundingClientRect(),feedback=document.querySelector('#estop-feedback').getBoundingClientRect();
              return {padding:parseFloat(css.paddingLeft),role:parseFloat(root.getPropertyValue('--inset-task-page')),
                left:box.left+parseFloat(css.paddingLeft),feedback:feedback.left,
                overflow:document.documentElement.scrollWidth-innerWidth};
            }""")
            assert geometry['padding']==geometry['role'] and abs(geometry['left']-geometry['feedback'])<=1, (name,geometry)
            assert geometry['overflow']<=0, (name,geometry)
            if shots := os.environ.get('ROSY_SHOT_DIR'):
                target=Path(shots).expanduser();target.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(target/f'layout-roles-{name}-{width}.png'))
            page.close()


def test_a_lost_link_is_readable_on_a_phone(tmp_path):
    from playwright.sync_api import expect

    # Fleet gone behind the proxy: every API answer is 502, the state poll included.
    with _fleet(tmp_path, console_token="header-token") as (browser, origin):
        for name, path in DOCS:
            page = browser.new_page(viewport={"width": 320, "height": 568})
            page.route("**/api/fleet/**", lambda route: route.fulfill(status=502, json={"detail": "bad gateway"}))
            page.goto(origin + path)
            word = page.locator("#link-state")
            expect(word).to_have_text("연결 끊김", timeout=15000)
            expect(word).to_be_visible()
            box, stop = word.bounding_box(), page.locator("#estop").bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= 320, (name, box)
            assert box["y"] >= stop["y"] + stop["height"] - 1, (name, box, stop)  # its own row under the bar
            expect(page.locator("#estop")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 0, name
            page.close()


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
