"""D-243: the operator screens are static files, not an API module."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_shell_and_modules_are_here():
    for name in ("index.html", "styles.css", "app.js", "client.js", "dom.js",
                 "map.js", "settings.js", "triage.js", "status-summary.js"):
        assert (ROOT / name).is_file(), name


# --- 편대 역할 칸 (D-280 문법: 대형에 속한 로봇만 말한다) --------------------------


def test_the_hero_strip_has_a_formation_cell_that_starts_hidden():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'class="hero-formation" id="hero-formation" hidden' in html
    assert 'id="robot-role"' in html and 'id="robot-formation"' in html


def test_the_formation_cell_hides_when_the_robot_has_no_role():
    # hidden must win over the flex layout, or an empty cell takes map height.
    css = (ROOT / "console-detail.css").read_text(encoding="utf-8")
    assert ".hero-formation[hidden] { display: none; }" in css


def test_the_mode_control_speaks_korean():
    """D-396: 모드 버튼과 히어로가 한국어로 말한다 (운용자의 언어)."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert ">대기</ui-button>" in html
    assert ">수동</ui-button>" in html
    assert ">자율주행</ui-button>" in html
    assert ">IDLE</ui-button>" not in html
    assert ">MANUAL</ui-button>" not in html
    # 히어로 모드 표시가 enumLabel 을 쓰는지 (원본 enum 이 아니라)
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'enumLabel(MODE_LABEL, state.mode)' in js
    assert 'setText("robot-mode", state.mode)' not in js


def test_escape_key_stops_the_robot_immediately():
    """D-396: Escape 키 = 즉시 비상정지 — 확인창 없음, 입력 필드 무시."""
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'event.key !== "Escape"' in js
    assert '"INPUT" || tag === "TEXTAREA"' in js  # 입력 필드 가드
    assert 'estop === true' in js  # 이미 정지 상태면 재발동 안 함
    assert 'safety/stop' in js  # 실제 API 호출
    # Escape 핸들러 블록에 confirm 이 없다 — 위급 순간의 장벽은 위험하다
    start = js.find('event.key !== "Escape"')
    end = js.find("});", start)
    handler = js[start:end] if start >= 0 and end > start else ""
    assert handler, "Escape 핸들러를 찾을 수 없다"
    assert "window.confirm" not in handler, f"Escape 핸들러에 confirm 이 있다: {handler[:200]}"


def test_the_navigation_line_shows_the_goal():
    """D-396: 지도에서 보낸 목표를 내비게이션 줄에 표시한다."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="navigation-goal"' in html
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "rosy:goal" in js  # 지도에서 목표 이벤트를 받는다
    assert "session.lastGoal" in js  # 목표를 기억한다
    assert "PLANNING" in js and "NAVIGATING" in js  # 활성 상태에서만 표시


def test_the_teleop_pad_shows_commanded_speed():
    """D-396: 텔레오퍼레이션 중 명령 속도를 패드 아래 표시한다."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="teleop-speed"' in html
    teleop = (ROOT / "teleop.js").read_text(encoding="utf-8")
    assert "teleop-speed" in teleop
    assert "m/s" in teleop and "rad/s" in teleop


def test_the_connection_banner_alerts_when_disconnected():
    """D-396: 연결 배너 — WebSocket 끊김 시 topbar 아래 전체 폭."""
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert 'id="connection-banner"' in html
    assert "connection-banner" in html
    client = (ROOT / "client.js").read_text(encoding="utf-8")
    assert "connection-banner" in client
    assert 'kind === "online"' in client  # online 일 때만 숨김


def test_the_action_message_fades_after_five_seconds():
    """D-396: 액션 메시지는 5초 후 조용히 사라진다."""
    js = (ROOT / "app.js").read_text(encoding="utf-8")
    assert "announceAction" in js
    assert "data-faded" in js
    assert "5000" in js  # 5초


