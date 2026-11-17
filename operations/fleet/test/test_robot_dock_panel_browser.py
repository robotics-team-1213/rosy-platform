"""Fleet Console C23 robot dock and C24 robot panel integration tests."""

import copy
import json

import pytest
from browser_harness import assert_layout_geometry, browser_tests_enabled
from test_console_queue_inline_browser import API, STUCK, _open, _robot, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in real Chromium scenario")

_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\x0bIDATx\x9cc`\x00\x02"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _charge_bays_fixture():
    return {
        "bays": [],
        "omx_cells": {
            "cell_s": {"owner_connected": True, "gate": {"phase": "READY", "allowed_owners": ["fleet"]}},
            "cell_ab": {"owner_connected": True, "gate": {"phase": "READY", "allowed_owners": ["fleet"]}},
        },
        "arm_live_states": {
            "arm_s": {"available": True, "online": True, "age_s": 0.2, "torque": True,
                      "current_ma": 240, "temp_c": 34.0, "joints_deg": [0, -15, 20, 5, 0, 0]},
            "arm_a": {"available": True, "online": True, "age_s": 0.2, "torque": True,
                      "current_ma": 210, "temp_c": 33.0, "joints_deg": [0, 10, 15, 0, 0, 0]},
            "arm_b": {"available": False, "online": False, "age_s": 12.0},
        },
        "arm_holds": {
            "arm_s": {"held": False},
            "arm_a": {"held": True, "reason": "적재 확인 대기"},
            "arm_b": {"held": False},
        },
        "human_safety": {"active_estop": False, "human_detected": {"all": False, "cell_s": False, "cell_ab": False}},
        "cell_tasks": [],
    }


_DOCK_GRID = {
    "map_id": "mock:1",
    "width": 40,
    "height": 40,
    "resolution": 0.05,
    "origin": {"x": -1.0, "y": -1.0, "yaw": 0.0},
    "data": [20] * 1600,
}


def _dock_api(*, operator=True, named=True):
    r45 = _robot("rosy_45")
    r46 = _robot("rosy_46")
    return {
        **copy.deepcopy(API),
        "/api/fleet/session": {"principal_id": "bob" if named else "shared", "role": "operator" if operator else "viewer",
                               "shared_token": not named},
        "/api/fleet/state": {"fleet": {"name": "site", "online": 2, "total": 2}, "ts": 0.0, "robots": [r45, r46]},
        "/api/fleet/map": copy.deepcopy(_DOCK_GRID),
        "/api/fleet/charge-bays": _charge_bays_fixture(),
        "/api/fleet/vision/sources": {"sources": ["omx_arm_s_top", "omx_arm_s_wrist", "omx_overhead", "omx_wrist_a"]},
    }


def _assert_layout_geometry_desktop_and_390(page, desktop=(1440, 900)):
    """가드는 호출처의 데스크톱 크기 그대로, 그리고 390×844 모바일 시트에서도 돈다."""
    assert_layout_geometry(page)
    page.set_viewport_size({"width": 390, "height": 844})
    assert_layout_geometry(page)
    page.set_viewport_size({"width": desktop[0], "height": desktop[1]})


def test_dock_and_panel_render_pinky_and_arms_with_layouts_and_exclusion(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1440, 900))
        try:
            dock = page.locator("#robot-dock-mount")
            expect(dock).to_be_visible()
            for rid in ("rosy_45", "rosy_46", "arm_s", "arm_a", "arm_b"):
                expect(dock.locator(f'.robot-dock-btn[data-robot-id="{rid}"]')).to_have_count(1)
            expect(page.locator("#roster-summary")).to_contain_text("로봇 5대")

            # 1440 desktop pushes stage width while keeping topbar #estop visible and panel open.
            before_main = page.locator("#fleet-main").bounding_box()
            dock.locator('.robot-dock-btn[data-robot-id="rosy_45"]').click()
            panel = page.locator("#robot-panel-mount")
            expect(panel).to_be_visible()
            expect(panel).to_have_attribute("data-robot-id", "rosy_45")
            after_main = page.locator("#fleet-main").bounding_box()
            assert after_main["width"] < before_main["width"]

            # Mutual exclusion: opening AI assistant closes robot panel; clicking dock closes assistant.
            page.locator("#assistant-toggle").click()
            expect(page.locator("#assistant-panel")).to_be_visible()
            expect(panel).to_be_hidden()
            dock.locator('.robot-dock-btn[data-robot-id="rosy_46"]').click()
            expect(panel).to_be_visible()
            expect(page.locator("#assistant-panel")).to_be_hidden()

            # 390 mobile renders below-header sheet while #estop stays visible and clickable.
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            estop_box = page.locator("#estop").bounding_box()
            panel_box = panel.bounding_box()
            assert estop_box and panel_box and panel_box["y"] >= estop_box["y"]
            assert page.locator("#estop").is_enabled()

            # Esc priority: armed pin disarms first without closing the panel; next Esc returns focus to dock.
            page.locator('#robot-panel-mount [data-pin-robot-id="rosy_46"]').click()
            page.keyboard.press("Escape")
            expect(panel).to_be_visible()
            page.keyboard.press("Escape")
            expect(panel).to_be_hidden()
            expect(dock.locator('.robot-dock-btn[data-robot-id="rosy_46"]')).to_be_focused()
            assert not any("/api/fleet/pipeline/" in p for p, _ in posts)
            assert not errors
        finally:
            browser.close()


def test_arm_panel_readiness_409_refresh_and_camera_lease_cleanup(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    leases = []
    api = _dock_api()
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1440, 900))
        try:
            page.route("**/api/fleet/vision/lease", lambda r: (
                leases.append(json.loads(r.request.post_data or "{}")["source_id"]),
                r.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "source_id": "omx_arm_s_top", "lease": "lease-s", "expires_in_s": 60,
                    "frame_path": "/api/vision/sources/omx_arm_s_top/frame",
                })),
            ))
            page.route("**/api/vision/sources/*/frame", lambda r: r.fulfill(
                status=200, headers={"Content-Type": "image/png", "X-Frame-Age-Ms": "200", "X-Frame-State": "live"},
                body=_PNG_1X1,
            ))

            dock = page.locator("#robot-dock-mount")
            # arm_s has cell_s cameras without 'side', readiness ok, and static stop note.
            dock.locator('.robot-dock-btn[data-robot-id="arm_s"]').click()
            panel = page.locator("#robot-panel-mount")
            expect(panel).to_have_attribute("data-kind", "arm")
            expect(panel.locator('[data-arm-camera="arm_s_top"]')).to_have_count(1)
            expect(panel.locator('[data-arm-camera="arm_s_wrist"]')).to_have_count(1)
            expect(panel.locator('[data-arm-camera="side"]')).to_have_count(0)
            expect(panel.locator(".robot-panel-stop-note")).to_contain_text("전체 비상 정지")
            page.clock.run_for(300)
            assert leases

            # HTTP 409 on propose refreshes and surfaces reason cleanly without pipeline calls.
            page.route("**/api/fleet/arm-transfers/jobs", lambda r: r.fulfill(
                status=409, content_type="application/json", body=json.dumps({"detail": "ARM_BUSY_CONFLICT"})
            ))
            panel.locator('[data-arm-transfer-propose="arm_s"]').click()
            expect(panel.locator("[data-arm-command-reason]")).to_have_text("ARM_BUSY_CONFLICT")
            page.clock.run_for(1500)
            expect(panel.locator("[data-arm-command-reason]")).to_have_text("ARM_BUSY_CONFLICT")
            expect(panel.locator(".robot-panel-work-link")).to_have_attribute("href", "/console?view=work#work-overview")

            # arm_a is held -> propose disabled with hold reason; arm_b is offline -> disconnected reason.
            dock.locator('.robot-dock-btn[data-robot-id="arm_a"]').click()
            expect(panel.locator('[data-arm-transfer-propose="arm_a"]')).to_be_disabled()
            expect(panel.locator("[data-arm-command-reason]")).to_contain_text("홀드 중")

            dock.locator('.robot-dock-btn[data-robot-id="arm_b"]').click()
            expect(panel.locator('[data-arm-transfer-propose="arm_b"]')).to_be_disabled()
            expect(panel.locator("[data-arm-command-reason]")).to_contain_text("연결 끊김")

            # Switching back to Pinky disposes arm camera timer so no new leases fire across polls.
            dock.locator('.robot-dock-btn[data-robot-id="rosy_45"]').click()
            expect(panel).to_have_attribute("data-kind", "mobile")
            count_before = len(leases)
            page.clock.run_for(2500)
            assert len(leases) == count_before
            assert not any("/api/fleet/pipeline/" in p for p, _ in posts)
            assert not errors
        finally:
            browser.close()


def test_step_nudge_survives_refresh_tick_while_holding_focus(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    step_posts = []
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1440, 900))
        try:
            page.route("**/api/fleet/robots/rosy_45/step", lambda r: (
                step_posts.append(r.request.post_data),
                r.fulfill(status=202, content_type="application/json", body='{"accepted":true}'),
            ))
            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="rosy_45"]').click()
            fwd = page.locator('#robot-panel-mount [data-step-nudge="forward"]')
            expect(fwd).to_be_enabled()
            fwd.focus()
            page.clock.run_for(1500)
            expect(fwd).to_be_focused()
            fwd.click()
            expect(fwd).to_be_disabled()
            assert len(step_posts) == 1
            assert not errors
        finally:
            browser.close()


def test_map_click_bell_focuses_queues_and_error_popup_flow(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    api["/api/fleet/state"]["robots"][0]["pose"] = {"x": 0.0, "y": 0.0, "yaw": 0.0, "frame_id": "map"}
    api["/api/fleet/state"]["robots"][0]["state"]["pose"] = {"x": 0.0, "y": 0.0, "yaw": 0.0}
    api["/api/fleet/state"]["robots"][0]["pose_state"] = "LOCALIZED"
    api["/api/fleet/state"]["robots"][0]["battery_pct"] = 84
    api["/api/fleet/state"]["robots"][1]["pose"] = {"x": 0.7, "y": 0.7, "yaw": 0.0, "frame_id": "map"}
    api["/api/fleet/state"]["robots"][1]["state"]["pose"] = {"x": 0.7, "y": 0.7, "yaw": 0.0}
    api["/api/fleet/state"]["robots"][1]["pose_state"] = "LOCALIZED"
    # 연결 끊김 경고 행 하나: 큐 패널(.queues-panel)이 알림의 단일 표면임을 보이는 데 쓴다.
    api["/api/fleet/state"]["robots"][1]["online"] = False
    api["/api/fleet/guide"] = {
        "anchors": [
            {"target_id": "arm_s", "kind": "omx_ai", "label": "OMX-AI #3 (S3)", "base_x": -0.45, "base_y": 0.0, "head_x": -0.45, "head_y": 0.25},
        ],
    }

    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1440, 900))
        try:
            page.route(
                "**/api/fleet/robots/rosy_45/step",
                lambda r: r.fulfill(
                    status=409,
                    content_type="application/json",
                    body=json.dumps({"detail": {"code": "ROBOT_STEP_BLOCKED", "message": "차단됨: 테스트 정지", "detail": {"reason": "obstacle"}}}),
                ),
            )
            # Wait for map + guide render, then click at map center (rosy_45 at (0, 0)).
            canvas = page.locator("#map-canvas")
            expect(canvas).to_be_visible()
            page.clock.run_for(1200)
            box = canvas.bounding_box()
            assert box and box["width"] > 100

            # 이 어설션은 큐 패널이 보이는 이 뷰에서만 성립한다: 패널이 보이면 syncCritRows가
            # 새 긴급 행을 토스트로 복제하지 않는다(패널 숨김 뷰의 긴급 토스트는 아래 시험과 노드 시험이 본다).
            expect(page.locator(".queues-panel")).to_be_visible()
            expect(page.locator("#warning-list li, #critical-list li").first).to_be_visible()
            expect(page.locator("#alert-popup-region .alert-popup-card")).to_have_count(0)
            expect(page.locator("#inbox-popover")).to_have_count(0)

            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

            panel = page.locator("#robot-panel-mount")
            dock = page.locator("#robot-dock-mount")
            expect(panel).to_be_visible()
            expect(panel).to_have_attribute("data-robot-id", "rosy_45")
            panel_box = panel.bounding_box()
            dock_box = dock.bounding_box()
            assert panel_box and dock_box and panel_box["x"] + panel_box["width"] <= dock_box["x"] + 2
            # Status body must be rendered (not blank).
            assert panel.locator(".facts dd").count() >= 2

            # Re-measure map canvas after right panel opens, then click OMX arm_s at (-0.45, 0.0).
            box = canvas.bounding_box()
            span = min(box["width"], box["height"])
            page.mouse.click(box["x"] + box["width"] / 2 - span * 0.225, box["y"] + box["height"] / 2)
            expect(panel).to_have_attribute("data-robot-id", "arm_s")
            expect(panel).to_contain_text("arm_s")

            # Click back to rosy_45 via dock and trigger HTTP 409 on step nudge -> floating error popup appears.
            dock.locator('.robot-dock-btn[data-robot-id="rosy_45"]').click()
            expect(panel).to_have_attribute("data-robot-id", "rosy_45")
            panel.locator('[data-step-nudge="forward"]').click()
            popup = page.locator("#alert-popup-region .alert-popup-card").first
            expect(popup).to_be_visible()
            expect(popup).to_contain_text("HTTP 409")
            expect(popup).to_contain_text("ROBOT_STEP_BLOCKED")
            expect(popup).to_contain_text("차단됨: 테스트 정지")
            expect(popup).to_contain_text("/api/fleet/robots/rosy_45/step")
            _assert_layout_geometry_desktop_and_390(page)
            assert page.locator("#estop").is_enabled()

            # Bell keeps the count badge but opens no list; it moves focus to the queues panel.
            popup.get_by_role("button", name="닫기").click()
            expect(page.locator("#alert-popup-region .alert-popup-card")).to_have_count(0)

            page.locator("#fleet-inbox").click()
            expect(page.locator("#inbox-popover")).to_have_count(0)  # 11-18: the popover is gone
            expect(page.locator(".queues-panel")).to_be_focused()
            assert not errors
        finally:
            browser.close()


def test_hidden_queues_panel_surfaces_new_critical_row_without_duplicate_toast(site):
    """빈 큐로 숨어 있던 큐 패널에 긴급 행(판단 요청)이 상태 폴링으로 도착하면 패널이 스스로 나타나
    행을 보여주고 토스트는 중복되지 않는다. 패널이 숨은 채 새 긴급 행이 오면 토스트로 뜨는 분기
    (panelVisible=false)와 해소 시 자동 닫힘은 노드 시험 alert-popup.test.mjs가 고정한다 —
    브라우저에서는 fillQueues가 같은 render에서 패널을 다시 펴서 이 경로가 도달 가능한 전부다."""
    from playwright.sync_api import expect, sync_playwright

    api = _dock_api()
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, [])
        try:
            # 빈 큐(ADR-1000): 목록이 비었으므로 패널은 스스로 숨는다 — 토스트도 없다.
            expect(page.locator("#warning-list li, #critical-list li")).to_have_count(0)
            expect(page.locator(".queues-panel")).to_be_hidden()
            expect(page.locator("#alert-popup-region .alert-popup-card")).to_have_count(0)

            # 상태 폴링 한 번으로 rosy_46에게 판단 요청(긴급 행)이 생긴다.
            stuck = {**STUCK, "robot_id": "rosy_46", "stuck_id": "stuck-46"}
            robots = list(api["/api/fleet/state"]["robots"])
            robots[1] = {**robots[1], "line_stuck": stuck}
            api["/api/fleet/state"] = {**api["/api/fleet/state"], "robots": robots}
            page.clock.run_for(1200)

            # 패널이 스스로 나타나 긴급 행을 보여주고, 같은 항목은 토스트로 중복되지 않는다.
            row = page.locator("#critical-list li[data-key='rosy_46|stuck']")
            expect(row).to_be_visible()
            expect(page.locator(".queues-panel")).to_be_visible()
            expect(page.locator("#alert-popup-region .alert-popup-card")).to_have_count(0)

            # 행이 해소되면 패널은 다시 숨는다 — 남은 토스트도 없다.
            robots = list(api["/api/fleet/state"]["robots"])
            robots[1] = {**robots[1], "line_stuck": None}
            api["/api/fleet/state"] = {**api["/api/fleet/state"], "robots": robots}
            page.clock.run_for(1200)
            expect(page.locator(".queues-panel")).to_be_hidden()
            expect(page.locator("#alert-popup-region .alert-popup-card")).to_have_count(0)
            assert not errors
        finally:
            browser.close()


def test_arm_panel_opens_when_charge_bays_arrives_after_deeplink_selection(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    fixture = _charge_bays_fixture()
    fixture["omx_cell_tasks"] = [
        {"task_id": "cell-task-99", "cell_id": "cell_s", "arm_id": "arm_s", "status": "RUNNING"},
    ]
    api["/api/fleet/charge-bays"] = fixture
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1440, 900))
        try:
            page.goto(site + "/console?robot=arm_s")
            page.clock.run_for(1000)
            panel = page.locator("#robot-panel-mount")
            expect(panel).to_be_visible()
            expect(panel).to_have_attribute("data-robot-id", "arm_s")
            expect(panel.locator('[data-arm-job-cancel="arm_s"]')).to_be_disabled()
            expect(panel.locator('[data-arm-job-cancel="arm_s"]')).to_have_attribute("reason", "셀 작업 취소는 작업대 화면에서 진행")
            expect(panel.locator(".robot-panel-work-link")).to_have_attribute("href", "/console?view=work&task=cell-task-99")
            assert not errors
        finally:
            browser.close()


def test_arm_propose_uses_matching_transfer_request_only_for_target_instance(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    fixture = _charge_bays_fixture()
    fixture["omx_cells"]["cell_ab"] = {
        "gate": {"phase": "IDLE"},
        "reachable": True,
        "transfer_request": {
            "workcell_id": "cell_ab",
            "instance_id": "arm_a",
            "object_ref": "cargo:green_cube",
            "source": "belt",
            "target": "pallet",
        },
    }
    fixture.setdefault("arm_live_states", {})
    fixture["arm_live_states"]["arm_a"] = {"available": True, "online": True, "age_s": 0.2}
    fixture["arm_live_states"]["arm_b"] = {"available": True, "online": True, "age_s": 0.2}
    fixture["arm_holds"] = {}
    api["/api/fleet/charge-bays"] = fixture

    transfer_bodies = []
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1440, 900))
        try:
            page.route("**/api/fleet/arm-transfers/jobs", lambda r: (
                transfer_bodies.append(r.request.post_data_json),
                r.fulfill(status=200, content_type="application/json",
                          body='{"job":{"mission_id":"arm-job-a","status":"PROPOSED"}}'),
            ))
            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="arm_a"]').click()
            propose_a = page.locator('#robot-panel-mount [data-arm-transfer-propose="arm_a"]')
            expect(propose_a).to_be_enabled()
            propose_a.click()
            page.wait_for_timeout(150)

            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="arm_b"]').click()
            propose_b = page.locator('#robot-panel-mount [data-arm-transfer-propose="arm_b"]')
            expect(propose_b).to_be_enabled()
            propose_b.click()
            page.wait_for_timeout(150)

            assert len(transfer_bodies) == 2
            assert transfer_bodies[0]["workcell_id"] == "cell_ab"
            assert transfer_bodies[0]["instance_id"] == "arm_a"
            assert transfer_bodies[0]["object_ref"] == "cargo:green_cube"
            assert transfer_bodies[0]["source"] == "belt"
            assert transfer_bodies[0]["target"] == "pallet"
            assert isinstance(transfer_bodies[0]["request_key"], str) and transfer_bodies[0]["request_key"]
            assert transfer_bodies[1] == {"arm_id": "arm_b", "cell_id": "cell_ab"}
            assert not errors
        finally:
            browser.close()


def test_dock_panel_roi_layout_and_robot_switch(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    api["/api/fleet/site-map/guide"] = {
        "robots": [
            {"robot_id": "rosy_45", "pose": {"x": 0.1, "y": 0.2, "yaw": 0.0, "state": "LOCALIZED", "source": "sighting"}},
            {"robot_id": "rosy_46", "pose": {"x": 0.4, "y": -0.1, "yaw": 0.5, "state": "LOCALIZED", "source": "sighting"}},
        ],
        "anchors": [
            {"target_id": "arm_s", "kind": "omx_ai", "base_x": 0.6, "base_y": 0.0, "head_x": 0.65, "head_y": 0.0,
             "head_yaw": 0.0, "zoom": 4, "cell_status": "READY", "extension_m": 0.2, "reach_m": 0.4},
        ],
    }
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1024, 768))
        try:
            dock = page.locator("#robot-dock-mount")
            dock.locator('.robot-dock-btn[data-robot-id="rosy_45"]').click()
            panel = page.locator("#robot-panel-mount")
            expect(panel).to_be_visible()
            expect(panel).to_have_attribute("data-robot-id", "rosy_45")

            # Expand cell link fold: unbound live-cell preview stays hidden so it never draws a broken box.
            panel.locator(".quick-cell-link > summary").click()
            expect(panel.locator("#anchor-cell-live-img")).to_be_hidden()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            roi_meta_box = panel.locator(".roi-meta").bounding_box()
            assert roi_meta_box and roi_meta_box["width"] >= 160

            # Switching directly to rosy_46 updates panel cleanly without leaving rosy_45 camera tiles.
            dock.locator('.robot-dock-btn[data-robot-id="rosy_46"]').click()
            expect(panel).to_have_attribute("data-robot-id", "rosy_46")
            expect(panel.locator('[data-robot-camera-tile="rosy_45"]')).to_have_count(0)
            expect(panel.locator('[data-robot-camera-tile="rosy_46"]')).to_have_count(1)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
        finally:
            browser.close()


def test_map_selection_bar_and_overlay_hides_ceiling_watch(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    site_map_obj = {
        "map_id": "yard",
        "polygon_m": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
        "bounds_m": {"min_x": -1.0, "min_y": -1.0, "max_x": 1.0, "max_y": 1.0},
        "places": [{"id": "P1", "name": "Stand", "x": 0.0, "y": 0.0, "role": "station"}],
        "sources": [{"camera_id": "cam_ceil", "online": True}],
    }
    api["/api/fleet/site-map"] = {"maps": [site_map_obj]}
    api["/api/fleet/site-map/active"] = {"version": 1, "map": site_map_obj}
    api["/api/fleet/site-map/guide"] = {
        "robots": [
            {"robot_id": "rosy_45", "pose": {"x": 0.65, "y": 0.65, "yaw": 0.0, "state": "LOCALIZED", "source": "sighting"}},
        ],
    }
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1280, 800))
        try:
            expect(page.locator("#map-stage")).to_have_attribute("data-map-state", "site")
            dock = page.locator("#robot-dock-mount")
            dock.locator('.robot-dock-btn[data-robot-id="rosy_45"]').click()
            expect(page.locator("#robot-panel-mount")).to_have_attribute("data-robot-id", "rosy_45")

            page.locator('#map-display-mode input[value="overlay"]').check()
            expect(page.locator("#watch-ceiling")).to_be_hidden()

            box = page.locator("#map-canvas").bounding_box()
            assert box and box["width"] > 100
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)

            bar = page.locator("#map-selection-bar")
            expect(bar).to_be_visible()
            expect(page.locator("#map-sel-name")).to_contain_text("Stand")
            expect(page.locator("#robot-panel-mount")).to_have_attribute("data-robot-id", "rosy_45")

            page.locator("#map-sel-clear").click()
            expect(bar).to_be_visible()
            expect(page.locator("#map-sel-name")).to_contain_text("rosy_45")
            expect(page.locator("#robot-panel-mount")).to_have_attribute("data-robot-id", "rosy_45")

            page.locator("#map-sel-clear").click()
            expect(bar).to_be_hidden()
            assert not errors
        finally:
            browser.close()


def test_overview_list_robots_view_and_twin3d_webgl_fallback(site):
    from playwright.sync_api import expect, sync_playwright

    posts = []
    api = _dock_api()
    api["/api/fleet/charge-bays"]["arm_live_states"]["arm_s"] = {
        "available": True, "online": True, "age_s": 3453.0, "stale": True,
        "torque": None, "current_ma": 42, "temp_c": 31.0, "joints_deg": [0, 0, 0, 0, 0, 0],
    }
    site_map_obj = {
        "map_id": "yard",
        "polygon_m": [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]],
        "bounds_m": {"min_x": -1.0, "min_y": -1.0, "max_x": 1.0, "max_y": 1.0},
        "places": [{"id": "P1", "name": "Stand", "x": 0.0, "y": 0.0, "role": "station"}],
        "sources": [{"camera_id": "cam_ceil", "online": True}],
    }
    api["/api/fleet/site-map"] = {"maps": [site_map_obj]}
    api["/api/fleet/site-map/active"] = {"version": 1, "map": site_map_obj}
    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, api, posts, size=(1440, 900))
        try:
            # 1) Live #robot-overview-list in 로봇·작업 tab lists both Pinky and OMX arms; clicking rosy_45 opens panel.
            overview = page.locator("#robot-overview-list")
            expect(overview).to_be_visible()
            _assert_layout_geometry_desktop_and_390(page)
            for rid in ("rosy_45", "rosy_46", "arm_s", "arm_a", "arm_b"):
                expect(overview.locator(f'.robot-overview-item[data-robot-id="{rid}"]')).to_have_count(1)
            arm_s_text = overview.locator('.robot-overview-item[data-robot-id="arm_s"]').inner_text()
            assert arm_s_text.count("3453초 전") == 1, arm_s_text
            overview.locator('.robot-overview-item[data-robot-id="rosy_45"]').click()
            panel = page.locator("#robot-panel-mount")
            expect(panel).to_be_visible()
            _assert_layout_geometry_desktop_and_390(page)
            expect(panel).to_have_attribute("data-robot-id", "rosy_45")
            expect(panel.locator(".facts dd").first).to_be_visible()
            expect(panel.locator('[data-robot-camera-tile="rosy_45"]')).to_have_count(1)
            expect(panel.locator('[data-step-nudge="forward"]')).to_be_visible()
            install_link = panel.locator('.robot-panel-settings-links a[href="/console/install?robot=rosy_45#install-heading"]')
            expect(install_link).to_contain_text("주소·페어링·네트워크 설정")

            # 2) /console?view=robots shows #robots-overview full-width roster (#robots-overview-grid) and hides map.
            page.goto(site + "/console?view=robots")
            page.clock.run_for(2500)
            expect(page.locator("#robots-overview")).to_be_visible()
            expect(page.locator('[aria-labelledby="map-heading"]')).to_be_hidden()
            grid = page.locator("#robots-overview-grid")
            expect(grid).to_be_visible()
            for rid in ("rosy_45", "rosy_46", "arm_s", "arm_a", "arm_b"):
                expect(grid.locator(f'[data-select-robot-id="{rid}"]')).to_have_count(1)

            # 3) WebGL unavailable in twin3d falls back to overlay with sticky notice across poll ticks and repeat clicks.
            page.add_init_script("""
                const origGetContext = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(type, ...args) {
                    if (typeof type === "string" && type.includes("webgl")) return null;
                    return origGetContext.call(this, type, ...args);
                };
            """)
            page.goto(site + "/console")
            page.clock.run_for(2500)
            expect(page.locator("#map-stage")).to_have_attribute("data-map-state", "site")

            twin_radio = page.locator('#map-display-mode input[value="twin3d"]')
            overlay_radio = page.locator('#map-display-mode input[value="overlay"]')
            status = page.locator("#map-display-status")
            notice = "3D 보기를 열 수 없어 CAD + 실영상으로 전환했습니다"

            twin_radio.check()
            page.wait_for_timeout(100)
            expect(overlay_radio).to_be_checked()
            expect(page.locator("#map-stage")).to_have_attribute("data-display-mode", "overlay")
            expect(page.locator("#map-stage")).to_have_attribute("data-view", "map")
            expect(page.locator("#map-twin-canvas")).to_be_hidden()
            expect(page.locator("#map-canvas")).to_be_visible()
            expect(status).to_have_text(notice)

            # Notice survives 1s polling ticks in overlay mode.
            page.clock.run_for(2500)
            expect(status).to_have_text(notice)

            # Second click on twin3d immediately redirects to overlay without blanking #map-stage.
            twin_radio.click()
            expect(overlay_radio).to_be_checked()
            expect(page.locator("#map-stage")).to_have_attribute("data-view", "map")
            expect(page.locator("#map-twin-canvas")).to_be_hidden()
            expect(page.locator("#map-canvas")).to_be_visible()
            expect(status).to_have_text(notice)
            assert not errors
        finally:
            browser.close()


@pytest.mark.parametrize("size", [(1440, 900), (390, 844)])
def test_robot_commands_live_only_in_the_left_panel(site, size):
    """P3 F3/F2: goal and manual commands exist once (left panel); manual is closed by default; one filled button."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, _dock_api(), [], size=size)
        try:
            page.locator('#robot-dock-mount .robot-dock-btn[data-robot-id="rosy_45"]').click()
            panel = page.locator("#robot-panel-mount")
            expect(panel).to_be_visible()
            manual = panel.locator("details.robot-panel-manual")
            expect(manual).to_have_count(1)
            assert manual.evaluate("node => node.open") is False
            expect(manual.locator("[data-manual-direction]").first).to_be_hidden()
            manual.locator("> summary").click()
            expect(manual.locator("[data-manual-direction]").first).to_be_visible()
            assert page.locator("ui-button[data-goal-robot-id]:visible").count() == 1
            assert panel.locator("ui-button[data-goal-robot-id]:visible").count() == 1
            assert page.locator("[data-manual-direction]").count() == 4
            expect(page.locator("#map-sel-goal, #map-sel-pad, #map-sel-manual-mode")).to_have_count(0)
            filled = page.locator("ui-button[kind=irreversible]:visible").evaluate_all("nodes => nodes.map(n => n.id)")
            assert filled == ["estop"], filled
            expect(page.locator("#robot-panel-stop")).to_have_text("주행 취소 · 이 로봇")
            expect(page.locator("#cancel-all")).to_have_text("전체 주행 취소")
            assert_layout_geometry(page)
            assert not errors
        finally:
            browser.close()
