"""concept 16 Law 1 / D-72 — 분류 규칙 계약.

색 예산을 경보 둘로 줄여 놓고(D-82) 동시 고장 규칙이 없으면 빨간 것이 셋
생기고 그 작업이 무의미해진다. 그래서 화면은 언제나 하나를 머리에 두고
나머지는 색 없는 맥락으로 내린다.

이 저장소에는 JS 실행 시험 러너가 없다 — `package.json`·jest·vitest가 없고
CI의 `node`는 ROS 노드 프로세스이지 Node.js 스텝이 아니며, 기존 JS 시험은
파일을 텍스트로 읽는다. 그래서 함수를 호출하는 대신 **규칙을 선언적 표로
만들고 그 표를 단언한다.** 표가 곧 규칙이므로 이것이 실제 계약이다.
"""

from pathlib import Path
import re

WEB_ROOT = Path(__file__).parent.parent.parent / "core_api_web" / "core_api_web" / "web"
TRIAGE = WEB_ROOT / "triage.js"
STYLES = WEB_ROOT / "styles.css"

# 심각도가 아니라 운용자가 지금 할 수 있는 일 순서다. 못 고치는 것이 머리를
# 차지하면 화면이 쓸모없어진다.
EXPECTED_ORDER = ["hazard", "blocked", "mission", "accuracy", "observation"]


def triage_source() -> str:
    return TRIAGE.read_text(encoding="utf-8")


def declared_order() -> list[str]:
    block = re.search(r"CATEGORY_ORDER\s*=\s*\[(.*?)\]", triage_source(), re.DOTALL)
    assert block, "triage.js에 CATEGORY_ORDER 표가 없다"
    return re.findall(r'"([a-z]+)"', block.group(1))


def test_the_ordering_table_puts_actionable_faults_first():
    assert declared_order() == EXPECTED_ORDER


def test_every_emitted_fault_maps_to_a_declared_category():
    """표에 없는 범주로 고장을 내보내면 정렬에서 맨 앞으로 튄다.

    `indexOf`가 -1을 돌려주기 때문이다 — 관측 결손이 비상정지를 밀어내는
    조용한 버그가 된다.
    """
    source = triage_source()
    emitted = set(re.findall(r'category:\s*"([a-z]+)"', source))
    emitted |= set(re.findall(r'^\s+[a-z]+:\s*"([a-z]+)",\s*$', source, re.MULTILINE))
    unknown = emitted - set(declared_order())
    assert not unknown, f"CATEGORY_ORDER에 없는 범주를 내보낸다: {sorted(unknown)}"


def test_only_the_headline_may_carry_a_status_colour():
    """맥락 목록이 색을 가지면 머리가 묻힌다 — 규칙 없는 화면으로 되돌아간다."""
    rules = re.findall(r"([^{}]+)\{([^}]*)\}", STYLES.read_text(encoding="utf-8"))
    offenders = []
    for selector, body in rules:
        if "triage-context" not in selector:
            continue
        if "--status-" in body:
            offenders.append(f"{selector.strip()[:60]} -> {body.strip()[:60]}")
    assert not offenders, f"맥락 목록이 status 토큰을 쓴다: {offenders}"


def test_the_headline_is_a_fill_for_hazard_and_blocked():
    """물리적 위험과 이동 차단은 되돌릴 수 없는 것과 같은 범주다(Law 3).

    빨간 글자가 아니라 채운 면이어야 형태로도 갈린다.
    """
    styles = STYLES.read_text(encoding="utf-8")
    rule = re.search(
        r'\.triage\[data-category="hazard"\][^{]*\{([^}]*)\}', styles, re.DOTALL
    )
    assert rule, "hazard 머리 규칙이 없다"
    assert "background: var(--status-crit)" in rule.group(1)


def test_no_fault_means_no_headline_and_no_colour():
    """정상에는 색도 자리도 쓰지 않는다 — '이상 없음'을 초록으로 칠하지 않는다."""
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    assert "node.hidden = !headline;" in app, "고장이 없을 때 머리를 숨기지 않는다"
    assert "status-good" not in app


def test_triage_consumes_only_fields_the_server_already_sends():
    """새 서버 필드를 요구하지 않는다 — S3·S4가 이미 보낸 것만 읽는다."""
    source = triage_source()
    for field in ("safety", "battery_status", "evidence", "navigation", "descriptors"):
        assert field in source, f"triage.js가 {field}를 읽지 않는다"
    assert "fetch(" not in source, "분류는 순수 파생이다 — 스스로 요청하지 않는다"


def test_the_module_is_served_and_imported():
    """allowlist에 없으면 404다. import만으로는 배포되지 않는다."""
    api = (WEB_ROOT.parent / "api" / "app.py").read_text(encoding="utf-8")
    assert '"triage.js": "application/javascript"' in api
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    assert 'from "./triage.js"' in app
    assert app.count("renderTriage()") >= 2, "상태와 inventory 양쪽에서 다시 분류해야 한다"
