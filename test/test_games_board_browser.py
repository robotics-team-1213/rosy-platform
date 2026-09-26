"""D-101 노트북 경기 보드의 브라우저 렌더 계약 (옵트인).

ROSY_RUN_BROWSER_TESTS=1 로 실행한다. games.host.preview 의 실제 서버와
games/web 의 실제 자산을 띄워, publish 한 상태가 보드에 그려지는지 단언한다.
D-153 회차2 — 게임 호스트 G2 캡처 수단. CORE `/dashboard` 자산을 전혀 쓰지
않는다(D-101).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ROSY_RUN_BROWSER_TESTS") != "1",
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "site" / "games"))

from browser_harness import open_page, save_temp_screenshot  # noqa: E402

from games.field import Field, Pose2D  # noqa: E402
from games.game import Observation, Phase  # noqa: E402
from games.game.state import MatchState  # noqa: E402
from games.host.preview import (  # noqa: E402
    PreviewBoard,
    PreviewServer,
    overlay_payload,
)


def _play_payload() -> dict:
    field = Field(length_m=2.0, width_m=1.4)
    observation = Observation(
        t=0.0,
        ball=Pose2D(0.1, -0.2, 0.0),
        robots={
            "rosy_01": Pose2D(-0.4, 0.0, 0.0),
            "rosy_02": Pose2D(0.4, 0.0, 3.14),
        },
        lost_ball=False,
        lost_robots=frozenset(),
        home_goal=((-1.0, -0.1), (-1.2, -0.1), (-1.2, 0.1), (-1.0, 0.1)),
        away_goal=None,
    )
    state = MatchState(
        phase=Phase.PLAY, score={"rosy_01": 2, "rosy_02": 1}, reason=""
    )
    return overlay_payload(field, observation, state, markers=(10, 11, 1, 20))


def test_match_board_renders_published_play_state():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function(
                "document.getElementById('phase')?.textContent === 'play'"
            )
            page.wait_for_function(
                "document.getElementById('home-score')?.textContent === '2'"
            )
            assert page.locator("#away-score").inner_text() == "1"
            assert page.locator("#lost").is_hidden()
            assert "아직" in page.locator("#stair1").inner_text()
            assert page.locator("#markers li.on").count() == 4
            assert not errors, f"페이지 오류: {errors}"
            save_temp_screenshot(page, "games_board_play.png")
            browser.close()
    finally:
        server.close()


def _lost_payload() -> dict:
    field = Field(length_m=2.0, width_m=1.4)
    observation = Observation(
        t=0.0,
        ball=None,
        robots={"rosy_01": Pose2D(-0.4, 0.0, 0.0)},
        lost_ball=True,
        lost_robots=frozenset(),
        home_goal=None,
        away_goal=None,
    )
    state = MatchState(
        phase=Phase.HOLD,
        score={"rosy_01": 2, "rosy_02": 1},
        reason="공을 잃음 · HOLD",
    )
    return overlay_payload(field, observation, state, markers=())


def _launch_board_page(playwright, url):
    browser, page, errors = open_page(playwright, 1280, 800)
    page.goto(url, wait_until="domcontentloaded")
    return browser, page, errors


def test_match_board_shows_lost_hold_state():
    """D-103 유실 HOLD — 공을 잃으면 이유와 함께 HOLD가 보드에 보인다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_lost_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function(
                "document.getElementById('phase')?.textContent === 'hold'"
            )
            assert page.locator("#lost").is_visible()
            assert "공을 잃음" in page.locator("#lost").inner_text()
            assert page.locator("#markers li.on").count() == 0
            assert not errors, f"페이지 오류: {errors}"
            save_temp_screenshot(page, "games_board_lost.png")
            browser.close()
    finally:
        server.close()


def test_match_board_initial_state_before_any_publish():
    """최초 기동 — publish 전 보드는 기본 안내만 보이고 아무 상태도 그리지 않는다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function(
                "document.getElementById('phase')?.textContent === '대기'"
            )
            assert page.locator("#home-score").inner_text() == "0"
            assert page.locator("#lost").is_hidden()
            assert page.locator("#markers li").count() == 0
            assert not errors, f"페이지 오류: {errors}"
            save_temp_screenshot(page, "games_board_initial.png")
            browser.close()
    finally:
        server.close()


# --- D-201: 초점 문법의 적합 계약 — 정지 행은 선언 뷰포트(1280×800) 안에 있다.

GAMES_FIT_PROBE = """() => {
  const halt = document.getElementById('halt').getBoundingClientRect();
  return {
    docOverflow: document.documentElement.scrollHeight - window.innerHeight,
    halt: { top: Math.round(halt.top), bottom: Math.round(halt.bottom) },
    vh: window.innerHeight,
  };
}"""


def test_halt_row_stays_inside_the_declared_viewport():
    """정지 버튼이 접힘 아래로 내려가면 스페이스를 알아도 손이 못 쓴다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function(
                "document.getElementById('phase')?.textContent === 'play'"
            )
            page.wait_for_timeout(400)
            fit = page.evaluate(GAMES_FIT_PROBE)
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()

    assert fit["docOverflow"] <= 0, (
        f"보드가 {fit['docOverflow']}px 스크롤된다 — 초점 문법 위반(D-201): {fit}"
    )
    assert fit["halt"]["bottom"] <= fit["vh"] and fit["halt"]["top"] >= 0, (
        f"정지 행이 뷰포트 밖이다(D-201): {fit}"
    )


def test_the_space_bar_promise_is_real():
    """D-224 — "스페이스도 양쪽을 세운다"가 참이어야 한다(Law 0).

    2026-09-25 까지 이 약속은 글자뿐이었다 — board.js 에 키보드 처리가 없어
    힌트가 거짓말을 했다. 몸에 포커스가 있을 때 Space 는 /stop 을 친다.
    """
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function(
                "document.getElementById('phase')?.textContent === 'play'"
            )
            stops: list[str] = []

            def serve_stop(route):
                stops.append(route.request.method)
                route.fulfill(status=200, json={"ok": True})

            page.route("**/stop", serve_stop)
            page.evaluate("document.body.focus(); null")
            page.keyboard.press("Space")
            page.wait_for_timeout(250)
            assert stops == ["POST"], f"스페이스가 /stop 을 치지 않는다: {stops}"
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()
