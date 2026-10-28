"""공용 콘텐츠 조합 어휘의 계약.

`DESIGN.md`의 「조합 어휘」 표가 묶음의 정본 이름을 정하고, 이 시험이 그 이름이 코드에
있는지 지킨다. 표면마다 같은 묶음을 다른 이름으로 다시 만드는 일이 다시 시작되면
표를 먼저 보라는 규칙(문서 439행)이 문서에만 남지 않게 하는 것이 목적이다.

단계 스트립(`.ui-stage-track` · `.ui-stage`)은 class-only라 JS가 없고, 표식의 순번은
CSS counter가 나른다. 그래서 이 시험은 규칙 본문까지 본다 — 상태 어휘가 `ui-tag`와
같은 넷인지, 역할 토큰만 쓰는지, 움직이지 않는지.
"""

from __future__ import annotations

import re
from pathlib import Path

import surface_registry as registry

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "shared" / "web"
COMPONENTS = WEB / "components.css"
STAGE_STRIP = WEB / "stage-strip.css"
APP_SHELL = WEB / "app-shell.css"
UI = WEB / "ui.js"
WORKSPACE = WEB / "workspace.js"
TEMPLATE = WEB / "template.html"
DESIGN = REPO / "DESIGN.md"
GALLERY = REPO / "middleware" / "robot_ui" / "robot" / "styleguide.html"

#: 단계 상태 어휘 — `ui-tag`와 같은 넷이다. `todo`는 기본값이라 자기 규칙이 없다.
STAGE_STATES = ("done", "now", "blocked", "todo")
#: `data-state` 없이 성립하는 `todo`를 빼고, 규칙이 있어야 하는 나머지 셋.
STAGE_OVERRIDES = ("done", "now", "blocked")

#: 부품이 직접 읽으면 안 되는 팔레트 이름. 의미 역할(`--text-*`·`--surface-*`·`--status-*`)을 쓴다.
PALETTE = re.compile(r"var\(\s*--(?:ink|ink-quiet|ground|ground-[a-z-]+|brand-rose[a-z-]*)\s*[,)]")
RAW_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|oklch|oklab|lab|lch|color)\(")
STATE_ATTR = re.compile(r'\[\s*data-state\s*=\s*["\']?([a-z-]+)')
#: 견본 HTML의 실제 속성 표기. 위 정규식은 CSS 선택자용이라 `[`가 필요하다.
HTML_STATE = re.compile(r'data-state="([a-z-]+)"')
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_TOP_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def stage_rules() -> list[tuple[str, str]]:
    """`(선택자, 본문)` — `.ui-stage`로 시작하는 규칙만. 주석은 먼저 지운다."""
    text = _COMMENT.sub(
        "", COMPONENTS.read_text(encoding="utf-8") + STAGE_STRIP.read_text(encoding="utf-8"))
    return [(selector.strip(), body)
            for selector, body in _TOP_RULE.findall(text)
            if "ui-stage" in selector]


def vocabulary_names() -> list[str]:
    """`DESIGN.md` 「조합 어휘」 표의 정본 이름 칸을 백틱 없이 편다."""
    text = DESIGN.read_text(encoding="utf-8")
    section = text.split("### 조합 어휘", 1)[1].split("\n### ", 1)[0]
    names = []
    for line in section.splitlines():
        if not line.startswith("|") or "---" in line or "정본 이름" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) > 1:
            names += [token.strip().strip("`") for token in cells[1].split("·")]
    return [name for name in names if name]


def declared(name: str) -> bool:
    """표의 한 이름이 코드에 실제로 있는가."""
    styles = (COMPONENTS.read_text(encoding="utf-8")
              + APP_SHELL.read_text(encoding="utf-8")
              + STAGE_STRIP.read_text(encoding="utf-8"))
    if name.startswith("<"):
        return f'"{name.strip("<>")}"' in UI.read_text(encoding="utf-8")
    if name.endswith("()"):
        return f"function {name[:-2]}" in WORKSPACE.read_text(encoding="utf-8")
    if name.startswith("."):
        class_name, _, rest = name.partition("[")
        attribute = rest.strip("[]")
        if attribute and attribute not in styles:
            return False
        return class_name in styles
    return False


