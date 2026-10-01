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

    # This case asserts the live label; a slow Chromium launch must not age the fixture.
    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function(
                "document.getElementById('phase')?.dataset.phase === 'play'"
            )
            page.wait_for_function(
                "document.getElementById('home-score')?.textContent === '2'"
            )
            assert page.locator("#phase").inner_text() == "경기 진행"
            assert page.locator("#away-score").inner_text() == "1"
            assert page.locator("#lost").is_hidden()
            assert "아직" in page.locator("#stair1").inner_text()
            assert page.locator("#markers li.on").count() == 4
            assert not errors, f"페이지 오류: {errors}"
            save_temp_screenshot(page, "games_board_play.png")
            browser.close()
    finally:
        server.close()


def test_match_board_names_server_judged_delay():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    now = [100.0]
    board = PreviewBoard(clock=lambda: now[0])
    board.publish(_play_payload())
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            now[0] += 3.0
            page.wait_for_function("document.getElementById('connection')?.textContent.includes('마지막 생성 3.0초 전')")
            assert page.locator("#home-score").inner_text() == "2"
            assert "마지막 수신" in page.locator("#connection").inner_text()
            assert page.locator("#phase").inner_text() == "마지막 수신 단계 · 경기 진행"
            assert page.locator("#field-evidence").is_visible()
            assert "현재 위치 아님" in page.locator("#field-evidence").inner_text()
            assert page.locator("#pitch").get_attribute("aria-describedby") == "field-evidence"
            assert page.locator(".score").get_attribute("aria-label") == "마지막 수신 점수"
            assert page.locator("#score-evidence").is_visible()
            announcement = page.locator("#match-announcement")
            page.wait_for_function("document.getElementById('match-announcement')?.textContent.includes('지연')")
            assert "마지막 수신 단계" in announcement.inner_text()
            assert "마지막 생성 3.0초 전" in announcement.inner_text()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth && "
                "document.documentElement.scrollHeight <= innerHeight"
            )
            page.evaluate("""() => {
              window.__announcementChanges = [];
              new MutationObserver(() => window.__announcementChanges.push(
                document.getElementById('match-announcement').textContent
              )).observe(document.getElementById('match-announcement'), {childList: true});
            }""")
            now[0] += 0.5
            page.wait_for_function("document.getElementById('connection')?.textContent.includes('마지막 생성 3.5초 전')")
            assert "마지막 생성 3.0초 전" in announcement.inner_text()
            assert page.evaluate("window.__announcementChanges") == []
            assert not errors
            save_temp_screenshot(page, "games_board_delayed.png")
            browser.close()
    finally:
        server.close()


def test_legacy_overlay_without_time_evidence_does_not_claim_fresh():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload())
    legacy = board.snapshot()[0]
    for key in ("generated_at", "age_s", "stale_after_s", "evidence"):
        legacy.pop(key, None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, 1280, 800)
            page.route("**/overlay.json", lambda route: route.fulfill(json=legacy))
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("document.getElementById('connection')?.dataset.evidence === 'unavailable'")
            assert "시각 정보 없음" in page.locator("#connection").inner_text()
            assert "시각 정보 없음" in page.locator("#match-announcement").inner_text()
            assert "호스트 연결됨" not in page.locator("#connection").inner_text()
            assert not errors
            browser.close()
    finally:
        server.close()


def test_first_overlay_failure_has_no_last_match_claim():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, 1280, 800)
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("document.getElementById('connection')?.textContent.includes('연결 오류')")
            assert "경기 정보 없음" in page.locator("#connection").inner_text()
            assert "마지막 수신 값" not in page.locator("#match-announcement").inner_text()
            assert page.locator("#home-score").inner_text() == "—"
            assert page.locator("#score-evidence").is_hidden()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth && "
                "document.documentElement.scrollHeight <= innerHeight"
            )
            save_temp_screenshot(page, "games_board_first_error.png")
            page.unroute("**/overlay.json")
            board.publish(_play_payload(), jpeg=None)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            assert page.locator("#connection").inner_text() == "호스트 연결됨"
            assert "경기 정보가 없습니다" not in page.locator("#match-announcement").inner_text()
            assert not errors
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

    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(_lost_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function(
                "document.getElementById('phase')?.dataset.phase === 'hold'"
            )
            assert page.locator("#lost").is_visible()
            assert page.locator("#phase").inner_text() == "경기 보류"
            assert "공을 잃음" in page.locator("#lost").inner_text()
            assert page.locator("#markers li.on").count() == 0
            assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
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
            assert page.locator("#home-score").inner_text() == "—"
            assert page.locator("#connection").inner_text() == "경기 데이터 대기 중"
            assert page.locator("#lost").is_hidden()
            assert page.locator("#markers li").count() == 0
            assert not errors, f"페이지 오류: {errors}"
            save_temp_screenshot(page, "games_board_initial.png")
            browser.close()
    finally:
        server.close()


def test_missing_camera_frame_does_not_render_broken_image_placeholder():
    """An absent optional camera image stays absent even when CSS styles the img."""
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
                "document.getElementById('phase')?.dataset.phase === 'play'"
            )
            assert page.locator("#frame").is_hidden()
            assert page.locator("#frame").evaluate("el => getComputedStyle(el).display") == "none"
            assert not errors, f"페이지 오류: {errors}"
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
                "document.getElementById('phase')?.dataset.phase === 'play'"
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


