from __future__ import annotations

from test_fleet_console_browser import (
    os, json, console_url, urlparse, pytest, pytestmark, DECLINE_CONFIRM, save_temp_screenshot,
    MAP_GRID, _robot, SNAPSHOT, FORMATION, API, _open_cards, _open_console, EMPTY_SNAPSHOT,
    DELAYED_FORMATION, UNREACHABLE_SNAPSHOT,
)


def test_stale_camera_calibration_keeps_the_frozen_picture_and_warns(console_url):
    from playwright.sync_api import sync_playwright

    # 카메라를 재조준한 뒤의 조감도: 정지 로봇의 추적 차이(offset_m)가 3폴링 연속 한계를
    # 넘으면 경고만 한다. D-595: 그림은 수락된 보정 그대로다(폴링마다 바뀌지 않는다).
    api = {
        "/api/fleet/state": EMPTY_SNAPSHOT,
        "/api/fleet/map": (503, {"detail": {"code": "MAP_UNAVAILABLE"}}),
        "/api/fleet/site-map": {"maps": [{"map_id": "map_v2_fleet",
                                      "polygon_m": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                      "bounds_m": {"min_x": 0, "min_y": 0,
                                                   "max_x": 1, "max_y": 1}}]},
        "/api/fleet/calibrations": {"calibrations": [{
            "source_id": "ceiling_north", "map_id": "map_v2_fleet",
            "calibration_revision": "paint-test", "image": {"width": 1280, "height": 720},
            "lens": {"kind": "wide", "focal_mm": 2.2, "hfov_deg": 104.1},
            "map_to_image": [1000, 0, 100, 0, 600, 50, 0, 0, 1]}]},
        "/api/fleet/vision/sources": {"sources": ["ceiling_north"]},
        "/api/fleet/vision/lease": {"source_id": "ceiling_north", "lease": "test-lease",
                                     "frame_path": "/api/vision/sources/ceiling_north/frame", "expires_in_s": 60},
        "/api/fleet/tracking": {"lease_s": 1, "sources": [
            {"source_id": "ceiling_north", "map_id": "map_v2_fleet", "status": "OK",
             "calibration_revision": "paint-test", "age_ms": 120, "fps": 3,
             "last_error": None, "relearn_seq": 0}],
            "robots": [{"robot_id": "rosy_01", "status": "MATCHED", "source_id": "ceiling_north",
                        "offset_m": 0.8, "camera": {"x": 0.2, "y": 0.2, "footprint_m": 0.18, "score": 0.9},
                        "pose": {"x": 0.8, "y": 0.8}, "pose_frame_verified": True}],
            "unknown": []},
    }
    with sync_playwright() as sync_playwright_p:
        browser, page, errors = _open_console(
            sync_playwright_p, api,
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')")

        def serve_frame(route):
            route.fulfill(status=200, content_type="image/svg+xml",
                          body='<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                               '<rect width="1280" height="720" fill="#bf2030"/></svg>',
                          headers={"X-Frame-Rectified": "false", "X-Frame-Seq": "42",
                                   "X-Frame-Age-Ms": "20",
                                   "X-Source-Lens": "kind=wide;focal_mm=2.2;hfov_deg=104.1"})

        page.route("**/api/vision/sources/ceiling_north/frame", serve_frame)
        # The 1 s tracking poll keeps the network busy; networkidle never comes (timed out on main too).
        page.goto(console_url, wait_until="domcontentloaded")
        page.select_option("#map-display-mode", "overlay")
        page.locator("#map-options > summary").click()
        page.wait_for_function(
            "() => document.querySelector('#map-tag')?.textContent.includes('카메라 교정 어긋남')",
            timeout=20000)
        tag = page.inner_text("#map-tag")
        assert "paint-test" in tag, tag
        page.select_option("#map-display-mode", "overlay")
        # 수락된 보정의 실영상(빨강)이 사이트 안에 그대로 있다. 표본 점은 로봇 차이 선(0.2→0.8 대각선)과
        # 0.5 m 격자를 피한다(siteBounds 0.25 여유, fitTransform pad 32, 화면 회전 없음).
        pixel = page.evaluate("""async () => {
          const { fitTransform, project } = await import('/console/assets/site-layer.js');
          const c = document.querySelector('#map-canvas'), g = c.getContext('2d');
          const r = c.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
          const t = fitTransform({ min_x: -0.25, min_y: -0.25, max_x: 1.25, max_y: 1.25 }, r.width, r.height, 32);
          const p = project(t, 0.25, 0.75);
          return [...g.getImageData(Math.round(p.px * dpr), Math.round(p.py * dpr), 1, 1).data];
        }""")
        assert pixel[0] > 150 and pixel[1] < 100, pixel
        assert page.evaluate("() => document.querySelector('#map-canvas')?.getAttribute('aria-label')"
                             ".includes('맵 고정을 다시 하세요')")
        assert not errors
        browser.close()


def test_server_checked_calibration_drift_warns_without_any_robot(console_url):
    from playwright.sync_api import sync_playwright

    # 서버 자동 검사: 로봇 관측이 0/0대(robots 없음)여도 출처의 calibration_drift(stale)
    # 하나로 실영상을 내리고 미터 눈금 + "(자동 검사)" 문구로 바뀐다(tracking-layer
    # serverCalibrationDrift · effectiveDriftVerdict, map-view 서버 판정 분기).
    # mutation-proven: effectiveDriftVerdict의 서버 폴백을 지우면 이 시험은 적색이다.
    api = {
        "/api/fleet/state": EMPTY_SNAPSHOT,
        "/api/fleet/map": (503, {"detail": {"code": "MAP_UNAVAILABLE"}}),
        "/api/fleet/site-map": {"maps": [{"map_id": "map_v2_fleet",
                                      "polygon_m": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                      "bounds_m": {"min_x": 0, "min_y": 0,
                                                   "max_x": 1, "max_y": 1}}]},
        "/api/fleet/calibrations": {"calibrations": [{
            "source_id": "ceiling_north", "map_id": "map_v2_fleet",
            "calibration_revision": "paint-test", "image": {"width": 1280, "height": 720},
            "lens": {"kind": "wide", "focal_mm": 2.2, "hfov_deg": 104.1},
            "map_to_image": [1000, 0, 100, 0, 600, 50, 0, 0, 1]}]},
        "/api/fleet/vision/sources": {"sources": ["ceiling_north"]},
        "/api/fleet/vision/lease": {"source_id": "ceiling_north", "lease": "test-lease",
                                     "frame_path": "/api/vision/sources/ceiling_north/frame", "expires_in_s": 60},
        "/api/fleet/tracking": {"lease_s": 1, "sources": [
            {"source_id": "ceiling_north", "map_id": "map_v2_fleet", "status": "OK",
             "calibration_revision": "paint-test", "age_ms": 120, "fps": 3,
             "last_error": None, "relearn_seq": 0,
             "calibration_drift": {"state": "stale", "max_move_m": 0.55, "rotation_deg": 1.2,
                                   "calibration_revision": "paint-test", "frame_seq": 900,
                                   "checked_at": 1_790_000_000.0}}],
            "robots": [], "unknown": []},
    }
    with sync_playwright() as sync_playwright_p:
        browser, page, errors = _open_console(
            sync_playwright_p, api,
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')" +
            ";(() => {window.__mapTexts=[];const fill=CanvasRenderingContext2D.prototype.fillText; CanvasRenderingContext2D.prototype.fillText=function(text,...args){ if(this.canvas.id==='map-canvas'){window.__mapTexts.push(String(text));window.__mapTexts=window.__mapTexts.slice(-100);} return fill.call(this,text,...args);};})()")

        def serve_frame(route):
            route.fulfill(status=200, content_type="image/svg+xml",
                          body='<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                               '<rect width="1280" height="720" fill="#bf2030"/></svg>',
                          headers={"X-Frame-Rectified": "false", "X-Frame-Seq": "42",
                                   "X-Frame-Age-Ms": "20",
                                   "X-Source-Lens": "kind=wide;focal_mm=2.2;hfov_deg=104.1"})

        page.route("**/api/vision/sources/ceiling_north/frame", serve_frame)
        page.goto(console_url, wait_until="domcontentloaded")
        page.select_option("#map-display-mode", "overlay")
        page.locator("#map-options > summary").click()
        page.wait_for_function(
            "() => document.querySelector('#map-calibration-status')?.textContent.includes('카메라 교정 어긋남(자동 검사)')",
            timeout=20000)
        tag = page.evaluate("() => document.querySelector('#map-tag')?.textContent")
        assert "카메라 교정 어긋남 — 맵 고정 다시 필요" in tag and "paint-test" in tag
        caption = page.locator("#map-calibration-status").inner_text()
        assert "자동 검사" in caption and "ceiling_north" in caption
        assert not page.evaluate("window.__mapTexts.some(text => text.includes('카메라 교정 어긋남'))")
        # D-560 retains the accepted camera calibration; the outer canvas margin stays dark.
        assert page.evaluate("() => { const c = document.querySelector('#map-canvas'); "
                             "const p = c.getContext('2d').getImageData(10, 10, 1, 1).data; "
                             "return p[0] < 100 && p[1] < 100; }")
        assert page.evaluate("() => document.querySelector('#map-canvas')?.getAttribute('aria-label')"
                             ".includes('그림은 수락된 보정 그대로')")
        assert not errors
        browser.close()


def test_robot_sample_drift_outranks_the_server_check(console_url):
    from playwright.sync_api import sync_playwright

    # 로봇 표본 판정(정지 로봇 차이)이 살아 있으면 서버 자동 검사 문구를 쓰지 않는다.
    # mutation-proven: effectiveDriftVerdict가 서버 판정을 먼저 보게 바꾸면 적색이다.
    api = {
        "/api/fleet/state": EMPTY_SNAPSHOT,
        "/api/fleet/map": (503, {"detail": {"code": "MAP_UNAVAILABLE"}}),
        "/api/fleet/site-map": {"maps": [{"map_id": "map_v2_fleet",
                                      "polygon_m": [[0, 0], [1, 0], [1, 1], [0, 1]],
                                      "bounds_m": {"min_x": 0, "min_y": 0,
                                                   "max_x": 1, "max_y": 1}}]},
        "/api/fleet/calibrations": {"calibrations": [{
            "source_id": "ceiling_north", "map_id": "map_v2_fleet",
            "calibration_revision": "paint-test", "image": {"width": 1280, "height": 720},
            "lens": {"kind": "wide", "focal_mm": 2.2, "hfov_deg": 104.1},
            "map_to_image": [1000, 0, 100, 0, 600, 50, 0, 0, 1]}]},
        "/api/fleet/vision/sources": {"sources": ["ceiling_north"]},
        "/api/fleet/vision/lease": {"source_id": "ceiling_north", "lease": "test-lease",
                                     "frame_path": "/api/vision/sources/ceiling_north/frame", "expires_in_s": 60},
        "/api/fleet/tracking": {"lease_s": 1, "sources": [
            {"source_id": "ceiling_north", "map_id": "map_v2_fleet", "status": "OK",
             "calibration_revision": "paint-test", "age_ms": 120, "fps": 3,
             "last_error": None, "relearn_seq": 0,
             "calibration_drift": {"state": "stale", "max_move_m": 0.55, "rotation_deg": 1.2,
                                   "calibration_revision": "paint-test", "frame_seq": 900,
                                   "checked_at": 1_790_000_000.0}}],
            "robots": [{"robot_id": "rosy_01", "status": "MATCHED", "source_id": "ceiling_north",
                        "offset_m": 0.8, "camera": {"x": 0.2, "y": 0.2, "footprint_m": 0.18, "score": 0.9},
                        "pose": {"x": 0.8, "y": 0.8}, "pose_frame_verified": True}],
            "unknown": []},
    }
    with sync_playwright() as sync_playwright_p:
        browser, page, errors = _open_console(
            sync_playwright_p, api,
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')" +
            ";(() => {window.__mapTexts=[];const fill=CanvasRenderingContext2D.prototype.fillText; CanvasRenderingContext2D.prototype.fillText=function(text,...args){ if(this.canvas.id==='map-canvas'){window.__mapTexts.push(String(text));window.__mapTexts=window.__mapTexts.slice(-100);} return fill.call(this,text,...args);};})()")

        def serve_frame(route):
            route.fulfill(status=200, content_type="image/svg+xml",
                          body='<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                               '<rect width="1280" height="720" fill="#bf2030"/></svg>',
                          headers={"X-Frame-Rectified": "false", "X-Frame-Seq": "42",
                                   "X-Frame-Age-Ms": "20",
                                   "X-Source-Lens": "kind=wide;focal_mm=2.2;hfov_deg=104.1"})

        page.route("**/api/vision/sources/ceiling_north/frame", serve_frame)
        page.goto(console_url, wait_until="domcontentloaded")
        page.select_option("#map-display-mode", "overlay")
        page.locator("#map-options > summary").click()
        page.wait_for_function(
            "() => document.querySelector('#map-calibration-status')?.textContent.includes('정지 로봇 관측 차이')",
            timeout=20000)
        tag = page.evaluate("() => document.querySelector('#map-tag')?.textContent")
        aria = page.evaluate("() => document.querySelector('#map-canvas')?.getAttribute('aria-label')")
        caption = page.locator("#map-calibration-status").inner_text()
        assert "정지 로봇 관측 차이" in caption and "rosy_01" in caption
        assert "자동 검사" not in caption  # The rendered robot verdict outranks the server check.
        assert "paint-test" in tag and "그림은 수락된 보정 그대로" in aria
        assert not errors
        browser.close()


# --- D-457 1: "추적 보정 적용"은 적용 시점 라이브 프레임의 렌즈를 본문에 찍는다 ----

LENS_WIDE_HEADER = "kind=wide;focal_mm=2.2;hfov_deg=104.1"
FIT_FRAME_BODY = ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                  '<rect width="1280" height="720" fill="#bf2030"/></svg>')
FIT_SITE_LANES = {
    "maps": [{
        "map_id": "map_v2_fleet", "source_ids": ["ceiling_north"],
        "lane_graph_sha256": "lane-sha", "paint_sha256": "paint-sha",
        "bounds_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 6.4, "max_y": 3.6},
        "polylines": [{"points": [[0.3, 0.4], [6.1, 0.4]]}, {"points": [[0.3, 3.2], [6.1, 3.2]]}],
        "paint_triangles": [[0.3, 0.4, 6.1, 0.4, 3.2, 2.8]],
    }],
}
# 1280×720 프레임 전체가 6.4×3.6 m 트랙에 닿는 통과 제안(가로 세로 배율 모두 0.005 m/px).
FIT_MAP_PROPOSAL = {
    "accepted": True,
    "image": {"width": 1280, "height": 720},
    "frame_seq": 42,
    "proposal": {"image_to_map": [[0.005, 0.0, 0.0], [0.0, -0.005, 3.6], [0.0, 0.0, 1.0]],
                 "score": 0.92, "precision": 0.88, "coverage": 0.9},
}


