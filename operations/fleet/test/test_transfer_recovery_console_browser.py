import asyncio
from hashlib import sha256
from pathlib import Path
import shutil
import threading
import time
from uuid import UUID

import pytest

from browser_harness import browser_tests_enabled, launch_options, safe_listener, save_temp_screenshot
from test_transfer_recovery_api import (
    rig, geometry, policy, installation, fail_transfer, observe_recovery, RECOVERY_CONTEXT,
)
from test_arm_transfer_job_api import PATH, headers
from test_physical_transfer_observer_api import OBSERVER
from fleet.server.physical_transfer_observations import _document
from test_physical_transfer_recovery import measured
from test_physical_transfer_store import NOW

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="real browser opt-in")


def close_child(case, child):
    dispatcher = case.app.state.arm_transfer_dispatcher
    state = dispatcher.execution.snapshot(child)
    for phase, offset, sequence, clock in [("PRE_DISPATCH", 2_000_000_000, 50, 2_350_000_000),
                                            ("POST_ACTION", 2_600_000_000, 100, 2_950_000_000)]:
        case.clock[0] = NOW + clock
        raw = measured(case.store, state, offset=offset, sequence=sequence, target=phase == "POST_ACTION")
        response = case.client.post(PATH + "/" + child + "/observations", headers=OBSERVER,
            json=dict(phase=phase, expected_request_digest=state["grant"]["request_digest"], observations=_document(raw)))
        assert response.status_code == 200, response.text
        if phase == "PRE_DISPATCH":
            assert dispatcher.tick()["status"] == "ACTION_SUCCEEDED"
    assert response.json()["job"]["status"] == "GOAL_CONFIRMED"


@pytest.mark.parametrize("width", [320, 390, 1920])
@pytest.mark.parametrize("lost_reply", [False, True])
def test_real_http_failure_request_observation_approval_and_child_result(rig, monkeypatch, width, lost_reply):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    async def monitor():
        await asyncio.Event().wait()
    monkeypatch.setattr(rig.app.state.arm_transfer_dispatcher, "run", monitor)
    rig.app.state.web_common = Path(__file__).resolve().parents[3] / "shared/web"
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(rig.app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        control = rig.tasks.dispatch_control()
        if not control["dispatch_enabled"]:
            rig.tasks.rearm_dispatch(expected_generation=control["generation"], actor_id="operator")
        c = fail_transfer(rig)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**launch_options())
            try:
                page = browser.new_page(viewport={"width": width, "height": 900})
                errors, posts = [], []
                proposer_posts = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: proposer_posts.append(request.url) if request.method == "POST" else None)
                page.add_init_script("sessionStorage.setItem('rosy-console-token', 'harbor-secret')")
                link = origin + "/console?view=work&arm_transfer=" + c.parent
                page.goto(link)
                request = page.locator("#arm-transfer-recovery-request")
                expect(request).to_be_enabled()
                expect(page.locator("#arm-transfer-recovery")).to_contain_text("시뮬레이션")
                if lost_reply:
                    def lose_request(route):
                        if route.request.method == "POST":
                            assert route.fetch().status == 200
                            route.abort("failed")
                        else:
                            route.continue_()
                    page.route("**" + c.url + "/recovery", lose_request)
                request.click()
                if lost_reply:
                    expect(page.locator("#arm-transfer-recovery-state")).to_contain_text("요청 결과 미확인")
                    expect(request).to_be_disabled()
                    assert len(proposer_posts) == 1
                    page.locator("#arm-transfer-read").click()
                    page.unroute("**" + c.url + "/recovery")
                    expect(page.locator("#arm-transfer-id")).to_be_editable()
                expect(page.locator("#arm-transfer-recovery-state")).to_contain_text("새 관측 대기")
                assert len(proposer_posts) == 1
                expect(page.locator("#arm-transfer-recovery-approve")).to_be_disabled()
                intent = c.client.get(c.url + "/recovery", headers=headers("harbor")).json()["recovery"]
                observe_recovery(c, intent)
                monkeypatch.setattr("fleet.server.physical_transfer_store.uuid4", lambda: UUID(hex="8" * 32))
                page.close()

                page = browser.new_page(viewport={"width": width, "height": 900})
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: posts.append(request.url) if request.method == "POST" else None)
                page.add_init_script("sessionStorage.setItem('rosy-console-token', 'operator-secret')")
                page.goto(link)
                approve = page.locator("#arm-transfer-recovery-approve")
                expect(approve).to_be_enabled()
                expect(page.locator("#arm-transfer-recovery")).to_contain_text("실패")
                assert not posts and len(c.port.submitted) == 1
                if lost_reply:
                    def lose(route):
                        response = route.fetch()
                        assert response.status == 200
                        route.abort("failed")
                    page.route("**/recovery/*/approve", lose)
                approve.click()
                page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
                if lost_reply:
                    expect(page.locator("#arm-transfer-recovery-state")).to_contain_text("결과 미확인")
                    expect(approve).to_be_disabled()
                    child = c.client.get(c.url + "/recovery", headers=headers("operator")).json()["recovery"]["child_mission_id"]
                    child_path = "**" + PATH + "/" + child
                    page.route(child_path, lambda route: route.fulfill(status=503, json={"detail": "read unavailable"}))
                    page.locator("#arm-transfer-read").click()
                    expect(page.locator("#arm-transfer-recovery-child")).to_contain_text("복구 횟수는 이미 사용됐습니다")
                    expect(page.locator("#arm-transfer-recovery-child")).to_contain_text(child)
                    expect(page.locator("#arm-transfer-recovery-request")).to_be_disabled()
                    assert len(posts) == 1
                    page.unroute(child_path)
                expect(page.locator("#arm-transfer-recovery-state")).to_contain_text("복구 시도")
                view = c.client.get(c.url + "/recovery", headers=headers("operator")).json()["recovery"]
                child = view["child_mission_id"]
                assert child and child != c.parent and len(posts) == 1
                close_child(c, child)
                page.locator("#arm-transfer-read").click()
                expect(page.locator("#arm-transfer-recovery-child")).to_contain_text("물리 목표 확인됨")
                expect(page.locator("#arm-transfer-recovery-child")).to_contain_text(child)
                expect(page.locator("#arm-transfer-recovery-request")).to_be_disabled()
                assert c.client.get(c.url, headers=headers("harbor")).json()["job"]["status"] == "HOLD"
                assert len(posts) == 1 and len(c.port.submitted) == 2 and not errors
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert page.locator("#arm-transfer-recovery-child").evaluate("node => node.scrollWidth <= node.clientWidth")
                bounds = page.locator("#arm-transfer-recovery-child").evaluate("""node => ({
                    child: node.getBoundingClientRect().right,
                    panel: node.closest('.work-overview').getBoundingClientRect().right,
                    viewport: innerWidth})""")
                assert bounds["child"] <= min(bounds["panel"], bounds["viewport"]), bounds
                page.locator("#arm-transfer-recovery").scroll_into_view_if_needed()
                shot = save_temp_screenshot(page, f"transfer-recovery-{width}-{'lost' if lost_reply else 'ok'}.png")
                retained = Path.home() / "rosy-test/artifacts/transfer-recovery" / c.parent / shot.name
                retained.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(shot, retained)
                print(f"retained screenshot: {retained} sha256 {sha256(retained.read_bytes()).hexdigest()}")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()
