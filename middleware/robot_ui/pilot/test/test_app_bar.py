"""D-741 3·4 — Pilot 웹 앱 바: 맥락(R 심볼, Pilot, 붙어 있는 로봇 이름), 상태, 운용 지도, 비상 정지 순서.

비상 정지는 CORE `safety/stop`이고 앱 바의 마지막 조작이다. 주행 중 머리가 얇아지는 규칙,
Android 셸의 숨김, 64rem 아래 접속 화면의 격자는 그대로다. 64rem 이상의 접속 화면만 한 줄 64px다
(D-741 2026-10-14 부기). 화면에서 잰 값은 `test_pilot_browser.py`가 고정한다.
"""

from __future__ import annotations

import re
from pathlib import Path

PILOT = Path(__file__).resolve().parents[1]


def _bar() -> list[str]:
    html = (PILOT / "index.html").read_text(encoding="utf-8")
    bar = re.search(r"<ui-topbar>(.*?)</ui-topbar>", html, re.S)
    assert bar, "index.html 에 ui-topbar 가 없다"
    return [line.strip() for line in bar.group(1).strip().splitlines()]


def test_bar_reads_context_state_map_then_the_always_live_stop():
    assert _bar() == [
        '<ui-brand><a href="/pilot" data-pilot-home aria-label="Rosy Pilot 접속 홈">'
        '<b>Pilot</b><small data-pilot-robot hidden></small></a></ui-brand>',
        "<span data-spacer></span>",
        '<ui-text id="pilot-notice" scale="label" role="status"></ui-text>',
        '<ui-tag data-gate-state aria-label="접속 상태">대기</ui-tag>',
        '<ui-button kind="quiet" type="button" data-goto="/console">운용 지도</ui-button>',
        '<ui-button kind="irreversible" type="button" data-estop data-always-live>비상 정지</ui-button>',
    ]


def test_brand_names_the_robot_this_page_is_attached_to():
    connect = (PILOT / "screens" / "connect.js").read_text(encoding="utf-8")
    assert 'document.querySelector("[data-pilot-robot]")' in connect
    assert "name.textContent = offer.robotId; name.hidden = false;" in connect


def test_connect_bar_is_one_row_from_64rem_and_other_fold_rules_stay():
    sheet = ''.join((PILOT / name).read_text(encoding="utf-8") for name in ('styles.css', 'layout.css'))
    one_row = ('html:not([data-pilot-shell="android"]) body[data-pilot-screen="connect"] ui-topbar '
               "{ align-items: center; min-height: var(--appbar-height); padding-block: var(--space-1); }")
    assert sheet.count("--appbar-height") == 1, "한 줄 높이는 접속 화면 한 규칙만 쓴다(주행·팔·Android 셸은 그대로)"
    wide = sheet[sheet.index("@media (width >= 64rem) {"):sheet.index("@media (width < 64rem) {")]
    assert one_row in wide, "한 줄 규칙은 64rem 이상 블록 안에만 있다"
    assert "var(--topbar-height)" in sheet
    assert 'html[data-pilot-shell="android"] ui-topbar ui-brand { display: none; }' in sheet
    assert 'html[data-pilot-shell="android"] ui-topbar [data-goto] { display: none; }' in sheet
    # Below 64rem the two-row grid stays (D-741 2026-10-14 addendum): the stop spans both rows.
    narrow = sheet[sheet.index("@media (width < 64rem) {"):]
    narrow = narrow[:narrow.index("\n}")]
    assert 'grid-template-areas: "brand brand stop" "state nav stop" "notice notice notice";' in narrow
    assert 'body[data-pilot-screen="connect"] [data-estop] { grid-area: stop; align-self: stretch; }' in narrow
