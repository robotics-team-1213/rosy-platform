"""Fleet 관제 콘솔의 운용 요약 큐 계약 — D-159 승격의 Fleet 쪽 실행 계약.

콘솔 쪽 분류(triage)는 test_triage_contract.py 가 선언적 표로 지킨다. 이
저장소에는 JS 러너가 없으므로 같은 방식을 쓴다: console.js 의 큐 규칙을
소스에서 읽어 단언한다. 표가 곧 규칙이다.

D-159(관리는 예외로)의 Fleet 번역: 정상 로봇은 큐에 없다. 큐는 HITL(최우선
개입)과 성능 저하(주의)만 말하고, 비면 칸 전체가 사라진다 — "이상 없음"을
초록으로 칠하지 않는다(D-82).
"""

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"
CONSOLE = WEB / "console.js"
ROSTER = WEB / "roster.js"
INDEX = WEB / "index.html"


def console_source() -> str:
    # 큐 렌더는 roster.js 팩토리가 가진다. 셸(console.js)은 호출만 남겼다.
    return CONSOLE.read_text(encoding="utf-8") + ROSTER.read_text(encoding="utf-8")


def test_hitl_names_the_robot_and_the_honest_path():
    """HITL 행은 로봇을 이름으로 부르고 갈 곳을 말한다 — 모의 조작이 아니다."""
    source = console_source()
    assert '개입 필요' in source
    # Law 0: 이 서버에 없는 능력(WebRTC 원격 조종)을 버튼으로 걸지 않는다.
    # D-218 회차 적발(F-20): kind=irreversible 모의 버튼이 alert(Mock)을 띄웠다.
    assert "WebRTC" not in source
    assert "Mock" not in source


def test_degraded_capabilities_feed_the_warning_queue():
    source = console_source()
    assert "capabilities_degraded" in source
    assert "성능 저하" in source
    # 브라우저 계약이 실제 DOM 내용을 검증한다. 여기서는 큐 경로의 문구를 고정한다.
    assert ": 성능 저하 [" in source


def test_empty_queues_disappear_by_attribute_not_style():
    """빈 큐는 hidden 속성으로 사라진다 — CSP style-src 'self' 는 style.display 를
    무시하므로 실서버에서 토글이 죽는다(D-201 회차 계측)."""
    source = console_source()
    assert ".queues-panel\").hidden" in source
    assert "queues-panel\").style.display" not in source
    assert "parentElement.hidden" in source


def test_the_queues_panel_heads_the_rail():
    """D-493 — 지도가 왼쪽 열 전체를 쓰고(3 : 2), 예외 큐는 오른쪽 열 맨 위다(D-201 예외가 먼저).
    2026-10-02 회차의 교훈(큐가 지도 아래 963px)은 그대로다: 큐는 지도 밑으로 가지 않는다."""
    styles = (WEB / "styles.css").read_text(encoding="utf-8")
    shell = CONSOLE.read_text(encoding="utf-8")
    assert "main { grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);" in styles
    assert ".console-primary { grid-column: 1; }" in styles
    assert "const layoutPanels = [document.querySelector('.queues-panel')," in shell
    assert "const MAP_PANEL = 2;" in shell


def test_queue_and_roster_attention_share_one_rule():
    """D-493 — 카드에 빨간 표지(릴레이 끊김)가 붙은 로봇이 큐에 없던 회차(2026-10-07)의 회귀 방지."""
    source = ROSTER.read_text(encoding="utf-8")
    assert "function attentionItems(robot)" in source
    assert "return view.stateUnavailable || attentionItems(robot).length > 0;" in source
    assert "for (const item of attentionItems(r))" in source


def test_queue_flags_stale_state_from_the_server_age_plus_receive_time():
    """D-493 — state_age_s 에 받은 뒤 흐른 시간을 더한다. 서버/브라우저 시계 차는 쓰지 않는다."""
    roster = ROSTER.read_text(encoding="utf-8")
    assert "staleAgeS(robot, view.receivedAtMs, Date.now())" in roster
    assert "상태 오래됨 — ${staleS}초 전 값" in roster
    assert "view.receivedAtMs = Date.now();" in CONSOLE.read_text(encoding="utf-8")
    assert "gathered_at" not in roster


def test_both_queues_exist_in_the_markup():
    index = INDEX.read_text(encoding="utf-8")
    assert 'id="warning-list"' in index
    assert 'id="critical-list"' in index
    assert "주의 요망" in index
    assert "최우선 개입" in index
