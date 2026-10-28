"""Fleet chrome icons are actionIcon names, and the stop verb is visible text.

settings stays a separate glyph from tools. Screen-reader-only text stays out of
the visible label. The two Fleet documents share one markup for the stop and
the top-bar icons.
"""

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui.js"
FLEET = Path(__file__).resolve().parents[3] / 'applications' / 'fleet' / 'web'

CHROME = ("settings:", '"theme-dark":', '"theme-light":', '"theme-system":', "estop:")
SESSION = ("login:", "account:", "logout:")


def test_action_icon_names_cover_fleet_chrome_and_keep_screen_reader_text():
    body = UI.read_text(encoding="utf-8").split("export function actionIcon", 1)[1]
    for name in (*CHROME, *SESSION):
        assert name in body, name
    assert "sr-only" in body
    # One name, one glyph: tools (wrench) and settings (sliders) once differed only by coordinates.
    glyphs = re.findall(r'^\s+"?([\w-]+)"?: "([^"]+)",$', body.split("};", 1)[0], re.M)
    paths = [d for _, d in glyphs]
    assert len(glyphs) > 40 and len(set(paths)) == len(paths), [n for n, d in glyphs if paths.count(d) > 1]
    names = dict(glyphs)
    assert names["tools"] != names["settings"] and names["fit"] != names["box"] != names["expand"]
    for side in ("pose:", "yaw:", "battery:", "safety:"):
        assert side in body, side


def test_fleet_documents_share_the_stop_and_chrome_icons():
    for name in ("index.html", "installation/install.html"):
        page = (FLEET / name).read_text(encoding="utf-8")
        assert 'data-action-icon="estop"' in page
        assert ">비상 정지</span>" in page
        assert "래치 · 로봇별 관리자 해제" in page
        assert 'sr-only">전체 비상 정지' not in page
        for icon in ("notification", "theme-dark", "refresh"):
            assert f'data-action-icon="{icon}"' in page, (name, icon)
        # D-741 3: 로봇 연결 수와 그 아이콘은 관제 문서의 지도 머리에만 있다.
        assert ('data-action-icon="connect"' in page) == (name == "index.html"), name
        assert 'd="M4 7h16' not in page
