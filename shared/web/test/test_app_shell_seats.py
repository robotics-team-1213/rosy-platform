"""D-741 — 공용 셸 자리: 토큰, 공용 시트, 등록."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
TOKENS = (WEB / "tokens.css").read_text(encoding="utf-8")
BASE_SCALE = {f"--space-{i}" for i in range(1, 7)}


def _decl(name: str) -> str | None:
    found = re.search(rf"^\s*{re.escape(name)}\s*:\s*([^;]+);", TOKENS, re.MULTILINE)
    return found.group(1).strip() if found else None


def test_seat_dimensions_are_tokens():
    assert _decl("--appbar-height") == "64px"
    assert _decl("--rail-track") == "72px"
    assert _decl("--subnav-track") == "232px"
    assert _decl("--context-track") == "360px"
    assert _decl("--pathbar-height") == "56px"


def test_seat_spacing_roles_reference_the_base_scale():
    for role in ("--inset-rail", "--gap-rail", "--inset-subnav", "--inset-pathbar",
                 "--gap-pathbar", "--inset-pane", "--gap-pane"):
        value = _decl(role)
        assert value, f"{role} 토큰이 없다"
        refs = set(re.findall(r"var\((--[a-z0-9-]+)", value))
        assert refs and refs <= BASE_SCALE, f"{role}은 기본 간격 척도만 참조해야 한다: {value}"


def test_control_line_and_chrome_surface_are_roles():
    assert _decl("--line-50") == "color-mix(in oklab, var(--ink) 50%, transparent)"
    assert _decl("--line-40") is None, "잉크 40%는 밝게 테마에서 2.4:1이라 남기지 않는다"
    assert _decl("--control-line") == "var(--line-50)"
    assert _decl("--surface-chrome") == "var(--ground-raise)"
    assert _decl("--border-default") == "var(--line-14)", "면을 가르는 선은 그대로 둔다"


SHEET = WEB / "app-shell.css"
SEATS = (".ui-app-shell", ".ui-app-body", ".ui-rail", ".ui-rail-nav", ".ui-rail-item",
         ".ui-subnav", ".ui-subnav-nav", ".ui-subnav-head", ".ui-subnav-item",
         ".ui-app-main", ".ui-pathbar", ".ui-crumbs", ".ui-stage-grid", ".ui-pane")


def test_sheet_is_served_and_installed():
    assets = json.loads((WEB / "shared-assets.json").read_text(encoding="utf-8"))["shared_assets"]
    assert assets.get("app-shell.css") == "text/css"
    assert "\n  app-shell.css\n" in (WEB / "CMakeLists.txt").read_text(encoding="utf-8")


def test_sheet_defines_every_seat():
    css = SHEET.read_text(encoding="utf-8")
    for seat in SEATS:
        assert re.search(rf"(?m)^{re.escape(seat)}\b", css), f"{seat} 자리가 없다"
    for pane in ("stage", "now", "more", "sense", "cam"):
        assert f'[data-pane="{pane}"] {{ grid-area: {pane}; }}' in css


def test_sheet_answers_its_container_not_the_viewport():
    css = SHEET.read_text(encoding="utf-8")
    assert "@media" not in css, "공용 자리는 칸에 반응한다(D-359 §6.3)"
    conditions = set(re.findall(r"@container \(([^)]+)\)", css))
    assert conditions == {"width < 64rem", "width < 48rem"}
    assert css.count("container-type: inline-size") == 2, "셸과 본문 둘만 칸이다"


def test_sheet_takes_sizes_and_paint_from_tokens():
    css = SHEET.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(", css), "원시 색을 쓰지 않는다"
    assert not re.search(r"var\(--space-", css), "간격은 역할 토큰으로 쓴다(D-292)"
    assert not re.search(r"font-size:\s*\d", css), "글자 크기는 토큰이다"
    for token in ("--rail-track", "--subnav-track", "--context-track", "--pathbar-height",
                  "--surface-chrome", "--inset-pane", "--gap-pane"):
        assert f"var({token})" in css, f"{token}을 쓰지 않는다"


def test_seats_with_padding_keep_their_token_size():
    css = SHEET.read_text(encoding="utf-8")
    rule = re.search(r"(?m)^([^{}]+)\{ box-sizing: border-box; \}$", css)
    assert rule, "자리의 높이 토큰은 여백을 포함한 값이다"
    for seat in (".ui-rail-item", ".ui-subnav-item", ".ui-pathbar", ".ui-pane"):
        assert seat in rule.group(1), f"{seat}에 box-sizing이 없다"


def test_collapsed_seats_do_not_stretch_or_overflow():
    css = SHEET.read_text(encoding="utf-8")
    medium = css.split("@container (width < 64rem) {", 1)[1].split("@container", 1)[0]
    compact = css.split("@container (width < 48rem) {", 1)[1]
    assert "flex-direction: column" in medium, "접힌 셸은 탐색 줄이 남는 높이를 나눠 갖지 않는다"
    assert ".ui-rail-nav { flex-direction: row; overflow-x: auto; }" in medium
    assert "align-content: start" in compact, "쌓인 본문 격자는 빈 칸을 늘리지 않는다"


def test_review_documents_share_the_app_bar_and_the_screen_rail():
    """D-741 3, 6, D-833 and D-857 §3: app/theme in the bar, the five loop stages in the rail, the stage's
    pages in the sub-menu, heading in the path row."""
    web = WEB.parents[1] / 'learning/curation/perception/review_app_web'
    stages = [('list', '/learning', '홈', '홈'), ('folder', '/catalog', '자료 등록', '자료'),
              ('pencil', '/', '정답 달기', '정답'), ('robot', '/learning/tasks', '학습 실행', '학습'),
              ('check', '/learning/evaluate', '평가·승격', '평가·승격')]
    subs = {'/learning': None, '/catalog': ['/catalog', '/learning/camera', '/learning/workspaces'],
            '/': ['/', '/pixels', '/learning/omx', '/learning/vlm'],
            '/learning/tasks': ['/learning/tasks', '/learning#pipeline', '/learning/sim'], '/learning/evaluate': None}
    rails = set()
    for name, stage, here in [('learning.html', '/learning', None), ('index.html', '/', '/'),
                              ('pixels.html', '/', '/pixels'), ('omx.html', '/', '/learning/omx'),
                              ('vlm.html', '/', '/learning/vlm'), ('catalog.html', '/catalog', '/catalog'),
                              ('camera.html', '/catalog', '/learning/camera'),
                              ('workspaces.html', '/catalog', '/learning/workspaces'), ('tasks.html', '/learning/tasks', '/learning/tasks'),
                              ('sim.html', '/learning/tasks', '/learning/sim'), ('evaluate.html', '/learning/evaluate', None)]:
        html = (web / name).read_text(encoding='utf-8')
        assert html.index('/common/components.css') < html.index('/common/app-shell.css') < html.index('/app.css')
        assert '<ui-shell grammar="procedure" class="ui-app-shell">' in html
        bar = re.search(r'<ui-topbar role="banner">(.*?)</ui-topbar>', html, re.S).group(1)
        assert bar.startswith('<ui-brand href="/learning" aria-label="Rosy Learning"><b>Learning</b></ui-brand>')
        assert '<h1' not in bar and '<nav' not in bar and 'data-theme-cycle=""' in bar, 'the shared theme cycle (D-668), no page select'
        assert 'data-learning-account-entry href="/accounts"' in bar, 'accounts stay in the top bar (D-857 §3)'
        assert 'kind="irreversible"' not in html, 'this tool commands no robot, so it has no stop'
        body = html.split('</ui-topbar>', 1)[1]
        # D-542 §2: every 정답 page carries the 정답 pages in one nav right after the title (shown in the title row on
        # wide screens and after the editor on phones), not in an extra sub-menu column; all four look alike.
        merged = name in ('index.html', 'pixels.html', 'omx.html', 'vlm.html')
        seats = ' data-seats="rail"' if subs[stage] is None or merged else ''
        rail = re.search(rf'<div class="ui-app-body"{seats}><div class="ui-rail">'
                         r'<nav class="ui-rail-nav workspace-tabs" aria-label="학습 화면">(.*?)</nav></div>', body, re.S).group(1)
        items = re.findall(r'<a class="ui-rail-item" data-action-icon="(\w+)" href="([^"]+)" aria-label="([^"]+)"'
                           r'(?: aria-current="(page|true)")?(?: data-icon-only="")?>([^<]+)</a>', rail)
        assert [(icon, href, full, short) for icon, href, full, _, short in items] == stages, name
        # "page" only on the link to this very page; a stage that merely holds it is "true".
        assert [(href, current) for _, href, _, current, _ in items if current] == [
            (stage, 'page' if here in (None, stage) else 'true')], name
        assert all(short in full for _, _, full, _, short in items), 'the stored label is part of the accessible name'
        sub = (re.search(r'<div class="ui-pathbar"><h1>[^<]+</h1>(?:<span data-spacer></span><ui-button [^>]*>[^<]*</ui-button>)?</div>'
                         r'<nav class="review-kinds" aria-label="정답 하위 메뉴">(.*?)</nav>', body, re.S) if merged else
               re.search(r'</nav></div><div class="ui-subnav"><nav class="ui-subnav-nav" aria-label="[^"]+ 하위 메뉴">'
                         r'<span class="ui-subnav-head">[^<]+</span>(.*?)</nav></div>', body, re.S))
        assert (sub is None) == (subs[stage] is None), name
        assert merged or '<div class="ui-subnav">' in body or subs[stage] is None, name
        if sub:
            links = re.findall(r'<a class="ui-subnav-item" href="([^"]+)"( aria-current="page")?[^>]*>[^<]+</a>', sub.group(1))
            assert [href for href, _ in links] == subs[stage], name
            assert [href for href, current in links if current] == [here], name
        assert re.search(r'<div class="ui-app-main"><div class="ui-pathbar"><h1>[^<]+</h1>', body)
        assert not merged or '<div class="ui-subnav">' not in body, name
        assert html.count('<h1') == 1
        rails.add(re.sub(r' aria-current="(?:page|true)"', '', rail))
    assert len(rails) == 1, 'the rail is the same in every document'
    css = (web / 'app.css').read_text(encoding='utf-8')
    assert '.workspace-tabs' not in css and '.ui-rail' not in css, 'the rail is laid out by the shared sheet'
