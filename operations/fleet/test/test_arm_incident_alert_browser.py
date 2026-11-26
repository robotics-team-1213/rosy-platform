"""An open arm incident is cleared from the alert drawer in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The real Fleet app serves /console and its asset allowlist; every /api call is a fake answer. One arm reports one open
incident. Cases: a person-check hold cleared with one check box and one confirm (the exact clear POST, then the row
goes once the refreshed observation has no open incident); a guarded-fold incident shows only its next step; a
viewer session sees the clear step locked. No arm moves.
"""

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, open_page, safe_listener

from fleet.server.app import create_app
from fleet.server.console import FleetConsole

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
ROOT = Path(__file__).resolve().parents[3]
SOURCE, INCIDENT = "arm_a_follower", "a" * 32
CLEAR_PATH = f"/api/fleet/workcell-observations/arms/{SOURCE}/incidents/{INCIDENT}/clear"
HOLD_PATH = "/api/fleet/pipeline/arm-holds/clear"
HUMAN_HOLD = "runner: human hold; a person checks the arm (jaws, contacts, wedged objects) before torque ON"
FOLD = "torque off with arm extended; guarded fold required"


@pytest.fixture(scope="module")
def site():
    app = create_app(FleetConsole([], []), console_token="operator-token", web_common=ROOT / "shared" / "web")
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3, log_config=None))
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


def _open(origin, *, reason, role="operator", hold=None, refuse=None, second=None):
    """/console with one arm and one open held incident; returns the page, the posts and the incident list."""
    incidents = [{"incident_id": INCIDENT, "source_id": SOURCE, "session_id": "s1", "state": "open", "held": True,
                  "reported_at": time.time() - 30, "facts": {}, "decision": {"hold": True, "reason": reason},
                  "recovery": None, "explanation": None, "cleared": None, "frames": [], "evidence": []}]
    if second:
        incidents.append({**incidents[0], "incident_id": "b" * 32, "reported_at": time.time() - 20,
                          "decision": {"hold": True, "reason": second}})
    posts = []
    api = {
        "/api/fleet/session": {"principal_id": "op-7", "role": role},
        "/api/fleet/incidents": {"reports": []},
        "/api/fleet/state": {"fleet": {"name": "cell", "online": 0, "total": 0}, "ts": 0.0, "robots": []},
    }
    browser, page, errors = open_page(None, 1440, 900, url=origin)

    def serve(route):
        request = route.request
        path = urlparse(request.url).path
        if request.method != "GET":
            posts.append((path, request.post_data))
            if path == HOLD_PATH:
                if refuse:
                    return route.fulfill(status=409, json={"detail": {"code": refuse}})
                return route.fulfill(json={"ok": True, "cleared_arms": ["arm_a"]})
            if path == CLEAR_PATH:
                incidents[0].update(state="cleared", held=False,
                                    cleared={"by": "op-7", "at": time.time(), **json.loads(request.post_data)})
                return route.fulfill(json={"held": False, "incident_ids": [], "reason": None})
            return route.fulfill(status=404, json={"detail": "no such api"})
        if path == "/api/fleet/workcell-observations":
            return route.fulfill(json={"read_only": True, "physical_acceptance": False, "workcells": [{
                "workcell_id": "cell", "label": "셀", "cameras": [], "arms": [{
                    "source_id": SOURCE, "arm_id": "arm_a", "label": "팔 A", "fresh": True, "sequence": 1,
                    "source_age_s": 0.1, "positions": {"joint1": 0.0}, "incidents": incidents}]}]})
        if path == "/api/fleet/pipeline/status" and hold is not None:
            return route.fulfill(json={"arm_holds": {"arm_a": {"held": hold}}})
        if path in api:
            return route.fulfill(json=api[path])
        return route.fulfill(status=404, json={"detail": "no such api"})

    page.route("**/api/**", serve)
    page.clock.install()
    page.goto(origin + "/console")
    page.clock.run_for(3000)
    return browser, page, errors, posts


def _settle(page, posts, count):
    """Advance the page clock until the confirm's sequential requests have all been sent."""
    for _ in range(60):
        if len(posts) >= count:
            return
        page.clock.run_for(50)
        time.sleep(0.02)


def _row(page):
    return page.locator("#critical-list > li[data-decision='arm-incident']")


def _open_drawer(page):
    from playwright.sync_api import expect

    expect(_row(page)).to_have_count(1)
    page.locator("#fleet-inbox").click()
    expect(page.locator("#queues-panel")).to_have_attribute("data-open", "true")
    expect(_row(page)).to_contain_text("팔 A")
    expect(_row(page)).to_contain_text("팔 보류")


