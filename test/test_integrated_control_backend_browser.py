"""Actual Fleet HTTP/UI composition on loopback; robot transport is synthetic, physical stop unverified."""
from hashlib import sha256
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit

import pytest
import uvicorn

from browser_harness import browser_tests_enabled, launch_options, safe_listener

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")
ROOT = Path(__file__).resolve().parents[1]
PREFIX = "/api/fleet/control-unit"


@pytest.fixture
def integrated_backend(tmp_path):
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    from fleet.server.console_routes import SharedGather
    from fleet.server.site_map_store import SiteMapStore
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    from fleet.site_map import SiteMap
    from fleet.swarm.robots import RobotEndpoint
    from operations.fleet.test.fakes import FakeRobot

    token = secrets.token_urlsafe(24)
    robot = FakeRobot("r", state={"robot_id": "r", "mode": "IDLE", "map_id": "unit-map",
        "localization": {"state": "LOCALIZED", "pose_frame": "map"},
        "pose": {"x": 0.0, "y": 0.0, "yaw": 0.0}, "battery": {"percent": 80.0},
        "safety": {"estop": False},
        "evidence": {channel: {"evidence": "fresh"} for channel in ("pose", "battery", "safety")}})
    console = FleetConsole([RobotEndpoint("r", "http://robot.invalid", "synthetic-device-token")], [robot])
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    store.create_task(task_id="owned-loopback-task", robot_id="r", task_type="navigate", source="operator",
                      actor_id="private-actor-must-not-leak", request_key="seed-task",
                      request={"private": "private-request-must-not-leak"},
                      evidence={"private": "private-evidence-must-not-leak"})
    store.enqueue("owned-loopback-task", priority_class=0)
    tasks = FleetTaskService(store, robot_ids=console.robot_ids)
    maps = SiteMapStore(tmp_path / "maps.sqlite3")
    maps.import_if_empty(SiteMap.model_validate({"map_id": "unit-map", "places": [
        {"id": "start", "name": "합성 출발", "x": 0.0, "y": 0.0},
        {"id": "end", "name": "합성 도착", "x": 1.0, "y": 0.0}],
        "edges": [{"id": "lane", "from": "start", "to": "end", "polyline": [[0.0, 0.0], [1.0, 0.0]],
                   "width_m": 0.4, "speed_cap_mps": 0.2}]}), source="synthetic-loopback-test")
    config = tmp_path / "control-unit.json"
    config.write_text(json.dumps({"unit_id": "R", "manifest": {"revision": "loopback-v1",
        "units": [{"id": "R", "resources": ["robot:r"]}]}, "peers": {}}), encoding="utf-8")
    app = create_app(console, task_service=tasks, site_maps=maps, control_unit_config=config,
                     site_users={sha256(token.encode()).hexdigest(): {
                         "principal_id": "named-loopback-operator", "role": "operator"}},
                     start_task_dispatcher=False, omx_instances={}, web_common=ROOT / "shared/web")
    assert isinstance(app.state.fleet_gather, SharedGather)
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False,
                                         proxy_headers=False, timeout_graceful_shutdown=3))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield origin, token, robot, store
    finally:
        server.should_exit = True
        worker.join(15)
        listener.close()
        assert not worker.is_alive()


def test_actual_backend_information_map_stop_and_identity_readback(integrated_backend):
    from playwright.sync_api import expect, sync_playwright

    origin, token, robot, store = integrated_backend
    with sync_playwright() as playwright:
        options = launch_options()
        options["args"] = [f"--explicitly-allowed-ports={urlsplit(origin).port}"]
        browser = playwright.chromium.launch(**options)
        try:
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            page.set_default_timeout(15000)
            page.add_init_script("sessionStorage.setItem('rosy-console-token', " + json.dumps(token) + ");")
            errors, external, writes = [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: external.append(request.url)
                    if request.url.startswith("http") and urlsplit(request.url).netloc != urlsplit(origin).netloc else None)
            page.on("request", lambda request: writes.append(request.post_data_json)
                    if request.method == "POST" and urlsplit(request.url).path == PREFIX + "/stops" else None)
            page.goto(origin + "/console?view=work")
            panel = page.locator("#integrated-control")
            expect(panel).to_be_visible()
            expect(panel).to_contain_text("R · 독립 관제")
            detail = page.locator("#integrated-control-detail")
            expect(detail).to_contain_text("owned-loopback-task")
            headers = {"Authorization": "Bearer " + token}
            response = page.request.get(origin + PREFIX + "/units/R", headers=headers)
            assert response.status == 200
            data = response.json()
            assert [row["robot_id"] for row in data["robots"]] == ["r"]
            assert {row["task_id"] for row in data["tasks"]} == {"owned-loopback-task"}
            assert set(data["tasks"][0]) == {"task_id", "robot_id", "status", "updated_at"}
            for private in ("private-actor-must-not-leak", "private-request-must-not-leak", "private-evidence-must-not-leak"):
                assert private not in response.text() and private not in panel.inner_text()
            with page.expect_response(lambda value: value.url.endswith(PREFIX + "/units/R/map")) as geometry:
                panel.get_by_role("button", name="선택 관제 지도 보기", exact=True).click()
            assert geometry.value.status == 200 and geometry.value.json()["unit_id"] == "R"
            expect(panel.locator("svg[role=img]")).to_have_attribute("aria-label", "R 관제 활성 지도 · 읽기 전용")
            expect(panel.locator("svg text").first).to_have_text("합성 출발")
            before = sum(call[0] == "estop" for call in robot.calls)
            with page.expect_response(lambda value: value.url.endswith(PREFIX + "/stops")
                                      and value.request.method == "POST") as submitted:
                page.locator("#integrated-stop").click()
            assert submitted.value.status == 200
            receipt = submitted.value.json()
            assert receipt["origin_id"] == receipt["target_unit"] == "R"
            assert receipt["results"][0]["state"] == "ACKNOWLEDGED"
            assert receipt["results"][0]["physical_stop"] == "UNVERIFIED"
            assert sum(call[0] == "estop" for call in robot.calls) == before + 1
            expect(page.locator("#integrated-stop-results")).to_contain_text("R · 요청 수신")
            expect(page.locator("#integrated-stop-results")).to_contain_text("물리 정지 미확인")
            identity = receipt["stop_id"]
            assert len(writes) == 1 and writes[0]["stop_id"] == identity
            generation = store.dispatch_control()["generation"]
            page.reload()
            expect(page.locator("#integrated-control")).to_be_visible()
            page.locator("#integrated-control summary").filter(has_text="이 관제의 정지 요청 기록").click()
            page.locator("#integrated-stop-history").get_by_role("button").click()
            expect(page.locator("#integrated-stop-results")).to_contain_text("R · 요청 수신")
            expect(page.locator("#integrated-stop-results li")).to_have_attribute("data-physical-stop", "UNVERIFIED")
            readback = page.request.get(origin + PREFIX + "/stops/R/" + identity, headers=headers)
            assert readback.status == 200 and readback.json()["stop_id"] == identity
            assert len(writes) == 1 and store.dispatch_control()["generation"] == generation
            assert sum(call[0] == "estop" for call in robot.calls) == before + 1
            assert not errors and not external
        finally:
            browser.close()
