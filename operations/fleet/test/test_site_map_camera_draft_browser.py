"""The camera draft panel and the camera-witnessed reality check in real Chromium (opt-in).

End-to-end over the served app: the Vision draft-map fetch is stubbed same-origin (the
D-375 browser pattern), everything else — panel wiring, draft-from-camera assembly, the
operator's PUT draft, the camera triangulation — is the real code the console runs.
"""

import json
import math
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, goto_with_network_change_retry, open_token_access, safe_listener
from fastapi import Response
from fastapi.testclient import TestClient

from test_site_map_trip import _app    # noqa: F401  (keeps the import graph like the sibling suites)

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason="opt-in real Chromium browser scenario")
ROOT = Path(__file__).resolve().parents[3]

#: what the stubbed Vision draft-map answers; the test moves `y` between phases
VISION = {"y": 0.0}


def _vision_body():
    y = VISION["y"]
    return {"source": "ceiling-north", "frame_seq": 42, "frame_age_ms": 10, "map_frame": "map",
            "plane": {"bounds_m": [-2, -1, 2, 1], "px_per_m": 100.0,
                      "calibration_revision": "paint-test", "width": 400, "height": 200},
            "lanes": [{"polyline_m": [[-1.0, y], [1.0, y]], "width_px": 10.0}],
            "zones": [{"polygon_m": [[0.4, 0.3], [0.7, 0.3], [0.7, 0.6], [0.4, 0.6]],
                       "kind": "exclusion"}],
            "reason": "ok", "detector": {"version": "draft-map-1"}}


@pytest.fixture
def page_camera(tmp_path):
    from playwright.sync_api import sync_playwright
    from fakes import FakeRobot, fresh_reads
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.sitemap.site_map_store import SiteMapStore
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.swarm.robots import RobotEndpoint
    from hashlib import sha256

    robot = FakeRobot("rosy_60", state={"robot_id": "rosy_60", "mode": "IDLE"})
    console = FleetConsole([RobotEndpoint("rosy_60", "http://127.0.0.1:8080", "t")], [robot])
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids={"rosy_60"})
    store = SiteMapStore(tmp_path / "tasks.sqlite")            # camera bootstrap: empty store
    users = {sha256(b"operator-token").hexdigest(): {"principal_id": "bob", "role": "operator"}}
    # The real preview lease routes run (as in production) for one source; only Vision — a
    # separate service in production — is stubbed same-origin for the draft-map read.
    client = TestClient(create_app(console, task_service=tasks, site_users=users, site_maps=store,
                                   vision_lease_secret="p" * 32, vision_sources=("ceiling-north",)))
    fresh_reads(client.app)
    client.app.state.web_common = ROOT / "shared" / "web"

    @client.app.get("/api/vision/sources/ceiling-north/draft-map")
    def _draft_map():
        return Response(json.dumps(_vision_body()) + "\n", media_type="application/json",
                        headers={"X-Proposal-State": "current", "X-Frame-Calibration": "paint-test"})

    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", timeout_graceful_shutdown=3, log_config=None))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        with sync_playwright() as toolkit:
            browser = toolkit.chromium.launch(headless=True,
                                              args=[f"--explicitly-allowed-ports={listener.getsockname()[1]}"])
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                goto_with_network_change_retry(page, origin + "/console/site-map")
                yield page, store, robot, client
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


def _connect(page):
    open_token_access(page)
    page.locator("#console-token").fill("operator-token")
    page.locator("#token-save").click()


def test_the_camera_draft_flows_from_the_vision_proposal_to_a_saved_draft(page_camera):
    from playwright.sync_api import expect

    page, store, robot, _client = page_camera
    messages = []
    page.on("console", lambda message: messages.append(f"{message.type}: {message.text}"))
    page.on("pageerror", lambda error: messages.append(f"pageerror: {error}"))
    _connect(page)
    page.evaluate("heading => { location.hash = heading }", "#camera-draft-heading")
    expect(page.locator("#camera-draft-heading")).to_be_visible()
    try:
        expect(page.locator("#camera-draft-source option")).to_have_count(2)   # placeholder + camera
    except AssertionError:
        dump = page.evaluate("""() => ({
            notice: document.getElementById('notice')?.textContent,
            status: document.getElementById('camera-draft-status')?.textContent,
            options: document.getElementById('camera-draft-source')?.options.length,
            role: window.__roleDebug})""")
        raise AssertionError(f"camera select did not populate: {dump}\nconsole: {messages[-20:]}")
    page.locator("#camera-draft-source").select_option("ceiling-north")
    expect(page.locator("#camera-draft-run")).to_be_enabled()

    page.locator("#camera-draft-run").click()
    expect(page.locator("#draft-status")).to_contain_text("저장된 초안")
    expect(page.locator("#camera-draft-status")).to_contain_text("차로 1개·구역 1개")
    expect(page.locator("#site-map-svg [data-place]")).to_have_count(2)
    expect(page.locator("#site-map-svg [data-edge]")).to_have_count(1)

    draft = store.draft_view()["map"]
    assert draft["survey"]["revision"] == "camera-paint-test"
    assert draft["edges"][0]["evidence"]["source"] == "camera"
    assert draft["edges"][0]["direction"] == "two_way" and draft["edges"][0]["width_m"] == 0.1
    assert draft["facilities"][0]["kind"] == "exclusion"
    assert store.active_view() is None                       # the active map is untouched
    assert not [call for call in robot.calls                  # and no motion command was sent
                if call[0] in ("navigation_goal", "swarm_arm", "line_follow_start")]


def test_the_camera_witnessed_check_shows_the_triangulated_verdict(page_camera):
    from playwright.sync_api import expect
    from fleet.site_map import SiteMap

    page, store, _robot, client = page_camera
    store.save_draft(SiteMap.model_validate(
        {"schema": "rosy.site_map/1", "map_id": "site",
         "places": [{"id": "A", "name": "A", "x": -1.0, "y": 0.0, "kind": "junction"},
                    {"id": "B", "name": "B", "x": 1.0, "y": 0.0, "kind": "junction"}],
         "edges": [{"id": "ab", "from": "A", "to": "B", "polyline": [[-1.0, 0.0], [1.0, 0.0]],
                    "width_m": 0.2, "speed_cap_mps": 1.0}]}),
        expected_revision=None, principal_id="bob")
    recorder = client.app.state.paths
    until = recorder.wall()
    recorder.store.append([{"robot_id": "rosy_60", "t": until - 60.0 + 0.1 * k,
                            "x": -1.0 + 0.1 * k, "y": 0.0, "state": "LOCALIZED", "source": "robot",
                            "seg": 1, "map_id": "site", "trip_id": None, "formation_id": None}
                           for k in range(21)])
    _connect(page)

    # C2 regression: the button is reachable; camera off the agreeing map and drive says camera_drift
    VISION["y"] = 0.5
    page.evaluate("heading => { location.hash = heading }", "#reality-heading")
    expect(page.locator("#reality-camera")).to_be_enabled()
    page.locator("#reality-camera").click()
    expect(page.locator("#reality-verdict")).to_contain_text("카메라 보정(추적 보정 화면)을 권장합니다")

    VISION["y"] = 0.0
    page.locator("#reality-camera").click()
    expect(page.locator("#reality-verdict")).to_contain_text("모두 일치")
