"""D-488 M1 site map page in real Chromium (opt-in, ROSY_BROWSER_TESTS=1). No robot moves."""

import os
import json
import re
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from browser_harness import browser_tests_enabled, safe_listener

from test_site_map_trip import _app, _on_ring_s

pytestmark = pytest.mark.skipif(not browser_tests_enabled(),
                                reason="opt-in real Chromium browser scenario")
ROOT = Path(__file__).resolve().parents[3]


def test_rectangular_camera_coordinates_are_display_only(page_site):
    import cv2
    import numpy as np
    from playwright.sync_api import expect

    page, store, robot = page_site
    writes = []
    page.on("request", lambda request: writes.append(request.url) if request.method in {"POST", "PUT", "DELETE"} else None)
    record = {"source_id": "camera-test", "map_id": store.active_view()["map"]["map_id"],
              "map_to_image": [50, 0, 100, 0, -50, 100, 0, 0, 1],
              "track_bounds_m": {"min_x": -1, "max_x": 3, "min_y": -1, "max_y": 1},
              "image": {"width": 300, "height": 200}, "lens": None}
    image = np.zeros((200, 300, 3), np.uint8)
    image[:, :150] = [0, 255, 0]
    encoded = cv2.imencode(".png", image)[1].tobytes()
    other = {**record, "source_id": "camera-other"}
    page.route("**/api/fleet/calibrations", lambda route: route.fulfill(json={"calibrations": [record, other]}))
    page.route("**/api/fleet/vision/lease", lambda route: route.fulfill(json={"lease": "preview-test", "frame_path": "/test-camera-frame"}))
    headers = {"X-Frame-Age-Ms": "10", "X-Frame-Rectified": "false"}
    page.route("**/test-camera-frame", lambda route: route.fulfill(body=encoded, content_type="image/png", headers=headers))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("bob")
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("불러온 평면 영상")
    expect(page.locator("#site-map-svg image")).to_be_visible()
    page.locator("#trip-pick").check()
    page.locator("#plane-pick").check()
    expect(page.locator("#trip-pick")).not_to_be_checked()
    writes.clear()
    point = page.locator("#site-map-svg").evaluate("svg => { const p = new DOMPoint(400, 240).matrixTransform(svg.getScreenCTM()); return {x: p.x, y: p.y}; }")
    page.mouse.click(point["x"], point["y"])
    expect(page.locator("#plane-point")).to_contain_text("확인한 좌표 x")
    x, y = map(float, re.search(r"x ([\d.-]+) m, y ([\d.-]+) m", page.locator("#plane-point").inner_text()).groups())
    # Native mouse events round screen pixels; one map pixel is about 5.3 mm here.
    assert abs(x - 1) <= 0.006 and abs(y) <= 0.006
    expect(page.locator("#trip-point")).to_contain_text("찍은 좌표 없음")
    assert not writes
    assert page.locator("#trip-start").evaluate("el => el.disabled")
    page.locator("#plane-source").select_option("camera-other")
    expect(page.locator("#site-map-svg image")).to_have_count(0)
    expect(page.locator("#plane-point")).to_contain_text("확인한 좌표 없음")
    assert page.locator("#plane-source").input_value() == "camera-other"
    headers["X-Source-Lens"] = "kind=standard;focal_mm=5.4;hfov_deg=67.8"
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("렌즈와 보정이 다릅니다")
    expect(page.locator("#site-map-svg image")).to_have_count(0)
    expect(page.locator("#plane-pick")).not_to_be_checked()
    expect(page.locator("#plane-pick")).to_be_disabled()
    headers.pop("X-Source-Lens")
    headers["X-Frame-Age-Ms"] = "4000"
    page.locator("#plane-load").click()
    expect(page.locator("#plane-status")).to_contain_text("신선한 원본 영상을 확인할 수 없습니다")


