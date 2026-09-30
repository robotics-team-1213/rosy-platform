"""D-359 §6·§7.7 — 반응형은 세 단 어휘를 쓴다.

웹 표면의 모든 `@media` 크기 조건(CSS 파일과 HTML 안 `<style>`)은 범위 문법으로
compact `(width < 30rem)`·medium `(30rem <= width < 64rem)`·wide `(width >= 64rem)`
(이웃한 두 단의 합 포함)이거나 §6.5 높이 조건이거나, `surfaces.yaml`의 그 표면
`breakpoints`에 이유와 함께 적힌 값이다. 판정은 `surface_registry.breakpoint_problems()`에
있고 표면 목록은 레지스트리에서만 읽는다.

변이 증명: 어느 표면 CSS에 `@media (max-width: 41rem) {}`을 넣으면 첫 시험이 빨갛다.
"""

from __future__ import annotations

import re

import surface_registry as registry

REPO = registry.REPO
COMPONENTS = REPO / "src" / "hmi" / "web_common" / "components.css"
PANELS = REPO / "src" / "hmi" / "dashboard" / "panels" / "surface-panels.css"
SHELL = REPO / "src" / "hmi" / "dashboard" / "shell" / "shell.css"


def _web_rows() -> list[dict]:
    return [row for row in registry.load(REPO) if row.get("medium") == "web"]


def test_every_media_query_uses_the_three_tiers_or_a_listed_value():
    found = [line for row in _web_rows() for line in registry.breakpoint_problems(REPO, row)]
    assert found == [], "\n".join(found)


def test_the_scan_reads_css_files_and_inline_styles():
    """스캔이 공허하지 않다 — 제품 표면의 CSS와 HTML 안 <style>에서 조건을 읽는다."""
    seen = {row["id"]: registry.media_conditions(REPO, row) for row in _web_rows()}
    for ident in ("robot-dashboard", "fleet-console", "game-board"):
        assert seen[ident], f"{ident}에서 @media 크기 조건을 하나도 읽지 못했다"
    inline = [here for here, _, _ in seen["lane-live-view"] + seen["control-diagnostic"]]
    assert inline and all(here.endswith(".html") for here in inline)


def test_breakpoint_allowlists_are_well_formed_and_used():
    assert registry.problems_with(REPO, "breakpoint") == []