def _apply_flow_api():
    return {
        "/api/fleet/state": EMPTY_SNAPSHOT,
        "/api/fleet/map": (503, {"detail": {"code": "MAP_UNAVAILABLE"}}),
        "/api/fleet/site-lanes": FIT_SITE_LANES,
        "/api/fleet/calibrations": {"calibrations": []},
        "/api/fleet/vision/sources": {"sources": ["ceiling_north"]},
        "/api/fleet/vision/lease": {"source_id": "ceiling_north", "lease": "test-lease",
                                    "frame_path": "/api/vision/sources/ceiling_north/frame",
                                    "expires_in_s": 60},
    }


def _run_map_fit_apply(page, console_url, lens_header):
    """맞춤 패널을 열어 제안을 받고 '추적 보정 적용'을 누른다; POST 본문 목록을 돌려준다."""
    applied = []

    def serve_vision(route):
        if urlparse(route.request.url).path.endswith("/map-proposal"):
            route.fulfill(status=200, json=FIT_MAP_PROPOSAL)
            return
        headers = {"X-Frame-Rectified": "false", "X-Frame-Seq": "42", "X-Frame-Age-Ms": "20"}
        if lens_header:
            headers["X-Source-Lens"] = lens_header
        route.fulfill(status=200, content_type="image/svg+xml", body=FIT_FRAME_BODY,
                      headers=headers)

    def capture_apply(route):
        if route.request.method == "POST":
            applied.append(route.request.post_data_json)
            route.fulfill(status=200, json={"source_id": "ceiling_north",
                                            "calibration_revision": "paint-lenstest",
                                            "use": "display-only"})
            return
        route.fulfill(status=200, json={"calibrations": [], "use": "display-only"})

    page.route("**/api/vision/**", serve_vision)
    page.route("**/api/fleet/calibrations", capture_apply)
    page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
    page.get_by_role("tab", name="카메라 설치·보정", exact=True).click()
    page.wait_for_function("() => document.querySelector('#vision-meta')?.textContent.includes('sequence 42')")
    page.locator("#map-fit-detect").click()
    page.wait_for_function("!document.querySelector('#map-fit-apply')?.hidden")
    page.locator("#map-fit-apply").click()
    page.wait_for_function(
        "() => document.querySelector('#map-fit-state')?.textContent.includes('paint-lenstest 적용')")
    return applied


