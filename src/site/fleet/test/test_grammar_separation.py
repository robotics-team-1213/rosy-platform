"""D-130.1 — L2 문법 분리 게이트(fleet 표면).

문법은 표면이 소유한다(D-72). 이 파일은 콘솔의 공간 문법 관용구가 fleet
시트에 밀반입되지 않는지, fleet 이 참조하는 스타일시트가 자기 것과 단일
토큰 파일(D-129)뿐인지 기계적으로 검사한다. 에이전트 세션이 기존 console
CSS를 복제하는 것 — concept 16 §4가 결함으로 규정한 "Fleet이 콘솔처럼
보이는" 최단 경로 — 를 리뷰가 아니라 여기서 잡는다.

표준 라이브러리만 쓴다.
"""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "fleet" / "server" / "web"

#: 콘솔의 공간 문법(concept 16 §7.1) — 고정 3분할 레일(sense/observe/act).
#: 이 이름들은 콘솔 styles.css 가 소유한다. fleet 이 쓰는 순간 fleet 은
#: 콘솔처럼 보이기 시작한 것이고 그것은 결함이다(D-92, concept 16 §4).
CONSOLE_GRAMMAR = re.compile(r"\.regions?\b|\.region-(sense|observe|act|head)\b")

SHEET = WEB / "styles.css"
PAGE = WEB / "index.html"


def test_the_console_region_grid_does_not_smuggle_into_fleet():
    hits = CONSOLE_GRAMMAR.findall(SHEET.read_text(encoding="utf-8"))
    assert not hits, f"fleet 시트에 콘솔 문법 관용구: {hits}"


def test_fleet_links_only_its_own_sheet_and_the_single_tokens_file():
    """D-129·D-130.1 — 참조할 수 있는 시트는 자기 것과 공용 토큰뿐이다."""
    hrefs = re.findall(r'<link[^>]+href="([^"]+\.css)"', PAGE.read_text(encoding="utf-8"))
    assert hrefs == [
        "/common/tokens.css",
        "/common/components.css",
        "/console/assets/styles.css",
    ], hrefs


def test_no_stylesheet_imports():
    """@import 로 다른 표면의 시트를 가져오면 문법 경계가 조용히 사라진다."""
    body = SHEET.read_text(encoding="utf-8")
    assert "@import" not in body