def test_match_layout_uses_desktop_width_and_keeps_narrow_status_separate():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    now = [100.0]
    board = PreviewBoard(clock=lambda: now[0])
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            desktop = page.evaluate("""() => {
              const rect = (s) => document.querySelector(s).getBoundingClientRect();
              return {field: rect('#pitch').toJSON(), details: rect('.field-details').toJSON(),
                halt: rect('#halt').toJSON(), scrollWidth: document.documentElement.scrollWidth,
                scrollHeight: document.documentElement.scrollHeight};
            }""")
            assert desktop["field"]["width"] >= 680
            assert desktop["details"]["left"] > desktop["field"]["right"]
            assert desktop["halt"]["bottom"] <= 800
            assert desktop["scrollWidth"] <= 1280 and desktop["scrollHeight"] <= 800

            page.set_viewport_size({"width": 390, "height": 800})
            now[0] += 3.0
            page.wait_for_function("document.getElementById('connection')?.dataset.evidence === 'delayed'")
            narrow = page.evaluate("""() => {
              const rect = (s) => document.querySelector(s).getBoundingClientRect();
              return {brand: rect('ui-brand').toJSON(), phase: rect('#phase').toJSON(),
                connection: rect('#connection').toJSON(), scoreEvidence: rect('#score-evidence').toJSON(),
                awayName: rect('#away-name').toJSON(), halt: rect('#halt').toJSON(),
                scrollWidth: document.documentElement.scrollWidth,
                sticky: getComputedStyle(document.querySelector('.halt-row')).position};
            }""")
            assert narrow["connection"]["top"] >= max(narrow["brand"]["bottom"], narrow["phase"]["bottom"])
            assert narrow["scoreEvidence"]["bottom"] <= narrow["awayName"]["top"]
            assert narrow["scrollWidth"] <= 390
            assert narrow["halt"]["bottom"] <= 800 and narrow["sticky"] == "sticky"
            page.set_viewport_size({"width": 600, "height": 800})
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(100)
            scrolled = page.evaluate("""() => ({
              halt: document.getElementById('halt').getBoundingClientRect().toJSON(),
              stair: document.getElementById('stair1').getBoundingClientRect().toJSON(),
              scrollWidth: document.documentElement.scrollWidth,
            })""")
            assert scrolled["scrollWidth"] <= 600
            assert scrolled["halt"]["bottom"] >= 780
            assert scrolled["stair"]["bottom"] <= scrolled["halt"]["top"]
            assert not errors
            browser.close()
    finally:
        server.close()


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
                "document.getElementById('phase')?.dataset.phase === 'play'"
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


def test_match_state_is_announced_only_when_it_changes():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    now = [100.0]
    board = PreviewBoard(clock=lambda: now[0])
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            announcement = page.locator("#match-announcement")
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            assert announcement.get_attribute("role") == "status"
            assert "rosy_01 2" in announcement.inner_text()
            assert "rosy_02 1" in announcement.inner_text()
            page.evaluate("""() => {
              window.__announcements = [];
              new MutationObserver(() => window.__announcements.push(
                document.getElementById('match-announcement').textContent
              )).observe(document.getElementById('match-announcement'), {childList: true});
              return null;
            }""")
            page.wait_for_timeout(700)
            assert page.evaluate("window.__announcements") == []
            board.publish(_lost_payload(), jpeg=None)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'hold'")
            assert "공을 잃음" in announcement.inner_text()
            assert len(page.evaluate("window.__announcements")) == 1
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


