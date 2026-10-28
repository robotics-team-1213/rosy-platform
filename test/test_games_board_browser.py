"""D-101 노트북 경기 보드의 브라우저 렌더 계약 (옵트인).

ROSY_RUN_BROWSER_TESTS=1 로 실행한다. games.host.preview 의 실제 서버와
games/web 의 실제 자산을 띄워, publish 한 상태가 보드에 그려지는지 단언한다.
D-153 회차2 — 게임 호스트 G2 캡처 수단. CORE `/dashboard` 자산을 전혀 쓰지
않는다(D-101).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from browser_harness import browser_tests_enabled

pytestmark = pytest.mark.skipif(
    not browser_tests_enabled(),
    reason="set ROSY_RUN_BROWSER_TESTS=1 to run the optional Chromium regression",
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "operations" / "apps" / "games"))

from browser_harness import open_page, save_temp_screenshot  # noqa: E402

from games.field import Field, Pose2D  # noqa: E402
from games.game import Observation, Phase  # noqa: E402
from games.game.state import MatchState  # noqa: E402
from games.host.preview import (  # noqa: E402
    PreviewBoard,
    PreviewServer as AccountPreviewServer,
    overlay_payload,
)


class _LayoutAccount:
    """Verified-claims fixture for layout only; security flow is tested below."""
    resource = 'site:layout'
    profile_url = 'https://account.test/console/profile'

    def profile(self, _cookie):
        return None

    def resolve(self, _cookie):
        from types import SimpleNamespace
        return SimpleNamespace(sub='layout-account', sid='family', rev=1, aud='site:one', grants=[], permits=lambda resource, capability:
                               (resource, capability) == (self.resource, 'games.operate'))

    def retry_revocations(self):
        pass


def PreviewServer(board, **kwargs):
    account = _LayoutAccount()
    server = AccountPreviewServer(board, account=account, **kwargs)
    account.callback = server.url.rstrip('/') + '/api/account/callback'
    return server


def test_account_login_scope_stop_and_revocation_in_real_browser(tmp_path):
    """Real HTTPS receiver/cookies/SQLite; only authority transport is a signed fixture."""
    pytest.importorskip('playwright.sync_api')
    import ssl
    import subprocess
    import time
    from functools import partial
    from urllib.parse import parse_qs, urlsplit, urlencode
    from playwright.sync_api import sync_playwright, expect
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    from core_common.protocol.account_access import sign_access
    from core_common.protocol.account_client import AccountClient
    from games.host.preview import _Handler

    cert, key = tmp_path/'cert.pem', tmp_path/'key.pem'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-keyout', str(key), '-out', str(cert), '-days', '1',
                    '-subj', '/CN=localhost'], check=True, capture_output=True)
    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(_play_payload())
    server = AccountPreviewServer(board, port=0)
    origin = server.url.rstrip('/').replace('http:', 'https:')
    issuer = origin.replace('127.0.0.1', 'localhost')
    callback = origin + '/api/account/callback'
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption())
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    clock = [int(time.time())]
    state = {'active': True, 'operate': False, 'challenge': '', 'display_name':'Game Alice'}

    def authority(endpoint, fields):
        if endpoint == 'userinfo':
            return {'account_id':'alice', 'login':'alice', 'display_name':state['display_name']}
        if endpoint == 'introspect':
            return {'active': state['active']}
        if endpoint == 'revoke':
            state['active'] = False
            return {}
        assert endpoint == 'token' and fields['grant_type'] == 'authorization_code'
        import base64
        from hashlib import sha256
        assert base64.urlsafe_b64encode(sha256(fields['code_verifier'].encode()).digest()).rstrip(b'=').decode() == state['challenge']
        assert fields['redirect_uri'] == callback and fields['code'] == 'browser-code'
        access = sign_access({'iss': issuer, 'aud': 'site:games',
            'sub': 'alice', 'sid': 'family', 'jti': 'browser-fixture-123', 'rev': 1,
            'iat': clock[0], 'exp': clock[0] + 300,
            'grants': [{'resource': 'site:games', 'capabilities': ['games.operate' if state['operate'] else 'fleet.read']}]},
            raw, key_id='key')
        return {'access_token': access, 'refresh_token': 'fixture-reusable-token', 'token_type': 'Bearer'}

    account = AccountClient(tmp_path/'account.db', issuer=issuer,
        client_id='games', resource='site:games', callback=callback, public_keys={'key': public},
        encryption_key=Fernet.generate_key(), clock=lambda: clock[0], post=authority)
    server.account = account
    class FixtureHandler(_Handler):
        def do_GET(self):
            request = urlsplit(self.path)
            if request.path == '/api/fleet/auth/authorize':
                query = parse_qs(request.query)
                state['challenge'] = query['code_challenge'][0]
                target = callback + '?' + urlencode({'state': query['state'][0], 'code': 'browser-code'})
                self._send(302, 'text/plain', b'', headers=[('Location', target)])
            else:
                super().do_GET()
    server._httpd.RequestHandlerClass = partial(FixtureHandler, board=board, account=account)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server._httpd.socket = tls.wrap_socket(server._httpd.socket, server_side=True)
    server.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(ignore_https_errors=True)
            navigation_errors = []
            page.on('requestfailed', lambda request: navigation_errors.append((request.url, request.failure)))
            page.goto(origin)
            page.locator('#account-login').wait_for(state='visible')
            assert page.locator('#halt').is_hidden()
            stop = "async () => (await fetch('/stop', {method:'POST'})).status"
            assert page.evaluate(stop) == 403 and not board.stop
            page.locator('#account-login').click()
            page.wait_for_url(origin + '/')
            page.locator('#account-logout').wait_for(state='visible')
            expect(page.locator('[data-account-profile]')).to_contain_text('Game Alice')
            assert page.locator('[data-account-profile]').get_attribute('href') == issuer + '/console/profile'
            assert page.locator('#halt').is_hidden()
            assert page.evaluate(stop) == 403 and not board.stop
            page.locator('#account-logout').click()
            page.locator('#account-login').wait_for(state='visible')
            assert page.locator('[data-account-profile]').is_hidden()
            state.update(active=True, operate=True)
            page.locator('#account-login').click()
            page.locator('#halt').wait_for(state='visible')
            state['display_name'] = 'Updated Player'
            expect(page.locator('[data-account-profile]')).to_contain_text('Updated Player', timeout=15000)
            page.locator('#halt').click()
            page.locator('#halt-status[data-state="sent"]').wait_for()
            assert board.stop
            board.stop = False
            state['active'] = False
            clock[0] += 11
            assert page.evaluate(stop) == 403 and not board.stop
            page.locator('#halt').wait_for(state='hidden', timeout=15000)
            assert page.locator('#account-login').is_visible()
            assert page.locator('[data-account-profile]').is_hidden()
            browser.close()
    finally:
        server.close()


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
                "() => document.getElementById('phase')?.dataset.phase === 'play'"
            )
            page.wait_for_function(
                "() => document.getElementById('home-score')?.textContent === '2'"
            )
            assert page.locator("#phase").inner_text() == "경기 진행"
            assert page.locator("#away-score").inner_text() == "1"
            assert page.locator("#lost").is_hidden()
            assert "필수 마커·공 관측 미완료" in page.locator("#stair1").inner_text()
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
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
            now[0] += 3.0
            page.wait_for_function("() => document.getElementById('connection')?.textContent.includes('마지막 생성 3.0초 전')")
            assert page.locator("#home-score").inner_text() == "2"
            assert "마지막 수신" in page.locator("#connection").inner_text()
            assert page.locator("#phase").inner_text() == "마지막 수신 단계 · 경기 진행"
            assert page.locator("#field-evidence").is_visible()
            assert "현재 위치 아님" in page.locator("#field-evidence").inner_text()
            assert page.locator("#pitch").get_attribute("aria-describedby") == "field-evidence"
            assert page.locator(".score").get_attribute("aria-label") == "마지막 수신 점수"
            assert page.locator("#score-evidence").is_visible()
            announcement = page.locator("#match-announcement")
            page.wait_for_function("() => document.getElementById('match-announcement')?.textContent.includes('지연')")
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
            page.wait_for_function("() => document.getElementById('connection')?.textContent.includes('마지막 생성 3.5초 전')")
            assert "마지막 생성 3.0초 전" in announcement.inner_text()
            assert page.evaluate("window.__announcementChanges") == []
            assert not errors
            save_temp_screenshot(page, "games_board_delayed.png")
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 800), (320, 568)])
def test_legacy_overlay_without_time_evidence_does_not_claim_fresh(width, height):
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
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.route("**/overlay.json", lambda route: route.fulfill(json=legacy))
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.getElementById('connection')?.dataset.evidence === 'unavailable'")
            assert "시각 정보 없음" in page.locator("#connection").inner_text()
            assert "시각 정보 없음" in page.locator("#match-announcement").inner_text()
            assert "호스트 연결됨" not in page.locator("#connection").inner_text()
            if width <= 390:
                panels = [page.locator(selector).bounding_box() for selector in
                          (".score", ".pitch-wrap", ".field-details")]
                assert max(box["width"] for box in panels) - min(box["width"] for box in panels) <= 1
                assert max(box["x"] for box in panels) - min(box["x"] for box in panels) <= 1
                halt = page.locator("#halt").bounding_box()
                assert halt["y"] + halt["height"] <= height
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors
            save_temp_screenshot(page, f"games_board_unavailable_{width}x{height}.png")
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
            browser, page, errors = open_page(playwright, 1280, 800, url=url)
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.getElementById('connection')?.textContent.includes('연결 오류')")
            assert "경기 정보 없음" in page.locator("#connection").inner_text()
            assert "마지막 수신 값" not in page.locator("#match-announcement").inner_text()
            assert page.locator("#home-score").inner_text() == "—"
            assert page.locator("#score-evidence").is_hidden()
            assert page.locator("#field-evidence").inner_text() == "호스트 연결 오류 · 경기장 정보 없음"
            assert page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth && "
                "document.documentElement.scrollHeight <= innerHeight"
            )
            save_temp_screenshot(page, "games_board_first_error.png")
            page.unroute("**/overlay.json")
            board.publish(_play_payload(), jpeg=None)
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
            assert page.locator("#connection").inner_text() == "호스트 연결됨"
            assert page.locator("#field-evidence").is_hidden()
            assert "경기 정보가 없습니다" not in page.locator("#match-announcement").inner_text()
            assert not errors
            browser.close()
    finally:
        server.close()


def _lost_payload(reason="lost_ball") -> dict:
    field = Field(length_m=2.0, width_m=1.4)
    observation = Observation(
        t=0.0,
        ball=None if reason == "lost_ball" else Pose2D(0.1, -0.2, 0.0),
        robots={"rosy_01": Pose2D(-0.4, 0.0, 0.0)},
        lost_ball=reason == "lost_ball",
        lost_robots=frozenset({"rosy_02"}) if reason == "lost_robots" else frozenset(),
        home_goal=None,
        away_goal=None,
    )
    state = MatchState(
        phase=Phase.HOLD,
        score={"rosy_01": 2, "rosy_02": 1},
        reason=reason,
    )
    return overlay_payload(field, observation, state, markers=())


def _launch_board_page(playwright, url):
    browser, page, errors = open_page(playwright, 1280, 800, url=url)
    page.goto(url, wait_until="domcontentloaded")
    return browser, page, errors


def test_chromium_opens_preview_on_a_normally_blocked_port():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    try:
        server = PreviewServer(PreviewBoard(), port=6000)
    except OSError:
        pytest.skip("port 6000 is occupied")
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, 390, 844, url=url)
            page.goto(url, wait_until="domcontentloaded")
            assert page.locator("#phase").is_visible()
            assert not errors
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 844), (320, 568)])
@pytest.mark.parametrize("reason,label", [("lost_ball", "공을 잃음"), ("lost_robots", "로봇을 잃음")])
def test_match_board_shows_lost_hold_state(width, height, reason, label):
    """D-103 유실 HOLD — 공이나 로봇을 잃으면 이유가 보드에 보인다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(_lost_payload(reason), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => document.getElementById('phase')?.dataset.phase === 'hold'"
            )
            assert page.locator("#lost").is_visible()
            assert page.locator("#phase").inner_text() == "경기 보류"
            assert label in page.locator("#lost").inner_text()
            assert reason not in page.locator("#lost").inner_text()
            assert page.locator("#markers li.on").count() == 0
            if width <= 390:
                layout = page.evaluate("""() => ({
                  overflow: document.documentElement.scrollWidth - innerWidth,
                  panels: ['.score', '.pitch-wrap', '.field-details']
                    .map(selector => document.querySelector(selector).getBoundingClientRect().toJSON()),
                  stop: document.querySelector('#halt').getBoundingClientRect().toJSON(),
                })""")
                assert layout["overflow"] <= 0, layout
                assert max(box["x"] for box in layout["panels"]) - min(box["x"] for box in layout["panels"]) <= 1, layout
                assert max(box["width"] for box in layout["panels"]) - min(box["width"] for box in layout["panels"]) <= 1, layout
                assert layout["stop"]["bottom"] <= height and layout["stop"]["right"] <= width, layout
                if height <= 568:
                    # D-741: the stop moved into the sticky top bar; the reason stays below it, in the first view.
                    lost = page.locator("#lost").bounding_box()
                    bar = page.locator("ui-topbar").bounding_box()
                    assert bar["y"] + bar["height"] <= lost["y"] and lost["y"] + lost["height"] <= height, (bar, lost)
            else:
                assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
            assert not errors, f"페이지 오류: {errors}"
            save_temp_screenshot(page, f"games_board_{reason}_{width}x{height}.png")
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 800), (320, 568)])
def test_match_board_initial_state_before_any_publish(width, height):
    """최초 기동 — publish 전 보드는 기본 안내만 보이고 아무 상태도 그리지 않는다."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function(
                "() => document.getElementById('phase')?.textContent === '대기'"
            )
            assert page.locator("#home-score").inner_text() == "—"
            assert page.locator("#connection").inner_text() == "경기 데이터 대기 중"
            assert page.locator("#field-evidence").inner_text() == "경기장 정보 대기 중"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("#lost").is_hidden()
            assert page.locator("#markers li").count() == 0
            if width <= 390:
                panels = [page.locator(selector).bounding_box() for selector in
                          (".score", ".pitch-wrap", ".field-details")]
                assert max(box["width"] for box in panels) - min(box["width"] for box in panels) <= 1
                assert max(box["x"] for box in panels) - min(box["x"] for box in panels) <= 1
                assert page.locator("#halt").bounding_box()["y"] + page.locator("#halt").bounding_box()["height"] <= height
            assert not errors, f"페이지 오류: {errors}"
            save_temp_screenshot(page, f"games_board_initial_{width}x{height}.png")
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
                "() => document.getElementById('phase')?.dataset.phase === 'play'"
            )
            assert page.locator("#frame").is_hidden()
            assert page.locator("#frame").evaluate("el => getComputedStyle(el).display") == "none"
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


# --- D-201 적합 계약, D-741 3·4의 자리 — 정지는 앱 바의 마지막 조작이고 선언 뷰포트(1280×800) 안에 있다.

GAMES_FIT_PROBE = """() => {
  const stop = document.getElementById('halt');
  const halt = stop.getBoundingClientRect();
  const bar = document.querySelector('ui-topbar');
  const box = bar.getBoundingClientRect();
  const controls = [...bar.querySelectorAll('a, button, ui-button, input, select')];
  return {
    docOverflow: document.documentElement.scrollHeight - window.innerHeight,
    halt: { top: Math.round(halt.top), bottom: Math.round(halt.bottom) },
    inBar: stop.closest('ui-topbar') === bar && halt.top >= box.top && halt.bottom <= box.bottom,
    last: controls.at(-1) === stop,
    rightmost: controls.every(node => node.getBoundingClientRect().right <= halt.right + 1),
    label: stop.textContent.trim(),
    note: document.querySelector('.halt-note').getBoundingClientRect().toJSON(),
    barBottom: box.bottom,
    vh: window.innerHeight,
  };
}"""


def test_stop_stays_in_the_top_bar_inside_the_declared_viewport():
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
                "() => document.getElementById('phase')?.dataset.phase === 'play'"
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
        f"정지가 뷰포트 밖이다(D-201): {fit}"
    )
    assert fit["inBar"] and fit["last"] and fit["rightmost"], f"정지는 앱 바의 마지막 조작이다(D-741 3): {fit}"
    assert fit["label"] == "두 로봇 정지", fit
    assert fit["note"]["height"] > 0 and fit["note"]["bottom"] <= fit["barBottom"], f"안내와 결과는 머리 안에 보인다: {fit}"


@pytest.mark.parametrize("medium_width", [600, 480])
def test_match_layout_uses_desktop_width_and_keeps_narrow_status_separate(medium_width):
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
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
            desktop = page.evaluate("""() => {
              const rect = (s) => document.querySelector(s).getBoundingClientRect();
              return {field: rect('#pitch').toJSON(), details: rect('.field-details').toJSON(),
                halt: rect('#halt').toJSON(), scrollWidth: document.documentElement.scrollWidth,
                scrollHeight: document.documentElement.scrollHeight};
            }""")
            assert desktop["field"]["width"] >= 680
            assert desktop["details"]["left"] > desktop["field"]["right"]
            assert desktop["details"]["height"] < desktop["field"]["height"] / 2
            assert desktop["halt"]["bottom"] <= 800
            assert desktop["scrollWidth"] <= 1280 and desktop["scrollHeight"] <= 800

            page.set_viewport_size({"width": 390, "height": 800})
            now[0] += 3.0
            page.wait_for_function("() => document.getElementById('connection')?.dataset.evidence === 'delayed'")
            narrow = page.evaluate("""() => {
              const rect = (s) => document.querySelector(s).getBoundingClientRect();
              return {brand: rect('ui-brand').toJSON(), phase: rect('#phase').toJSON(),
                connection: rect('#connection').toJSON(), scoreEvidence: rect('#score-evidence').toJSON(),
                awayName: rect('#away-name').toJSON(), halt: rect('#halt').toJSON(),
                scrollWidth: document.documentElement.scrollWidth,
                sticky: getComputedStyle(document.querySelector('ui-topbar')).position};
            }""")
            assert narrow["connection"]["top"] >= max(narrow["brand"]["bottom"], narrow["phase"]["bottom"])
            assert narrow["scoreEvidence"]["bottom"] <= narrow["awayName"]["top"]
            assert narrow["scrollWidth"] <= 390
            assert narrow["halt"]["bottom"] <= 800 and narrow["sticky"] == "sticky"
            save_temp_screenshot(page, "games_board_delayed_390x800.png")
            page.set_viewport_size({"width": 320, "height": 568})
            small = page.evaluate("""() => {
              const rect = (s) => document.querySelector(s).getBoundingClientRect();
              return {panels: ['.score', '.pitch-wrap', '.field-details'].map(s => rect(s).toJSON()),
                halt: rect('#halt').toJSON(), scrollWidth: document.documentElement.scrollWidth};
            }""")
            assert max(r["width"] for r in small["panels"]) - min(r["width"] for r in small["panels"]) <= 1
            assert small["scrollWidth"] <= 320 and small["halt"]["bottom"] <= 568
            save_temp_screenshot(page, "games_board_delayed_320x568.png")
            page.set_viewport_size({"width": medium_width, "height": 800})
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(100)
            scrolled = page.evaluate("""() => ({
              halt: document.getElementById('halt').getBoundingClientRect().toJSON(),
              bar: document.querySelector('ui-topbar').getBoundingClientRect().toJSON(),
              stair: document.getElementById('stair1').getBoundingClientRect().toJSON(),
              scrollWidth: document.documentElement.scrollWidth,
            })""")
            assert scrolled["scrollWidth"] <= medium_width
            # D-741: the bar is sticky, so the stop is still at the top after scrolling to the end,
            # and the last line of the page is in view (nothing is parked under a bottom row).
            assert abs(scrolled["bar"]["top"]) <= 1, scrolled
            assert scrolled["halt"]["top"] >= 0 and scrolled["halt"]["bottom"] <= scrolled["bar"]["bottom"], scrolled
            assert scrolled["stair"]["bottom"] <= 800, scrolled
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
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
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
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'hold'")
            assert "공을 잃음" in announcement.inner_text()
            assert len(page.evaluate("window.__announcements")) == 1
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 844), (320, 568)])
def test_stop_failure_is_visible_and_can_be_retried(width, height):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
            calls = []

            def serve_stop(route):
                calls.append(route.request.method)
                if len(calls) == 1:
                    route.fulfill(status=503, json={"error": "unavailable"})
                else:
                    route.fulfill(status=200, json={"ok": True})

            page.route("**/stop", serve_stop)
            page.locator("#halt").click()
            page.wait_for_function("() => document.getElementById('halt-status')?.dataset.state === 'error'")
            assert "다시" in page.locator("#halt-status").inner_text()
            assert page.locator("#halt-status").get_attribute("role") == "status"
            assert page.locator("#halt").get_attribute("aria-disabled") == "false"
            layout = page.evaluate("""() => ({
              overflow: document.documentElement.scrollWidth - innerWidth,
              stop: document.querySelector('#halt').getBoundingClientRect().toJSON(),
              status: document.querySelector('#halt-status').getBoundingClientRect().toJSON(),
            })""")
            assert layout["overflow"] <= 0, layout
            assert layout["stop"]["right"] <= width and layout["stop"]["bottom"] <= height, layout
            assert layout["status"]["right"] <= width and layout["status"]["bottom"] <= height, layout
            if width == 1280:
                assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
            save_temp_screenshot(page, f"games_board_stop_retry_{width}x{height}.png")
            page.locator("#halt").focus()
            page.keyboard.press("Space")
            page.locator('#halt-status[data-state="sent"]').wait_for()
            assert "접수" in page.locator("#halt-status").inner_text()
            assert page.evaluate("document.activeElement?.id") == "halt"
            assert calls == ["POST", "POST"]
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize('width,height', [(1280, 800), (320, 900)])
@pytest.mark.parametrize('stage', ['headers', 'body'])
@pytest.mark.parametrize('prior_match', [False, True])
@pytest.mark.parametrize('mode', ['timeout', 'late'])
def test_hung_overlay_expires_and_recovers_without_stopping_controls(width, height, stage, prior_match, mode):
    import json
    import threading
    from functools import partial
    from playwright.sync_api import sync_playwright, expect
    from games.host.preview import _Handler

    paused, entered, release, first_release = (threading.Event() for _ in range(4))
    class PausedHandler(_Handler):
        def do_GET(self):
            if self.path != '/overlay.json' or not paused.is_set():
                return super().do_GET()
            first = not entered.is_set()
            payload = self.board.snapshot()[0]
            if mode == 'late' and first:
                payload['score'] = {**payload['score'], payload['field']['home_id']: 3}
                self.board.publish(payload, jpeg=None)
            body = json.dumps(self.board.snapshot()[0]).encode()
            entered.set()
            try:
                if stage == 'body':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body[:1]); self.wfile.flush()
                (first_release if mode == 'late' and first else release).wait(12)
                if stage == 'body':
                    self.wfile.write(body[1:])
                else:
                    self._send(200, 'application/json', body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    server._httpd.RequestHandlerClass = partial(PausedHandler, board=board, account=server.account)
    if not prior_match:
        paused.set()
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            try:
                page.goto(url, wait_until='domcontentloaded')
                if prior_match:
                    page.wait_for_function("() => document.querySelector('#connection').dataset.evidence === 'fresh'")
                    paused.set()
                assert entered.wait(5), 'fixture did not receive the paused overlay GET'
                if mode == 'late':
                    assert not release.wait(board.snapshot()[0]['stale_after_s'] + 0.3)
                    first_release.set()
                    page.wait_for_function("() => document.querySelector('#home-score').textContent === '3'")
                    assert page.locator('#connection').get_attribute('data-evidence') == 'delayed'
                    expect(page.locator('#phase')).to_have_text('마지막 수신 단계 · 경기 진행')
                    expect(page.locator('.score')).to_have_attribute('aria-label', '마지막 수신 점수')
                elif prior_match:
                    page.wait_for_function("() => document.querySelector('#connection').dataset.evidence === 'delayed'", timeout=4500)
                    expect(page.locator('#home-score')).to_have_text('2')
                    expect(page.locator('#phase')).to_have_text('마지막 수신 단계 · 경기 진행')
                    expect(page.locator('#field-evidence')).to_contain_text('현재 위치 아님')
                    expect(page.locator('.score')).to_have_attribute('aria-label', '마지막 수신 점수')
                if mode == 'timeout':
                    page.wait_for_function("() => document.querySelector('#connection').dataset.evidence === 'disconnected'", timeout=7500)
                expect(page.locator('#halt')).to_be_enabled()
                expect(page.locator('#halt')).to_be_visible()
                expect(page.locator('#home-score')).to_have_text('3' if mode == 'late' else '2' if prior_match else '—')
                if mode == 'timeout' and not prior_match:
                    expect(page.locator('#connection')).to_contain_text('경기 정보 없음')
                    assert '마지막 수신 값' not in page.locator('#match-announcement').inner_text()
                paused.clear(); release.set(); first_release.set()
                page.wait_for_function("() => document.querySelector('#connection').dataset.evidence === 'fresh'")
                expect(page.locator('#phase')).to_have_text('경기 진행')
                expect(page.locator('#field-evidence')).to_be_hidden()
                expect(page.locator('.score')).to_have_attribute('aria-label', '점수')
                assert not errors, errors
            finally:
                release.set()
                first_release.set()
                browser.close()
    finally:
        release.set()
        first_release.set()
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
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.wait_for_function("() => document.getElementById('connection')?.textContent.includes('연결 오류')")
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
            page.wait_for_function("() => document.getElementById('connection')?.dataset.evidence === 'fresh'")
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


@pytest.mark.parametrize("width,height", [(390, 844), (320, 568)])
def test_compact_board_recovery_keeps_equal_panels_and_stop_visible(width, height):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.querySelector('#connection')?.textContent.includes('연결 오류')")
            assert page.locator("#home-score").inner_text() == "—"
            assert "경기장 정보 없음" in page.locator("#field-evidence").inner_text()

            def check_layout(state):
                layout = page.evaluate("""() => ({
                  overflow: document.documentElement.scrollWidth - innerWidth,
                  panels: ['.score', '.pitch-wrap', '.field-details']
                    .map(selector => document.querySelector(selector).getBoundingClientRect().toJSON()),
                  stop: document.querySelector('#halt').getBoundingClientRect().toJSON(),
                  connection: (() => { const node = document.querySelector('#connection'); return {
                    box: node.getBoundingClientRect().toJSON(),
                    scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
                  }; })(),
                })""")
                assert layout["overflow"] <= 0, (state, layout)
                assert max(box["x"] for box in layout["panels"]) - min(box["x"] for box in layout["panels"]) <= 1, (state, layout)
                assert max(box["width"] for box in layout["panels"]) - min(box["width"] for box in layout["panels"]) <= 1, (state, layout)
                assert layout["stop"]["right"] <= width and layout["stop"]["bottom"] <= height, (state, layout)
                connection = layout["connection"]
                assert connection["box"]["left"] >= 0 and connection["box"]["right"] <= width, (state, connection)
                assert connection["scrollWidth"] <= connection["clientWidth"], (state, connection)
                page.wait_for_timeout(100)
                save_temp_screenshot(page, f"games_board_{state}_{width}x{height}.png")

            check_layout("first_error")
            page.unroute("**/overlay.json")
            board.publish(_play_payload(), jpeg=None)
            page.wait_for_function("() => document.querySelector('#phase')?.dataset.phase === 'play'")
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.wait_for_function("() => document.querySelector('#connection')?.textContent.includes('연결 오류')")
            assert "현재 위치 아님" in page.locator("#field-evidence").inner_text()
            assert page.locator(".score").get_attribute("aria-label") == "마지막 수신 점수"
            check_layout("lost_after_live")
            page.unroute("**/overlay.json")
            board.publish(_play_payload(), jpeg=None)
            page.wait_for_function("() => document.querySelector('#connection')?.dataset.evidence === 'fresh'")
            assert page.locator("#connection").inner_text() == "호스트 연결됨"
            assert page.locator("#field-evidence").is_hidden()
            assert page.locator("#home-score").inner_text() == "2"
            check_layout("recovered")
            assert not errors, errors
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
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
            board.publish({}, jpeg=None)
            page.wait_for_function("() => document.getElementById('connection')?.textContent.includes('마지막 경기 정보')")
            assert page.locator("#home-score").inner_text() == "2"
            assert page.locator("#phase").inner_text() == "마지막 수신 단계 · 경기 진행"
            assert "마지막 수신 값" in page.locator("#match-announcement").inner_text()
            assert not errors, f"페이지 오류: {errors}"
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 844), (320, 568)])
def test_stalled_stop_request_recovers_for_retry(width, height):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    board = PreviewBoard()
    board.publish(_play_payload(), jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.getElementById('phase')?.dataset.phase === 'play'")
            page.evaluate("""() => {
              const original = window.fetch;
              window.fetch = (url, options) => url === '/stop'
                ? new Promise((resolve, reject) => options?.signal?.addEventListener(
                    'abort', () => reject(new DOMException('Aborted', 'AbortError'))))
                : original(url, options);
            }""")
            page.locator("#halt").click()
            page.locator('#halt-status[data-state="pending"]').wait_for()
            assert page.locator("#halt").get_attribute("aria-disabled") == "true"
            for state in ("pending", "timeout"):
                if state == "timeout":
                    page.locator('#halt-status[data-state="error"]').wait_for(timeout=8_000)
                layout = page.evaluate("""() => ({
                  overflow: document.documentElement.scrollWidth - innerWidth,
                  stop: document.querySelector('#halt').getBoundingClientRect().toJSON(),
                  status: document.querySelector('#halt-status').getBoundingClientRect().toJSON(),
                  score: document.querySelector('.score').getBoundingClientRect().toJSON(),
                })""")
                assert layout["overflow"] <= 0, (state, layout)
                assert layout["stop"]["right"] <= width and layout["stop"]["bottom"] <= height, (state, layout)
                assert layout["status"]["right"] <= width and layout["status"]["bottom"] <= height, (state, layout)
                if width <= 390:
                    # D-741: the stop is the right end of the top bar (was a full-width bottom row).
                    assert abs(layout["stop"]["right"] - layout["score"]["right"]) <= 1, (state, layout)
                    assert layout["stop"]["bottom"] <= layout["score"]["top"], (state, layout)
                    assert layout["stop"]["width"] >= 96 and layout["stop"]["height"] >= 44, (state, layout)
                save_temp_screenshot(page, f"games_board_stop_{state}_{width}x{height}.png")
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
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.add_init_script("""(() => {
              const arc = CanvasRenderingContext2D.prototype.arc;
              CanvasRenderingContext2D.prototype.arc = function(x, y, radius, ...rest) {
                window.__ballRadius = radius;
                return arc.call(this, x, y, radius, ...rest);
              };
            })()""")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.querySelectorAll('#markers li').length === 8")
            page.get_by_text('마커 ID 자세히', exact=True).click()
            assert page.locator('#markers li').first.is_visible()
            fit = page.evaluate("""() => ({
              overflow: document.documentElement.scrollWidth - innerWidth,
              topbar: document.querySelector('ui-topbar').getBoundingClientRect().height,
              halt: document.getElementById('halt').getBoundingClientRect().toJSON(),
              panels: ['.score', '.pitch-wrap', '.field-details']
                .map(selector => document.querySelector(selector).getBoundingClientRect().toJSON()),
              ballRadius: window.__ballRadius,
              canvasScale: document.querySelector('#pitch').clientWidth / document.querySelector('#pitch').width,
              chips: [...document.querySelectorAll('#markers li')]
                .filter(li => li.scrollWidth > li.clientWidth).map(li => li.textContent),
              account: (() => { const link = document.querySelector('[data-account-profile]');
                return {...link.getBoundingClientRect().toJSON(), inBar: !!link.closest('ui-topbar'),
                  color: getComputedStyle(link).color}; })(),
              mark: document.querySelector('ui-brand b').getBoundingClientRect().width,
            })""")
            mark_status = page.evaluate("fetch('/common/brand/mark.svg').then(response => response.status)")
            save_temp_screenshot(page, f"games_board_live_{width}x{height}.png")
            browser.close()
    finally:
        server.close()

    assert errors == [], errors
    assert fit["overflow"] <= 0, fit
    assert fit["topbar"] <= 0.2 * height, fit
    halt = fit["halt"]
    assert halt["top"] >= 0 and halt["bottom"] <= height and halt["right"] <= width, fit
    # D-741: the stop is the right end of the top bar (was a full-width bottom row).
    assert abs(halt["right"] - fit["panels"][0]["right"]) <= 1 and halt["bottom"] <= fit["topbar"], fit
    assert halt["right"] - halt["left"] >= 96 and halt["bottom"] - halt["top"] >= 44, fit
    assert max(panel["x"] for panel in fit["panels"]) - min(panel["x"] for panel in fit["panels"]) <= 1, fit
    assert max(panel["width"] for panel in fit["panels"]) - min(panel["width"] for panel in fit["panels"]) <= 1, fit
    assert fit["ballRadius"] * fit["canvasScale"] >= 4.99, fit
    assert fit["chips"] == [], fit
    # D-741 3·5: the R mark stays when the wordmark folds; the account link is in the bar's 나 seat, in the gutter,
    # in the page's ink (it was a default-blue link flush at x=0 under the bar).
    assert mark_status == 200 and fit["mark"] >= 16, (mark_status, fit)
    account = fit["account"]
    assert account["inBar"] and account["width"] > 0 and account["bottom"] <= fit["topbar"], fit
    assert account["left"] >= fit["panels"][0]["x"] - 1 and account["right"] <= fit["panels"][0]["right"] + 1, fit
    assert account["color"] != "rgb(0, 0, 238)", fit
def test_visibility_observations_are_not_operational_approval():
    from playwright.sync_api import sync_playwright, expect
    board = PreviewBoard(clock=lambda: 100.0)
    payload = _play_payload()
    payload.pop('visibility')
    board.publish(payload, jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, 390, 844, url=url)
            page.goto(url)
            expect(page.locator('#phase')).to_have_text('경기 진행')
            expect(page.locator('#stair1')).to_have_text('마커·공 관측 정보 대기 · 운용 승인 아님')
            for ready, word in [(False, '미완료'), (True, '완료')]:
                payload['visibility'] = {'ready': ready, 'ball': ready}
                board.publish(payload, jpeg=None)
                expect(page.locator('#stair1')).to_have_text(f'필수 마커·공 관측 {word} · 운용 승인 아님')
            disclosure = page.get_by_text('마커 ID 자세히', exact=True)
            disclosure.click()
            assert page.locator('#markers li').first.is_visible()
            assert errors == []
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 800), (320, 568)])
def test_board_evidence_matrix_on_declared_widths(width, height):
    """D-153 LOCAL cells; accepted stop requests are not physical SAFE_STOP readback."""
    from playwright.sync_api import sync_playwright

    now = [100.0]
    board = PreviewBoard(clock=lambda: now[0])
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.goto(url, wait_until="domcontentloaded")

            def capture(state):
                boxes = page.evaluate("""() => ({
                  overflow: document.documentElement.scrollWidth - innerWidth,
                  scrollY,
                  panels: ['.score', '.pitch-wrap', '.field-details']
                    .map(s => document.querySelector(s).getBoundingClientRect().toJSON()),
                  stop: document.querySelector('#halt').getBoundingClientRect().toJSON(),
                })""")
                assert boxes["overflow"] <= 0, (state, boxes)
                if state == "fresh":
                    assert boxes["scrollY"] == 0, (state, boxes)
                assert boxes["stop"]["bottom"] <= height and boxes["stop"]["right"] <= width, (state, boxes)
                if width <= 390:
                    assert max(b["width"] for b in boxes["panels"]) - min(b["width"] for b in boxes["panels"]) <= 1, (state, boxes)
                    assert max(b["x"] for b in boxes["panels"]) - min(b["x"] for b in boxes["panels"]) <= 1, (state, boxes)
                save_temp_screenshot(page, f"games_matrix_{state}_{width}x{height}.png")

            page.wait_for_function("() => document.querySelector('#home-score')?.textContent === '—'")
            capture("first_boot")
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.wait_for_function("() => document.querySelector('#connection')?.dataset.evidence === 'disconnected'")
            assert page.locator("#home-score").inner_text() == "—"
            capture("first_error")
            page.unroute("**/overlay.json")
            board.publish(_play_payload(), jpeg=None)
            page.wait_for_function("() => document.querySelector('#connection')?.dataset.evidence === 'fresh'")
            capture("fresh")
            now[0] += 3.0
            page.wait_for_function("() => document.querySelector('#connection')?.dataset.evidence === 'delayed'")
            assert "3.0초 전" in page.locator("#connection").inner_text()
            capture("delayed")
            page.route("**/overlay.json", lambda route: route.fulfill(status=503))
            page.wait_for_function("() => document.querySelector('#connection')?.dataset.evidence === 'disconnected'")
            capture("disconnected")
            page.unroute("**/overlay.json")
            legacy = board.snapshot()[0]
            for key in ("generated_at", "age_s", "stale_after_s", "evidence"):
                legacy.pop(key, None)
            page.route("**/overlay.json", lambda route: route.fulfill(json=legacy))
            page.wait_for_function("() => document.querySelector('#connection')?.dataset.evidence === 'unavailable'")
            capture("unavailable")
            page.route("**/stop", lambda route: route.fulfill(status=200, json={"ok": True}))
            page.locator("#halt").click()
            page.locator('#halt-status[data-state="sent"]').wait_for()
            assert "실제 정지 확인 중" in page.locator("#halt-status").inner_text()
            capture("stop_requested")
            assert not errors, errors
            browser.close()
    finally:
        server.close()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 800), (320, 568)])
def test_board_long_robot_ids_keep_score_columns_inside_viewport(width, height):
    from playwright.sync_api import expect, sync_playwright

    payload = _play_payload()
    home_id = "home_" + "robot" * 24
    away_id = "away_" + "robot" * 12
    payload["field"].update(home_id=home_id, away_id=away_id)
    payload["score"] = {home_id: 2, away_id: 1}
    board = PreviewBoard(clock=lambda: 100.0)
    board.publish(payload, jpeg=None)
    server = PreviewServer(board, port=0)
    url = server.start()
    try:
        with sync_playwright() as playwright:
            browser, page, errors = open_page(playwright, width, height, url=url)
            page.goto(url, wait_until="domcontentloaded")
            expect(page.locator("#home-name")).to_have_text(home_id)
            expect(page.locator("#away-name")).to_have_text(away_id)
            expect(page.locator("#home-score")).to_have_text("2")
            expect(page.locator("#away-score")).to_have_text("1")
            layout = page.evaluate("""() => ({
              overflow: document.documentElement.scrollWidth - innerWidth,
              score: document.querySelector('.score').getBoundingClientRect().toJSON(),
              columns: [...document.querySelectorAll('.score > div')].map(node => ({
                box: node.getBoundingClientRect().toJSON(),
                scrollWidth: node.scrollWidth, clientWidth: node.clientWidth,
              })),
            })""")
            save_temp_screenshot(page, f"games_board_long_ids_{width}x{height}.png")
            assert layout["overflow"] <= 0, layout
            assert layout["score"]["right"] <= width, layout
            home, away = layout["columns"]
            assert abs(home["box"]["width"] - away["box"]["width"]) <= 1, layout
            for column in layout["columns"]:
                assert column["scrollWidth"] <= column["clientWidth"], layout
                assert column["box"]["right"] <= layout["score"]["right"] + 1, layout
            assert not errors, errors
            browser.close()
    finally:
        server.close()
