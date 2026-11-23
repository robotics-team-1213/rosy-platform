"""Product adoption tests verifying C18/C23/C24 cockpit dock+panel and wrapped actions."""

import copy
import os
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled
from test_console_queue_inline_browser import API, _open, site  # noqa: F401

pytestmark = pytest.mark.skipif(not browser_tests_enabled(), reason="opt-in Chromium scenario")


@pytest.mark.parametrize("width,height", [(1920, 1080), (1366, 768), (390, 844), (320, 568)])
def test_cockpit_dock_and_panel_replace_legacy_robot_selector(site, width, height):
    from playwright.sync_api import expect, sync_playwright

    api = copy.deepcopy(API)
    api["/api/fleet/site-map"] = {
        "maps": [{
            "map_id": "site",
            "polygon_m": [[-1, -1], [1.5, -1], [1.5, 1], [-1, 1]],
            "bounds_m": {"min_x": -1, "min_y": -1, "max_x": 1.5, "max_y": 1},
            "places": [],
        }],
    }
    api["/api/fleet/tracking"] = {
        "lease_s": 10,
        "sources": [{"source_id": "ceiling_north", "status": "OK", "age_ms": 20}],
        "robots": [],
        "unknown": [],
        "anchors": [{
            "target_id": "arm_a",
            "kind": "omx_ai",
            "label": "OMX A",
            "base_x": 0.55,
            "base_y": 0.36,
            "cell_status": "READY",
            "live": True,
        }],
    }

    with sync_playwright() as pw:
        posts = []
        browser, page, errors = _open(pw, site, api, posts, size=(width, height))

        # C23 right-dock + C24 stage & panel mount cleanly; retired legacy selectors stay absent.
        stage = page.locator("#" + "robot-stage")
        dock = page.locator("#" + "robot-dock")
        panel = page.locator("#" + "robot-panel")
        expect(stage).to_be_visible()
        expect(dock).to_be_visible()
        expect(panel).to_be_hidden()

        for retired in (
            "#robot-choice",
            "#focus-robot-choice",
            ".workspace-heading",
            "#robot-workspace-empty",
            "[data-select-robot-id]",
            ".omx-dense-card",
        ):
            assert page.locator(retired).count() == 0, f"retired selector still in DOM: {retired}"
        assert "/api/fleet/pipeline/" not in page.content()

        buttons = dock.locator(".robot-dock-btn")
        assert buttons.count() >= 2
        boxes = buttons.evaluate_all("nodes => nodes.map(n => n.getBoundingClientRect().toJSON())")
        if width >= 1024:
            assert all(b["width"] >= 48 and b["height"] >= 44 for b in boxes)
        else:
            assert all(b["height"] >= 44 and b["width"] >= 44 for b in boxes)

        hud_text = page.locator("#cockpit-hud").inner_text()
        assert "0 STBY" in hud_text and "IDLE" not in hud_text and "0/1 OK" not in hud_text

        # Open a mobile robot from C23 dock -> C24 panel shows workspace card with collapsed manual controls.
        mobile_btn = dock.locator('.robot-dock-btn[data-kind="mobile"]').first
        mobile_id = mobile_btn.get_attribute("data-robot-id")
        mobile_btn.click()
        expect(panel).to_be_visible()
        expect(panel).to_have_attribute("data-robot-id", mobile_id)
        expect(panel.locator(".robot-panel-twin .robot-view")).to_have_count(1)
        expect(panel.locator(".telemetry-chart-plot canvas")).to_have_count(1)
        assert panel.locator(".telemetry-chart-plot").evaluate("node => node.clientWidth >= 180")
        cam_details = panel.locator('details[data-section="camera"]')
        expect(cam_details).to_have_count(1)
        assert cam_details.evaluate("node => node.open") is (height > 800)
        expect(page.locator(f'#robot-workspace article[data-robot-id="{mobile_id}"]')).to_be_visible()
        manual_details = panel.locator('details[data-section="manual"]')
        expect(manual_details).to_have_count(1)
        assert manual_details.evaluate("node => !node.open")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert page.evaluate("() => { const t = document.getElementById('rosy-shared-tooltip'); return !t || t.hidden || getComputedStyle(t).display === 'none' || !t.textContent.trim(); }")
        if width < 1024:
            dock_box = dock.bounding_box()
            panel_box = panel.bounding_box()
            assert dock_box and panel_box
            assert dock_box["y"] + dock_box["height"] <= panel_box["y"] + 1
            if width == 390:
                twin_box = panel.locator(".robot-panel-twin").bounding_box()
                ws_box = panel.locator("#robot-workspace").bounding_box()
                assert twin_box and ws_box
                assert twin_box["y"] < ws_box["y"]
                assert twin_box["y"] + twin_box["height"] <= 844
        if width >= 1024:
            if width < 1520:
                expect(page.locator(".console-context")).to_be_visible()
                expect(page.locator("#cancel-all")).to_be_visible()
                expect(page.locator("#estop")).to_be_visible()
                map_box = page.locator("#map-stage").bounding_box()
                ctx_box = page.locator(".console-context").bounding_box()
                assert map_box and map_box["width"] >= 700
                assert ctx_box and ctx_box["y"] >= map_box["y"] + map_box["height"] - 4
            assert page.evaluate("() => { const s = document.querySelector('#fleet-main > .console-secondary'); return !s || s.scrollWidth <= s.clientWidth + 1; }")
            stamp_ok = page.evaluate("""() => {
              const stamp = document.getElementById('map-camera-stamp');
              const watch = document.getElementById('device-watch');
              const stageEl = document.getElementById('map-stage');
              if (!stamp || !watch || !stageEl) return true;
              const wasHidden = stamp.hidden;
              stamp.hidden = false;
              stamp.textContent = '카메라 12:34:56';
              const sr = stamp.getBoundingClientRect();
              const wr = watch.getBoundingClientRect();
              const st = stageEl.getBoundingClientRect();
              stamp.hidden = wasHidden;
              const overlapWatch = sr.left < wr.right && wr.left < sr.right && sr.top < wr.bottom && wr.top < sr.bottom;
              const inTopBand = sr.top <= st.top + 48;
              return !overlapWatch && inTopBand;
            }""")
            assert stamp_ok
            if width == 1366:
                dock.locator('.robot-dock-btn[data-robot-id="rosy_04"]').click()
                expect(panel).to_have_attribute("data-robot-id", "rosy_04")
                cam_sec = panel.locator('details[data-section="camera"]')
                if not cam_sec.evaluate("n => n.open"):
                    cam_sec.locator("summary").click()
                cam_btn = cam_sec.locator("ui-button")
                expect(cam_btn).to_have_attribute("disabled", "")
                assert "오프라인" in (cam_btn.get_attribute("reason") or "")
                expect(cam_btn.locator("small[data-reason]")).to_be_visible()
                mobile_btn.click()
                expect(panel).to_have_attribute("data-robot-id", mobile_id)
                expect(cam_sec.locator("ui-button")).not_to_have_attribute("disabled", "")
                expect(cam_sec.locator("ui-button small[data-reason]")).to_have_count(0)

        # Switching to observed OMX arm via dock hides mobile jog, marks unverified joints, and collapses empty telemetry plot.
        arm_btn = dock.locator('.robot-dock-btn[data-robot-id="arm_a"]')
        expect(arm_btn).to_be_visible()
        arm_btn.click()
        expect(panel).to_have_attribute("data-robot-id", "arm_a")
        expect(panel).to_have_attribute("data-kind", "arm")
        arm_fig = panel.locator(".robot-panel-twin .robot-view")
        expect(arm_fig).to_have_count(1)
        expect(arm_fig).to_have_attribute("data-pose", "unverified")
        expect(arm_fig.locator(".robot-view-badge")).to_be_visible()
        assert panel.locator(".telemetry-chart-plot").evaluate("n => n.offsetHeight") == 0
        assert panel.locator('details[data-section="manual"]').count() == 0
        expect(panel.locator('a[href="/console/cell"]')).to_have_count(1)

        if output := os.environ.get("ROSY_SHOT_DIR"):
            Path(output).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(output) / f"fleet-cockpit-{width}.png"))

        if width == 1366:
            close_box = panel.locator(".robot-panel-close").bounding_box()
            assert close_box and abs(close_box["height"] - 36) <= 1
        panel.locator(".robot-panel-close").click()
        expect(panel).to_be_hidden()
        expect(panel.locator(".robot-panel-twin .robot-view")).to_have_count(0)
        if width == 1366:
            expect(page.locator(".console-context")).to_be_visible()
            arm_btn.click()
            expect(panel).to_be_visible()
            page.keyboard.press("Escape")
            expect(panel).to_be_hidden()
            expect(arm_btn).to_be_focused()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        assert not posts and not errors
        browser.close()