def test_import_camera_map_draft_never_activates(page_site):
    from playwright.sync_api import expect
    from test_site_map_trip import _line

    page, store, robot = page_site
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("bob")
    previous = store.active_view()
    camera_fixture = os.environ.get("ROSY_CAMERA_MAP_FIXTURE")
    draft = json.loads(Path(camera_fixture).read_text(encoding="utf-8")) if camera_fixture \
        else {"schema": "rosy.site_map/1", **_line()}
    page.locator("#camera-map-file").set_input_files({
        "name": "camera-draft.json", "mimeType": "application/json",
        "buffer": json.dumps(draft).encode()})
    page.locator("#import-camera-map").click()
    expect(page.locator("#notice")).to_contain_text("카메라 지도 초안")
    expect(page.locator("#site-map-svg [data-edge]")).to_have_count(len(draft["edges"]))
    assert store.active_view() == previous
    assert store.draft_view()["map"]["edges"]
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]
    if output := os.environ.get("ROSY_SHOT_DIR"):
        for width, height in ((1440, 1000), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            page.screenshot(path=str(Path(output) / f"camera-map-import-{width}x{height}.png"), full_page=True)
    page.locator("#camera-map-file").set_input_files({
        "name": "invalid.json", "mimeType": "application/json", "buffer": b'{"schema":"wrong"}'})
    page.locator("#import-camera-map").click()
    expect(page.locator("#notice")).to_contain_text("rosy.site_map/1")
    assert store.active_view() == previous


@pytest.fixture
def page_site(tmp_path):
    from playwright.sync_api import sync_playwright

    client, tasks, store, robot = _app(tmp_path)
    robot._state = _on_ring_s(store)
    client.app.state.web_common = ROOT / "shared" / "web"
    listener = safe_listener()
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", timeout_graceful_shutdown=3))
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
                page.goto(origin + "/console/site-map")
                yield page, store, robot
            finally:
                browser.close()
    finally:
        server.should_exit = True
        worker.join(timeout=20)
        listener.close()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_view_edit_activate_and_preview_a_trip(page_site, width, height):
    from playwright.sync_api import expect

    page, store, robot = page_site
    page.set_viewport_size({"width": width, "height": height})
    expect(page).to_have_title("Rosy Fleet · 현장 지도")
    expect(page.locator("ui-brand")).to_contain_text("Rosy Fleet")
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("bob")
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#site-map-svg [data-place]")).to_have_count(4)
    expect(page.locator("#site-map-svg .arrow")).to_have_count(8)  # 4 one-way + 2 two-way edges
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-fresh-{width}x{height}.png"), full_page=True)

    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    expect(page.locator("#trip-summary")).to_contain_text("3개 차로")
    expect(page.locator("#site-map-svg .plan")).to_have_count(3)
    expect(page.locator("#trip-actions li").last).to_contain_text("정지")
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-preview-{width}x{height}.png"), full_page=True)

    page.locator('#site-map-svg [data-place="NW"]').click()
    page.locator("#place-name").fill("A동 입구")
    page.select_option("#place-kind", "stop")
    page.locator("#apply-edit").click()
    page.locator('#site-map-svg [data-edge="ring_n"]').dispatch_event("click")  # a thin arc stroke
    page.select_option("#edge-direction", "two_way")
    page.locator("#apply-edit").click()
    page.locator("#save-draft").click()
    expect(page.locator("#draft-status")).to_contain_text("저장된 초안")
    page.locator("#activate").click()
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-confirm-{width}x{height}.png"), full_page=True)
    page.locator("dialog.ui-confirm ui-button[kind=irreversible]").click()
    expect(page.locator("#notice")).to_contain_text("활성 지도 v2")
    active = store.active()[1]
    assert next(p for p in active.places if p.id == "NW").name == "A동 입구"
    assert next(e for e in active.edges if e.id == "ring_n").direction == "two_way"

    page.locator("#trip-pick").check()
    page.locator(".map-viewport").evaluate("element => element.scrollLeft = 0")
    page.locator(".map-viewport").click(position={"x": 5, "y": 5})
    expect(page.locator("#trip-point")).to_contain_text("찍은 좌표 x")
    page.locator("#trip-plan").click()
    if width >= 1024:
        expect(page.locator("#trip-summary")).to_contain_text("차로 폭 두 배 안에 차로가 없습니다")
    else:
        expect(page.locator("#trip-summary")).to_contain_text("실행하지 않음")


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_site_map_fits_declared_widths(page_site, width, height):
    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    from playwright.sync_api import expect

    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    sizes = page.evaluate("""() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
      map: document.querySelector('#site-map-svg').getBoundingClientRect().width,
      label: document.querySelector('#site-map-svg .label').getBoundingClientRect().height,
      mapWindow: document.querySelector('.map-viewport').clientWidth,
      mapContent: document.querySelector('.map-viewport').scrollWidth,
      edit: document.querySelector('[aria-labelledby=edit-heading]').getBoundingClientRect().width,
      trip: document.querySelector('[aria-labelledby=trip-heading]').getBoundingClientRect().width,
      stop: document.querySelector('#estop').getBoundingClientRect().right
    })""")
    assert sizes["overflow"] <= 0, sizes
    assert sizes["label"] >= 12, sizes
    if width < 1024:
        assert sizes["mapWindow"] <= width and sizes["mapContent"] > sizes["mapWindow"], sizes
    assert abs(sizes["edit"] - sizes["trip"]) <= 1, sizes
    assert sizes["stop"] <= width, sizes


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_first_boot_explains_access_before_any_map_evidence(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    expect(page.locator("#map-status")).to_contain_text("관제 접속 필요")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-first-boot-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
@pytest.mark.parametrize("safety,label", [(True, "비상 정지"), (None, "정지 상태 미확인")])
def test_robot_safety_is_named_during_plan_only_preview(page_site, width, height, safety, label):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"robots":[{"robot_id":"rosy_60","online":true,"state":{"safety":'
             + ('{"estop":true}' if safety else 'null') + '}}]}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#trip-robot option")).to_contain_text(label)
    expect(page.locator("#trip-summary")).to_contain_text("실행은 하지 않습니다")
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-safety-{'stopped' if safety else 'unknown'}-{width}x{height}.png"), full_page=True)


def test_changing_trip_target_clears_old_plan_evidence(page_site):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    expect(page.locator("#trip-summary")).to_contain_text("3개 차로")
    expect(page.locator("#site-map-svg .plan")).to_have_count(3)
    page.select_option("#trip-place", "SE")
    expect(page.locator("#trip-summary")).to_contain_text("계산 전")
    expect(page.locator("#site-map-svg .plan")).to_have_count(0)
    expect(page.locator("#trip-actions li")).to_have_count(0)


def test_late_trip_response_cannot_restore_old_target(page_site):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    pending = []
    page.route("**/api/fleet/robots/rosy_60/trip", lambda route: pending.append(route))
    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    page.wait_for_timeout(200)
    assert pending
    page.select_option("#trip-place", "SE")
    with page.expect_response("**/api/fleet/robots/rosy_60/trip"):
        pending[0].continue_()
    expect(page.locator("#trip-summary")).to_contain_text("계산 전")
    expect(page.locator("#site-map-svg .plan")).to_have_count(0)
    expect(page.locator("#trip-actions li")).to_have_count(0)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_viewer_cannot_be_offered_operator_actions(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#credential input").fill("viewer-token")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_contain_text("vic · viewer")
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#map-viewport")).to_be_visible()
    page.locator('#site-map-svg [data-place="NW"]').click()
    for selector in ("#apply-edit", "#save-draft", "#activate", "#trip-plan", "#estop", "#trip-start",
                     "#trip-cancel"):
        expect(page.locator(selector)).to_be_disabled()
        expect(page.locator(selector)).to_have_attribute("reason", "운영자 권한이 필요합니다")
    expect(page.locator("#place-form")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth && document.querySelector('#estop').getBoundingClientRect().right <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-viewer-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_failed_reconnect_clears_old_map_and_actions(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    page.locator("#credential input").fill("invalid-token")
    page.locator("#connect").click()
    expect(page.locator("#session")).to_have_text("접속 전")
    expect(page.locator("#notice")).to_contain_text("토큰을 확인하고 다시 접속")
    expect(page.locator("#map-status")).to_contain_text("관제 접속 필요")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#draft-status")).to_contain_text("관제 접속 필요")
    expect(page.locator("#site-map-svg [data-place]")).to_have_count(0)
    expect(page.locator("#estop")).to_be_disabled()
    layout = page.evaluate("""() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
      stop: document.querySelector('#estop').getBoundingClientRect().right,
      actions: ['apply-edit', 'save-draft', 'activate'].map(id => document.getElementById(id).getBoundingClientRect().width)
    })""")
    assert layout["overflow"] <= 0 and layout["stop"] <= width, layout
    assert max(layout["actions"]) - min(layout["actions"]) <= 1, layout
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-auth-rejected-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_site_map_server_error_has_recovery_and_no_stale_controls(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(
        status=503, content_type="application/json", body='{"detail":{"code":"SITE_MAP_UNAVAILABLE"}}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#notice")).to_contain_text("잠시 뒤 다시 접속")
    expect(page.locator("#map-status")).to_contain_text("지도 조회 실패")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#draft-status")).to_contain_text("초안 확인 불가")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#apply-edit")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth && document.querySelector('#estop').getBoundingClientRect().right <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-map-error-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_slow_site_map_load_shows_elapsed_wait(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})

    pending = []
    page.route("**/api/fleet/site-map/active", lambda route: pending.append(route))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#notice")).to_contain_text("접속 중")
    expect(page.locator("#notice")).to_contain_text(re.compile(r"[1-9]초 경과"), timeout=4000)
    expect(page.locator("#connect")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert pending
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-delayed-{width}x{height}.png"), full_page=True)
    pending[0].continue_()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1", timeout=8000)
    expect(page.locator("#connect")).to_be_enabled()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_pending_map_read_then_disconnect(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    pending = []
    page.route("**/api/fleet/site-map/active", lambda route: pending.append(route))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("지도 조회 중")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#draft-status")).to_contain_text("초안 조회 중")
    expect(page.locator("#notice")).to_contain_text(re.compile(r"[1-9]초 경과"), timeout=4000)
    expect(page.locator("#connect")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert pending
    pending[0].abort()
    expect(page.locator("#notice")).to_contain_text("연결이 끊겼습니다")
    expect(page.locator("#map-status")).to_contain_text("지도 조회 실패")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-disconnected-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_empty_site_map_names_the_next_step(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/site-map/active", lambda route: route.fulfill(
        status=404, content_type="application/json", body='{"detail":{"code":"SITE_MAP_NOT_ACTIVE"}}'))
    page.route("**/api/fleet/site-map/draft", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"map":null,"revision":null}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 없음")
    expect(page.locator("#notice")).to_contain_text("관리자에게 현장 지도 가져오기를 요청")
    expect(page.locator("#map-viewport")).to_be_hidden()
    expect(page.locator("#save-draft")).to_be_disabled()
    expect(page.locator("#activate")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-empty-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_offline_robot_cannot_be_offered_for_trip_preview(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"robots":[{"robot_id":"rosy_60","online":false}]}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#trip-robot option")).to_have_text("rosy_60 · 연결 끊김")
    expect(page.locator("#trip-robot")).to_have_value("rosy_60")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_have_attribute("reason", "연결된 로봇이 없습니다 · 로봇 연결을 확인하세요")
    expect(page.locator("#trip-summary")).to_contain_text("연결된 로봇이 없습니다")
    stop = page.locator("#estop").bounding_box()
    assert stop and 0 <= stop["y"] < height
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-offline-{width}x{height}.png"), full_page=True)


def test_connected_robot_can_be_selected_after_offline_robot(page_site):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"robots":[{"robot_id":"rosy_99","online":false},{"robot_id":"rosy_60","online":true}]}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_have_attribute("reason", "선택한 로봇의 연결을 확인하세요")
    page.select_option("#trip-robot", "rosy_60")
    expect(page.locator("#trip-plan")).to_be_enabled()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_no_robot_explains_why_trip_preview_is_unavailable(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"robots":[]}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#trip-summary")).to_contain_text("등록된 로봇이 없습니다")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-no-robot-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_robot_state_failure_keeps_loaded_map_and_names_missing_evidence(page_site, width, height):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=503, content_type="application/json", body='{"detail":"state unavailable"}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#map-viewport")).to_be_visible()
    expect(page.locator("#trip-summary")).to_contain_text("로봇 상태 확인 불가")
    expect(page.locator("#trip-plan")).to_be_disabled()
    expect(page.locator("#estop")).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-robot-state-error-{width}x{height}.png"), full_page=True)


@pytest.mark.parametrize("status", [401, 403])
def test_robot_state_auth_failure_removes_operator_controls(page_site, status):
    from playwright.sync_api import expect

    page, _, _ = page_site
    page.route("**/api/fleet/state", lambda route: route.fulfill(
        status=status, content_type="application/json", body='{"detail":"unauthorized"}'))
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("관제 접속 필요" if status == 401 else "지도 조회 실패")
    expect(page.locator("#estop")).to_be_disabled()
    expect(page.locator("#trip-plan")).to_be_disabled()


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_changed_draft_warns_before_reconnect_discards_local_edits(page_site, width, height):
    from playwright.sync_api import expect
    from fleet.site_map import SiteMap

    page, store, _ = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    page.locator('#site-map-svg [data-place="NW"]').click()
    page.locator("#place-name").fill("북서 정차")
    page.locator("#apply-edit").click()
    store.save_draft(SiteMap.model_validate(store.active_view()["map"]), expected_revision=None, principal_id="alice")
    page.locator("#save-draft").click()
    expect(page.locator("#notice")).to_contain_text("변경 내용을 기록한 뒤 다시 접속")
    expect(page.locator("#draft-status")).to_contain_text("저장 안 된 초안")
    expect(page.locator("#activate")).to_be_disabled()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if output := os.environ.get("ROSY_SHOT_DIR"):
        page.screenshot(path=str(Path(output) / f"site-map-conflict-{width}x{height}.png"), full_page=True)
    page.locator("#connect").click()
    expect(page.locator("#draft-status")).to_contain_text("저장된 초안")


@pytest.mark.parametrize("width,height", [(1440, 1000), (390, 844), (320, 568)])
def test_trip_start_is_gated_and_names_the_d491_refusal(page_site, width, height):
    from playwright.sync_api import expect

    page, _, robot = page_site
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#credential input").fill("operator-token")
    page.locator("#connect").click()
    expect(page.locator("#map-status")).to_contain_text("활성 지도 v1")
    expect(page.locator("#trip-start")).to_have_attribute("reason", "먼저 경로를 계산하세요")
    expect(page.locator("#trip-cancel")).to_have_attribute("reason", "진행 중인 운행이 없습니다")
    expect(page.locator("#trip-run")).to_contain_text("진행 중인 운행 없음")
    page.select_option("#trip-place", "NW")
    page.locator("#trip-plan").click()
    expect(page.locator("#trip-start")).to_be_enabled()
    page.locator("#trip-start").click()  # default wiring: no D-494 1 capability provider yet
    expect(page.locator("#notice")).to_contain_text("주행 능력")
    assert not [call for call in robot.calls if call[0] == "navigation_goal"]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