def test_stage_strip_uses_role_tokens_and_no_motion():
    rules = stage_rules()
    selectors = [selector for selector, _ in rules]
    assert any(".ui-stage-track" in selector for selector in selectors), selectors
    assert any(selector.strip() == ".ui-stage" for selector in selectors), selectors

    offenders = []
    for selector, body in rules:
        for pattern in (RAW_COLOUR, PALETTE):
            offenders += [f"{selector}: {match.group(0)}" for match in pattern.finditer(body)]
        if "100vh" in body:
            offenders.append(f"{selector}: 100vh — 100dvh를 쓴다(D-398)")
        if "transition" in body or "animation" in body:
            offenders.append(f"{selector}: 움직임 — 단계는 정적이다(D-398)")
    assert offenders == [], f"단계 스트립은 역할 토큰만 쓴다: {offenders}"

    css = "\n".join(body for _, body in rules)
    assert "counter-increment: ui-stage" in css, "순번은 CSS counter가 나른다(JS 없음)"
    assert "counter(ui-stage)" in css, "표식이 순번을 보여 준다"
    assert "ui-stage" not in COMPONENTS.read_text(encoding="utf-8"), (
        "단계 스트립은 자기 시트에 산다 — components.css는 D-766 한도(942줄)에서 동결됐다")




def test_stage_states_are_the_tag_vocabulary():
    css_states = {match.group(1) for selector, _ in stage_rules()
                  for match in [STATE_ATTR.search(selector)] if match}
    assert css_states == set(STAGE_OVERRIDES), (
        f"규칙이 있어야 하는 상태는 {STAGE_OVERRIDES}다. todo는 기본 규칙이 나른다: {css_states}")
    assert "todo" not in css_states, "todo에 규칙을 더하면 닫힌 어휘가 둘로 갈라진다"

    design = DESIGN.read_text(encoding="utf-8")
    assert "`data-state`가 없으면 `todo`다" in design, "문서가 todo 기본값을 말해야 한다"

    section = GALLERY.read_text(encoding="utf-8").split('id="stage-track"', 1)[1].split("</section>", 1)[0]
    used = set(HTML_STATE.findall(section))
    assert used == set(STAGE_STATES), f"견본이 네 상태를 모두 보여야 한다: {used}"
    assert 'aria-current="step"' in section, "지금 단계는 색이 아니라 aria-current가 나른다"

    assert STATE_ATTR.findall('[data-state="paused"]') == ["paused"], "탐지기가 상태를 읽는다"


def test_product_surfaces_do_not_use_the_ui_field_element():
    """`<ui-field>`는 견본·스캐폴드 전용이다. 생산 표면은 네이티브 폼 + `.ui-form`을 쓴다."""
    allowed = {GALLERY.resolve(), TEMPLATE.resolve()}
    offenders = []
    for row in registry.load(REPO):
        path = row.get("path")
        if not isinstance(path, str):
            continue
        for page in registry._pages(REPO, path, ".html"):
            if page.resolve() in allowed:
                continue
            if "<ui-field" in page.read_text(encoding="utf-8"):
                offenders.append(page.relative_to(REPO).as_posix())
    assert offenders == [], f"`<ui-field>`는 견본 전용이다: {offenders}"

    for kept in allowed:
        assert "<ui-field" in kept.read_text(encoding="utf-8"), f"예외 목록이 죽었다: {kept.name}"


def test_composition_vocabulary_names_real_code():
    names = vocabulary_names()
    assert len(names) >= 8, f"표를 읽지 못했다: {names}"
    missing = [name for name in names if not declared(name)]
    assert missing == [], f"「조합 어휘」가 코드에 없는 이름을 부른다: {missing}"
    assert not declared(".ui-not-a-real-part"), "탐지기가 없는 이름을 통과시킨다"
