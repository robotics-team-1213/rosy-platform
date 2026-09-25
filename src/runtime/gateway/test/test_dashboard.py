import re
from types import SimpleNamespace
from pathlib import Path

import pytest

from core_api_web.api.app import create_app


WEB_ROOT = Path(__file__).resolve().parents[3] / "hmi" / "dashboard"


def dashboard_js(*, without: tuple[str, ...] = ()) -> str:
    """Every ES module the dashboard loads, concatenated.

    The dashboard is `app.js` plus the modules it imports. A test that reads
    only `app.js` starts passing or failing for the wrong reason the moment a
    handler moves between modules, so read them all.
    """
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(WEB_ROOT.glob("*.js"))
        if path.name not in without
    )



def assert_storage_rule(bundle: str) -> None:
    """D-193 6: localStorage holds only a paired token, and only when asked to.

    Every other use of localStorage in the dashboard would be a way for a
    non-expiring token to outlive the tab.
    """
    client = (WEB_ROOT / "client.js").read_text(encoding="utf-8")
    others = dashboard_js(without=("client.js",))
    assert "localStorage" not in others
    assert client.count("localStorage.setItem(") == 1
    guarded = client.split("localStorage.setItem(", 1)[0].rsplit("export function rememberToken", 1)[1]
    assert "if (persist && left > 0 && left <= REMEMBER_MAX_MS)" in guarded
    assert "localStorage" in bundle


@pytest.fixture
def dashboard_client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    return TestClient(create_app({}, SimpleNamespace()))


def test_dashboard_shell_is_served_with_accessible_landmarks(dashboard_client):
    response = dashboard_client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'lang="ko"' in response.text
    assert "Rosy OS" in response.text
    assert "<main" in response.text
    assert 'aria-label="Rosy OS 상태"' in response.text
    assert 'data-mode="NAVIGATION" disabled' in response.text
    assert "https://" not in response.text