def test_a_breakpoint_drift_is_caught(tmp_path):
    """min-/max- 문법, .01 보정, 목록에 없는 값, 세 단 값 등재, 쓰이지 않는 값, 이유 없는 값."""
    common = tmp_path / "src" / "hmi" / "web_common"
    common.mkdir(parents=True)
    (common / "ui.js").write_text("const GRAMMARS = ['spatial'];", encoding="utf-8")
    (common / "tokens.css").write_text(':root, [data-theme="dark"] { --ground: #101214; }\n', encoding="utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "styles.css").write_text(
        "@media (max-width: 41rem) { a { color: red; } }\n"
        "@media (width < 30.01rem) { a { gap: 0; } }\n"
        "@media (width < 50rem) { a { gap: 0; } }\n"
        "@media (width >= 90rem) { a { gap: 0; } }\n"
        "/* @media (width < 77rem) — 주석은 조건이 아니다 */\n"
        "@media (30rem <= width < 64rem), (height < 40rem) { a { gap: 0; } }\n"
        "@media (prefers-reduced-motion: reduce) { a { gap: 0; } }\n",
        encoding="utf-8")
    (web / "index.html").write_text(
        '<html data-theme-pin="dark"><head><style>\n\n@media (width <= 700px) { b { gap: 0; } }\n'
        "</style></head></html>", encoding="utf-8")
    (tmp_path / registry.REGISTRY).write_text(
        "surfaces:\n"
        "  - id: drift\n    path: web\n    themes: [dark]\n    surface: site\n    medium: web\n"
        "    audience: x\n    contracts: []\n    contract_reason: x\n    baseline_reason: x\n"
        "    breakpoints:\n"
        "      - {value: 90rem, reason: 넓은 벽 모니터}\n"
        "      - {value: 64rem, reason: 세 단 값}\n"
        "      - {value: 12rem, reason: 쓰이지 않는다}\n"
        "      - {value: 50rem}\n"
        "      - {value: 30.5rem, reason: 소수}\n"
        "  - id: native\n    path: web\n    themes: [dark]\n    surface: site\n    medium: native\n"
        "    audience: x\n    contracts: []\n    contract_reason: x\n    baseline_reason: x\n"
        "    breakpoints: [{value: 10rem, reason: x}]\n",
        encoding="utf-8")

    row = registry.load(tmp_path)[0]
    media = "\n".join(registry.breakpoint_problems(tmp_path, row))
    assert "styles.css:1 (max-width: 41rem) — min-/max- 문법이다" in media
    assert "styles.css:2 (width < 30.01rem) — 30.01rem는 소수 보정값이다" in media
    assert "(width < 50rem)" not in media  # 이유가 없어도 목록 값이다 — 이유는 필드 검사가 잡는다
    assert "90rem" not in media and "77rem" not in media and "40rem" not in media
    assert "index.html:3 (width <= 700px) — 700px가 세 단도 아니고" in media
    assert len(media.splitlines()) == 3, media

    field = "\n".join(registry.problems_with(tmp_path, "breakpoint"))
    assert "(drift) 64rem는 세 단 값이라 등재하지 않는다" in field
    assert "(drift) 12rem를 쓰는 @media가 없다" in field
    assert "(drift) 50rem에 reason이 없다" in field
    assert "(drift) breakpoints 값이 정수 px/rem이 아니다: '30.5rem'" in field
    assert "(native)는 웹 표면이 아닌데 breakpoints가 있다" in field


def test_shared_layout_parts_answer_their_slot_not_the_viewport():
    """§6.3 — ui-form·ui-readout·ui-actions는 @container로 반응하고 표면은 칸을 정한다.
    표면 CSS가 공용 ui-actions를 뷰포트 질의로 다시 정의하지 않는다."""
    css = COMPONENTS.read_text(encoding="utf-8")
    assert "@media" not in css, "components.css가 뷰포트 질의를 쓴다 — 공용 부품은 칸에 반응한다"
    container = re.search(r"@container \(width < [0-9.]+rem\) \{(.*?)\n\}", css, re.S)
    assert container, "components.css에 공용 부품의 @container 규칙이 없다"
    for part in (".ui-form {", ".ui-readout {", "ui-actions {"):
        assert part in container.group(1), f"{part}가 @container 안에 없다"
    assert not re.search(r"(?m)^\s*ui-actions\b", PANELS.read_text(encoding="utf-8")), (
        "surface-panels.css가 공용 ui-actions를 다시 정의한다(D-292 §4)")
    shell = SHELL.read_text(encoding="utf-8")
    slots = re.search(r"([^{}]+)\{\s*container-type:\s*inline-size;\s*\}", shell)
    assert slots and ".surface-slot" in slots.group(1) and ".surface-main" in slots.group(1)


def test_surface_style_braces_balance():
    """반응형 블록을 옮기다 남은 `}` 하나가 다음 규칙(예: Fleet .dispatch-control)을 조용히 지운다.
    2026-09-30 US-005 캡처에서 실제로 잡힌 결함이다 — 괄호 짝을 표면 CSS·<style>마다 본다."""
    broken = []
    for row in _web_rows():
        for page, css in registry._style_sources(REPO, row["path"]):
            depth = lowest = 0
            for char in re.sub(r'"[^"\n]*"|\'[^\'\n]*\'', "", css):
                depth += (char == "{") - (char == "}")
                lowest = min(lowest, depth)
            if depth or lowest < 0:
                broken.append(f"{page.relative_to(REPO).as_posix()} depth={depth} lowest={lowest}")
    assert broken == [], broken
