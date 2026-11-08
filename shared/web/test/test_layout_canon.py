"""D-945 — 어느 표면을 열어도 같은 뼈대: 자리 순서, 제목 하나, 표식 어휘 셋."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT / "applications/fleet/web"
ROBOT = ROOT / "middleware/robot_ui/robot"
REVIEW = ROOT / "learning/curation/perception/review_app_web"

AREA_DOCS = ["index.html", "installation/install.html", "sitemap/site-map.html", "cell/cell.html", "work/policy.html", "maintenance/maintenance.html"]
LIGHT_DOCS = ["login.html", "profile.html", "accounts.html", "learning.html"]


def _page(base, name):
    return (base / name).read_text(encoding="utf-8")


def test_fleet_area_documents_keep_the_seat_order_and_one_h1():
    """앱 바 → 레일 → 하위 탐색 → 경로 줄 → 본문. h1은 경로 줄의 문서 제목 하나뿐이다."""
    for name in AREA_DOCS:
        page = _page(WEB, name)
        body = page[page.index("<body"):]
        order = [body.index(marker) for marker in
                 ("<ui-topbar", 'class="doc-tabs ui-rail ui-rail-nav"', 'class="ui-subnav"', 'class="ui-pathbar"', "<main")]
        assert order == sorted(order), f"{name}: seat order"
        assert page.count("<h1") == 1 and '<div class="ui-pathbar"><h1>' in page, f"{name}: one h1, in the path bar"


def test_fleet_light_documents_are_header_then_main_with_one_h1():
    """가벼운 문서는 머리 랜드마크 → 본문. 레일·하위 탐색 자리는 아예 없다(비움은 아래부터)."""
    for name in LIGHT_DOCS:
        page = _page(WEB, name)
        body = page[page.index("<body"):]
        assert body.index("<ui-topbar") < body.index("<main"), name
        assert 'class="fleet-document-header"' in page and page.count("<h1") == 1, name
        assert not re.search(r'class="[^"]*\bdoc-tabs\b', page) and 'class="ui-subnav"' not in page, name


def test_current_markers_use_only_the_three_agreed_words():
    """표식 어휘는 표준 토큰 page·step·true뿐이다(넷째는 탭의 aria-selected).
    page=현 문서·화면, step=같은 문서 안 단계, true=현 화면을 담은 상위 단계(학습 검수의 단계 홀더)."""
    for base, names in ((WEB, AREA_DOCS + LIGHT_DOCS),
                        (REVIEW, [path.name for path in REVIEW.glob("*.html")])):
        for name in names:
            for value in re.findall(r'aria-current="([^"]+)"', _page(base, name)):
                assert value in ("page", "step", "true"), (name, value)


def test_robot_shell_keeps_the_seat_order():
    surface = _page(ROBOT, "surface.html")
    body = surface[surface.index("<body"):]
    order = [body.index(marker) for marker in
             ("<ui-topbar", 'class="ui-rail"', 'class="ui-subnav"', "<main")]
    assert order == sorted(order), "robot shell seat order"


def test_focal_surfaces_keep_topbar_first_main_and_a_skip_link():
    """D-945 — focal 문법(Pilot·경기 보드)은 자리를 아래부터 비우는 게 합법이지만, 건너뛰기와 순서는 지키고
    문서의 h1은 하나다(키오스크 화면은 한 화면 예산을 지키려 sr-only h1). 로봇 대시보드는 두 상태 셸(입장 게이트·연결 후
    공간 콘솔)이 각자 h1 하나를 지닌다 — 공간 문법의 hero-strip이 제목 줄이고 고정 프레임 예산(D-201·test_console_layout)과
    본문 영역 문법(감지·관측·조작, D-741가 아니라 콘솔 고유 계약)은 그대로다."""
    pilot = _page(ROOT / "middleware/robot_ui/pilot", "index.html")
    body = pilot[pilot.index("<body"):]
    assert body.index('class="skip-link"') < body.index("<ui-topbar") < body.index("<main")
    assert pilot.count("<h1") == 1
    games = _page(ROOT / "operations/apps/games/games/web", "index.html")
    gbody = games[games.index("<body"):]
    assert gbody.index("<ui-topbar") < gbody.index("<main") and 'class="skip-link"' in games
    assert games.count("<h1") == 1 and 'class="sr-only"' in games
    dashboard = _page(ROBOT, "index.html")
    dbody = dashboard[dashboard.index("<body"):]
    assert dbody.index("<ui-topbar") < dbody.index("<main") and 'class="skip-link"' in dashboard
    # 두 상태 셸이 각자 h1 하나(게이트: 로봇에 연결 / 공간: 로봇 이름·연결 상태)
    entry_shell = dbody[:dbody.index('id="compatibility-shell"')]
    compat_shell = dbody[dbody.index('id="compatibility-shell"'):]
    assert entry_shell.count("<h1") == 1 and compat_shell.count("<h1") == 1


def test_review_pages_have_one_title_in_their_declared_composition():
    for path in sorted(REVIEW.glob("*.html")):
        page = path.read_text(encoding="utf-8")
        assert page.count("<h1") == 1, path.name
        if path.name == "accounts.html":
            # D-961: anonymous auth uses a focused main; signed-in navigation is restored by the account owner.
            assert 'ui-task-page ui-auth-page' in page
            assert page.index('<main') < page.index('<h1') < page.index('id="account-login"')
            assert 'data-seats="none"' in page and 'class="ui-rail" hidden' in page
            assert 'class="ui-action-link" data-kind="primary" hidden' in page
        else:
            assert re.search(r'<div class="ui-pathbar"><nav class="ui-crumbs" aria-label="현재 위치">'
                             r'<a href="/learning">Learning</a><span aria-hidden="true">/</span></nav>'
                             r'<h1>[^<]+</h1><span class="ui-crumbs" id="learning-tool-path"></span>', page), path.name


def test_robot_operating_surfaces_explain_no_script_and_keep_styles_out_of_markup():
    """스크립트 없이 열린 조작 표면은 물리 정지 경로를 알린다. 표면 CSP는 style-src 'self'라 style 속성은 조용히 무시된다."""
    operating = [WEB / name for name in AREA_DOCS] + [ROOT / "middleware/robot_ui/pilot/index.html", ROBOT / "index.html", ROOT / "operations/apps/games/games/web/index.html"]
    for path in operating:
        assert '<noscript><ui-status state="error">' in path.read_text(encoding="utf-8"), path.name
    for base in (WEB, ROBOT, ROOT / "middleware/robot_ui/pilot", REVIEW, ROOT / "operations/apps/games/games/web"):
        for path in base.rglob("*.html"):
            if "test" not in path.parts:
                assert not re.search(r'<[^>]*\sstyle="', path.read_text(encoding="utf-8")), path