def test_applying_tracking_calibration_stamps_the_live_frame_lens(console_url):
    """라이브 프레임이 렌즈를 알리면 적용 본문에 그 렌즈가 실려 저장된다(X-Source-Lens)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, _apply_flow_api(),
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')")
        applied = _run_map_fit_apply(page, console_url, LENS_WIDE_HEADER)
        assert len(applied) == 1, applied
        assert applied[0]["source_id"] == "ceiling_north"
        assert applied[0]["map_id"] == "map_v2_fleet"
        assert applied[0]["lens"] == {"kind": "wide", "focal_mm": 2.2, "hfov_deg": 104.1}
        # 렌즈가 찍혔으니 '렌즈 검사 없이 적용' 안내는 붙지 않는다.
        assert "렌즈 정보가 없어" not in page.locator("#map-fit-state").inner_text()
        save_temp_screenshot(page, "fleet_map_fit_apply_lens.png")
        assert not errors
        browser.close()


def test_applying_tracking_calibration_without_a_frame_lens_says_so(console_url):
    """프레임에 렌즈 정보가 없을 때만 lens 없이 저장하고 그 안내를 유지한다."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, _apply_flow_api(),
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')")
        applied = _run_map_fit_apply(page, console_url, None)
        assert len(applied) == 1, applied
        assert applied[0]["lens"] is None
        assert "렌즈 정보가 없어 렌즈 검사 없이 적용했습니다" in page.locator("#map-fit-state").inner_text()
        assert not errors
        browser.close()


# --- D-224: 예외 문법의 키보드 어휘 — ↑/↓ 순회 · Enter 목표 · Escape 해소 ----

def test_keyboard_traverses_the_roster_and_arms_a_goal(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        _open_cards(page)
        # D-540 3: every card is listed, exceptions first (rosy_03), then the robots' own order.
        page.keyboard.press("ArrowDown")
        page.wait_for_function(
            "() => document.activeElement"
            " && document.activeElement.matches('#roster article')"
            " && document.activeElement.querySelector('b')?.textContent === 'rosy_03'"
        )
        page.evaluate("() => { window.__focusedCard = document.activeElement; }")
        page.wait_for_function("() => !window.__focusedCard.isConnected", timeout=3000)
        assert page.evaluate(
            "() => document.activeElement.matches('#roster article')"
            " && document.activeElement.querySelector('b')?.textContent === 'rosy_03'"
        )
        page.keyboard.press("ArrowDown")
        page.wait_for_function(
            "() => document.activeElement.querySelector('b')?.textContent === 'rosy_01'"
        )
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.querySelector('#robot-choice')?.value === 'rosy_01'")
        assert page.locator('.robot.selected').count() == 0
        page.locator('#robot-workspace ui-button[data-goal-robot-id]').click()
        page.wait_for_function(
            "() => document.querySelectorAll('.robot.selected').length === 1"
            " && document.querySelector('.robot.selected b')?.textContent === 'rosy_01'"
        )
        page.keyboard.press("Escape")
        page.wait_for_function(
            "() => document.querySelectorAll('.robot.selected').length === 0"
        )
        assert not errors, f"페이지 오류: {errors}"
        browser.close()


def test_fleet_map_keyboard_goal_requires_confirmation_and_can_cancel(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[tuple[str, str]] = []
    goal_path = "/api/fleet/robots/rosy_02/goal"
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
        goal_path: {"accepted": True, "task": {"task_id": "keyboard-goal", "status": "ACCEPTED"}},
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api, posts=posts,
                                               init_script=DECLINE_CONFIRM)
        page.goto(console_url, wait_until="networkidle")
        page.locator('[data-context-tab="inbox"]').click()
        assert page.locator("#log ui-empty").inner_text() == "최근 이벤트가 없습니다 — 관제 요청과 연결 상태 변화가 여기에 표시됩니다."
        page.locator('[data-context-tab="status"]').click()
        _open_cards(page, "rosy_02")
        page.wait_for_function("() => !document.querySelector('[data-goal-robot-id=rosy_02]')?.disabled")
        aim = page.locator('[data-goal-robot-id="rosy_02"]')
        aim.click()
        canvas = page.locator("#map-canvas")
        assert canvas.get_attribute("tabindex") == "0"
        assert page.evaluate("document.activeElement?.id") == "map-canvas"
        page.keyboard.press("ArrowRight")
        assert "rosy_02" in page.inner_text("#hint")
        assert "Enter" in page.inner_text("#hint")
        save_temp_screenshot(page, "fleet_goal_preconfirm.png")
        page.keyboard.press("Enter")
        dialog = page.locator('dialog.ui-confirm')
        dialog.wait_for()
        assert "rosy_02" in dialog.inner_text()
        save_temp_screenshot(page, "fleet_goal_confirm_open.png")
        dialog.locator('ui-button[kind=quiet]').click()
        assert not any(method == "POST" and path == goal_path for method, path in posts)
        page.keyboard.press("Escape")
        assert page.locator(".robot.selected").count() == 0
        assert page.evaluate("document.activeElement?.dataset.goalRobotId") == "rosy_02"

        aim.click()
        page.keyboard.press("Enter")
        dialog.locator('ui-button[kind=irreversible]').click()
        page.wait_for_function("() => document.querySelector('#log')?.textContent.includes('미션 하달')")
        assert sum(method == "POST" and path == goal_path for method, path in posts) == 1
        assert page.locator("#log ui-empty").count() == 0
        assert page.locator(".robot.selected").count() == 0
        assert page.evaluate("document.activeElement?.dataset.goalRobotId") == "rosy_02"
        page.locator('[data-context-tab="inbox"]').click()
        assert page.locator("#log").is_visible()
        assert not errors
        browser.close()


def test_queued_navigation_is_successful_and_cancel_targets_task(console_url):
    from playwright.sync_api import sync_playwright

    posts: list[tuple[str, str]] = []
    task = {"task_id": "task-queued-123", "status": "QUEUED", "attempt_seq": 0,
            "reason": "ROUTE_CONFLICT", "waiting_on": ["rosy_02"], "queue_position": 1}
    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
        "/api/fleet/robots/rosy_01/goal": {"accepted": False, "queued": True, "task": task},
        "/api/fleet/tasks/task-queued-123": {"task": task},
        "/api/fleet/tasks/task-queued-123/cancel": {"task": {**task, "status": "CANCELED"}},
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api, posts=posts,
                                              init_script="window.confirm = () => true")
        page.goto(console_url, wait_until="networkidle")
        _open_cards(page)
        page.wait_for_function("() => document.querySelectorAll('#robot-workspace article').length > 0")
        page.wait_for_function("() => !document.querySelector('[data-goal-robot-id=rosy_01]')?.disabled")
        page.locator('[data-goal-robot-id="rosy_01"]').click()
        canvas_box = page.locator("#map-canvas").bounding_box()
        assert canvas_box
        page.mouse.click(canvas_box["x"] + canvas_box["width"] / 2,
                         canvas_box["y"] + canvas_box["height"] / 2)
        page.locator('dialog.ui-confirm ui-button[kind=irreversible]').click()
        page.wait_for_function("() => document.querySelector('#log')?.textContent.includes('task-queued-123')")
        page.locator('[data-context-tab="inbox"]').click()
        assert "QUEUED" in page.inner_text("#log")
        assert "#1" in page.inner_text("#log")
        page.locator('[data-context-tab="status"]').click()
        page.locator("#robot-workspace article").filter(has_text="rosy_01").locator("ui-button[data-cancel-scope]").click()
        page.wait_for_timeout(200)
        assert not errors
        browser.close()

    assert ("POST", "/api/fleet/tasks/task-queued-123/cancel") in posts