@pytest.mark.parametrize("width", [320, 390])
def test_long_intervention_action_wraps_and_keeps_confirmation(site, width):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, page, errors = _open(pw, site, API, [], size=(width, 844))
        page.locator("#fleet-inbox").click()
        button = page.locator('[data-decision="BACK_AND_RETRY"]').first
        assert button.inner_text().rstrip().endswith("…")
        button.evaluate("node => node.firstChild.textContent = '뒤쪽 공간을 확인한 뒤 후진하여 다시 시도하기…'")
        assert button.evaluate("node => node.scrollWidth <= node.clientWidth + 1")
        assert not errors
        browser.close()


def test_arm_cell_scope_shows_cell_cockpit_and_zero_drive_404s(site):
    from playwright.sync_api import expect, sync_playwright

    api = copy.deepcopy(API)
    api["/api/fleet/state"] = {
        "fleet": {
            "name": "ARM-CELL",
            "online": 0,
            "total": 0,
            "scope": {
                "role": "cell",
                "drive": False,
                "arms": True,
                "children": False,
                "enrollment": False,
            },
        },
        "ts": 0.0,
        "robots": [],
    }
    api["/api/fleet/control-unit"] = {
        "schema_version": "rosy.control-unit.v1",
        "unit_id": "ARM-CELL",
        "scope": {
            "role": "cell",
            "drive": False,
            "arms": True,
            "children": False,
            "enrollment": False,
        },
        "site": {"name": "ARM-CELL"},
    }
    api["/api/fleet/vision/sources"] = {
        "sources": [
            {"source_id": "omx_overhead", "name": "상단 셀 카메라", "live": True, "fresh": True},
            {"source_id": "omx_wrist_a", "name": "팔 A 손목", "live": True, "fresh": True},
        ]
    }
    api["/api/fleet/vision/lease"] = {"lease_id": "test-lease", "frames": []}
    api["/api/fleet/auth/connection"] = {"mode": "loopback"}
    api["/api/fleet/auth/session"] = {"authenticated": True, "role": "operator", "account_id": "op", "estop": False}
    api["/api/fleet/peers"] = {"peers": []}
    api["/api/fleet/dispatch-control"] = {"paused": False}
    api["/api/fleet/workcell-observations"] = {
        "schema_version": "rosy.workcell-observations.v1",
        "workcells": [{
            "workcell_id": "cell-a",
            "arms": [
                {
                    "arm_id": "arm_a",
                    "source_id": "omx_arm_a",
                    "label": "팔 A",
                    "fresh": True,
                    "source_age_s": 0.2,
                    "positions": {"joint1": 0.1, "joint2": -0.4, "joint3": 0.2, "joint4": 0.0, "joint5": 0.3, "gripper_joint_1": 0.02},
                    "motor_health": {
                        "schema_version": "rosy.motor-health.v1",
                        "status": "ok",
                        "evidence": "fresh",
                        "motors": [{"id": 11, "joint": "joint1", "temperature_c": 41, "pwm_utilization": 0.25, "current_ma": 220, "hardware_error": 0, "warnings": []}],
                    },
                    "incidents": [],
                },
                {
                    "arm_id": "arm_b",
                    "source_id": "omx_arm_b",
                    "label": "팔 B",
                    "fresh": True,
                    "source_age_s": 0.3,
                    "positions": {"joint1": -0.1, "joint2": -0.3, "joint3": 0.1, "joint4": 0.0, "joint5": 0.2, "gripper_joint_1": 0.01},
                    "motor_health": {"schema_version": "rosy.motor-health.v1", "status": "ok", "evidence": "fresh", "motors": []},
                    "incidents": [],
                },
                {
                    "arm_id": "arm_s",
                    "source_id": "omx_arm_s",
                    "label": "보조 팔 S",
                    "fresh": True,
                    "source_age_s": 0.1,
                    "positions": {"joint1": 0.0, "joint2": -0.5, "joint3": 0.3, "joint4": 0.1, "joint5": 0.2, "gripper_joint_1": 0.03},
                    "motor_health": {
                        "schema_version": "rosy.motor-health.v1",
                        "status": "warn",
                        "evidence": "fresh",
                        "motors": [{"id": 12, "joint": "joint2", "temperature_c": 49, "pwm_utilization": 0.65, "current_ma": 480, "hardware_error": 0, "warnings": ["warm"]}],
                    },
                    "incidents": [],
                },
            ],
            "cameras": [
                {"source_id": "omx_overhead", "role": "overhead", "stream": "color", "fresh": True},
                {"source_id": "omx_wrist_a", "role": "wrist", "stream": "color", "arm_id": "arm_a", "fresh": True},
            ],
        }],
    }

    with sync_playwright() as pw:
        posts = []
        browser, page, errors = _open(pw, site, api, posts, size=(1366, 768))
        seen_urls = []
        failed_404 = []
        page.on("request", lambda req: seen_urls.append(req.url))
        page.on("response", lambda res: failed_404.append((res.status, res.url)) if res.status >= 400 and "/api/fleet/" in res.url else None)
        page.reload(wait_until="networkidle")

        stage = page.locator("#" + "cell-cockpit-stage")
        expect(stage).to_be_visible()
        expect(page.locator('section[aria-labelledby="map-heading"]')).to_be_hidden()
        expect(page.locator("#roster-heading")).to_be_hidden()
        expect(page.locator("#site-path")).to_be_hidden()
        for arm_id in ("arm_a", "arm_b", "arm_s"):
            expect(stage.locator(f'.cell-stage-arm[data-arm-id="{arm_id}"]')).to_be_visible()
        expect(stage.locator('.cell-stage-arm[data-arm-id="arm_a"] .cell-stage-joints-grid .cell-stage-joint')).to_have_count(6)
        assert "모터 확인 불가 · 확인 불가" not in stage.locator('.cell-stage-arm[data-arm-id="arm_b"]').inner_text()
        work_link_box = stage.locator('.cell-stage-actions a[href="/console/cell"]').bounding_box()
        assert work_link_box and abs(work_link_box["height"] - 36) <= 1
        hud_text = page.locator("#" + "cockpit-hud").inner_text()
        assert "ARM-CELL" in hud_text

        dock = page.locator("#" + "robot-dock")
        expect(dock).to_be_visible()
        assert dock.locator(".robot-dock-btn").count() == 3

        dock.locator('.robot-dock-btn[data-robot-id="arm_s"]').click()
        panel = page.locator('#robot-panel[data-robot-id="arm_s"]')
        expect(panel).to_be_visible()
        expect(panel.locator('.robot-panel-jumps button[data-jump-section="health"]')).to_have_count(1)
        arm_fig = panel.locator(".robot-panel-twin .robot-view")
        expect(arm_fig).to_be_visible()
        expect(arm_fig).to_have_attribute("data-pose", "live")
        expect(arm_fig.locator(".robot-view-badge")).to_be_hidden()
        assert "Arm S · S3" in panel.inner_text()
        assert "S3 하역 셔틀" in panel.inner_text()
        expect(panel.locator('[data-section="health"] .motor-health-table')).to_be_visible()

        forbidden = (
            "/api/fleet/site-map",
            "/api/fleet/tracking",
            "/api/fleet/charge-bays",
            "/api/fleet/platoon",
            "/api/fleet/station-recovery",
            "/api/fleet/person-requests",
            "/api/fleet/discovery",
        )
        hit_drive = [u for u in seen_urls if any(p in u for p in forbidden)]
        assert not hit_drive, f"drive/discovery APIs hit under ARM-CELL scope: {hit_drive}"
        assert not failed_404, f"4xx/5xx API responses under ARM-CELL scope: {failed_404}"
        assert not posts and not errors
        browser.close()


def test_cockpit_battery_expiry_syncs_hud_and_panel(site):
    from playwright.sync_api import expect, sync_playwright

    api = copy.deepcopy(API)
    with sync_playwright() as pw:
        posts = []
        browser, page, errors = _open(pw, site, api, posts, size=(1366, 768))
        expect(page.locator('#cockpit-hud [data-hud-key="battery"]')).to_contain_text("80%")
        page.locator('#robot-dock .robot-dock-btn[data-kind="mobile"]').first.click()
        panel = page.locator("#" + "robot-panel")
        expect(panel).to_be_visible()
        expect(panel.locator(".telemetry-chart-value")).to_contain_text("80%")

        for robot in api["/api/fleet/state"]["robots"]:
            if robot.get("online"):
                robot["power_health_age_s"] = 10.0

        page.wait_for_function(
            "() => document.querySelector('#cockpit-hud [data-hud-key=\"battery\"] .cockpit-hud-val')?.textContent === '확인 불가'",
            timeout=8000,
        )
        expect(panel.locator(".telemetry-chart-value")).to_contain_text("확인 불가")
        assert panel.locator(".telemetry-chart-plot").evaluate("n => n.offsetHeight") == 0
        assert not posts and not errors
        browser.close()
