"""D-793 real Chromium: three named logins walk the learned-policy approval page on a real Fleet."""
import base64
import threading
import time

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, safe_listener

from fleet.cli import default_web_common
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.mission_service import MissionService
from fleet.server.mission_store import MissionStore
from fleet.server.proposal_store import ProposalStore
from fleet.server.site_users import hash_password
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

from test_password_session import TYPED as PASSWORD  # noqa: E402  shared fixture value
REV = dict(rig_revision="rig-1", calibration_revision="cal-1")


class Transport:
    def owner_state(self, *, workcell_id, instance_id):
        return {"version": 1, "status": 200, "workcell_id": workcell_id, "instance_id": instance_id,
                "owner": {"state": "ready", "observed_sequence": 1}}


def _serve(tmp_path):
    db, digest = tmp_path / "fleet.db", hash_password(PASSWORD)
    logins = {name: {"principal_id": name, "role": "operator", "password_scrypt": digest, **extra}
              for name, extra in (("alice", {"policy_admin": True}), ("bob", {"policy_admin": True}),
                                  ("carol", {}))}
    app = create_app(FleetConsole([], []), task_service=FleetTaskService(FleetTaskStore(db), robot_ids=()),
                     site_users={}, site_logins=logins, mission_service=MissionService(MissionStore(db)),
                     proposal_store=ProposalStore(db), omx_instances={"cell-1": "arm-1"},
                     omx_stop_transport=Transport(), web_common=default_web_common(), start_task_dispatcher=False)
    store = app.state.policy_governance
    for stage in ("L0", "L1", "L2"):
        proposal = store.propose(workcell_id="cell-1", policy_revision="act-r1", to_stage=stage,
                                 evidence_sha256="a" * 64, note="offline eval", principal_id="alice", **REV)
        store.decide(proposal_id=proposal["proposal_id"], approve=True, principal_id="bob")
    store.propose(workcell_id="cell-1", policy_revision="act-r1", to_stage="L3", evidence_sha256="b" * 64,
                  note="shadow agreement", principal_id="alice", **REV)
    listener = safe_listener()
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    deadline = time.monotonic() + 20
    while not server.started and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    return server, worker, f"http://localhost:{listener.getsockname()[1]}"


def _login(browser, origin, name, size):
    page = browser.new_context(viewport={"width": size[0], "height": size[1]}).new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(origin + "/console/policy")
    page.locator("#policy-login").click()
    page.locator("[data-login=login]").fill(name)
    page.locator("[data-login=password]").fill(PASSWORD)
    page.locator("[data-login=submit]").click()
    page.wait_for_url(origin + "/console/policy")
    return page, errors


def _confirm(page):
    page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()


@pytest.mark.parametrize("size", [(1366, 768), (390, 844)])
def test_two_people_approve_and_anyone_can_lock(tmp_path, size):
    from playwright.sync_api import expect, sync_playwright
    server, worker, origin = _serve(tmp_path)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                alice, alice_errors = _login(browser, origin, "alice", size)
                verdict = alice.locator("#policy-verdict")
                expect(verdict).to_contain_text("열린 승인 창이 없습니다")
                own = alice.locator("#policy-proposals li", has_text="3단계 · 입회 시험").locator("ui-button", has_text="승인…")
                expect(own).to_be_disabled()
                expect(own).to_have_attribute("reason", "제안한 사람과 다른 관리자가 승인해야 합니다")

                bob, bob_errors = _login(browser, origin, "bob", size)
                bob.locator("#policy-proposals li", has_text="3단계 · 입회 시험").locator("ui-button", has_text="승인…").click()
                _confirm(bob)
                expect(bob.locator("#policy-stages")).to_contain_text("3단계 · 입회 시험")
                bob.locator("#policy-window-kind").select_option("supervised")
                bob.locator("#policy-window-scope").fill("strawberry pick")
                bob.locator("#policy-window-request").click()
                expect(bob.locator("#policy-message")).to_contain_text("승인 창을 요청했습니다")

                alice.reload()
                alice.locator("#policy-windows li", has_text="승인 대기").locator("ui-button", has_text="승인…").click()
                _confirm(alice)
                expect(verdict).to_contain_text("입회 시험 승인 창")

                carol, carol_errors = _login(browser, origin, "carol", size)
                expect(carol.locator("#policy-window-request")).to_be_disabled()
                carol.locator("#policy-incident-text").fill("gripper hit the bowl")
                carol.locator("#policy-incident-report").click()
                _confirm(carol)
                expect(carol.locator("#policy-verdict")).to_contain_text("사고 잠금 1건")

                bob.reload()
                bob.locator("#policy-incidents li").locator("ui-button", has_text="잠금 해제…").click()
                _confirm(bob)
                expect(bob.locator("#policy-verdict")).to_contain_text("열린 승인 창이 없습니다")
                for page in (alice, bob, carol):
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert not (alice_errors or bob_errors or carol_errors)
                shot = base64.b64encode(alice.screenshot(full_page=True)).decode()
                print(f"\nPOLICY_SHOT_{size[0]} {shot}")
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=10)