def test_event_severity_is_colored():
    """D-396: 이벤트 심각도 — critical/error 는 채움, warning 은 색."""
    telemetry = (ROOT / "telemetry.js").read_text(encoding="utf-8")
    assert 'dataset.severity = "crit"' in telemetry
    assert 'dataset.severity = "warn"' in telemetry
    css = (ROOT / "console-detail.css").read_text(encoding="utf-8")
    assert '[data-severity="crit"]' in css
    assert '[data-severity="warn"]' in css


def test_the_state_render_feeds_swarm_to_the_formation_cell():
    shell = (ROOT / "app.js").read_text(encoding="utf-8")
    telemetry = (ROOT / "telemetry.js").read_text(encoding="utf-8")
    assert "renderFormationHero(state.swarm);" in shell
    assert 'role === "leader" || role === "follower"' in telemetry
    assert 'role === "leader" ? "리더" : "팔로워"' in telemetry
    # none (and anything unknown) keeps the cell hidden — no guessed role.
    assert "cell.hidden = !known;" in telemetry


def test_the_identity_line_carries_the_software_version():
    telemetry = (ROOT / "telemetry.js").read_text(encoding="utf-8")
    assert "info.software_version" in telemetry


def test_the_fast_state_render_does_not_clobber_the_identity_line():
    # robot-id is the lineage line; renderRobotInfo (slow cycle) is its one writer.
    # The 10 Hz state render used to overwrite it with the bare robot_id, so the
    # model/version/runtime flashed and vanished every tick (found on the device).
    shell = (ROOT / "app.js").read_text(encoding="utf-8")
    assert 'setText("robot-id"' not in shell


def test_the_shell_has_no_inline_script():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "onclick=" not in html


def test_the_summary_line_builds_no_markup_from_server_text():
    # D-260 5: state, reason, devices and todos come from CORE; they are text only.
    script = (ROOT / "status-summary.js").read_text(encoding="utf-8")
    assert "innerHTML" not in script and "insertAdjacentHTML" not in script
    assert 'import { createStatusSummary } from "./status-summary.js";' in (ROOT / "app.js").read_text(
        encoding="utf-8")
    assert '"/api/v1/host/status-summary"' in (ROOT / "app.js").read_text(encoding="utf-8")


def test_map_interaction_controls_explain_and_enforce_the_operator_boundary():
    script = (ROOT / "panels" / "console" / "map.js").read_text(encoding="utf-8")
    shell = (ROOT / "shell" / "shell.css").read_text(encoding="utf-8")
    shared_controls = (ROOT.parents[2] / "src" / "hmi" / "web_common" / "components.css").read_text(encoding="utf-8")
    assert 'ctx.role === "operator" || ctx.role === "administrator"' in script
    assert 'button.disabled = !enabled' in script
    assert 'button.setAttribute("aria-describedby", clickReason.id)' in script
    assert "위치·주행 목표 설정에는 운용자 권한이 필요합니다." in script
    assert "canGoal: () => ctx.role !== \"viewer\"" in script
    assert 'el("ui-actions", "surface-actions map-layer-actions")' in script
    panel_styles = (ROOT / "panels" / "surface-panels.css").read_text(encoding="utf-8")
    assert ".surface-link[hidden] { display: none; }" in panel_styles
    assert 'ui-button[kind="segment"][aria-pressed="true"]' in shared_controls
    assert "#shell-estop { flex: none; white-space: nowrap; }" in shell
    assert ".surface-actions.map-layer-actions > ui-button { flex: 1;" in shell


def test_every_module_the_shell_imports_is_installed_and_served():
    # A module missing from either list 404s on the robot and the page dies at import.
    import re

    imported = set(re.findall(r'from "\./([a-z-]+\.js)"', (ROOT / "app.js").read_text(encoding="utf-8")))
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8-sig")
    served = (ROOT.parents[2] / "src/runtime/api_web/core_api_web/api/app.py").read_text(encoding="utf-8")
    assert "status-summary.js" in imported
    for name in imported:
        assert f"  {name}" in cmake, name
        assert f'"{name}": "application/javascript"' in served, name