# --- D-219: 큐의 렌더 계약 — HITL 과 성능 저하가 보이고, 비면 사라진다 ---------

def _with_state(robot: dict, **state_extra) -> dict:
    row = {**robot, "state": {**robot["state"], **state_extra}}
    return row


def test_queues_render_hitl_and_degraded_then_hide_when_empty(console_url):
    from playwright.sync_api import sync_playwright

    degraded = {
        "fleet": {"name": "site", "online": 3, "total": 3},
        "robots": [
            _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0}),
            _with_state(_robot("rosy_02", {"x": 0.45, "y": 1.0, "yaw": 0.0}),
                        hitl_requested=True),
            _with_state(_robot("rosy_03", {"x": 0.45, "y": 0.4, "yaw": 0.0}),
                        capabilities_degraded=["lidar", "docking"]),
        ],
        "ts": 0.0,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, {
            "/api/fleet/state": degraded,
            "/api/fleet/map": MAP_GRID,
            "/api/fleet/formation": {"active": False, "state": "IDLE"},
        })
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => document.querySelectorAll('#critical-list li').length === 1"
            " && document.querySelectorAll('#warning-list li').length === 1"
        )
        crit = page.inner_text("#critical-list")
        warn = page.inner_text("#warning-list")
        assert "rosy_02" in crit and "개입 필요" in crit
        assert "로봇 화면에서 확인" in crit  # 정직한 경로(D-218, F-20)
        assert "rosy_03" in warn and "lidar" in warn
        assert page.locator(".queues-panel").is_visible()
        assert not errors, f"페이지 오류: {errors}"
        save_temp_screenshot(page, "fleet_console_queues.png")
        browser.close()

    normal = {
        "fleet": {"name": "site", "online": 3, "total": 3},
        "robots": [_robot(f"rosy_0{i}", {"x": 0.4 * i, "y": 1.0, "yaw": 0.0}) for i in (1, 2, 3)],
        "ts": 0.0,
    }
    with sync_playwright() as p:
        browser, page, _errors = _open_console(p, {
            "/api/fleet/state": normal,
            "/api/fleet/map": MAP_GRID,
            "/api/fleet/formation": {"active": False, "state": "IDLE"},
        })
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
        # 정상 로스터에는 큐 패널이 아예 없다 — '이상 없음'을 칠하지 않는다.
        assert page.locator(".queues-panel").is_hidden()
        browser.close()

    # D-493: SNAPSHOT is not a normal roster — rosy_03's card carries a red relay tag and a traffic wait.
    # The queue says so with the card's own rule (2026-10-07: the queue used to stay hidden here).
    with sync_playwright() as p:
        browser, page, _errors = _open_console(p, {
            "/api/fleet/state": SNAPSHOT,
            "/api/fleet/map": MAP_GRID,
            "/api/fleet/formation": FORMATION,
        })
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        assert page.locator(".queues-panel").is_visible()
        assert "릴레이 끊김" in page.inner_text("#critical-list")
        # D-540 3: the robot is named once, in its row; the head counts (names stay in its title).
        assert "rosy_03" in page.inner_text("#critical-list")
        assert "rosy_03" in page.locator("#critical-head small").get_attribute("title")
        browser.close()


# --- D-201: 예외 문법의 적합 계약 — 선언 뷰포트(사이트 PC 1920×1080)에서
#     문서가 스크롤되지 않고 신호등·대형이 뷰포트 안에 있다. -------------------

FLEET_FIT_PROBE = """() => {
  const inside = (sel) => {
    const n = document.querySelector(sel);
    if (!n) return null;
    const b = n.getBoundingClientRect();
    return { top: Math.round(b.top), bottom: Math.round(b.bottom), height: Math.round(b.height), width: Math.round(b.width) };
  };
  return {
    docOverflow: document.documentElement.scrollHeight - window.innerHeight,
    primary: inside('.console-primary'),
    secondary: inside('.console-secondary'),
    mapPanel: inside('.panel[aria-labelledby="map-heading"]'),
    mapCanvas: inside('#map-canvas'),
    visionFrame: inside('#vision-frame'),
    visionPreview: inside('.vision-preview'),
    signals: inside('.signals'),
    formation: inside('.formation'),
    rosterPanel: inside('.panel[aria-labelledby="roster-heading"]'),
    stop: inside('#estop'),
    roster: inside('#roster'),
    rosterHeading: inside('#roster-heading'),
    rosterPreceding: inside('.robot-list-details > h3'),
    vh: window.innerHeight,
  };
}"""


