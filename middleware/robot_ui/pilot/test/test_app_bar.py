"""D-741 3·4 — Pilot 웹 앱 바: 맥락(R 심볼, Pilot, 붙어 있는 로봇 이름), 상태, 운용 지도, 비상 정지 순서.

비상 정지는 CORE `safety/stop`이고 앱 바의 마지막 조작이다. 주행 중 머리가 얇아지는 규칙,
Android 셸의 숨김, 64rem 아래 접속 화면의 격자는 이 조각이 바꾸지 않는다.
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


def test_bar_keeps_its_height_token_and_existing_fold_rules():
    sheet = (PILOT / "styles.css").read_text(encoding="utf-8")
    assert "--appbar-height" not in sheet, "Pilot 머리 높이는 이 조각에서 --topbar-height 그대로다"
    assert "var(--topbar-height)" in sheet
    assert 'html[data-pilot-shell="android"] ui-topbar ui-brand { display: none; }' in sheet
    assert 'html[data-pilot-shell="android"] ui-topbar [data-goto] { display: none; }' in sheet
    assert 'grid-template-areas: "brand brand stop" "state nav stop" "notice notice notice";' in sheet
    assert 'body[data-pilot-screen="connect"] [data-estop] { grid-area: stop; align-self: stretch; }' in sheet
