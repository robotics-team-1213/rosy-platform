"""concept 16 §10 / D-72 L1 — 표면 토큰 계약.

색의 단일 출처는 `src/hmi/web/tokens.css`다. 이 시험은 공용 L1 자산과
단언한다(D-73). `control`의 맵 래스터 색 계약은 별개 파이프라인이며
그 모듈의 시험이 소유한다.
"""

from pathlib import Path
import re

import pytest

WEB_ROOT = Path(__file__).resolve().parents[2] / "dashboard"
TOKENS = Path(__file__).parent.parent.parent / "web" / "tokens.css"

COLOR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d|hsla?\(\s*\d"
)
DECLARATION = re.compile(r"^\s*(--[a-z0-9-]+)\s*:", re.MULTILINE)
# 폴백 없는 참조만 위험하다. `var(--x, <fallback>)`는 의도적인 선택 오버라이드이고
# (호스트 카드의 테마 훅), `--meter`처럼 JS가 런타임에 넣는 값도 이 형태를 쓴다.
# 폴백이 없는 `var(--x)`가 선언되지 않으면 그 속성은 조용히 값을 잃는다.
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


@pytest.mark.parametrize("path", surface_stylesheets(), ids=lambda p: p.name)
def test_no_raw_colour_outside_the_token_file(path: Path):
    """표면 스타일시트에 원시 색이 있으면 실패한다.

    hex뿐 아니라 `rgba()`/`hsl()`도 원시 색이다. v1 계획이 hex만 셌다가
    37개의 rgba를 놓쳤다 — 같은 종류의 누락을 다시 만들지 않는다.
    """
    found = COLOR_LITERAL.findall(path.read_text(encoding="utf-8"))
    assert not found, f"{path.name}에 원시 색 {len(found)}개: {found[:5]}"


@pytest.mark.parametrize("path", surface_scripts(), ids=lambda p: p.name)
def test_no_raw_colour_in_dashboard_scripts(path: Path):
    """캔버스도 예외가 아니다. 색은 tokens.css에서 읽어 쓴다."""
    found = COLOR_LITERAL.findall(path.read_text(encoding="utf-8"))
    assert not found, f"{path.name}에 원시 색 {len(found)}개: {found[:5]}"


def test_every_referenced_token_is_declared():
    """폴백 없는 `var(--x)` 오타를 잡는다. 선언되지 않으면 조용히 값을 잃는다.

    폴백이 붙은 참조(`var(--surface-raised, var(--sheen-04))`)는 의도적인
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
    """`--paper: var(--paper)`는 CSS에서 무효이고 조용히 값을 잃는다."""
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
    assert declared.get("--button-irreversible-ink") in ("--paper", "--ink")


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
        if ink and ink.group(1) not in ("--paper", "--ink", "--nominal"):
            offenders.append(f"{selector.strip()[:50]} -> color {ink.group(1)}")
    assert not offenders, f"위험 면 위에 잉크가 아닌 색을 얹는다: {offenders}"