def test_console_fits_the_declared_viewport(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        fit = page.evaluate(FLEET_FIT_PROBE)
        page.locator('[data-context-tab="tools"]').click()
        tools_fit = page.evaluate(FLEET_FIT_PROBE)
        page.locator('[data-context-tab="status"]').click()
        assert not errors
        save_temp_screenshot(page, "fleet_console_fit.png")
        browser.close()

    assert fit["docOverflow"] <= 0, (
        f"문서가 {fit['docOverflow']}px 스크롤된다 — 예외 문법은 한눈에 다"
        " 보인다(D-201): " + str(fit)
    )
    assert abs(fit["primary"]["width"] / fit["secondary"]["width"] - 2) <= 0.03, fit  # D-629: map 2 : rail 1
    # D-540 3 replaces D-493's 1920 rail fit: the rail is the one scroll, its first panels start on screen.
    assert fit["rosterPanel"]["top"] < fit["vh"], fit
    for name in ("mapCanvas", "roster", "rosterPanel", "stop"):
        assert fit[name]["width"] > 0 and fit[name]["height"] > 0, fit
    for name in ("signals", "formation", "visionPreview"):
        assert tools_fit[name]["width"] > 0 and tools_fit[name]["height"] > 0, tools_fit
    assert tools_fit["visionFrame"]["height"] == 0, tools_fit  # No camera source in this fixture.
    assert fit["stop"]["width"] >= 48 and fit["stop"]["height"] >= 48, fit
    assert fit["stop"]["top"] >= 0 and fit["stop"]["bottom"] <= fit["vh"], fit
    assert fit["rosterPreceding"]["top"] >= fit["rosterHeading"]["bottom"], fit
    assert fit["roster"]["top"] - fit["rosterPreceding"]["bottom"] <= 24, fit
    assert fit["rosterPanel"]["height"] <= 0.75 * fit["vh"], fit


@pytest.mark.parametrize("scenario", ["delayed", "disconnected", "viewer"])
def test_desktop_exception_states_fit_without_hiding_evidence(console_url, scenario):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": UNREACHABLE_SNAPSHOT if scenario == "disconnected" else SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": DELAYED_FORMATION if scenario == "delayed" else FORMATION,
    }
    if scenario == "viewer":
        api["/api/fleet/session"] = {"principal_id": "test-viewer", "role": "viewer"}
    with sync_playwright() as p:
        browser, page, errors = _open_console(p, api)
        page.goto(console_url, wait_until="networkidle")
        fit = page.evaluate(FLEET_FIT_PROBE)
        assert fit["docOverflow"] <= 0, fit
        assert abs(fit["primary"]["width"] / fit["secondary"]["width"] - 2) <= 0.03, fit  # D-629: map 2 : rail 1
        assert fit["stop"]["bottom"] <= fit["vh"]
        if scenario == "delayed":
            assert "지연" in page.inner_text("#roster")
            # D-540 3: the roster has no scroll of its own; the rail is the one scroll.
            assert page.locator("#roster").evaluate("e => e.scrollHeight <= e.clientHeight")
        elif scenario == "disconnected":
            assert "닿지 않음" in page.inner_text("#roster")
            assert page.locator(".queues-panel").is_visible()
            # D-493: the queue lives in the rail, so the map stays the main view.
            assert fit["mapCanvas"]["height"] >= 0.5 * fit["vh"]
        else:
            page.locator('[data-context-tab="tools"]').click()
            assert page.locator("#formation-role-lock").is_visible()
            assert page.locator(".formation ui-button[reason]").count() == 0
            assert page.locator("#estop").get_attribute("reason") == "운영자 권한이 필요합니다"
        assert not errors
        save_temp_screenshot(page, f"fleet_desktop_{scenario}.png")
        browser.close()


def test_fleet_control_groups_are_semantic_subheadings(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        "/api/fleet/state": SNAPSHOT,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": FORMATION,
    }
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)
        page.goto(console_url, wait_until="networkidle")
        page.wait_for_function(
            "() => (window.__swarmOverlay?.slots || 0) === 2", timeout=8000
        )
        page.locator('[data-context-tab="tools"]').click()
        headings = [
            "대형·대열",  # D-540 3
            "신호등",
        ]
        for name in headings:
            assert page.get_by_role("heading", name=name, exact=True).count() == 1
        # D-493: document navigation owns one link to each other document; recovery CTAs may repeat a destination.
        for href in ("/console/install", "/console/site-map", "/console?view=work", "/console?view=records"):
            assert page.get_by_role("navigation", name="Rosy Fleet 문서", exact=True).locator(f'a[href="{href}"]').count() == 1, href
        assert page.locator('.install-link, .device-link').count() == 0
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        assert page.get_by_role("heading", name="로봇 등록", exact=True).count() == 1
        assert not errors
        browser.close()


def test_robot_enrollment_panel_enrolls_by_screen_code(console_url):
    """D-361 S3: a named operator enrolls a discovered robot; the code goes only to Fleet."""
    import os
    from playwright.sync_api import sync_playwright

    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": ["rosy_01"],
               "robots": [], "alarms": []}
    enrolled = {"robot_id": "rosy_09", "hostname": "rosy-pinky-8kcn", "address": "192.168.1.202:8080",
                "state": "active", "legacy_lifetime": True, "origin": "enrolled", "hold": None,
                "expires_at": "2026-10-07T00:00:00+00:00"}
    api = {
        "/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID, "/api/fleet/formation": FORMATION,
        "/api/fleet/session": {"principal_id": "alice", "role": "operator"},
        "/api/fleet/discovery": {"scanner_online": True, "devices": [{
            "name": "rosy-pinky-8kcn", "hostname": "rosy-pinky-8kcn.local",
            "address": "192.168.1.202", "port": 8080, "stage": "CORE_READY", "release": "",
            "robot_id": None, "status": "registration_pending", "enrollable": True}]},
        "/api/fleet/enrollment/robots": listing,
    }
    bodies = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, api)

        def enroll(route):
            if route.request.method != "POST":
                route.fallback()
                return
            bodies.append(route.request.post_data_json)
            listing["robots"] = [enrolled]
            route.fulfill(status=201, json=enrolled)

        page.route("**/api/fleet/enrollment/robots", enroll)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        page.get_by_role("heading", name="로봇 등록", exact=True).wait_for()
        page.locator("#discovery-list ui-button", has_text="등록").first.click()
        assert not page.locator("#enroll-move-check").is_visible()
        page.locator("#enroll-code").fill("7kxm" + "p3qa")
        page.locator("#enroll-submit").click()
        page.wait_for_function(
            "() => document.querySelector('#enrolled-list')?.textContent.includes('rosy_09')")
        assert bodies == [{"discovery_name": "rosy-pinky-8kcn", "code": "7KXM-" + "P3QA"}]
        text = page.locator("#enrolled-list").text_content()
        assert "출처 등록" in text and "7일 뒤 새 코드" in text and "출처 파일" in text
        shot = os.environ.get("ROSY_ENROLL_SCREENSHOT")
        if shot:
            page.screenshot(path=shot, full_page=True)
        assert not errors
        browser.close()


def _enrollment_api(listing):
    return {
        "/api/fleet/state": SNAPSHOT, "/api/fleet/map": MAP_GRID, "/api/fleet/formation": FORMATION,
        "/api/fleet/session": {"principal_id": "alice", "role": "operator"},
        "/api/fleet/discovery": {"scanner_online": True, "devices": [{
            "name": "rosy-pinky-8kcn", "hostname": "rosy-pinky-8kcn.local",
            "address": "192.168.1.202", "port": 8080, "stage": "CORE_READY", "release": "",
            "robot_id": None, "status": "registration_pending", "enrollable": True}]},
        "/api/fleet/enrollment/robots": listing,
        "/api/fleet/estop": {"stopped": 3, "total": 3, "robots": []},
    }