def test_dashboard_assets_are_local_and_reference_runtime_contract(dashboard_client):
    css = dashboard_client.get("/dashboard/assets/styles.css")
    script = dashboard_client.get("/dashboard/assets/app.js")
    headless = dashboard_client.get("/common/core_ui_logic.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "--signal-danger" in css.text
    assert "prefers-reduced-motion" in css.text

    assert script.status_code == 200
    assert headless.status_code == 200
    assert "export class HeadlessState" in headless.text
    bundle = dashboard_js()
    assert "sessionStorage" in bundle
    assert "runtime_mode" in bundle
    assert_storage_rule(bundle)
    assert "/api/v1/system/runtime" in bundle
    assert "/api/v1/robot/state" in bundle
    assert "/api/v1/safety/stop" in bundle
    assert "/ws/state" in bundle
    assert "modeChangePending" in bundle
    assert "window.confirm" in bundle
    assert "navigation?.goal_navigation" in bundle
    assert "/api/v1/teleop" in bundle
    assert "pointerdown" in bundle
    assert "pointerup" in bundle
    assert "pointercancel" in bundle
    assert "pointerleave" in bundle
    assert "visibilitychange" in bundle
    assert "pagehide" in bundle
    assert "window.addEventListener(\"blur\"" in bundle
    assert "sendTeleop(0, 0, true)" in bundle
    assert "teleopIntervalMs: 100" in bundle


def test_dashboard_requires_local_bench_acknowledgement_for_motion():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'id="bench-safety-confirmed"' in html
    assert 'data-teleop="forward"' in html
    assert 'data-teleop="backward"' in html
    assert 'data-teleop="left"' in html
    assert 'data-teleop="right"' in html
    assert "누르고 있는 동안만" in html


def test_dashboard_motion_fails_to_zero_on_release_and_page_loss():
    script = dashboard_js()

    assert "/api/v1/teleop" in script
    assert "sendTeleop(0, 0, true)" in script
    assert "pointerdown" in script
    assert "pointerup" in script
    assert "pointercancel" in script
    assert "pointerleave" in script
    assert "visibilitychange" in script
    assert "pagehide" in script
    assert 'window.addEventListener("blur"' in script
    assert "teleopIntervalMs: 100" in script
    assert "teleopPending" in script
    assert "teleopAbortController" not in script
    assert "immediateZero" in script


def test_dashboard_exposes_exclusive_ir_and_camera_line_follow_modes():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = dashboard_js()

    for mode in ("OFF", "IR_LINE", "CAMERA_LINE"):
        assert f'data-line-mode="{mode}"' in html
    for element_id in (
        "line-follow-state", "line-follow-source", "line-follow-error",
        "line-follow-confidence", "line-follow-linear", "line-follow-angular",
        "line-follow-reason",
    ):
        assert f'id="{element_id}"' in html
    assert "/api/v1/line-follow" in script
    assert "/api/v1/line-follow/mode" in script
    assert "lineFollowPending" in script


def test_dashboard_exposes_traffic_evidence_and_staged_policy_controls():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = dashboard_js()

    for element_id in (
        "traffic-policy-state", "traffic-policy-reason",
        "traffic-policy-signal", "traffic-policy-stop-distance",
        "traffic-policy-scene", "traffic-policy-revision",
        "traffic-policy-mode", "traffic-approach-distance",
        "traffic-policy-revision-input",
        "traffic-stop-distance", "traffic-stop-dwell",
        "traffic-min-confidence", "traffic-policy-stage",
        "traffic-policy-apply", "traffic-policy-message",
    ):
        assert f'id="{element_id}"' in html
    for colour in ("RED", "YELLOW", "GREEN"):
        assert f'data-simulation-signal="{colour}"' in html
    assert "/api/v1/traffic" in script
    assert "/api/v1/traffic/policy/stage" in script
    assert "/api/v1/traffic/policy/apply" in script
    assert "/api/v1/traffic/simulation/signal" in script
    assert "trafficPolicyPending" in script


def test_dashboard_exposes_authenticated_live_camera_preview():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = dashboard_js()
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "vision-panel", "vision-status", "vision-stage", "vision-frame",
        "vision-empty", "vision-source", "vision-resolution", "vision-age",
        "vision-captured",
    ):
        assert f'id="{element_id}"' in html
    assert 'aria-label="로봇 전방 카메라와 도로 인식 오버레이"' in html
    assert "/api/v1/vision/front/status" in script
    assert "/api/v1/vision/front/frame" in script
    assert "authHeaders()" in script
    assert "URL.createObjectURL" in script
    assert "URL.revokeObjectURL" in script
    assert "visionSequence" in script
    assert "AbortController" in script
    assert "stopVisionPreview" in script
    assert "X-Rosy-Camera-Sequence" in script
    assert ".vision-stage" in css
    assert '.vision-stage[data-state="live"]' in css
    assert '.vision-stage[data-state="stale"]' in css


def test_dashboard_html_cannot_bypass_security_headers_through_assets(dashboard_client):
    response = dashboard_client.get("/dashboard/assets/index.html")

    assert response.status_code == 404

    dashboard = dashboard_client.get("/dashboard")
    assert "frame-ancestors 'none'" in dashboard.headers["content-security-policy"]
    assert "img-src 'self' data: blob:" in dashboard.headers["content-security-policy"]


def test_root_redirects_to_operator_dashboard(dashboard_client):
    response = dashboard_client.get("/", follow_redirects=False)

    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/dashboard"