def test_person_check_hold_clears_with_one_check_and_one_confirm(site):
    from playwright.sync_api import expect

    browser, page, errors, posts = _open(site, reason=HUMAN_HOLD)
    try:
        _open_drawer(page)
        step = _row(page).locator("[data-arm-incident-clear]")
        expect(step).to_be_visible()  # the most urgent decision row opens on its clear step
        check = step.locator("input[type=checkbox]")
        expect(step.locator("label")).to_contain_text("집게 · 닿은 곳 · 끼인 물체")
        confirm = step.locator("ui-button", has_text="확인했습니다 · 해제")
        assert confirm.evaluate("node => node.disabled") is True  # nothing sent before the check
        check.check()
        expect(confirm).not_to_have_attribute("reason", "확인 항목을 직접 확인하고 체크하세요.")
        confirm.click()
        _settle(page, posts, 1)
        assert [p for p, _ in posts] == [CLEAR_PATH]
        assert json.loads(posts[0][1]) == {"note": "현장 확인: 집게, 닿은 곳, 끼인 물체 이상 없음",
                                          "cause": "unknown", "basis": "unknown"}
        page.clock.run_for(3000)
        expect(_row(page)).to_have_count(0)
        expect(page.locator("#queues-empty")).to_be_visible()
        assert errors == []
    finally:
        browser.close()


def test_guarded_fold_incident_shows_only_its_next_step(site):
    from playwright.sync_api import expect

    browser, page, errors, posts = _open(site, reason=FOLD)
    try:
        _open_drawer(page)
        step = _row(page).locator("[data-arm-incident-step]")
        expect(step).to_contain_text("가드 홈 복귀")
        expect(step.locator("a")).to_have_attribute("href", f"/console/cell?focus=arm:{SOURCE}#observation-heading")
        expect(_row(page).locator("[data-arm-incident-clear]")).to_have_count(0)
        expect(_row(page).locator("ui-button", has_text="해제")).to_have_count(0)
        assert posts == [] and errors == []
    finally:
        browser.close()


def test_viewer_session_sees_the_clear_step_locked(site):
    from playwright.sync_api import expect

    browser, page, errors, posts = _open(site, reason=HUMAN_HOLD, role="viewer")
    try:
        _open_drawer(page)
        step = _row(page).locator("[data-arm-incident-clear]")
        expect(step.locator("input[type=checkbox]")).to_be_disabled()
        confirm = step.locator("ui-button", has_text="확인했습니다 · 해제")
        assert confirm.evaluate("node => node.disabled") is True
        expect(confirm).to_have_attribute("reason", "운영자 권한이 필요합니다")
        confirm.click(force=True)
        page.clock.run_for(100)
        assert posts == [] and errors == []
    finally:
        browser.close()


def test_held_fleet_arm_hold_clears_in_the_same_confirm(site):
    from playwright.sync_api import expect

    browser, page, errors, posts = _open(site, reason=HUMAN_HOLD, hold=True)
    try:
        _open_drawer(page)
        step = _row(page).locator("[data-arm-incident-clear]")
        step.locator("input[type=checkbox]").check()
        step.locator("ui-button", has_text="확인했습니다 · 해제").click()
        _settle(page, posts, 2)
        note = {"note": "현장 확인: 집게, 닿은 곳, 끼인 물체 이상 없음", "cause": "unknown", "basis": "unknown"}
        assert [p for p, _ in posts] == [HOLD_PATH, CLEAR_PATH]
        assert json.loads(posts[0][1]) == {"arm_id": "arm_a", **note}
        assert json.loads(posts[1][1]) == note
        page.clock.run_for(3000)
        expect(_row(page)).to_have_count(0)
        assert errors == []
    finally:
        browser.close()


def test_refused_fleet_arm_hold_keeps_the_row_with_its_next_step(site):
    from playwright.sync_api import expect

    browser, page, errors, posts = _open(site, reason=HUMAN_HOLD, hold=True, refuse="STAGED_HOMING_VISUAL_VERIFY_REQUIRED")
    try:
        _open_drawer(page)
        step = _row(page).locator("[data-arm-incident-clear]")
        step.locator("input[type=checkbox]").check()
        step.locator("ui-button", has_text="확인했습니다 · 해제").click()
        _settle(page, posts, 1)
        expect(step.locator("[role=status]")).to_be_visible()
        assert [p for p, _ in posts] == [HOLD_PATH]  # nothing cleared: the incident stays open
        expect(step.locator("[role=status]")).to_contain_text("카메라 접힘 확인")
        page.clock.run_for(3000)
        expect(_row(page)).to_have_count(1)
        assert errors == []
    finally:
        browser.close()


def test_second_incident_needing_a_guarded_fold_blocks_the_clear(site):
    from playwright.sync_api import expect

    browser, page, errors, posts = _open(site, reason=HUMAN_HOLD, hold=True, second=FOLD)
    try:
        expect(_row(page)).to_have_count(2)
        page.locator("#fleet-inbox").click()
        step = page.locator("#critical-list [data-arm-incident-clear]").first
        expect(step).to_be_visible()
        step.locator("input[type=checkbox]").check()
        step.locator("ui-button", has_text="확인했습니다 · 해제").click()
        expect(step.locator("[role=status]")).to_contain_text("가드 홈 복귀")
        page.clock.run_for(500)
        assert posts == []  # neither the hold clear nor the incident clear
        expect(_row(page)).to_have_count(2)
        assert errors == []
    finally:
        browser.close()