def test_enrollment_dialog_leaves_the_fleet_stop_live(console_url):
    """D-280 원칙 2 (P1-2 review): the enrollment dialog is non-modal — #estop stays live."""
    from playwright.sync_api import sync_playwright

    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": [], "robots": [], "alarms": []}
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _enrollment_api(listing), posts)
        page.on("dialog", lambda dialog: dialog.accept())  # 전체 정지의 window.confirm
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        page.get_by_role("heading", name="로봇 등록", exact=True).wait_for()
        opener = page.locator("#discovery-list ui-button", has_text="등록").first
        opener.click()
        page.wait_for_function("document.getElementById('enroll-dialog').open")
        assert page.evaluate("document.activeElement?.id") == "enroll-code"
        state = page.evaluate("""() => {
          const stop = document.getElementById('estop');
          const box = stop.getBoundingClientRect();
          const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
          const inertAncestor = (node) => { for (; node; node = node.parentElement) if (node.inert) return true; return false; };
          return {stopInert: inertAncestor(stop), hitsStop: Boolean(hit && stop.contains(hit)),
                  dialogInert: inertAncestor(document.getElementById('enroll-dialog')),
                  panelInert: inertAncestor(document.getElementById('enrolled-list'))};
        }""")
        assert state == {"stopInert": False, "hitsStop": True, "dialogInert": False, "panelInert": True}
        page.locator("#estop").click()
        page.wait_for_function("!document.getElementById('enroll-dialog').open")
        for _ in range(50):
            if ("POST", "/api/fleet/estop") in posts:
                break
            page.wait_for_timeout(100)
        assert ("POST", "/api/fleet/estop") in posts
        assert page.evaluate("[...document.querySelectorAll('[inert]')].length") == 0
        # the dialog went back to its panel (it sat at the end of body only while open)
        assert page.evaluate("document.getElementById('enroll-dialog').parentElement !== document.body")
        assert not errors
        browser.close()


def test_unenroll_is_a_quiet_row_action_confirmed_by_name(console_url):
    """D-371 (P2-3 review): 등록 해제 revokes the site token, so it is `등록 해제…` + confirmIrreversible."""
    from playwright.sync_api import sync_playwright

    enrolled = {"robot_id": "rosy_09", "hostname": "rosy-pinky-8kcn", "address": "192.168.1.202:8080",
                "state": "active", "legacy_lifetime": True, "origin": "enrolled", "hold": None,
                "expires_at": "2026-10-07T00:00:00+00:00"}
    listing = {"available": True, "unavailable_reason": None, "static_robot_ids": [], "robots": [enrolled],
               "alarms": []}
    deletes = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, _enrollment_api(listing))

        def remove(route):
            if route.request.method != "DELETE":
                route.fallback()
                return
            deletes.append(route.request.url)
            route.fulfill(status=200, json={"state": "removed"})

        page.route("**/api/fleet/enrollment/robots/rosy_09", remove)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="로봇 등록", exact=True).click()
        row_button = page.locator('#enrolled-list li[data-robot-id="rosy_09"] ui-button[data-action="unenroll"]')
        row_button.wait_for()
        assert row_button.inner_text() == "등록 해제…"
        assert row_button.get_attribute("kind") == "quiet"
        row_button.click()
        dialog = page.locator("dialog.ui-confirm")
        dialog.wait_for()
        assert '"rosy_09"' in dialog.locator("p").inner_text()
        run = dialog.locator('ui-button[kind="irreversible"]')
        assert run.inner_text() == "등록 해제"
        page.keyboard.press("Escape")
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        assert deletes == []
        assert page.evaluate("document.activeElement?.dataset.action") == "unenroll"
        row_button.click()
        page.locator('dialog.ui-confirm ui-button[kind="irreversible"]').click()
        page.wait_for_function("!document.querySelector('dialog.ui-confirm')")
        for _ in range(50):
            if deletes:
                break
            page.wait_for_timeout(100)
        assert len(deletes) == 1
        assert not errors
        browser.close()


def test_camera_rectification_controls_are_accessible_source_scoped_and_reset(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        **API,
        "/api/fleet/vision/sources": {"sources": ["ceiling-north"]},
        "/api/fleet/vision/lease": {
            "source_id": "ceiling-north", "lease": "preview-lease",
            "frame_path": "/api/vision/sources/ceiling-north/frame", "expires_in_s": 60,
        },
    }
    lease_payloads = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api,
            init_script="sessionStorage.setItem('rosy-console-token', 'test-token')",
        )
        page.on("request", lambda request: lease_payloads.append(json.loads(request.post_data))
                if request.url.endswith("/api/fleet/vision/lease") and request.post_data else None)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 설치·보정", exact=True).click()
        page.get_by_text("왜곡 및 사각 보정", exact=True).click()
        page.get_by_label("왼쪽 위 X (%)").fill("10")
        page.get_by_label("출력 비율").select_option("1")
        page.wait_for_function(
            "() => { const p = JSON.parse(localStorage.getItem('rosy-camera-rectification:ceiling-north') || '{}'); return p.output_aspect === 1 && p.corners?.[0]?.[0] === 0.1; }"
        )
        page.wait_for_timeout(600)
        assert page.get_by_label("왼쪽 위 X (%)").input_value() == "10"
        assert any(payload["rectification"]["output_aspect"] == 1
                   and payload["rectification"]["corners"][0][0] == 0.1
                   for payload in lease_payloads)
        page.get_by_role("button", name="조정 초기화").click()
        page.wait_for_function(
            "() => localStorage.getItem('rosy-camera-rectification:ceiling-north') === null"
        )
        assert page.get_by_label("왼쪽 위 X (%)").input_value() == "0"
        assert page.get_by_label("출력 비율").input_value() == "0"
        assert page.get_by_text("기본 조정값으로 초기화했습니다.").count() == 1
        assert not errors
        browser.close()