def test_dashboard_assets_are_their_own_package():
    text = (WEB_ROOT / "package.xml").read_text(encoding="utf-8")
    cmake = (WEB_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "<name>dashboard</name>" in text
    assert "index.html" in cmake and "app.js" in cmake


def test_dashboard_exposes_ros_domain_bandwidth_and_topology_panel():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = dashboard_js()
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "ros-network-panel",
        "ros-domain-id",
        "dds-isolation",
        "dds-rmw",
        "dds-cyclone-apply",
        "ros-node-count",
        "ros-topic-count",
        "network-rx-rate",
        "network-tx-rate",
        "network-sparkline-rx",
        "network-sparkline-tx",
        "ros-graph-map",
        "ros-risk-list",
    ):
        assert f'id="{element_id}"' in html

    assert 'aria-label="ROS 노드와 토픽 연결 지도"' in html
    assert "renderRosNetwork" in script
    assert "renderSparkline" in script
    assert "renderRosGraph" in script
    assert "networkHistory" in script
    assert "runtime.ros" in script
    assert "graph.rmw" in script
    assert "/api/v1/system/dds/cyclone" in script
    assert "createElementNS" in script
    assert "https://" not in script
    assert ".ros-network-panel" in css
    assert ".ros-graph-map" in css


def test_dashboard_draws_occupancy_map_path_and_click_goal():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app = dashboard_js(without=("map.js",))
    mapper = (WEB_ROOT / "map.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "field-map-panel", "map-canvas", "map-status", "map-empty", "map-legend",
    ):
        assert f'id="{element_id}"' in html
    assert 'aria-label="점유 격자 지도"' in html
    assert 'data-map-layer="occupancy"' in html
    assert 'data-map-layer="costmap"' in html
    assert 'data-map-layer="path"' in html
    assert 'data-map-click="pose"' in html
    assert 'data-map-click="goal"' in html
    assert "초기 자세" in html
    assert "/api/v1/localization/initialpose" in mapper
    assert "/api/v1/navigation/goal" in mapper

    assert 'from "./map.js"' in app
    assert "createFieldMap" in app
    assert "putImageData" not in app

    assert "export function createFieldMap" in mapper
    assert "export function GridFrame" not in mapper
    assert "function GridFrame" in mapper
    assert "worldToCell" in mapper
    assert "sampleWorld" in mapper
    assert "/api/v1/map" in mapper
    assert "/api/v1/navigation/path" in mapper
    assert "/api/v1/map/costmap" in mapper
    assert "/api/v1/navigation/goal" in mapper
    assert "putImageData" in mapper
    assert "fitCanvas" in mapper
    assert "ResizeObserver" in mapper
    assert "refreshPath" in mapper
    assert "window.confirm" in mapper
    assert "https://" not in mapper
    assert "localStorage" not in mapper

    assert ".field-map-panel" in css
    assert ".map-stage" in css
    assert "#map-canvas" in css
    assert ".map-legend" in css
    assert ".map-empty" in css


