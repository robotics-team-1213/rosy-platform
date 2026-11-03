"""Native Cell observations use Fleet auth and expire without a developer viewer."""
from io import BytesIO
import base64
import json
import os
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
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", log_config=None))
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


@pytest.mark.parametrize("width", [1366, 390])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_cell_catalog_fits_the_full_page_and_belongs_to_saved_documents(cell_url, width, theme):
    from playwright.sync_api import expect, sync_playwright
    source = "긴 카탈로그 출처 " * 20
    body = {"objects": [{"id": "example-object", "length_mm": 60, "width_mm": 30,
                         "top_height_mm": 30, "mass_kg": 0.02,
                         "mass_measured": {"at": "2026-11-03", "source": source}, "carry": "ok"}]}
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, width, 844, url=cell_url)
        try:
            state, _ = observation_feed(page)
            page.route("**/api/fleet/cell-app/object-catalog", lambda route: route.fulfill(json=body))
            page.goto(cell_url)
            page.evaluate("theme => window.RosyTheme.set(theme)", theme)
            table = page.locator("#catalog-table")
            expect(table).to_be_visible()
            expect(table).to_contain_text("20.0 g")
            expect(table).to_contain_text(source.strip())
            table.scroll_into_view_if_needed()
            assert table.evaluate("el => getComputedStyle(el).borderCollapse") == "collapse"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            if os.environ.get("ROSY_CAPTURE_INLINE") == "1":
                shot = page.screenshot(type="jpeg", quality=35)
                print(f"ROSY_SCREENSHOT cell-catalog-{theme}-{width} " + base64.b64encode(shot).decode())
            page.locator('.ui-subnav-nav a[href="#recipe-heading"]').click()
            expect(page.locator('[aria-labelledby="catalog-heading"]')).to_be_hidden()
            page.locator('.ui-subnav-nav a[href="#saved-heading"]').click()
            expect(table).to_be_visible()
            assert not errors and not state.failed_assets
        finally:
            page.unroute_all(behavior="ignoreErrors")
            browser.close()


@pytest.mark.parametrize("pending", [False, True])
def test_cell_logout_clears_catalog_and_ignores_its_late_response(cell_url, pending):
    from playwright.sync_api import expect, sync_playwright
    held = []
    body = {"objects": [{"id": "previous-account-object", "mass_kg": 0.02, "carry": "ok"}]}
    with sync_playwright() as playwright:
        browser, page, errors = open_page(playwright, 390, 844, url=cell_url)
        try:
            observation_feed(page)
            def catalog(route):
                held.append(route) if pending else route.fulfill(json=body)
            page.route("**/api/fleet/cell-app/object-catalog", catalog)
            with page.expect_request("**/api/fleet/cell-app/object-catalog"):
                page.goto(cell_url)
            if not pending:
                expect(page.locator("#catalog-table")).to_contain_text("previous-account-object")
            page.locator("#topbar-more").click()
            page.locator('[data-login="logout"]').click()
            expect(page.locator("#workcell-observations [data-arm-source]")).to_have_count(0)
            for route in held:
                route.fulfill(json=body)
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
            expect(page.locator("#catalog-table")).to_be_hidden()
            expect(page.locator("#catalog-rows tr")).to_have_count(0)
            expect(page.locator("#catalog-status")).to_contain_text("접속하면")
            assert not errors
        finally:
            page.unroute_all(behavior="ignoreErrors")
            browser.close()