def test_camera_rectification_direct_manipulation(console_url):
    from playwright.sync_api import sync_playwright

    api = {
        **API,
        "/api/fleet/vision/sources": {"sources": ["ceiling-north"]},
        "/api/fleet/vision/lease": {
            "source_id": "ceiling-north", "lease": "preview-lease",
            "frame_path": "/api/vision/sources/ceiling-north/frame", "expires_in_s": 60,
        },
    }
    lease_payloads = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api,
            init_script=(
                "sessionStorage.setItem('rosy-console-token', 'test-token');"
                "if (!localStorage.getItem('rosy-camera-rectification:ceiling-north')) "
                "localStorage.setItem('rosy-camera-rectification:ceiling-north', JSON.stringify({"
                "corners:[[0.2,0.2],[0.8,0.2],[0.8,0.8],[0.2,0.8]]}))"
            ),
        )
        page.on("request", lambda request: lease_payloads.append(json.loads(request.post_data))
                if request.url.endswith("/api/fleet/vision/lease") and request.post_data else None)
        def serve_frame(route):
            corners = lease_payloads[-1]["rectification"]["corners"] if lease_payloads else []
            identity = corners == [[0, 0], [1, 0], [1, 1], [0, 1]]
            route.fulfill(
                status=200, content_type="image/svg+xml",
                body=b'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#111"/></svg>',
                headers={"X-Frame-Rectified": str(not identity).lower(),
                         "X-Frame-Seq": "42", "X-Frame-Age-Ms": "20"},
            )

        page.route("**/api/vision/**", serve_frame)
        page.goto(console_url.rsplit("/", 1)[0] + "/install.html", wait_until="networkidle")
        page.get_by_role("tab", name="카메라 설치·보정", exact=True).click()
        page.get_by_text("왜곡 및 사각 보정", exact=True).click()
        page.get_by_role("button", name="원본에서 영역 조정").click()
        page.wait_for_timeout(500)
        assert not errors, (errors, lease_payloads, page.locator("#vision-state").inner_text(),
                            page.locator("#vision-message").inner_text())
        assert page.locator("#vision-image-stage").get_attribute("hidden") is None, (
            lease_payloads, page.locator("#vision-state").inner_text(),
            page.locator("#vision-message").inner_text(),
        )
        assert page.locator("#vision-corner-overlay").get_attribute("hidden") is None, (
            page.locator("#vision-frame").get_attribute("data-editing"),
            page.locator("#vision-edit-corners").get_attribute("aria-pressed"),
            lease_payloads,
        )
        page.locator("[data-corner-handle='0']").wait_for(state="visible")

        handle = page.locator("[data-corner-handle='0']")
        handle.scroll_into_view_if_needed()
        box = handle.bounding_box()
        assert box is not None
        hit_test = page.evaluate("([x, y]) => document.elementFromPoint(x, y)?.outerHTML", [
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2,
        ])
        assert "data-corner-handle" in (hit_test or ""), (box, hit_test)
        page.evaluate("""() => {
          window.__pointerLog = [];
          for (const type of ['pointerdown', 'pointermove', 'pointerup'])
            document.querySelector('#vision-corner-overlay').addEventListener(type,
              (event) => window.__pointerLog.push({type, primary: event.isPrimary,
                x: event.clientX, y: event.clientY, target: event.target.dataset.cornerHandle}), true);
        }""")
        start_x, start_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + 0.1 * box["width"], start_y + 0.1 * box["height"])
        page.mouse.up()
        page.wait_for_timeout(250)
        assert page.evaluate("window.__pointerLog"), page.evaluate("window.__pointerLog")
        page.wait_for_function(
            "() => JSON.parse(localStorage.getItem('rosy-camera-rectification:ceiling-north') || '{}')"
            ".corners?.[0]?.[0] > 0.2 && JSON.parse(localStorage.getItem('rosy-camera-rectification:ceiling-north') || '{}')"
            ".corners?.[0]?.[1] > 0.2",
            timeout=1000,
        )
        moved_x = page.get_by_label("왼쪽 위 X (%)").input_value()
        assert float(moved_x) > 20
        assert lease_payloads and lease_payloads[-1]["rectification"]["corners"][0] == [0, 0]

        page.locator("[data-corner-handle='1']").focus()
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("ArrowDown")
        assert page.evaluate("document.activeElement.dataset.cornerHandle") == "1"
        coarse_x = float(page.get_by_label("오른쪽 위 X (%)").input_value())
        page.keyboard.press("Shift+ArrowRight")
        preserved_x = page.get_by_label("오른쪽 위 X (%)").input_value()
        assert float(preserved_x) == pytest.approx(coarse_x + 0.1)
        save_temp_screenshot(page, "fleet_camera_direct_adjustment_desktop.png")
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("[data-corner-handle='1']").scroll_into_view_if_needed()
        save_temp_screenshot(page, "fleet_camera_direct_adjustment_mobile.png")
        assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") == 0
        page.get_by_role("button", name="보정 결과 미리보기").click()
        page.wait_for_function(
            "() => document.querySelector('#vision-state').textContent.includes('보정')"
        )
        assert lease_payloads[-1]["rectification"]["corners"][0][0] > 0.2
        assert lease_payloads[-1]["rectification"]["corners"][1][0] < 0.8
        assert lease_payloads[-1]["rectification"]["corners"][1][1] > 0.2
        assert not errors
        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name="카메라 설치·보정", exact=True).click()
        page.get_by_text("왜곡 및 사각 보정", exact=True).click()
        assert page.get_by_label("오른쪽 위 X (%)").input_value() == preserved_x
        browser.close()


def test_camera_fault_ir_fallback_decline_sends_no_request(console_url):
    from playwright.sync_api import sync_playwright

    robot = _robot("rosy_01", {"x": 1.0, "y": 1.0, "yaw": 0.0})
    robot["state"]["line_follow"] = {
        "mode": "CAMERA_LINE",
        "state": "LOST",
        "reason": "camera_reselection_required",
    }
    snapshot = {"fleet": {"name": "site", "online": 1, "total": 1}, "robots": [robot], "ts": 0.0}
    api = {
        "/api/fleet/state": snapshot,
        "/api/fleet/map": MAP_GRID,
        "/api/fleet/formation": {"active": False, "state": "IDLE"},
    }
    posts = []
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(
            playwright, api, posts=posts, init_script=DECLINE_CONFIRM
        )
        page.goto(console_url, wait_until="networkidle")
        _open_cards(page)
        fallback = page.get_by_role("button", name="IR 차선 추종으로 전환…", exact=True)
        fallback.wait_for(state="visible")
        fallback.click()
        dialog = page.locator('dialog.ui-confirm')
        dialog.wait_for()
        confirm = dialog.inner_text()
        dialog.locator('ui-button[kind=quiet]').click()
        browser.close()

    assert "rosy_01" in confirm and "IR 차선 추종" in confirm and "요청할까요?" in confirm
    assert not [method_path for method_path in posts if method_path[0] == "POST"]
    assert errors == []


