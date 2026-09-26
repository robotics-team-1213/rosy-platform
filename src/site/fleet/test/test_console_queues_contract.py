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
    # 저하 항목은 붙임 순서로 주의 큐로 간다 — 표기와 코드가 한 블록에 있다.
    assert abs(source.index("성능 저하") - source.index("capabilities_degraded")) < 200


def test_empty_queues_disappear_by_attribute_not_style():
    """빈 큐는 hidden 속성으로 사라진다 — CSP style-src 'self' 는 style.display 를
    무시하므로 실서버에서 토글이 죽는다(D-201 회차 계측)."""
    source = console_source()
    assert ".queues-panel\").hidden" in source
    assert "queues-panel\").style.display" not in source
    assert "parentElement.hidden" in source


def test_the_queues_panel_is_pinned_to_the_left_column():
    """배치는 큐 가시성과 무관하다 — grid 영역이 고정돼 있다(D-201)."""
    styles = (WEB / "styles.css").read_text(encoding="utf-8")
    assert ".queues-panel { grid-column: 1; grid-row: 2; }" in styles


def test_both_queues_exist_in_the_markup():
    index = INDEX.read_text(encoding="utf-8")
    assert 'id="warning-list"' in index
    assert 'id="critical-list"' in index
    assert "주의 요망" in index
    assert "최우선 개입" in index
