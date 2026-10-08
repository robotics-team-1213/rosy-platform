"""concept 16 §10 / D-72 L1 — 표면 토큰 계약.

색의 단일 출처는 `shared/web/tokens.css`다. 이 시험은 공용 L1 자산과
단언한다(D-73). `control`의 맵 래스터 색 계약은 별개 파이프라인이며
그 모듈의 시험이 소유한다.
"""

from pathlib import Path
import re

import pytest

import surface_registry as registry

WEB_ROOT = (Path(__file__).resolve().parents[3] / "middleware" / "ui") / "robot"
TOKENS = (Path(__file__).parents[3] / "shared") / "web" / "tokens.css"

DECLARATION = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.MULTILINE)
# 폴백 없는 참조만 위험하다. `var(--x, <fallback>)`는 의도적인 선택 오버라이드다
# (호스트 카드의 테마 훅). 폴백이 없는 `var(--x)`가 선언되지 않으면 그 속성은 조용히 값을 잃는다.
REFERENCE = re.compile(r"var\(\s*(--[a-z0-9-]+)\s*\)")


def tokens_text() -> str:
    return TOKENS.read_text(encoding="utf-8")


def surface_stylesheets() -> list[Path]:
    """토큰 파일을 뺀 표면 스타일시트."""
    return [path for path in sorted(WEB_ROOT.glob("*.css")) if path != TOKENS]


def surface_scripts() -> list[Path]:
    return sorted(WEB_ROOT.glob("*.js"))


def test_tokens_file_is_the_single_source_of_colour():
    assert TOKENS.exists(), "web_common/tokens.css가 없다"
    declared = set(DECLARATION.findall(tokens_text()))
    assert declared, "tokens.css가 토큰을 하나도 선언하지 않는다"


def _web_rows() -> list[dict]:
    return [row for row in registry.load(registry.REPO) if row.get("medium") == "web"]


@pytest.mark.parametrize("row", _web_rows(), ids=lambda row: row["id"])
def test_no_raw_colour_outside_the_token_file(row):
    """D-359 §7.2 — 모든 웹 표면(하위 폴더·Fleet·games의 CSS·JS·HTML)에 원시 색이 없다.

    hex·`rgb(`·`hsl(`·`oklch(`·`oklab(`·`color(`는 모두 원시 색이다. 예전 판정은
    dashboard 최상위 `*.css|*.js`만 보고 `oklch`/`color(`를 놓쳤다. 예외는 셋뿐이다:
    tokens.css 테마 팔레트 블록(색의 원본), `[dark]` 고정 표면이 surfaces.yaml
    `raw_colours`에 이유와 함께 등록한 블록·파일, 정적 `theme-color`(§7.3 판정이 따로 본다).
    """
    found = registry.raw_colour_problems(registry.REPO, row)
    assert found == [], "\n".join(found)


def test_the_raw_colour_scan_reads_every_web_file():
    """스캔이 공허하지 않다 — 하위 폴더·Fleet·games의 CSS·JS·HTML을 실제로 읽는다."""
    seen = {
        path.relative_to(registry.REPO).as_posix()
        for row in _web_rows() for path, _ in registry.colour_sources(registry.REPO, row)
    }
    for expected in (
        "middleware/ui/robot/styles.css", "middleware/ui/robot/app.js", "middleware/ui/robot/index.html",
        "middleware/ui/robot/shell/shell.css", "middleware/ui/robot/shell/shell.js",
        "middleware/ui/robot/panels/surface-panels.css", "middleware/ui/robot/panels/setup/waypoints.js",
        "shared/web/components.css", "shared/web/ui.js", "shared/web/tokens.css",
        "operations/fleet/fleet/server/web/shared/styles.css", "operations/fleet/fleet/server/web/map-view.js",
        "operations/fleet/fleet/server/web/index.html",
        "operations/apps/games/games/web/styles.css", "operations/apps/games/games/web/board.js",
        "operations/apps/games/games/web/index.html",
    ):
        assert expected in seen, f"원시 색 스캔이 {expected}를 읽지 않는다"
    assert not any("/test/" in here for here in seen), "시험 파일은 표면이 아니다"


def test_raw_colour_exceptions_are_registered_with_a_reason():
    assert registry.problems_with(registry.REPO, "colour") == []


