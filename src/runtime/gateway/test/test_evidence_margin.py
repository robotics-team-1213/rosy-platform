"""D-72 S4 / concept 16 §5 — 낡은 값은 얼마나 낡았는지를 말한다.

판정 자체는 서버가 내린 `evidence` 문자열이 말한다. 화면은 "얼마나"만 더한다 —
지금은 `delayed`라는 사실만 보이고 2.4초인지 20초인지는 보이지 않는다.

임계값(`stale_after_s`)은 읽지 않는다. 피어가 커밋한 게이트
(test_dashboard.py:427-429)가 클라이언트의 접근 자체를 금지하며, 그 경계를 이
세션이 일방적으로 옮기지 않는다.

JS 실행 러너가 없으므로 바인딩이 DOM에 무엇을 노출하는지를 소스로 단언한다.
"""

from pathlib import Path
import re

WEB_ROOT = Path(__file__).resolve().parents[3] / "hmi" / "dashboard"
DOM = WEB_ROOT / "dom.js"
STYLES = WEB_ROOT / "styles.css"


def dom_source() -> str:
    return DOM.read_text(encoding="utf-8")


def test_a_delayed_binding_exposes_its_age():
    source = dom_source()
    assert "dataset.age" in source, "낡은 값에 나이를 노출하지 않는다"


def test_a_fresh_binding_exposes_neither():
    """여유로울 때 시간을 적으면 화면 전체가 시끄러워진다."""
    source = dom_source()
    guard = re.search(
        r'if \(state !== "delayed" && state !== "disconnected"\) \{(.*?)\n  \}',
        source,
        re.DOTALL,
    )
    assert guard, "신선한 값을 빠져나가는 분기가 없다"
    assert "dataset.age" not in guard.group(1)
    # 분기 앞에서 매번 지운다 — 값이 신선해지면 나이가 남아 있으면 안 된다.
    prelude = source.split("if (evidence == null)")[0]
    assert "delete node.dataset.age" in prelude


def test_the_client_does_not_recompute_the_threshold():
    """임계 산술을 화면에 두면 서버와 다른 판정을 내린다(D-72 S4)."""
    source = dom_source()
    assert "CHANNEL_STALE_AFTER" not in source
    # 피어가 커밋한 게이트(test_dashboard.py:427-429)는 클라이언트가 임계값을
    # 읽는 것 자체를 금지한다. 표시와 재계산은 다르지만 그 경계는 그쪽 계약이다.
    assert "stale_after_s" not in source, "클라이언트가 임계값을 읽는다"


def test_the_age_is_visible_not_only_a_tooltip():
    """title만으로는 장갑 낀 손과 2초짜리 시선에 닿지 않는다."""
    styles = STYLES.read_text(encoding="utf-8")
    rule = re.search(
        r'\[data-evidence="delayed"\]\[data-age\]::after\s*\{([^}]*)\}', styles
    )
    assert rule, "낡은 값의 나이를 그리는 규칙이 없다"
    assert "attr(data-age)" in rule.group(1)
