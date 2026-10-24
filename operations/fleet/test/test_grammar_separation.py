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

import pytest

WEB = Path(__file__).resolve().parents[3] / 'applications/fleet/web'

#: 콘솔의 공간 문법(concept 16 §7.1) — 고정 3분할 레일(sense/observe/act).
#: 이 이름들은 콘솔 styles.css 가 소유한다. fleet 이 쓰는 순간 fleet 은
#: 콘솔처럼 보이기 시작한 것이고 그것은 결함이다(D-92, concept 16 §4).
CONSOLE_GRAMMAR = re.compile(r"\.regions?\b|\.region-(sense|observe|act|head)\b")

SHEET = WEB / "shared" / "styles.css"
PAGE = WEB / "index.html"


def test_the_console_region_grid_does_not_smuggle_into_fleet():
    hits = CONSOLE_GRAMMAR.findall(SHEET.read_text(encoding="utf-8"))
    assert not hits, f"fleet 시트에 콘솔 문법 관용구: {hits}"


def test_fleet_links_only_its_own_sheet_and_the_single_tokens_file():
    """D-129·D-130.1 — 참조할 수 있는 시트는 자기 것과 공용 토큰뿐이다."""
    shared_sheets = ["/common/tokens.css", "/common/components.css"]
    page_sheets = {
        # D-501: doc-tabs.css is Fleet's own tab-row sheet, shared by its four documents.
        # D-519: password-login.css is Fleet's own login-form sheet, shared the same way.
        # D-540: fleet-header.css is the one header sheet of the four documents.
        # D-741 6: app-shell.css is the shared seat sheet; Fleet uses its sub-nav seat.
        # Motor health is the shared evidence component, not Robot console layout grammar.
        "index.html": [*shared_sheets, "/common/motor-health.css", "/common/app-shell.css", "/console/assets/styles.css",
                       "/common/component-controls.css", "/console/assets/doc-tabs.css",
                       "/console/assets/assistant.css",
                       "/console/assets/fleet-header.css", "/console/assets/password-login.css",
                       "/console/assets/device-watch.css", "/console/assets/work.css"],
        "installation/install.html": [*shared_sheets, "/common/task-chooser.css",
                         "/console/assets/styles.css", "/console/assets/doc-tabs.css",
                         "/console/assets/fleet-header.css", "/console/assets/password-login.css",
                         "/console/assets/measured-calibration.css"],
    }
    for page_name, expected_sheets in page_sheets.items():
        hrefs = re.findall(r'<link[^>]+href="([^"]+\.css)"',
                           (WEB / page_name).read_text(encoding="utf-8"))
        assert hrefs == expected_sheets, (page_name, hrefs)


def test_no_stylesheet_imports():
    """@import 로 다른 표면의 시트를 가져오면 문법 경계가 조용히 사라진다."""
    body = SHEET.read_text(encoding="utf-8")
    assert "@import" not in body


def test_closed_sheet_list_still_rejects_another_surface(tmp_path, monkeypatch):
    for name in ("index.html", "installation/install.html"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (WEB / name).read_text(encoding="utf-8")
        if name == "index.html":
            text = text.replace("</head>", '<link rel="stylesheet" href="/dashboard/assets/styles.css"></head>')
            assert '/dashboard/assets/styles.css' in text
        target.write_text(text, encoding="utf-8")
    monkeypatch.setitem(globals(), "WEB", tmp_path)
    with pytest.raises(AssertionError):
        test_fleet_links_only_its_own_sheet_and_the_single_tokens_file()