def test_a_raw_colour_drift_is_caught(tmp_path):
    """하위 폴더 JS의 oklch, CSS의 color(, HTML의 hsl(, 패널 hex는 빨갛다. 주석·정적
    theme-color·등록된 고정 블록은 아니다. 테마 표면의 예외, 이유·파일·블록 없는 예외,
    쓰이지 않는 예외도 빨갛다."""
    common = tmp_path / "shared" / "web"
    common.mkdir(parents=True)
    (common / "ui.js").write_text("const GRAMMARS = ['spatial'];", encoding="utf-8")
    (common / "tokens.css").write_text(
        ':root, [data-theme="dark"] { --ground: #101214; }\n:root { --line: #222222; }\n',
        encoding="utf-8")
    themed = tmp_path / "themed"
    (themed / "panels").mkdir(parents=True)
    (themed / "panels" / "map.js").write_text(
        "// #abcdef 주석은 색이 아니다\nctx.fillStyle = 'oklch(0.5 0.1 200)';\n", encoding="utf-8")
    (themed / "panels" / "p.css").write_text(
        "/* rgb(1, 2, 3) */\n.a { color: color(srgb 1 0 0); }\n.b { border-color: #fff; }\n",
        encoding="utf-8")
    (themed / "index.html").write_text(
        '<html><head><meta name="theme-color" content="#101214">\n'
        '<link rel="stylesheet" href="/common/tokens.css"><script src="/common/theme.js"></script>\n'
        '</head><body style="background: hsl(10 20% 30%)"></body></html>', encoding="utf-8")
    pinned = tmp_path / "pinned"
    pinned.mkdir()
    (pinned / "styles.css").write_text(
        ":root {\n  --pitch: #17351f;\n}\n.x { color: rgb(0 0 0); }\n", encoding="utf-8")
    (pinned / "index.html").write_text('<html data-theme-pin="dark"></html>', encoding="utf-8")
    base = ("    surface: site\n    medium: web\n    audience: x\n    contracts: []\n"
            "    contract_reason: x\n    baseline_reason: x\n")
    (tmp_path / registry.REGISTRY).write_text(
        "surfaces:\n"
        "  - id: common\n    path: shared/web\n    themes: [dark, light]\n" + base +
        "  - id: themed\n    path: themed\n    themes: [dark, light]\n" + base +
        "    raw_colours: [{file: index.html, reason: 테마 표면은 예외를 가질 수 없다}]\n"
        "  - id: pinned\n    path: pinned\n    themes: [dark]\n" + base +
        "    raw_colours:\n"
        "      - {file: styles.css, block: ':root', reason: 경기장 팔레트}\n"
        "      - {file: index.html, reason: 색이 없는데 적힌 예외}\n"
        "      - {file: missing.css, reason: 없는 파일}\n"
        "      - {file: styles.css, block: '.nope', reason: 없는 블록}\n"
        "      - {file: styles.css}\n",
        encoding="utf-8")

    rows = {row["id"]: row for row in registry.load(tmp_path)}
    common_found = registry.raw_colour_problems(tmp_path, rows["common"])
    assert common_found == ["colour: common shared/web/tokens.css:2 #222222"], common_found
    themed_found = "\n".join(registry.raw_colour_problems(tmp_path, rows["themed"]))
    assert "themed/panels/map.js:2 oklch(" in themed_found
    assert "themed/panels/p.css:2 color(" in themed_found
    assert "themed/panels/p.css:3 #fff" in themed_found
    assert "themed/index.html:3 hsl(" in themed_found
    assert len(themed_found.splitlines()) == 4, themed_found  # 주석·theme-color는 세지 않는다
    pinned_found = registry.raw_colour_problems(tmp_path, rows["pinned"])
    assert pinned_found == ["colour: pinned pinned/styles.css:4 rgb("], pinned_found

    field = "\n".join(registry.problems_with(tmp_path, "colour"))
    assert "(themed) raw_colours는 [dark] 고정 웹 표면만 가진다" in field
    assert "(pinned) raw_colours index.html가 가리는 원시 색이 없다 — 목록에서 지운다" in field
    assert "(pinned) raw_colours missing.css가 표면 파일이 아니다" in field
    assert "(pinned) raw_colours styles.css에 .nope 블록이 없다" in field
    assert "(pinned) raw_colours styles.css에 reason이 없다" in field
    assert len(field.splitlines()) == 5, field