@pytest.mark.parametrize("width", [320, 390])
def test_mobile_console_has_no_horizontal_overflow(console_url, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(console_url, wait_until="networkidle")
        assert page.locator('#roster article').first.get_attribute('data-robot-id') == 'rosy_03'
        assert page.locator('#robot-workspace article').count() == 0
        _open_cards(page, 'rosy_03')
        save_temp_screenshot(page, f"fleet_console_mobile_default_{width}.png")
        actions = page.locator("#robot-workspace article .robot-actions:has([data-goal-robot-id])")
        action_widths, actions_width = actions.locator("ui-button").evaluate_all(
            "buttons => [buttons.map(button => button.getBoundingClientRect().width), "
            "buttons[0].parentElement.getBoundingClientRect().width]")
        # D-540 (d), D-440 6: goal, trip, cancel, LED, map pin and sleep/wake wrap whole, never wider than the row.
        assert len(action_widths) == 6 and abs(action_widths[0] - action_widths[1]) <= 1, action_widths
        assert all(w <= actions_width + 1 for w in action_widths), action_widths
        _open_cards(page)
        save_temp_screenshot(page, f"fleet_console_mobile_{width}.png")
        layout = page.evaluate("""() => ({
          overflow: document.documentElement.scrollWidth - innerWidth,
          outside: [...document.querySelectorAll('*')].filter(node => node.getBoundingClientRect().right > innerWidth + 1)
            .slice(0, 8).map(node => ({tag:node.tagName, className:String(node.className),
              right:node.getBoundingClientRect().right})),
          headerRows: getComputedStyle(document.querySelector('ui-topbar')).gridTemplateRows
            .trim().split(' ').length,
          headerOverlaps: (() => {
            const boxes = ['ui-brand', '#online-pill', '#estop', '#console-token',
              '#token-save', '#user-role', '#clock'].map(selector => {
                const rect = document.querySelector(selector).getBoundingClientRect();
                return {selector, left:rect.left, right:rect.right, top:rect.top, bottom:rect.bottom};
              });
            return boxes.flatMap((a, index) => boxes.slice(index + 1).filter(b =>
              Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
              Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1
            ).map(b => [a.selector, b.selector]));
          })(),
          brand: document.querySelector('ui-brand').getBoundingClientRect().toJSON(),
          brandSize: parseFloat(getComputedStyle(document.querySelector('ui-brand b')).fontSize),
          stop: document.querySelector('#estop').getBoundingClientRect().toJSON(),
          status: document.querySelector('#online-pill').getBoundingClientRect().toJSON(),
          operator: document.querySelector('#user-role').getBoundingClientRect().toJSON(),
          clock: document.querySelector('#clock').getBoundingClientRect().toJSON(),
          inbox: document.querySelector('#fleet-inbox').getBoundingClientRect().toJSON(),
          stopScopeHidden: (() => {
            const small = document.querySelector('#estop small');
            return !!small && getComputedStyle(small).display === 'none';
          })(),
          stopVerb: [...document.querySelectorAll('#estop span')].filter(node => !node.classList.contains('sr-only')).map(node => node.textContent).join(''),
          stopAccessibleName: document.querySelector('#estop').getAttribute('aria-label'),
        })""")
        if width <= 320:
            # D-741 2: the work area link lives in the rail, visible without opening settings.
            assert page.locator('.doc-tabs a[href="/console?view=work"]').is_visible()
        browser.close()
    assert errors == []
    assert layout["overflow"] == 0, layout["outside"]
    assert layout["stop"]["right"] <= width, layout
    assert layout["status"]["right"] <= width, layout
    assert layout["brand"]["left"] >= 0 and layout["brandSize"] >= 12, layout
    assert layout["brand"]["right"] <= layout["status"]["left"] or layout["brand"]["bottom"] <= layout["status"]["top"], layout
    assert layout["headerRows"] == 1, layout  # D-741 5: one row down to 320px.
    assert layout["headerOverlaps"] == [], layout
    if width <= 384:
        # D-741 3: the clock lives in the app bar and folds below 48rem; the robot count sits in the map head.
        assert layout["status"]["top"] >= layout["stop"]["bottom"], layout
        assert layout["clock"]["height"] == 0, layout
        assert layout["stopScopeHidden"], layout
        # 보이는 동사는 비상 정지. 래치 부제는 이 폭에서 숨고, 접근 이름은 보이는 글이다.
        assert layout["stopVerb"] == "비상 정지", layout
        assert layout["stopAccessibleName"] is None, layout


@pytest.mark.parametrize("width", [320, 390, 1366])
def test_formation_buttons_keep_their_reasons_readable(console_url, width):
    """D-359 US-007 캡처: 네 버튼을 한 줄에 같은 폭으로 눌러 담아 390px에서 '무장 / 이미 대형 중'이
    어절마다 한 줄씩 네 줄이 됐다. 버튼 줄은 접히고, 이름·사유는 각각 두 줄을 넘지 않는다."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.set_viewport_size({"width": width, "height": 844})
        page.goto(console_url, wait_until="networkidle")
        page.locator('[data-context-tab="tools"]').click()
        page.wait_for_function("() => document.querySelector('#formation-start small[data-reason]')")
        tall = page.evaluate("""() => [...document.querySelector('#formation-start').parentElement.querySelectorAll('ui-button')].flatMap(button => {
          const note = button.querySelector('small[data-reason]');
          const lines = (node) => node ? Math.round(node.getBoundingClientRect().height
            / parseFloat(getComputedStyle(node).lineHeight)) : 0;
          const label = [...button.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
          const range = document.createRange();
          const text = [...button.childNodes].find(n => n.nodeType === 3 && n.textContent.trim());
          let labelLines = 0;
          if (text) { range.selectNodeContents(text); labelLines = range.getClientRects().length; }
          return (lines(note) > 2 || labelLines > 2) ? [`${button.id} ${label}: label ${labelLines}, reason ${lines(note)}`] : [];
        })""")
        browser.close()
    assert errors == []
    assert tall == []


# --- D-359 §6.4: 세로 예산 — 붙박이 머리 ≤ 창 높이 20%, 비상 정지는 첫 화면에 ---------

@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_compact_header_budget_keeps_the_stop_in_view(console_url, width, height):
    """접속 입력·현재 역할은 상태 센터 뒤로 접히고 테마 버튼 하나는 계정 접힘 안에 남는다(D-668). 머리는 창 높이의 20% 이하다.

    변이 증명: components.css `ui-topbar`에 `min-height: 300px`을 넣으면 빨갛다."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        page.set_viewport_size({"width": width, "height": height})
        page.goto(console_url, wait_until="networkidle")
        probe = """() => {
          const box = (s) => document.querySelector(s).getBoundingClientRect().toJSON();
          const shown = (s) => { const n = document.querySelector(s); return !!n && n.getClientRects().length > 0; };
          return {overflow: document.documentElement.scrollWidth - innerWidth,
            topbar: box('ui-topbar'), sticky: getComputedStyle(document.querySelector('ui-topbar')).position,
            stop: box('#estop'), more: box('#topbar-more'),
            expanded: document.querySelector('#topbar-more').getAttribute('aria-expanded'),
            token: shown('#console-token'), theme: shown('#fleet-theme'), role: shown('#user-role'),
            roleText: document.querySelector('#user-role').textContent.trim(),
            moreName: document.querySelector('#topbar-more').getAttribute('aria-label'),
            status: shown('#online-pill'), clock: shown('#clock'),
            footer: !!document.querySelector('footer'),
            clockInHeader: !!document.querySelector('ui-topbar #clock')};
        }"""
        folded = page.evaluate(probe)
        page.locator("#topbar-more").click()
        opened = page.evaluate(probe)
        page.locator("#topbar-more").click()
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        scrolled = page.evaluate(probe)
        save_temp_screenshot(page, f"fleet_header_budget_{width}.png")
        browser.close()

    assert errors == []
    assert folded["overflow"] <= 0, folded
    assert folded["topbar"]["height"] <= 0.2 * height, folded
    assert folded["sticky"] == "sticky", folded
    stop = folded["stop"]
    assert stop["top"] >= 0 and stop["left"] >= 0 and stop["bottom"] <= height and stop["right"] <= width, folded
    assert folded["expanded"] == "false" and not folded["token"] and not folded["theme"], folded
    # D-741 3: below 30rem the role text folds (fleet-header.css); the account button's name says the role.
    role_text_shown = width >= 480
    for state in (folded, opened):
        assert state["role"] == role_text_shown, state
        assert state["roleText"] and state["moreName"].startswith(f"계정과 접속 · {state['roleText']}"), state
    assert folded["status"] and not folded["clock"] and not folded["footer"], folded
    assert folded["clockInHeader"], folded
    assert folded["stop"]["height"] >= 48 and folded["more"]["height"] >= 48, folded
    assert opened["expanded"] == "true" and opened["token"] and opened["theme"], opened
    assert opened["overflow"] <= 0, opened
    assert scrolled["expanded"] == "false", scrolled
    assert 0 <= scrolled["stop"]["top"] and scrolled["stop"]["bottom"] <= height, scrolled


def test_wide_header_keeps_every_item_on_one_line(console_url):
    """D-658 넓은 화면도 접속·화면 표시 상세는 접힌다. 네 영역과 비상 정지는 상단에 남는다."""
    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as playwright:
        browser, page, errors = _open_console(playwright, API)
        for width, height in ((1920, 1080), (1366, 768), (1280, 800)):
            page.set_viewport_size({"width": width, "height": height})
            page.goto(console_url, wait_until="networkidle")
            # D-741 3: 화면 표시와 접속 상세는 계정 단추 아래에 접혀 있다.
            assert page.locator('#fleet-theme').is_hidden()
            assert page.locator('#topbar-extra').is_hidden()
            results[width] = page.evaluate("""() => {
              const more = document.querySelector('#topbar-more');
              return {moreShown: more.getClientRects().length > 0,
                topbar: document.querySelector('ui-topbar').getBoundingClientRect().height,
                stop: document.querySelector('#estop').getBoundingClientRect().toJSON()};
            }""")
        browser.close()

    assert errors == []
    for width in (1920, 1366, 1280):
        assert results[width]["moreShown"], results
    for width, result in results.items():
        assert result["topbar"] <= 100, results
        assert result["stop"]["top"] <= 30 and width - result["stop"]["right"] <= 32, results
