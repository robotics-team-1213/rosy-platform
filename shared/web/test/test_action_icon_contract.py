"""Fleet chrome icons are actionIcon names, and the stop verb is visible text.

settings stays a separate glyph from tools. Screen-reader-only text stays out of
the visible label. The two Fleet documents share one markup for the stop and
the top-bar icons.
"""

from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui.js"
FLEET = Path(__file__).resolve().parents[3] / "operations" / "fleet" / "fleet" / "server" / "web"

CHROME = ("settings:", '"theme-dark":', '"theme-light":', '"theme-system":', "estop:")


def test_action_icon_names_cover_fleet_chrome_and_keep_screen_reader_text():
    body = UI.read_text(encoding="utf-8").split("export function actionIcon", 1)[1]
    for name in CHROME:
        assert name in body, name
    assert "sr-only" in body
    assert 'tools: "M4 6h16M4 12h16M4 18h16M9 3v6M15 9v6M8 15v6"' in body
    assert 'settings: "M4 7h16M4 12h16M4 17h16M9 5v4M15 10v4M7 15v4"' in body
    for side in ("pose:", "yaw:", "battery:", "safety:"):
        assert side in body, side


def test_fleet_documents_share_the_stop_and_chrome_icons():
    for name in ("index.html", "install.html"):
        page = (FLEET / name).read_text(encoding="utf-8")
        assert 'data-action-icon="estop"' in page
        assert ">비상 정지</span>" in page
        assert "래치 · 로봇별 관리자 해제" in page
        assert 'sr-only">전체 비상 정지' not in page
        for icon in ("settings", "theme-dark", "theme-light", "theme-system", "refresh"):
            assert f'data-action-icon="{icon}"' in page, (name, icon)
        assert 'd="M4 7h16' not in page