def test_every_referenced_token_is_declared():
    """폴백 없는 `var(--x)` 오타를 잡는다. 선언되지 않으면 조용히 값을 잃는다.

    폴백이 붙은 참조(`var(--surface-raised, var(--line-06))`)는 의도적인
    오버라이드 훅이므로 대상이 아니다.
    """
    declared = set(DECLARATION.findall(tokens_text()))
    for path in surface_stylesheets():
        text = path.read_text(encoding="utf-8")
        declared |= set(DECLARATION.findall(text))

    missing: dict[str, set[str]] = {}
    for path in surface_stylesheets():
        used = set(REFERENCE.findall(path.read_text(encoding="utf-8")))
        gap = used - declared
        if gap:
            missing[path.name] = gap

    assert not missing, f"선언되지 않은 토큰 참조: {missing}"


def test_no_token_refers_to_itself():
    """`--ink: var(--ink)`는 CSS에서 무효이고 조용히 값을 잃는다."""
    for path in [TOKENS, *surface_stylesheets()]:
        text = path.read_text(encoding="utf-8")
        for name, value in re.findall(
            r"^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);", text, re.MULTILINE
        ):
            assert f"var({name})" not in value.replace(" ", ""), (
                f"{path.name}: {name}이(가) 자기 자신을 참조한다"
            )


def test_status_colour_never_fills_a_categorical_slot():
    """concept 16 §6 — status 집합은 임계에만 쓴다.

    지도에서 점유 셀과 로봇 위치는 계열·지형이지 임계가 아니다. 예전에는
    둘 다 `#c4db76`(status good)이었고, 그래서 임계 경보가 눈에 띌 대비
    예산이 남지 않았다. costmap lethality만은 실제로 임계이므로 예외다.
    """
    script = (WEB_ROOT / "map.js").read_text(encoding="utf-8")
    block = re.search(r"PALETTE_TOKENS\s*=\s*\{(.*?)\n\};", script, re.DOTALL)
    assert block, "map.js에 PALETTE_TOKENS 선언이 없다"

    bindings = dict(re.findall(r"(\w+)\s*:\s*\"(--[a-z0-9-]+)\"", block.group(1)))
    assert bindings, "PALETTE_TOKENS가 비어 있다"

    categorical = {key: token for key, token in bindings.items() if key != "costLethal"}
    offenders = {
        key: token for key, token in categorical.items() if token.startswith("--status-")
    }
    assert not offenders, f"status 색이 계열·지형 자리에 있다: {offenders}"

    assert bindings.get("costLethal", "").startswith("--status-"), (
        "costmap lethality는 임계이므로 status 토큰이어야 한다"
    )


def test_every_palette_token_map_js_reads_is_declared():
    """map.js가 읽는 토큰이 tokens.css에 없으면 캔버스가 검게 칠해진다."""
    script = (WEB_ROOT / "map.js").read_text(encoding="utf-8")
    block = re.search(r"PALETTE_TOKENS\s*=\s*\{(.*?)\n\};", script, re.DOTALL)
    used = set(re.findall(r"\"(--[a-z0-9-]+)\"", block.group(1)))
    declared = set(DECLARATION.findall(tokens_text()))

    assert used <= declared, f"tokens.css에 없는 토큰: {sorted(used - declared)}"


def test_tokens_are_linked_before_the_surface_stylesheet():
    """토큰이 나중에 로드되면 표면 규칙이 정의되지 않은 값을 먼저 만난다."""
    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    tokens_at = html.find("tokens.css")
    styles_at = html.find("styles.css")

    assert tokens_at != -1, "index.html이 tokens.css를 링크하지 않는다"
    assert styles_at != -1
    assert tokens_at < styles_at, "tokens.css가 styles.css보다 먼저 와야 한다"


