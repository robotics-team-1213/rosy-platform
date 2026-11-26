"""ARM-CELL run/recover panel for arms A/B in real Chromium (opt-in, ROSY_RUN_BROWSER_TESTS=1).

The real Fleet app serves /console and its asset allowlist; every /api call is a fake answer, so no arm moves.
Cases: a dry run is sent first, its job is polled, and only then the same real run opens; recovery buttons appear
only where readiness says they apply; a job API refusal shows inline in the panel with its own reason; a viewer
sees every control locked and sends nothing.
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
BASE = "/api/fleet/cells/cell_ab/jobs"
SCOPE = {"role": "cell", "drive": False, "arms": True, "children": False, "enrollment": False}
REFUSAL = {"error_code": "PEER_ARM_NOT_FOLDED", "error": "arm_b is not folded",
           "detail": {"code": "PEER_ARM_NOT_FOLDED", "message": "arm_b is not folded"}}


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


def _arm(arm_id, label):
    return {"arm_id": arm_id, "source_id": f"omx_{arm_id}", "label": label, "fresh": True, "sequence": 1,
            "source_age_s": 0.1, "positions": {"joint1": 0.0}, "incidents": []}


def _open(origin, *, role="operator", refuse=False):
    posts, job = [], {"id": "j1", "job": "cell_policy_drive", "running": True, "exit": None}
    api = {
        "/api/fleet/session": {"principal_id": "op-7", "role": role},
        "/api/fleet/auth/session": {"authenticated": True, "role": role, "account_id": "op-7", "estop": False},
        "/api/fleet/incidents": {"reports": []},
        "/api/fleet/work": {"rows": []},
        "/api/fleet/state": {"fleet": {"name": "ARM-CELL", "online": 0, "total": 0, "scope": SCOPE}, "ts": 0.0, "robots": []},
        "/api/fleet/control-unit": {"schema_version": "rosy.control-unit.v1", "unit_id": "ARM-CELL", "scope": SCOPE,
                                    "site": {"name": "ARM-CELL"}},
        "/api/fleet/workcell-observations": {"read_only": True, "physical_acceptance": False, "workcells": [{
            "workcell_id": "cell", "label": "셀", "cameras": [], "arms": [_arm("arm_a", "팔 A"), _arm("arm_b", "팔 B")]}]},
        BASE + "/options": {"cell": "cell_ab", "arms": ["arm_a", "arm_b"],
                            "models": [{"id": "m1", "label": "A 운반 v3", "policy_revision": "f" * 64}]},
        BASE + "/readiness": {"arms": {
            "arm_a": {"folded": True, "human_hold_latched": False, "incident_held": False, "session_lock_held": False,
                      "live_state_age_s": 0.4, "active_job_id": None},
            "arm_b": {"folded": True, "human_hold_latched": True, "incident_held": False, "session_lock_held": True,
                      "live_state_age_s": 0.6, "active_job_id": None}}},
    }
    browser, page, errors = open_page(None, 1440, 900, url=origin)

    def serve(route):
        request = route.request
        path = urlparse(request.url).path
        if request.method != "GET":
            posts.append((path, json.loads(request.post_data or "{}")))
            if refuse:
                return route.fulfill(status=409, json=REFUSAL)
            if path.startswith(BASE + "/"):
                job.update(id=f"j{len(posts)}", job=path.rsplit("/", 1)[1], running=True, exit=None)
                return route.fulfill(status=202, json={"id": job["id"]})
            return route.fulfill(status=404, json={"detail": "no such api"})
        if path.startswith(BASE + "/j"):
            return route.fulfill(json=job)
        if path in api:
            return route.fulfill(json=api[path])
        return route.fulfill(status=404, json={"detail": "no such api"})

    page.route("**/api/**", serve)
    page.clock.install()
    page.goto(origin + "/console")
    page.clock.run_for(3000)
    return browser, page, errors, posts, job


def _panel(page):
    return page.locator("#cell-context-panel [data-cell-jobs]")


def _fill(panel):
    panel.get_by_label("모델").select_option("m1")
    panel.get_by_label("최대 청크 수").fill("3")
    panel.get_by_label("제안자").fill("proposer-b")


def test_dry_run_first_then_the_same_real_run(site):
    from playwright.sync_api import expect

    browser, page, errors, posts, job = _open(site)
    try:
        panel = _panel(page)
        expect(panel).to_be_visible()
        expect(panel.locator("[data-arm=arm_b]")).to_contain_text("사람 보류 걸림")
        expect(panel.locator("[data-arm=arm_b] ui-button", has_text="보류 복구")).to_have_count(1)
        expect(panel.locator("[data-arm=arm_a] ui-button")).to_have_count(0)
        expect(panel.locator("ui-button", has_text="안전 홈 복귀")).to_have_count(0)
        _fill(panel)
        panel.locator("ui-button", has_text="시험 실행").click()
        page.clock.run_for(100)
        assert posts == [(BASE + "/cell_policy_drive", {"arm": "arm_a", "proposer": "proposer-b", "mode": "act",
                                                       "paced_chunks": False, "max_chunks": 3, "dry_run": True,
                                                       "model": "m1"})]
        panel.get_by_label("시험 실행 (팔을 움직이지 않음)").uncheck()
        real = panel.locator("ui-button", has_text="실제 실행")
        assert real.evaluate("node => node.disabled") is True  # the dry run is still running
        job.update(running=False, exit=0)
        page.clock.run_for(6000)
        expect(panel.locator("[data-job-state]")).to_contain_text("완료")
        expect(real).not_to_have_attribute("reason", "같은 조건의 시험 실행이 먼저 성공해야 합니다.")
        assert real.evaluate("node => node.disabled") is False
        real.click()
        page.clock.run_for(100)
        assert posts[-1] == (BASE + "/cell_policy_drive", {**posts[0][1], "dry_run": False})
        assert errors == []
    finally:
        browser.close()


def test_recover_hold_and_refusal_shown_inline(site):
    from playwright.sync_api import expect

    browser, page, errors, posts, _ = _open(site, refuse=True)
    try:
        panel = _panel(page)
        panel.get_by_label("제안자").fill("proposer-b")
        panel.locator("[data-arm=arm_b] ui-button", has_text="보류 복구").click()
        page.clock.run_for(100)
        assert posts == [(BASE + "/recover_hold", {"arm": "arm_b", "proposer": "proposer-b"})]
        expect(panel.locator("[data-job-error]")).to_have_text("거절됨 (PEER_ARM_NOT_FOLDED): arm_b is not folded")
        assert errors == []
    finally:
        browser.close()


def test_viewer_sees_every_control_locked(site):
    from playwright.sync_api import expect

    browser, page, errors, posts, _ = _open(site, role="viewer")
    try:
        panel = _panel(page)
        expect(panel).to_be_visible()
        expect(panel.get_by_label("제안자")).to_be_disabled()
        run = panel.locator("ui-button", has_text="시험 실행")
        expect(run).to_have_attribute("reason", "운영자 권한이 필요합니다")
        recover = panel.locator("ui-button", has_text="보류 복구")
        assert recover.evaluate("node => node.disabled") is True
        run.click(force=True)
        recover.click(force=True)
        page.clock.run_for(100)
        assert posts == [] and errors == []
    finally:
        browser.close()
