"""Native Cell observations use Fleet auth and expire without a developer viewer."""
from io import BytesIO
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from browser_harness import browser_tests_enabled, open_page, safe_listener

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium")


@pytest.fixture
def cell_url():
    import uvicorn
    from fleet.server.app import create_app
    from fleet.server.console import FleetConsole
    app = create_app(FleetConsole([], []), console_token="viewer-token", cell_job_compiler=None,
                     web_common=Path(__file__).resolve().parents[1] / "shared" / "web")
    listener = safe_listener()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}/console/cell"
    finally:
        server.should_exit = True
        worker.join(timeout=10)
        listener.close()


def observation_feed(page):
    from PIL import Image
    state = SimpleNamespace(freeze_b=None, sequence=0, stall=False, held=[], failed_assets=[])
    page.on("response", lambda response: state.failed_assets.append(f"{response.status} {response.url}")
            if response.request.resource_type in ("script", "stylesheet") and not response.ok else None)
    encoded = BytesIO()
    Image.new("RGB", (4, 4), color="green").save(encoded, format="JPEG")
    jpeg = encoded.getvalue()

    def snapshot():
        now = time.time()
        state.sequence += 1
        arms = []
        for side, position in (("a", 0.25), ("b", 0.75)):
            age = now - state.freeze_b if side == "b" and state.freeze_b else 0
            arms.append({"source_id": f"feedback_{side}", "arm_id": f"arm_{side}", "label": f"팔 {side}",
                         "units": "encoder_rad", "fresh": age <= 2, "epoch": side * 32,
                         "sequence": state.sequence, "captured_at": now - age, "source_age_s": age,
                         "receipt_age_s": age, "positions": {"joint1": position} if age <= 2 else None})
        return {"read_only": True, "physical_acceptance": False, "workcells": [{
            "workcell_id": "example", "label": "예시 작업 셀", "arms": arms, "cameras": [
                {"source_id": "top", "label": "공용 상단", "role": "overhead", "arm_id": None},
                {"source_id": "wrist_a", "label": "손목 a", "role": "wrist", "arm_id": "arm_a"},
                {"source_id": "wrist_b", "label": "손목 b", "role": "wrist", "arm_id": "arm_b"}]}]}

    def route_api(route):
        path = urlsplit(route.request.url).path
        if path == "/api/fleet/workcell-observations":
            if state.stall:
                state.held.append(route)
                return
            return route.fulfill(json=snapshot())
        if path == "/api/fleet/vision/lease":
            source = route.request.post_data_json["source_id"]
            assert route.request.headers.get("authorization") == "Bearer viewer-token"
            return route.fulfill(json={"source_id": source, "lease": "preview-only-lease", "expires_in_s": 60,
                                       "frame_path": f"/api/vision/sources/{source}/frame"})
        if path in ("/api/fleet/session", "/api/fleet/auth/session"):
            if route.request.headers.get("authorization") != "Bearer viewer-token":
                return route.fulfill(status=401, json={"detail": "signed out"})
            return route.fulfill(json={"role": "viewer", "principal_id": "reader", "via": "bearer"})
        if path == "/api/fleet/auth/connection":
            return route.fulfill(json={"mode": "paired", "password_login": False})
        if "/cell-app/" in path:
            return route.fulfill(status=503, json={"detail": {"code": "CELL_APP_UNCONFIGURED"}})
        return route.continue_()

    def route_frame(route):
        assert route.request.headers.get("authorization") == "Bearer preview-only-lease"
        if state.stall:
            state.held.append(route)
            return
        if "/wrist_b/" in route.request.url and state.freeze_b:
            return route.fulfill(status=503, body="unavailable")
        state.sequence += 1
        route.fulfill(content_type="image/jpeg", body=jpeg,
                      headers={"X-Frame-Age-Ms": "0", "X-Frame-Seq": str(state.sequence), "Cache-Control": "no-store"})

    page.route("**/api/fleet/**", route_api)
    page.route("**/api/vision/sources/*/frame", route_frame)
    page.add_init_script("sessionStorage.setItem('rosy-console-token','viewer-token')")
    return state, snapshot


def test_cell_displays_two_arms_three_cameras_and_expires_each_disconnected_source(cell_url):
    from playwright.sync_api import expect, sync_playwright
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 390, 844, url=cell_url)
        state, _ = observation_feed(page)
        page.goto(cell_url)
        assert not state.failed_assets, state.failed_assets
        assert not errors, errors
        root = page.locator("#workcell-observations")
        expect(root.locator("[data-arm-source]")).to_have_count(2)
        expect(root.locator('[data-arm-source="feedback_a"] pre')).to_contain_text("0.25")
        expect(root.locator('[data-arm-source="feedback_b"] pre')).to_contain_text("0.75")
        expect(root.locator("[data-camera-source] img")).to_have_count(3)
        for source in ("top", "wrist_a", "wrist_b"):
            expect(root.locator(f'[data-camera-source="{source}"] img')).to_be_visible()
        state.freeze_b = time.time()
        expect(root.locator('[data-arm-source="feedback_b"] pre')).not_to_contain_text("0.75", timeout=4000)
        expect(root.locator('[data-camera-source="wrist_b"] img')).to_be_hidden(timeout=4000)
        expect(root.locator('[data-arm-source="feedback_a"] pre')).to_contain_text("0.25")
        expect(root.locator('[data-camera-source="wrist_a"] img')).to_be_visible()
        expect(root.locator('[data-camera-source="top"] img')).to_be_visible()
        state.stall = True
        expect(root.locator('[data-arm-source="feedback_a"] pre')).not_to_contain_text("0.25", timeout=3000)
        for source in ("top", "wrist_a"):
            expect(root.locator(f'[data-camera-source="{source}"] img')).to_be_hidden(timeout=3000)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator("iframe").count() == 0
        assert urlsplit(page.url).path == "/console/cell"
        assert not errors
        page.unroute_all(behavior="ignoreErrors")
        browser.close()


def test_cell_logout_clears_observations_and_ignores_late_responses(cell_url):
    from playwright.sync_api import expect, sync_playwright
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 390, 844, url=cell_url)
        state, snapshot = observation_feed(page)
        page.goto(cell_url)
        assert not state.failed_assets, state.failed_assets
        assert not errors, errors
        root = page.locator("#workcell-observations")
        expect(root.locator('[data-arm-source="feedback_a"] pre')).to_contain_text("0.25")
        expect(root.locator('[data-camera-source="top"] img')).to_be_visible()
        state.stall = True
        with page.expect_request("**/api/fleet/workcell-observations"):
            page.locator("#topbar-more").click()
        page.locator('[data-login="logout"]').click()
        expect(root.locator("[data-arm-source]")).to_have_count(0)
        expect(root.locator("img")).to_have_count(0)
        for route in state.held:
            if urlsplit(route.request.url).path.endswith("/workcell-observations"):
                route.fulfill(content_type="application/json", body=json.dumps(snapshot()))
            else:
                route.fulfill(status=503, body="late frame")
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        expect(root.locator("[data-arm-source]")).to_have_count(0)
        expect(root.locator("img")).to_have_count(0)
        assert not errors
        page.unroute_all(behavior="ignoreErrors")
        browser.close()