def test_tokens_css_is_served():
    """allowlist에 없으면 404다 — 링크만으로는 배포되지 않는다."""
    pytest.importorskip("httpx")
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from core_api_web.api.app import create_app

    client = TestClient(create_app({}, SimpleNamespace()))
    response = client.get("/common/tokens.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "--status-crit" in response.text


def test_nominal_carries_no_colour():
    """D-82: 정상에는 색이 없다.

    계기의 안전 구간에는 아무것도 칠하지 않는다. 초록을 status로 쓰면 화면
    대부분이 색을 갖게 되고, 임계 경보가 눈에 띌 대비 예산이 남지 않는다.
    초록은 `--series-goal`(지도의 목표 표식)로만 살아남는다.
    """
    offenders: dict[str, list[str]] = {}
    for path in surface_stylesheets() + surface_scripts():
        hits = [
            line.strip()[:80]
            for line in path.read_text(encoding="utf-8").splitlines()
            if "--status-good" in line or "--status-ok" in line or "--signal-lime" in line
        ]
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"정상을 초록으로 칠한 자리: {offenders}"


def test_no_decoration_effects_in_surfaces():
    """장식은 임계 경보가 쓸 대비를 먼저 써버린다.

    gradient wash, glow, drop-shadow는 concept 16 Law 1이 금지하는 장식이다.
    깊이를 주는 그림자(`box-shadow: inset ...`)는 면 위계이므로 대상이 아니다.
    """
    banned = ("linear-gradient", "radial-gradient", "drop-shadow(")
    offenders: dict[str, list[str]] = {}
    for path in surface_stylesheets():
        hits = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if any(token in stripped for token in banned):
                hits.append(stripped[:80])
            elif "box-shadow:" in stripped and not any(
                ok in stripped for ok in ("inset", "none")
            ):
                # `inset`은 면 위계이고 `none`은 그림자를 **없애는** 선언이다.
                # 둘 다 이 게이트가 막으려는 장식이 아니다.
                hits.append(stripped[:80])
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"장식 효과가 남아 있다: {offenders}"


def test_component_token_layer_exists():
    """컴포넌트와 치수도 토큰이다. 임의 값을 쓰면 다음 사람이 다른 값을 고른다."""
    declared = set(DECLARATION.findall(tokens_text()))
    required = {
        "--space-1", "--space-2", "--space-3", "--space-4", "--space-5", "--space-6",
        "--radius-control", "--radius-button", "--radius-panel", "--radius-flag",
        "--target-secondary", "--target-primary", "--target-irreversible",
        "--surface-flat", "--surface-raised", "--surface-line",
        "--nominal", "--nominal-quiet",
        "--button-primary-bg", "--button-primary-ink",
        "--button-irreversible-bg", "--button-irreversible-ink",
        "--field-bg", "--field-line", "--field-invalid",
        "--focus-ring", "--gauge-track", "--gauge-fill",
    }
    missing = required - declared
    assert not missing, f"tokens.css에 없는 컴포넌트 토큰: {sorted(missing)}"


def test_component_spacing_roles_are_closed_and_backed_by_the_base_scale():
    """D-292 — 공용 간격 결정은 역할 이름으로 소비하고 기본 척도에 연결한다."""
    text = tokens_text()
    declarations = dict(
        re.findall(r"^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);", text, re.MULTILINE)
    )
    roles = {
        "--inset-button", "--inset-button-primary", "--inset-button-irreversible",
        "--inset-field", "--inset-tag", "--inset-grid-cell", "--inset-chip",
        "--inset-evidence-unavailable", "--gap-button-content", "--gap-grid-cell", "--gap-actions",
        "--gap-form", "--gap-field-label", "--gap-readout", "--gap-readout-mobile",
        "--gap-readback", "--gap-heading", "--gap-triage", "--gap-topbar",
        "--gap-brand", "--gap-section", "--inset-topbar", "--inset-topbar-focal",
        "--gap-button-detail", "--offset-readout-mobile",
    }
    missing = roles - declarations.keys()
    assert not missing, f"D-292 컴포넌트 간격 역할 토큰이 없다: {sorted(missing)}"

    base_scale = {f"--space-{i}" for i in range(1, 7)}
    for role in roles:
        refs = set(re.findall(r"var\((--[a-z0-9-]+)", declarations[role]))
        assert refs and refs <= base_scale, (
            f"{role}은 기본 간격 척도만 참조해야 한다: {declarations[role]}"
        )


def test_shared_components_consume_component_spacing_roles():
    """레이아웃은 표면이 소유하고 반복되는 컴포넌트 간격은 공용이 소유한다."""
    css = (TOKENS.parent / "components.css").read_text(encoding="utf-8")
    expected = {
        "--inset-button", "--inset-button-primary", "--inset-button-irreversible",
        "--inset-field", "--inset-tag", "--inset-grid-cell", "--inset-chip",
        "--inset-evidence-unavailable", "--gap-button-content", "--gap-grid-cell", "--gap-actions",
        "--gap-form", "--gap-field-label", "--gap-readout", "--gap-readout-mobile",
        "--gap-readback", "--gap-heading", "--gap-triage", "--gap-topbar",
        "--gap-brand", "--gap-section", "--inset-topbar", "--inset-topbar-focal",
        "--gap-button-detail", "--offset-readout-mobile",
    }
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert expected <= used, f"components.css가 소비하지 않는 역할 토큰: {sorted(expected - used)}"

    direct_spacing = re.findall(
        r"(?<![-a-z])(padding|margin|gap|row-gap|column-gap)[a-z-]*:\s*([^;}]+)", css
    )
    offenders = [f"{prop}: {value.strip()}" for prop, value in direct_spacing
                 if re.search(r"var\(--space-", value)]
    assert not offenders, f"공용 컴포넌트가 기초 간격 대신 역할 토큰을 써야 한다: {offenders}"


def test_focus_is_interaction_not_status():
    """포커스 링은 상태가 아니다. status 색을 쓰면 '주의'와 헷갈린다."""
    text = tokens_text()
    match = re.search(r"--focus-ring:\s*var\((--[a-z0-9-]+)\)", text)
    assert match, "tokens.css에 --focus-ring 선언이 없다"
    assert not match.group(1).startswith("--status-"), (
        f"--focus-ring이 status 토큰({match.group(1)})을 가리킨다"
    )


def test_irreversible_actions_are_a_fill_not_text():
    """concept 16 Law 3 — 되돌릴 수 없는 것은 종류가 다르다.

    빨간 글자가 아니라 채운 면이므로, 토큰은 배경과 그 위 잉크가 짝을 이룬다.
    """
    declared = dict(
        re.findall(r"(--[a-z0-9-]+):\s*var\((--[a-z0-9-]+)\)", tokens_text())
    )
    assert declared.get("--button-irreversible-bg", "").startswith("--status-crit")
    assert declared.get("--button-irreversible-ink") in ("--ink", "--ink-on-crit")


def test_typography_is_declared_in_the_token_file():
    """타이포그래피도 L1이다 — 토큰 파일 밖에 있으면 게이트가 못 본다."""
    tokens = tokens_text()
    assert "--body:" in tokens and "--mono:" in tokens, "폰트 토큰이 tokens.css에 없다"
    for path in surface_stylesheets():
        body = path.read_text(encoding="utf-8")
        assert "--body:" not in body and "--mono:" not in body, (
            f"{path.name}이 폰트 토큰을 따로 선언한다"
        )


def test_font_stacks_do_not_fall_through_on_any_platform():
    """웹폰트를 쓰지 않으므로(D-75) 스택이 곧 설계다.

    예전 스택은 `Aptos`(MS Office 전용)로 시작해 Linux와 macOS에서 라틴
    문자가 한글 서체로 떨어졌고, `Malgun Gothic`이 없어 Windows에서는 한글이
    스택 전체를 빠져나갔다. 등폭은 macOS 항목이 없어 Courier로 떨어졌다 —
    계기의 숫자에 가장 나쁜 결과다.
    """
    tokens = tokens_text()
    body = re.search(r"--body:\s*([^;]+);", tokens, re.DOTALL)
    mono = re.search(r"--mono:\s*([^;]+);", tokens, re.DOTALL)
    assert body and mono

    body_stack = " ".join(body.group(1).split())
    mono_stack = " ".join(mono.group(1).split())

    assert "Aptos" not in body_stack, "Aptos는 MS Office 전용이라 세 플랫폼에서 빠진다"
    for face, why in (
        ("-apple-system", "macOS UI 서체"),
        ("Segoe UI", "Windows UI 서체"),
        ("Roboto", "Linux/Android UI 서체"),
        ("Malgun Gothic", "Windows 한글"),
        ("Apple SD Gothic Neo", "macOS 한글"),
        ("Noto Sans KR", "Linux 한글"),
    ):
        assert face in body_stack, f"본문 스택에 {face}({why})가 없다"
    assert body_stack.rstrip().endswith("sans-serif")

    for face, why in (
        ("ui-monospace", "현대 제네릭"),
        ("Cascadia Mono", "Windows"),
        ("Noto Sans Mono", "Linux"),
    ):
        assert face in mono_stack, f"등폭 스택에 {face}({why})가 없다"
    assert "SF Mono" in mono_stack, "등폭 스택에 macOS 항목이 없다 — Courier로 떨어진다"
    assert mono_stack.rstrip().endswith("monospace")


def test_touch_targets_clear_the_floor():
    """장갑 낀 손이 누른다. 최소 타겟은 --target-secondary(44px)다.

    예전에는 설정·호스트 카드의 입력과 선택이 42px였다 — 내가 정한 바닥보다
    낮았고, 토큰을 선언만 하고 쓰지 않아 아무도 몰랐다.
    """
    interactive = re.compile(r"(input|select|button|\[type=)")
    offenders: dict[str, list[str]] = {}
    for path in surface_stylesheets():
        hits = []
        for rule in re.findall(r"([^{}]+)\{([^}]*)\}", path.read_text(encoding="utf-8")):
            selector, body = rule
            if not interactive.search(selector):
                continue
            for value in re.findall(r"min-height:\s*(\d+)px", body):
                if int(value) < 44:
                    hits.append(f"{selector.strip()[:50]} -> {value}px")
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"44px 미만 터치 타겟: {offenders}"


def test_the_surface_sheet_declares_no_vocabulary_of_its_own():
    """별칭 층은 같은 것을 부르는 이름을 둘로 만든다.

    표면 규칙에는 `--ink: var(--ground)`, `--line: var(--line-14)`,
    `--signal-danger: var(--status-crit)` 같은 선언이 있었다. 토큰 파일이
    단일 출처라고 해 놓고 그 옆에 두 번째 어휘를 세운 셈이고, 값을 지키는
    게이트들은 전부 토큰 이름을 보므로 별칭 쪽은 아무도 검사하지 않았다.
    표면은 토큰을 **쓰기만** 한다.
    """
    offenders: dict[str, list[str]] = {}
    for path in surface_stylesheets():
        declared = DECLARATION.findall(path.read_text(encoding="utf-8"))
        if declared:
            offenders[path.name] = sorted(set(declared))
    assert not offenders, f"표면 스타일시트가 토큰을 새로 선언한다: {offenders}"


# 1px은 간격이 아니라 **실선**이다 — 격자를 선으로 짤 때 칸 사이에 바탕을
# 비치게 하는 관용구(`gap: 1px`)이고, 치수 계단의 대상이 아니다.
SPACING = re.compile(r"(?<![-a-z])(padding|margin|gap|row-gap|column-gap)[a-z-]*:\s*([^;}]+)")
PX_VALUE = re.compile(r"(\d+(?:\.\d+)?)px")


def test_spacing_comes_from_the_step_scale():
    """치수는 여섯 단계다. 임의 값을 쓰면 다음 사람이 다른 값을 고른다.

    예전 표면 규칙에는 간격으로 쓰인 px 값이 3px부터 50px까지 열아홉 가지
    있었고 그중 열한 가지는 한 번씩만 쓰였다. 계단이 없으면 리듬도 없다.
    """
    offenders: dict[str, list[str]] = {}
    for path in surface_stylesheets():
        hits = [
            f"{prop}: {value.strip()[:40]}"
            for prop, value in SPACING.findall(path.read_text(encoding="utf-8"))
            for px in PX_VALUE.findall(value)
            if float(px) != 1.0
        ]
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"--space-* 밖의 간격: {offenders}"


FONT_SIZE = re.compile(r"(?<![-a-z])(font-size|font):\s*([^;}]+)")


def test_type_sizes_come_from_the_scale():
    """글자도 닫힌 계단이다(--text-micro ~ --text-title).

    `clamp(3rem, 7vw, 6.7rem)`짜리 제목과 0.55rem짜리 라벨이 한 화면에 있으면
    그건 위계가 아니라 소음이다. 상대 단위(`em`)는 부모 값에 매이므로 계단을
    벗어나지 않는다 — 나이 접미사가 값 크기를 따라가는 자리에 쓴다.
    """
    offenders: dict[str, list[str]] = {}
    for path in surface_stylesheets():
        hits = []
        for prop, value in FONT_SIZE.findall(path.read_text(encoding="utf-8")):
            text = value.strip()
            if "--text-" in text or text == "inherit":
                continue
            if prop == "font-size" and re.fullmatch(r"[\d.]+em", text):
                continue
            hits.append(f"{prop}: {text[:40]}")
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"--text-* 밖의 글자 크기: {offenders}"


def test_a_danger_fill_carries_ink_not_dark_text():
    """D-82는 위험을 어두운 빨강으로 바꿨다. 옛 옅은 빨강에 맞춰진 어두운
    잉크를 그대로 두면 대비가 2.86:1로 떨어진다 — 실제로 그랬고, 값만 보는
    게이트는 CSS 안의 **짝**을 보지 못해 놓쳤다.
    """
    rules = re.findall(r"([^{}]+)\{([^}]*)\}", surface_stylesheets()[0].read_text(encoding="utf-8"))
    offenders = []
    for selector, body in rules:
        if "background: var(--status-crit)" not in body:
            continue
        ink = re.search(r"(?<![-a-z])color:\s*var\((--[a-z0-9-]+)\)", body)
        if ink and ink.group(1) not in ("--ink", "--ink-on-crit", "--nominal"):
            offenders.append(f"{selector.strip()[:50]} -> color {ink.group(1)}")
    assert not offenders, f"위험 면 위에 잉크가 아닌 색을 얹는다: {offenders}"


def test_shared_type_and_interaction_tokens_are_closed_and_keep_current_metrics():
    """D-294 — 반복되는 타이포그래피와 조작 피드백은 이름 있는 척도로 닫는다."""
    declarations = dict(
        re.findall(r"^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);", tokens_text(), re.MULTILINE)
    )
    expected = {
        "--weight-regular": "400",
        "--weight-medium": "500",
        "--weight-label": "600",
        "--weight-emphasis": "650",
        "--weight-strong": "700",
        "--leading-flat": "1",
        "--leading-dense": "1.1",
        "--leading-compact": "1.25",
        "--leading-control": "1.2",
        "--leading-label": "1.3",
        "--leading-body": "1.4",
        "--leading-copy": "1.5",
        "--track-wide": "0.04em",
        "--track-state": "0.06em",
        "--focus-ring-width": "2px",
        "--focus-ring-offset": "1px",
        "--focus-ring-offset-outer": "2px",
        "--contract-mark-width": "2px",
        "--contract-mark-offset": "2px",
        "--disabled-opacity": "0.45",
    }
    missing = expected.keys() - declarations.keys()
    assert not missing, f"D-294 토큰이 없다: {sorted(missing)}"
    changed = {
        token: (declarations[token].strip(), value)
        for token, value in expected.items()
        if declarations[token].strip() != value
    }
    assert not changed, f"기존 공용 컴포넌트 지표가 달라졌다: {changed}"
    assert declarations.get("--track-label", "").strip() == "0.12em"


def test_shared_components_consume_type_and_interaction_tokens():
    """공용 컴포넌트에서 반복되는 값은 토큰으로만 바꿀 수 있다."""
    css = (TOKENS.parent / "components.css").read_text(encoding="utf-8")
    required = {
        "--weight-medium", "--weight-label", "--weight-emphasis", "--weight-strong",
        "--leading-flat", "--leading-dense", "--leading-control", "--leading-label",
        "--leading-body", "--leading-copy", "--track-wide", "--track-state", "--track-label",
        "--focus-ring-width", "--focus-ring-offset", "--contract-mark-width",
        "--contract-mark-offset", "--disabled-opacity",
    }
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert required <= used, f"components.css가 소비하지 않는 토큰: {sorted(required - used)}"

    raw_values = re.findall(
        r"(?:font-weight\s*:\s*\d+|font\s*:\s*\d+\s+[^;}]+/\s*[\d.]+|"
        r"letter-spacing\s*:\s*(?:0|[\d.]+em)|outline\s*:\s*[\d.]+px|"
        r"outline-offset\s*:\s*-?[\d.]+px|opacity\s*:\s*[\d.]+)",
        css,
    )
    assert not raw_values, f"components.css에 원시 타이포그래피/상호작용 값: {raw_values}"


def test_styleguide_renders_the_shared_type_and_interaction_contract():
    """D-294의 실례는 문서 전용 CSS가 아닌 실제 공용 컴포넌트를 보여준다."""
    html = (WEB_ROOT / "styleguide.html").read_text(encoding="utf-8")
    components = ((WEB_ROOT.parents[2] / "shared") / "web" / "components.css").read_text(encoding="utf-8")
    assert 'class="entry" id="type-and-interaction"' in html
    assert 'kind="quiet" type="button"' in html
    assert "disabled" in html
    # 초점 링 토큰은 공용 시트가 소비한다 — 견본 시트가 따로 그리지 않는다(D-398 정리).
    assert "--focus-ring-width" in components and "--focus-ring-offset" in components