def test_dashboard_serves_map_module(dashboard_client):
    response = dashboard_client.get("/dashboard/assets/map.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "createFieldMap" in response.text


def test_dashboard_assets_send_no_cache_so_field_settings_keep_pace(dashboard_client):
    script = dashboard_client.get("/dashboard/assets/app.js")
    css = dashboard_client.get("/dashboard/assets/styles.css")
    mapper = dashboard_client.get("/dashboard/assets/map.js")
    assert script.status_code == 200
    assert "no-cache" in script.headers["cache-control"]
    assert "no-cache" in css.headers["cache-control"]
    assert "no-cache" in mapper.headers["cache-control"]


def test_dashboard_field_settings_use_click_handlers_not_form_submit():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = dashboard_js()
    settings = html.split('id="field-settings-panel"', 1)[1]
    assert 'type="submit"' not in settings
    assert 'id="waypoint-save"' in settings
    assert 'id="limits-save"' in settings
    assert 'id="dock-register"' in settings
    assert 'id="limits-save" class="primary-button" disabled' in html
    assert 'id="dock-register" class="primary-button" disabled' in html
    assert 'id="identity-save" class="primary-button" disabled' in html
    assert 'id="robot-id-input"' in html
    assert "readonly" in html.split('id="robot-id-input"', 1)[1].split(">", 1)[0]
    assert "JSON.stringify({ robot_name: robotName })" in script
    assert "robot_id: robotId" not in script
    assert 'id="token-add" class="primary-button" disabled' in html
    assert 'id="slam-save"' in settings
    assert '["waypoint-save"]?.addEventListener("click"' in script
    assert '["limits-save"]?.addEventListener("click"' in script
    assert '["dock-register"]?.addEventListener("click"' in script
    assert '["slam-save"]?.addEventListener("click"' in script
    assert "detectRole" in script
    # US-010 / D-193 5: the role comes from whoami, never from an admin-only
    # probe that answers every viewer with a 403.
    assert "/api/v1/auth/whoami" in script
    assert "/api/v1/logs/audit" not in script
    assert "bindFormSave" in script
    assert "const optional" in script
    assert "requiredResults" in script
    assert 'bindFormSave("waypoint-form", "waypoint-save")' in script
    assert "patch_local_config" not in script
    assert "/api/v1/safety/limits" in script
    assert "/api/v1/docking/types" in script
    assert "/api/v1/host/network/apply" in script
    assert "/api/v1/host/network/mode" in script
    assert "/api/v1/host/network/connect" in script
    assert "battery_warning_percent" in script
    assert "fleet_loss_policy" in script
    assert "/api/v1/system/tokens" in script
    assert 'method: "PUT"' in script
    assert "renderTokens" in script
    assert_storage_rule(script)


def test_dashboard_exposes_local_field_settings_not_fleet():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = dashboard_js()
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for element_id in (
        "field-settings-panel",
        "waypoint-form",
        "waypoint-name",
        "waypoint-save",
        "waypoint-list",
        "limits-form",
        "limit-manual-linear",
        "limit-manual-angular",
        "limits-save",
        "fleet-loss-policy",
        "battery-warning",
        "battery-critical",
        "battery-deep",
        "battery-critical-policy",
        "network-apply",
        "network-profile-id",
        "network-ap",
        "network-ap-off",
        "network-ap-on",
        "network-ssid-input",
        "network-psk-input",
        "network-connect",
        "identity-form",
        "robot-id-input",
        "robot-name-input",
        "identity-save",
        "token-form",
        "token-new",
        "token-add",
        "token-list",
        "slam-start",
        "slam-stop",
        "slam-save-form",
        "slam-save",
        "dock-form",
        "dock-id",
        "dock-register",
        "dock-list",
        "dock-undock",
        "dock-cancel",
        "fleet-settings-note",
    ):
        assert f'id="{element_id}"' in html

    assert "onclick=" not in html
    assert "<style" not in html
    assert 'id="dock-register"' in html
    assert 'id="waypoint-save"' in html
    assert 'type="submit"' not in html.split('id="field-settings-panel"')[1]
    assert "FLEET_HOLD" in html
    # Fleet 은 상태 카드(읽기 전용 FLEET_HOLD 칩)까지만 노린다 — 대시보드가 Fleet
    # 조종 통로(swarm goal·fleet 명령 API)가 되지 않는다는 것이 이 파일의 계약이다.
    # fleet-loss-policy 는 Fleet 단절 시 로봇이 스스로 취할 로컬 동작의 현장 설정이다.
    assert "/api/v1/swarm" not in html
    assert "/api/fleet" not in html

    assert "/api/v1/waypoints" in script
    assert "/api/v1/safety/limits" in script
    assert "/api/v1/slam/start" in script
    assert "/api/v1/navigation/home" in script
    assert "/api/v1/docking/docks" in script
    assert "/api/v1/docking/dock" in script
    assert "renderDocks" in script
    assert "renderWaypoints" in script
    assert "window.confirm" in script
    assert "/api/v1/swarm" not in script

    assert ".field-settings-panel" in css
    assert ".waypoint-list" in css
    assert ".settings-card" in css


def test_dashboard_assets_are_compressed_for_the_robot_access_point(dashboard_client):
    """현장 화면은 로봇 AP 위에서 뜬다. 자산이 압축되지 않으면 첫 로드가
    122 KB이고, 압축하면 29 KB다. 별도 런타임 없이 미들웨어로만 얻는다."""
    for asset in ("styles.css", "app.js"):
        response = dashboard_client.get(
            f"/dashboard/assets/{asset}",
            headers={"accept-encoding": "gzip"},
        )

        assert response.status_code == 200
        assert response.headers.get("content-encoding") == "gzip", asset

    page = dashboard_client.get("/dashboard", headers={"accept-encoding": "gzip"})

    assert page.status_code == 200
    assert page.headers.get("content-encoding") == "gzip"


def test_dashboard_drops_ornament_and_stacks_boot_stages():
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for token in ("eyebrow", "ambient-grid", "data-tone"):
        assert token not in html
        assert token not in css
    assert "Georgia" not in css
    assert "--display" not in css
    assert "--shadow" not in css
    assert "FIELD RUNTIME / 01" not in html
    assert html.index('data-step="1"') < html.index('data-step="2"') < html.index('data-step="3"')
    grid = css.split(".host-card-grid", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: 1fr" in grid
    assert "font-variant-numeric: tabular-nums" in css
    meter = css.split(".meter-rail i", 1)[1].split("}", 1)[0]
    assert "var(--paper)" in meter
    assert "var(--status-crit)" not in meter
    assert "var(--signal-danger)" not in meter


def test_dashboard_renders_inventory_states_from_the_server():
    """S6: 목록은 inventory. CAP-001은 게이트만. 이유는 서버가 준다."""
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert 'api("/api/v1/system/inventory")' in app
    assert "renderInventory" in app
    assert "flattenCapabilities" not in app
    assert "node down" not in app
    assert "row.reason" in app
    assert 'row.state !== "not_provided"' in app
    assert 'api("/api/v1/system/capabilities")' in app
    assert "session.capabilities" in app
    assert '[data-state="blocked"]' in css
    assert '[data-state="constrained"]' in css


def test_dashboard_binds_server_evidence_and_gates_stale_motion():
    """S4 / G4: 텔레메트리만 서버 evidence를 싣고, 낡은 pose·velocity는 teleop을 막는다.

    호스트명·시계 같은 정적 텍스트는 대상이 아니다. 클라이언트는 임계값을
    다시 계산하지 않는다.
    """
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    dom = (WEB_ROOT / "dom.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    channels = {
        "pose-x": "pose",
        "pose-y": "pose",
        "pose-yaw": "pose",
        "velocity-linear": "velocity",
        "velocity-angular": "velocity",
        "battery-value": "battery",
        "battery-voltage": "battery",
        "navigation-state": "navigation",
    }
    assert "export const TELEMETRY_CHANNELS" in app
    for element_id, channel in channels.items():
        assert f'"{element_id}": "{channel}"' in app
        assert f'setText("{element_id}"' in app

    assert 'setText("host-name", runtime.hostname);' in app
    assert 'setText("clock"' in app
    assert "motionEvidenceBlocks" in app
    assert "!motionEvidenceBlocks(session.robotState)" in app
    assert 'new HeadlessState(state).evidenceOf(channel)' in app
    assert '!hs.isFresh("pose")' in app
    assert '!hs.isFresh("velocity")' in app
    assert "pose ${pose} · velocity ${velocity}" in app
    assert 'new HeadlessState(session.robotState).isFresh("pose")' in app
    assert "dataset.evidence" in dom
    assert '[data-evidence="delayed"]' in css
    assert '[data-evidence="disconnected"]' in css
    assert '[data-evidence="unavailable"]' in css
    assert "stale_after_s" not in app
    assert "stale_after_s" not in dom
    assert "stale_after_s" not in css


def test_dashboard_hitl_handoff_points_to_existing_teleop_controls():
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert 'id="hitl-escalation"' in html
    assert 'id="teleop-override"' in html
    assert 'elements["teleop-override"]' in app
    assert 'elements["teleop-heading"]' in app


def test_uncompressed_clients_still_get_the_dashboard(dashboard_client):
    """압축은 협상이다. Accept-Encoding이 없으면 원본을 그대로 준다."""
    response = dashboard_client.get(
        "/dashboard/assets/styles.css",
        headers={"accept-encoding": "identity"},
    )

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert "--signal-danger" in response.text


def test_dashboard_login_has_code_and_token_tabs_and_a_whoami_badge():
    """D-193 S3: robot-screen code first, API token second, identity in the header."""
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script = dashboard_js()
    drawer = html.split('id="auth-drawer"', 1)[1].split("</aside>", 1)[0]
    assert drawer.index('id="auth-tab-code"') < drawer.index('id="auth-tab-token"')
    assert 'id="auth-tab-code" class="view-tab" type="button" role="tab" aria-selected="true"' in drawer
    assert 'id="auth-form" role="tabpanel" aria-labelledby="auth-tab-token" hidden' in drawer
    assert 'id="code-input"' in drawer and 'id="code-remember" type="checkbox"' in drawer
    assert 'id="whoami-badge"' in html and 'id="logout"' in html
    assert "/api/v1/auth/pair" in script
    assert "/api/v1/auth/logout" in script
    assert 'LOGIN_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"' in script


def test_dashboard_code_alphabet_matches_the_server():
    from core_api_web.api.v1.auth import ALPHABET, CODE_LENGTH

    client = (WEB_ROOT / "client.js").read_text(encoding="utf-8")
    assert f'LOGIN_CODE_ALPHABET = "{ALPHABET}"' in client
    assert f"LOGIN_CODE_LENGTH = {CODE_LENGTH};" in client


def test_dashboard_never_puts_a_token_in_a_url_or_the_console():
    """D-193 10: WebSocket auth is the first message; tokens never reach a URL or a log."""
    script = dashboard_js()
    assert "?token=" not in script
    assert "encodeURIComponent(session.token)" not in script
    assert 'socket.send(JSON.stringify({ type: "auth", token: session.token }))' in script
    assert re.search(r"console\.(log|info|warn|error|debug)\(", script) is None
    assert "document.cookie" not in script


def test_dashboard_websocket_reconnect_backs_off_and_honours_close_codes():
    script = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    assert "event.code === 4401" in script and "event.code === 4403" in script
    assert "RECONNECT_MAX_MS" in script and "session.reconnectDelayMs * 2" not in script
    assert "Math.min(delay * 2, RECONNECT_MAX_MS)" in script
    # The backoff resets only after a socket delivered state, not on open.
    message = script.split('socket.addEventListener("message"', 1)[1].split("});", 1)[0]
    assert "session.reconnectDelayMs = RECONNECT_MIN_MS" in message
    assert "RECONNECT_STABLE_MS" in message and "const RECONNECT_STABLE_MS = 10000;" in script
    opened = script.split('socket.addEventListener("open"', 1)[1].split("});", 1)[0]
    assert "reconnectDelayMs" not in opened


def test_remember_me_is_capped_at_seven_days_in_the_browser():
    client = (WEB_ROOT / "client.js").read_text(encoding="utf-8")
    assert "REMEMBER_MAX_MS = 7 * 24 * 60 * 60 * 1000;" in client
    guarded = client.split("export function rememberToken", 1)[1].split("localStorage.setItem(", 1)[0]
    assert "left <= REMEMBER_MAX_MS" in guarded
    loader = client.split("function persistedPairedToken", 1)[1].split("\n}\n", 1)[0]
    assert "left <= REMEMBER_MAX_MS" in loader