def test_stop_failure_is_visible_and_can_be_retried():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            calls = []

            def serve_stop(route):
                calls.append(route.request.method)
                if len(calls) == 1:
                    route.fulfill(status=503, json={"error": "unavailable"})
                else:
                    route.fulfill(status=200, json={"ok": True})

            page.route("**/stop", serve_stop)
            page.locator("#halt").click()
            page.wait_for_function("document.getElementById('halt-status')?.dataset.state === 'error'")
            assert "다시" in page.locator("#halt-status").inner_text()
            assert page.locator("#halt-status").get_attribute("role") == "status"
            assert page.locator("#halt").get_attribute("aria-disabled") == "false"
            assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
            save_temp_screenshot(page, "games_board_stop_retry.png")
            page.locator("#halt").focus()
            page.keyboard.press("Space")
            page.wait_for_function("document.getElementById('halt-status')?.dataset.state === 'sent'")
            assert "접수" in page.locator("#halt-status").inner_text()
            assert page.evaluate("document.activeElement?.id") == "halt"
            assert calls == ["POST", "POST"]
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


def test_overlay_failure_marks_last_received_match_as_stale():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.wait_for_function("document.getElementById('connection')?.textContent.includes('연결 오류')")
            assert page.locator("#home-score").inner_text() == "2"
            assert page.locator("#phase").inner_text() == "마지막 수신 단계 · 경기 진행"
            assert page.locator("#field-evidence").is_visible()
            assert "현재 위치 아님" in page.locator("#field-evidence").inner_text()
            assert page.locator("#pitch").get_attribute("aria-describedby") == "field-evidence"
            assert page.locator(".score").get_attribute("aria-label") == "마지막 수신 점수"
            assert page.locator("#score-evidence").is_visible()
            assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
            assert "마지막 수신 값" in page.locator("#match-announcement").inner_text()
            save_temp_screenshot(page, "games_board_host_disconnected.png")
            page.unroute("**/overlay.json")
            board.publish(_play_payload(), jpeg=None)
            page.wait_for_function("document.getElementById('connection')?.dataset.evidence === 'fresh'")
            assert page.locator("#field-evidence").is_hidden()
            assert page.locator("#phase").inner_text() == "경기 진행"
            assert "마지막 수신 단계" not in page.locator("#match-announcement").inner_text()
            assert page.locator("#pitch").get_attribute("aria-describedby") is None
            assert page.locator("#score-evidence").is_hidden()
            assert page.locator(".score").get_attribute("aria-label") == "점수"
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


def test_missing_overlay_after_play_marks_cached_score_as_last_received():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            board.publish({}, jpeg=None)
            page.wait_for_function("document.getElementById('connection')?.textContent.includes('마지막 경기 정보')")
            assert page.locator("#home-score").inner_text() == "2"
            assert page.locator("#phase").inner_text() == "마지막 수신 단계 · 경기 진행"
            assert "마지막 수신 값" in page.locator("#match-announcement").inner_text()
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


def test_stalled_stop_request_recovers_for_retry():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = _launch_board_page(playwright, url)
            page.wait_for_function("document.getElementById('phase')?.dataset.phase === 'play'")
            page.evaluate("""() => {
              const original = window.fetch;
              window.fetch = (url, options) => url === '/stop'
                ? new Promise((resolve, reject) => options?.signal?.addEventListener(
                    'abort', () => reject(new DOMException('Aborted', 'AbortError'))))
                : original(url, options);
            }""")
            page.locator("#halt").click()
            page.wait_for_function(
                "document.getElementById('halt-status')?.dataset.state === 'error'",
                timeout=8_000,
            )
            assert "시간 초과" in page.locator("#halt-status").inner_text()
            assert page.locator("#halt").get_attribute("aria-disabled") == "false"
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_compact_board_keeps_header_budget_stop_and_chips_in_view(width, height):
    """D-359 §6.4·§6.6 — 붙박이 머리 ≤ 창 높이 20%, 정지는 첫 화면에, 마커 칩은 칸 안에.

    변이 증명: components.css `ui-topbar`에 `min-height: 300px`을 넣으면 빨갛다. 칩 검사는
    감시용이다 — US-003의 자간 0 이후 옛 네 칸 격자도 320px에서 넘치지 않는다(2026-09-30 실측)."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelectorAll('#markers li').length === 8")
            fit = page.evaluate("""() => ({
              overflow: document.documentElement.scrollWidth - innerWidth,
              topbar: document.querySelector('ui-topbar').getBoundingClientRect().height,
              halt: document.getElementById('halt').getBoundingClientRect().toJSON(),
              chips: [...document.querySelectorAll('#markers li')]
                .filter(li => li.scrollWidth > li.clientWidth).map(li => li.textContent),
            })""")
            browser.close()
    finally:
        server.close()

    assert errors == [], errors
    assert fit["overflow"] <= 0, fit
    assert fit["topbar"] <= 0.2 * height, fit
    halt = fit["halt"]
    assert halt["top"] >= 0 and halt["bottom"] <= height and halt["right"] <= width, fit
    assert fit["chips"] == [], fit
