"""Shared browser controls live in one file.

A later page may place a control. It may not invent its kind, repaint it,
or copy a token colour into a second number.
"""

from pathlib import Path
import re
from collections import Counter

import pytest

import surface_registry as registry
import token_themes

ROOT = Path(__file__).resolve().parents[3]
COMMON = Path(__file__).parent.parent
COMPONENTS = COMMON / "components.css"
UI = COMMON / "ui.js"
TOKENS = COMMON / "tokens.css"
FACE = ROOT / "middleware" / "ui" / "face" / "emotion" / "info_screen.py"
PITCH = ROOT / "operations" / "apps" / "games" / "games" / "web" / "styles.css"

# 표면 목록은 shared/web/surfaces.yaml 한 곳에서만 읽는다 (D-329 Decision 1).
STYLE_SUFFIXES = {".css", ".html", ".js"}

RAW_SIZE = re.compile(r"font-size:\s*[0-9.]+(?:px|rem)")
RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d")
TAG = re.compile(r"<ui-button\b([^>]*)>", re.S)
RULE = re.compile(r"([^{}]+)\{([^}]*)\}")
CONTROL = re.compile(
    r"ui-button|ui-field|ui-tag|ui-text|ui-head|ui-grid|ui-chip|ui-triage|ui-evidence|"
    r"ui-shell|ui-topbar|ui-brand|ui-section|ui-empty|ui-status|ui-actions"
)
EVIDENCE_TAG = re.compile(r"<ui-evidence\b([^>]*)>", re.S)
# D-359 §7.4 — outline도 덧칠이다(포커스처럼 보인다). 눌림은 aria-pressed의 공용 표현이다.
PAINT = re.compile(
    r"(?<![-a-z])(background|color|font-size|font-weight|font|opacity|border-radius|border-color|border|outline)\s*:"
)
CREATE = re.compile(r"""createElement\(\s*["']ui-button["']\s*\)""")
HELPER_CREATE = re.compile(r"""(?:\bel|\bnode)\(\s*["']ui-button["']\s*,""")
KIND_ATTR = re.compile(r"""setAttribute\(\s*["']kind["']\s*,\s*["']([a-z]+)["']\s*\)""")
HELPER_ASSIGNMENT = re.compile(
    r"""\b(?:const|let|var)\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:el|node)\(\s*["']ui-button["']"""
)
FACE_COLOUR = {
    "--ground": "_BG",
    "--ink": "_FG",
    "--ink-quiet": "_MUTED",
    "--status-warn": "_WARN",
    "--status-crit": "_CRIT",
}


def _kinds() -> set[str]:
    match = re.search(r"const KINDS = \[(.*?)\];", UI.read_text(encoding="utf-8"), re.S)
    assert match, "ui.js가 KINDS를 선언하지 않는다"
    return set(re.findall(r'"([a-z]+)"', match.group(1)))


def _surface_texts():
    for path in registry.for_contract(registry.REPO, "shared_controls"):
        if path.is_file():
            yield path
            continue
        for child in sorted(path.rglob("*")):
            if child.suffix in STYLE_SUFFIXES and "test" not in child.parts:
                yield child


def test_shared_controls_are_the_only_painted_components():
    css = COMPONENTS.read_text(encoding="utf-8")
    script = UI.read_text(encoding="utf-8")
    names = (
        "ui-button", "ui-field", "ui-tag", "ui-text",
        "ui-head", "ui-grid", "ui-chip", "ui-triage", "ui-evidence",
        "ui-shell", "ui-topbar", "ui-brand", "ui-section", "ui-empty", "ui-status", "ui-actions",
    )
    for name in names:
        assert name in css
        assert f'"{name}"' in script
    assert not RAW_COLOR.findall(css), "components.css에 원시 색이 있다"
    assert not RAW_SIZE.findall(css)


def test_shared_status_component_owns_accessibility_and_palette_states():
    css = COMPONENTS.read_text(encoding="utf-8")
    script = UI.read_text(encoding="utf-8")
    states = {
        "pending", "empty", "ready", "warning", "error", "unavailable", "forbidden",
    }
    declaration = re.search(r"const STATUS_STATES = \[(.*?)\];", script, re.S)
    assert declaration
    assert set(re.findall(r'"([a-z]+)"', declaration.group(1))) == states
    assert 'if (!this.hasAttribute("role")) this.setAttribute("role", "status")' in script
    assert 'if (!this.hasAttribute("aria-live")) this.setAttribute("aria-live", "polite")' in script
    assert "ui-status[state=\"warning\"]" in css
    assert "ui-status[hidden] { display: none; }" in css
    assert "color: var(--status-warn)" in css
    assert not RAW_COLOR.findall(css)


def test_role_recovery_panels_use_shared_status_component():
    console_map = (ROOT / "middleware" / "ui" / "robot" / "panels" / "console" / "map.js").read_text(encoding="utf-8")
    host_operations = (ROOT / "middleware" / "ui" / "robot" / "panels" / "host" / "operations.js").read_text(encoding="utf-8")
    assert 'el("ui-status"' in console_map
    assert 'el("ui-status"' in host_operations


def test_role_live_announcements_use_shared_status_component():
    panels = ROOT / "middleware" / "ui" / "robot" / "panels"
    owners = (
        "console/camera.js", "console/docking.js", "console/line-follow.js",
        "console/mode.js", "console/teleop.js", "host/system.js",
        "setup/docking.js", "setup/dock-admin.js", "setup/localization.js",
        "setup/traffic-policy.js", "system/security.js",
    )
    for owner in owners:
        source = (panels / owner).read_text(encoding="utf-8")
        assert re.search(r'el\("ui-status",\s*"",\s*"', source), owner
        assert 'el("p", "surface-message"' not in source, owner


def test_selected_action_tabs_use_shared_segment_palette():
    css = COMPONENTS.read_text(encoding="utf-8")
    shell_css = (ROOT / "middleware" / "ui" / "robot" / "shell" / "shell.css").read_text(encoding="utf-8")
    assert 'ui-button[kind="segment"][aria-selected="true"]' in css
    assert ".action-group-tabs ui-button[aria-selected" not in shell_css


def test_buttons_and_action_groups_use_shared_size_and_layout_tokens():
    css = COMPONENTS.read_text(encoding="utf-8")
    script = UI.read_text(encoding="utf-8")
    assert 'const BUTTON_SIZES = ["secondary", "primary", "irreversible"]' in script
    assert 'const KIND_SIZES = { primary: "primary", irreversible: "irreversible" }' in script
    for size, token in (("secondary", "target-secondary"), ("primary", "target-primary"), ("irreversible", "target-irreversible")):
        assert f'ui-button[data-size="{size}"]' in css
        assert f"min-height: var(--{token})" in css
    assert "ui-actions" in script and "ui-actions" in css
    assert "gap: var(--gap-actions)" in css[css.index("ui-actions {"):]
    dashboard = ROOT / "middleware" / "ui" / "robot" / "panels"
    owners = ("console/docking.js", "console/mode.js", "console/map.js", "host/operations.js", "setup/localization.js")
    for owner in owners:
        source = (dashboard / owner).read_text(encoding="utf-8")
        assert 'el("ui-actions"' in source, owner
    teleop = (dashboard / "console" / "teleop.js").read_text(encoding="utf-8")
    assert 'setAttribute("size", "primary")' in teleop
    panel_css = (dashboard / "surface-panels.css").read_text(encoding="utf-8")
    teleop_rule = re.search(r"\.surface-teleop-controls ui-button\s*\{([^}]*)\}", panel_css)
    assert teleop_rule and "min-height" not in teleop_rule.group(1)


def test_role_forms_use_shared_responsive_layout_and_field_labels():
    css = COMPONENTS.read_text(encoding="utf-8")
    panel_css = (ROOT / "middleware" / "ui" / "robot" / "panels" / "surface-panels.css").read_text(encoding="utf-8")
    layout = re.search(r"\.ui-form\s*\{([^}]*)\}", css)
    field = re.search(r"\.ui-field-label\s*\{([^}]*)\}", css)
    assert layout and "display: flex" in layout.group(1)
    assert "flex-wrap: wrap" in layout.group(1)
    assert "align-items: end" in layout.group(1)
    assert "gap: var(--gap-form)" in layout.group(1)
    assert field and "display: grid" in field.group(1)
    assert "min-width: min(100%, 10rem)" in field.group(1)
    assert ".ui-form > * { width: 100%; }" in css
    assert ".surface-form" not in panel_css
    assert ".surface-inline-form" not in panel_css
    assert ".surface-field" not in panel_css

    panels = ROOT / "middleware" / "ui" / "robot" / "panels"
    sources = [path.read_text(encoding="utf-8") for path in panels.rglob("*.js")]
    role_forms = "\n".join(sources)
    assert 'el("form", "ui-form")' in role_forms
    assert 'el("label", "ui-field-label"' in role_forms
    assert "surface-form" not in role_forms
    assert "surface-inline-form" not in role_forms
    assert "surface-field" not in role_forms


def test_role_readouts_use_a_shared_semantic_definition_list_layout():
    css = COMPONENTS.read_text(encoding="utf-8")
    panel_css = (ROOT / "middleware" / "ui" / "robot" / "panels" / "surface-panels.css").read_text(encoding="utf-8")
    readout = re.search(r"\.ui-readout\s*\{([^}]*)\}", css)
    assert readout and "display: grid" in readout.group(1)
    assert "grid-template-columns: minmax(7rem, 1fr) 2fr" in readout.group(1)
    assert "gap: var(--gap-readout)" in readout.group(1)
    assert ".ui-readout dt { color: var(--nominal-quiet); }" in css
    assert ".ui-readout dd { margin: 0; font-variant-numeric: tabular-nums; }" in css
    assert ".surface-readout" not in panel_css
    assert ".surface-readout" not in "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "middleware" / "ui" / "robot" / "panels").rglob("*.js")
    )


def test_role_readback_sections_use_shared_layout_primitives():
    css = COMPONENTS.read_text(encoding="utf-8")
    panel_css = (ROOT / "middleware" / "ui" / "robot" / "panels" / "surface-panels.css").read_text(encoding="utf-8")
    section = re.search(r"\.ui-readback\s*\{([^}]*)\}", css)
    assert section and "min-width: 0" in section.group(1)
    assert "display: grid" in section.group(1)
    assert "gap: var(--gap-readback)" in section.group(1)
    assert re.search(
        r"\.ui-readback > h3,\s*\.ui-readback > h4\s*\{\s*margin:\s*0;\s*\}",
        css,
    )
    assert ".surface-readback" not in panel_css
    panel_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "middleware" / "ui" / "robot" / "panels").rglob("*.js")
    )
    assert ".surface-readback" not in panel_source
    assert 'el("section", "ui-readback")' in panel_source


def test_browser_surfaces_use_the_type_scale():
    offenders = {}
    for path in _surface_texts():
        if path.suffix not in {".css", ".html"}:
            continue
        hits = RAW_SIZE.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[path.name] = hits
    assert not offenders, offenders


def test_every_button_names_its_kind():
    """종류는 표시에 적는다. 부모 클래스에서 짐작하지 않는다."""
    allowed = _kinds()
    missing = []
    for path in _surface_texts():
        if path.suffix != ".html":
            continue
        for attrs in TAG.findall(path.read_text(encoding="utf-8")):
            found = re.search(r'kind="([a-z]+)"', attrs)
            if not found or found.group(1) not in allowed:
                missing.append(f"{path.name}: {attrs.strip()[:80]}")
    assert not missing, missing

    invented = []
    for path in _surface_texts():
        if path.suffix != ".js":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not CREATE.search(line):
                continue
            window = "\n".join(lines[index:index + 4])
            found = KIND_ATTR.search(window)
            if not found or found.group(1) not in allowed:
                invented.append(f"{path.name}:{index + 1}")
    assert not invented, invented


def test_helper_created_buttons_name_their_kind():
    """Factory helpers must not bypass the kind contract for dynamic panels."""
    allowed = _kinds()
    missing = []
    for path in _surface_texts():
        if path.suffix != ".js":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not HELPER_CREATE.search(line):
                continue
            assigned = HELPER_ASSIGNMENT.search(line)
            if not assigned:
                missing.append(f"{path.name}:{index + 1} (button variable not explicit)")
                continue
            variable = re.escape(assigned.group(1))
            kind = re.compile(
                rf"\b{variable}\.setAttribute\(\s*['\"]kind['\"]\s*,\s*['\"]([a-z]+)['\"]"
            )
            window = "\n".join(lines[index:index + 8])
            found = kind.search(window)
            if not found or found.group(1) not in allowed:
                missing.append(f"{path.name}:{index + 1}")
    assert not missing, "\n".join(missing)
    evidence = re.search(
        r"const EVIDENCE = \[(.*?)\];", UI.read_text(encoding="utf-8"), re.S
    )
    assert evidence, "ui.js가 EVIDENCE를 선언하지 않는다"
    states = set(re.findall(r'"([a-z]+)"', evidence.group(1)))
    bare = []
    for path in _surface_texts():
        if path.suffix != ".html":
            continue
        for attrs in EVIDENCE_TAG.findall(path.read_text(encoding="utf-8")):
            found = re.search(r'state="([a-z]+)"', attrs)
            if not found or found.group(1) not in states:
                bare.append(path.name)
    assert not bare, bare


def test_surfaces_do_not_repaint_shared_controls():
    """자리만 정한다. 면·글자·테두리는 components.css가 그린다."""
    offenders = []
    for path in _surface_texts():
        if path.suffix not in {".css", ".html"}:
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            blocks = re.findall(r"<style>(.*?)</style>", text, re.S)
            text = "\n".join(blocks)
        for selector, body in RULE.findall(text):
            if not CONTROL.search(selector):
                continue
            painted = PAINT.findall(body)
            if painted:
                offenders.append(f"{path.name} {selector.strip()[:60]} -> {painted}")
    assert not offenders, offenders


def test_pitch_colours_live_in_one_block():
    css = PITCH.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{([^}]*)\}", css)
    assert root, "경기 보드에 팔레트 블록이 없다"
    rest = css[root.end():]
    leaked = RAW_COLOR.findall(rest)
    assert not leaked, leaked


def _dark_tokens() -> dict[str, str]:
    """`--이름` → `rrggbb`. LCD·진단 사본은 어두운 팔레트에 고정한다(D-359 §3.3–3.4)."""
    palette = token_themes.palettes(TOKENS.read_text(encoding="utf-8"))["dark"]
    return {f"--{name}": value.lstrip("#") for name, value in palette.items()}


def test_face_literals_match_the_token_file():
    """LCD는 DOM 부품을 쓰지 않는다. 숫자는 토큰과 같아야 한다."""
    tokens = _dark_tokens()
    source = FACE.read_text(encoding="utf-8")
    mismatch = []
    for token, name in FACE_COLOUR.items():
        found = re.search(rf"{name}\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", source)
        assert found, f"{name} 튜플이 없다"
        rgb = tuple(int(part) for part in found.groups())
        hex_colour = tokens[token]
        expected = tuple(int(hex_colour[i:i + 2], 16) for i in (0, 2, 4))
        if rgb != expected:
            mismatch.append(f"{name} {rgb} != --{token.lstrip('-')} #{hex_colour}")
    assert not mismatch, mismatch


_MEASURE = re.compile(
    r"(?<![-a-z])(padding|margin|gap|row-gap|column-gap|border-radius)[a-z-]*\s*:\s*([^;}{]+)"
)
_LENGTH = re.compile(r"(?<![\w.-])(\d*\.?\d+)(px|rem)")

# Diagnostic names that are the shared palette, written as hex so the canvas
# mirror can read them. Raster and the two colours with no token stay local.
_DIAGNOSTIC_TWINS = {
    "bg": "--ground-deep",
    "observe": "--ground",
    "act": "--ground-card",
    "act-2": "--ground-card-2",
    "ink": "--ink",
    "ink-2": "--ink-quiet",
    "ink-quiet": "--ink-quiet",
    "route": "--series-primary",
    "goal": "--series-goal",
    "good": "--status-good",
    "warn": "--status-warn",
    "crit": "--status-crit",
    "hist": "--ink-quiet",
}


def test_measure_comes_from_the_scale():
    """간격과 모서리는 닫힌 계단이다. 1px은 실선이다."""
    offenders = []
    for path in _surface_texts():
        if path.suffix not in {".css", ".html"}:
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            blocks = re.findall(r"<style>(.*?)</style>", text, re.S)
            blocks.extend(re.findall(r'style="([^"]*)"', text))
            text = "\n".join(blocks)
        for prop, value in _MEASURE.findall(text):
            if "var(--space-" in value or "var(--radius-" in value:
                value = re.sub(r"var\(--(?:space|radius)-[a-z0-9-]+\)", "", value)
            for raw, unit in _LENGTH.findall(value):
                px = float(raw) * (16 if unit == "rem" else 1)
                if px in (0, 1):
                    continue
                offenders.append(f"{path.name} {prop}: {raw}{unit}")
    assert not offenders, offenders


def test_diagnostic_palette_matches_the_token_hex():
    tokens = _dark_tokens()
    page = (ROOT / "middleware" / "perception" / "web" / "diagnostic.html").read_text(encoding="utf-8")
    declared = dict(re.findall(r"--([a-z0-9-]+):\s*#([0-9a-fA-F]{6})", page))
    mismatch = []
    for local, token in _DIAGNOSTIC_TWINS.items():
        got = declared.get(local)
        expected = tokens.get(token)
        if got != expected:
            mismatch.append(f"--{local} #{got} != {token} #{expected}")
    assert not mismatch, mismatch


def test_a_browser_page_starts_from_the_shell():
    """다음 화면은 template.html 의 틀을 쓴다. 문법 없는 껍질은 실패다."""
    if not registry.git_available(registry.REPO):
        pytest.skip("D-329 발견 스캔은 git 체크아웃이 필요하다")
    pages = [
        path for path in registry.discover_html(registry.REPO)
        if path.name in {"index.html", "diagnostic.html"}
        and "<!doctype html>" in path.read_text(encoding="utf-8").lower()
    ]
    assert pages, "제품 화면이 없다"
    missing = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        for bit in (
            "<ui-shell", "<ui-topbar", 'grammar="',
            "/common/tokens.css", "/common/components.css", "/common/ui.js",
        ):
            if bit not in text:
                missing.append(f"{page.relative_to(ROOT)} 에 {bit} 이 없다")
    template = (COMMON / "template.html").read_text(encoding="utf-8")
    for bit in (
        "<ui-shell", "<ui-topbar", "<ui-brand", "<ui-section", "<ui-empty",
        'kind="primary"', 'kind="quiet"', 'kind="irreversible"',
    ):
        if bit not in template:
            missing.append(f"template.html 에 {bit} 이 없다")
    assert not missing, missing


def test_evidence_states_are_one_closed_set():
    """fresh·delayed·disconnected·unavailable 네 이름만 쓴다."""
    logic = (COMMON / "core_ui_logic.js").read_text(encoding="utf-8")
    ui = UI.read_text(encoding="utf-8")
    block = re.search(r"EVIDENCE_STATES = new Set\(\[(.*?)\]\)", logic, re.S)
    ui_block = re.search(r"const EVIDENCE = \[(.*?)\];", ui, re.S)
    assert block and ui_block
    from_logic = set(re.findall(r'"([a-z]+)"', block.group(1)))
    from_ui = set(re.findall(r'"([a-z]+)"', ui_block.group(1)))
    assert from_logic == from_ui == {
        "fresh", "delayed", "disconnected", "unavailable",
    }
    painted = set()
    for path in _surface_texts():
        if path.suffix not in {".css", ".html"}:
            continue
        painted.update(re.findall(
            r'data-evidence="([a-z]+)"', path.read_text(encoding="utf-8"),
        ))
    assert painted <= from_logic, sorted(painted - from_logic)


def test_the_brand_renders_the_home_link_as_a_shared_behaviour():
    # D-335: 페이지가 앵커를 따로 적지 않는다 - ui-brand href가 자식을 하나의
    # 링크로 감싸고, hover와 포커스 링도 components.css가 담당한다.
    script = UI.read_text(encoding="utf-8")
    css = COMPONENTS.read_text(encoding="utf-8")
    brand = script.split("class UiBrand extends HTMLElement", 1)[1].split("\nclass ", 1)[0]
    assert 'this.getAttribute("href")' in brand
    assert 'link.setAttribute("href", href)' in brand
    assert "aria-label" in brand
    assert "ui-brand a:hover b" in css and "ui-brand a:hover small" in css
    assert "ui-brand a:focus-visible" in css


# ---- D-359 §5 / §7.4–7.5 — 공용 필드·버튼 상태·사유 -----------------------------

FIELD_TAG = re.compile(r"<(input|select|textarea)\b([^>]*)>", re.S)
FIELD_CREATE = re.compile(
    r"""(?:createElement|\bel|\bnode)\(\s*["'](input|select|textarea)["']\s*(?:,\s*["']([^"']*)["'])?"""
)
FIELD_CLASS_SET = re.compile(
    r"""\.className\s*=\s*["'][^"']*\bui-field\b|classList\.add\([^)]*["']ui-field["']"""
)
CHECK_TYPE = re.compile(r"""type\s*=\s*["'](?:checkbox|radio)""")


def _product_texts():
    """제품 화면(D-359 §5.1): 로봇 표면(셸·패널 포함)·Fleet·games. 라이브러리 자체는 뺀다."""
    for surface in registry.for_contract(registry.REPO, "typography_focus"):
        if surface.resolve() == COMMON.resolve():
            continue
        paths = [surface] if surface.is_file() else sorted(surface.rglob("*"))
        for path in paths:
            if path.suffix in STYLE_SUFFIXES and "test" not in path.parts:
                yield path


def test_product_fields_carry_the_shared_field_class():
    """입력·선택은 components.css의 input.ui-field 얼굴을 쓴다. 이름이 다른 사본을 구조로 찾는다."""
    missing = []
    for path in _product_texts():
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".html":
            for match in FIELD_TAG.finditer(text):
                tag, attrs = match.groups()
                if 'type="hidden"' in attrs:
                    continue
                classes = re.search(r'class="([^"]*)"', attrs)
                if not classes or "ui-field" not in classes.group(1).split():
                    missing.append(f"{path.name}: <{tag}{attrs.strip()[:60]}>")
                if CHECK_TYPE.search(attrs):
                    start = text.rfind("<label", 0, match.start())
                    opener = text[start:text.find(">", start) + 1] if start >= 0 else ""
                    if "ui-check" not in opener:
                        missing.append(f"{path.name}: checkbox outside label.ui-check")
            continue
        if path.suffix != ".js":
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            for match in FIELD_CREATE.finditer(line):
                if "ui-field" in (match.group(2) or "").split():
                    continue
                window = "\n".join(lines[index:index + 4])
                if not FIELD_CLASS_SET.search(window):
                    missing.append(f"{path.name}:{index + 1} {match.group(0)}")
                    continue
                around = "\n".join(lines[max(0, index - 3):index + 4])
                if CHECK_TYPE.search(window) and "ui-check" not in around:
                    missing.append(f"{path.name}:{index + 1} checkbox outside label.ui-check")
    assert not missing, "\n".join(missing)


FIELD_SELECTOR = re.compile(r"\b(?:input|select|textarea)\b|\.ui-field\b")
HEIGHT = re.compile(r"(?<![-a-z])(min-height|height|max-height|block-size)\s*:\s*([^;}]+)")
TARGET = re.compile(r"\s*var\(--target-(?:secondary|primary|irreversible)\)\s*")


def test_fields_clear_the_secondary_target_on_every_surface():
    """공용 필드는 44px 바닥을 가진다. 표면은 입력 높이를 다시 정하지 않는다(체크는 label이 면)."""
    css = COMPONENTS.read_text(encoding="utf-8")
    field = re.search(
        r"ui-field,\s*input\.ui-field,\s*select\.ui-field,\s*textarea\.ui-field\s*\{([^}]*)\}", css)
    assert field and "min-height: var(--target-secondary)" in field.group(1)
    check = re.search(r"\.ui-check\s*\{([^}]*)\}", css)
    assert check and "min-height: var(--target-secondary)" in check.group(1)
    offenders = []
    for path in _product_texts():
        if path.suffix not in {".css", ".html"}:
            continue
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        if path.suffix == ".html":
            text = "\n".join(re.findall(r"<style>(.*?)</style>", text, re.S))
        for selector, body in RULE.findall(text):
            if not FIELD_SELECTOR.search(selector) or re.search(r"checkbox|radio", selector):
                continue
            for prop, value in HEIGHT.findall(body):
                if not TARGET.fullmatch(value):
                    offenders.append(f"{path.name} {selector.strip()[:50]} {prop}: {value.strip()}")
    assert not offenders, offenders


def _rules(css: str):
    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(selector.strip(), body) for selector, body in RULE.findall(stripped)]


def test_every_button_kind_has_shared_interaction_states():
    """hover·active·focus-visible·비활성은 모든 종류에 components.css가 준다(D-359 §5.4)."""
    rules = _rules(COMPONENTS.read_text(encoding="utf-8"))
    missing = []
    for kind in sorted(_kinds()):
        for state in (":hover", ":active"):
            if not any(
                state in selector and f'[kind="{kind}"]' in selector and ":not([disabled]" in selector
                for selector, _ in rules
            ):
                missing.append(f"{kind} {state}")
    assert not missing, missing
    assert any(selector.startswith("ui-button:focus-visible") for selector, _ in rules)
    assert any(selector == "ui-button[disabled]" for selector, _ in rules)
    assert any('[kind="toggle"][aria-pressed="true"]' in selector for selector, _ in rules), (
        "눌림(aria-pressed)의 공용 표현이 없다")
    body = dict(rules).get("body", "")
    assert "word-break: keep-all" in body and "overflow-wrap: break-word" in body
    focus = [decl for selector, decl in rules if selector.startswith(":where(") and ":focus-visible" in selector]
    assert focus and "var(--focus-ring-width)" in focus[0]


DISABLE_SITE = re.compile(
    r"""\.disabled\s*=(?!=)|setAttribute\(\s*["']disabled["']|toggleAttribute\(\s*["']disabled["']""")
REASON_WRITE = re.compile(r"""(?:set|remove)Attribute\(\s*["']reason["']""")
REASON_HELPER = re.compile(r"\b(setOff|setEnabled)\(")
DISABLE_ROOTS = (
    ROOT / "middleware" / "ui" / "robot",
    ROOT / "operations" / "fleet" / "fleet" / "server" / "web",
)
# D-359 §5.3 — 사유 없이 끄는 곳의 닫힌 목록. (src/ 기준 경로, 줄 조각) → 이유. 새 항목은 이유를 적는다.
# 키는 경로로 파일을 가리키고(같은 이름 파일이 여러 폴더에 있다), 조각 하나는 한 곳만 덮는다(DISABLED_SITE_COUNT).
TRANSIENT = "요청 처리 중 잠금 — 누른 직후 몇 초, 결과 문구가 곧 뒤따른다"
INITIAL = "첫 readback 전 초기값 — 같은 파일의 sync 함수가 첫 응답에서 reason과 함께 다시 정한다"
NATIVE = "네이티브 option/select/fieldset/checkbox — 사유를 그릴 자리가 없고, 곁의 상태 문구·태그가 까닭을 말한다"
NOTE = "공용 보이는 안내(ui-status/p)가 aria-describedby로 이 버튼들에 이어져 사유를 말한다"
DISABLED_WITHOUT_REASON = {
    ("middleware/ui/robot/app.js", 'elements["code-submit"].disabled = true;'): TRANSIENT,
    ("middleware/ui/robot/app.js", 'clearTimeout(codeRetryTimer); clearTimeout(actionMessageTimer); elements["code-submit"].disabled = false;'):
        TRANSIENT + " (자격·페이지 수명 취소 뒤 잠금 복구)",
    ("middleware/ui/robot/app.js", 'elements["code-submit"].disabled = false;'): TRANSIENT,
    ("middleware/ui/robot/telemetry.js", 'setEnabled("traffic-policy-stage", !trafficPolicyPending);'): TRANSIENT,
    ("middleware/ui/robot/app.js", 'setEnabled("hardware-refresh", false);'): TRANSIENT + " (장치 점검 요청)",
    ("middleware/ui/robot/app.js", "button.disabled = true;"): TRANSIENT + " (장치 시험 요청)",
    ("middleware/ui/robot/app.js", "button.disabled = false;"): TRANSIENT + " (장치 시험 실패 뒤 복구)",
    ("middleware/ui/robot/panels/console/camera.js", "button.disabled = true;"): TRANSIENT,
    ("middleware/ui/robot/panels/console/camera.js", "finally { button.disabled = false; }"): TRANSIENT,
    ("middleware/ui/robot/panels/console/camera.js", "option.disabled = true;"): NATIVE,
    ("middleware/ui/robot/panels/console/camera.js", "storage.disabled = state.recording || state.uploading;"): NATIVE,
    ("middleware/ui/robot/panels/console/docking.js", 'dock.type = "button"; dock.disabled = true;'): INITIAL,
    ("middleware/ui/robot/panels/console/docking.js", "select.disabled = locked || !hasDocks;"): NATIVE,
    ("middleware/ui/robot/panels/console/map.js", "button.disabled = !enabled;"): NOTE + " (#map-action-reason)",
    ("middleware/ui/robot/panels/console/mode.js", "button.dataset.mode = mode.id; button.disabled = true;"): INITIAL,
    ("middleware/ui/robot/panels/console/teleop.js", "button.disabled = true;"): INITIAL,
    ("middleware/ui/robot/panels/console/teleop.js", "button.disabled = !can && button !== activeButton;"): NOTE + " (readinessStatus)",
    ("middleware/ui/robot/panels/console/teleop.js", "button.disabled = !eligible();"): NOTE + " (readinessStatus)",
    ("middleware/ui/robot/panels/host/hardware.js", "refresh.disabled = true;"): TRANSIENT,
    ("middleware/ui/robot/panels/host/operations.js", "rollback.disabled = clearHold.disabled = true;"): INITIAL,
    ("middleware/ui/robot/panels/host/system.js", "identitySave.disabled = true;"): TRANSIENT,
    ("middleware/ui/robot/panels/host/system.js", "identityInput.disabled = true;"): TRANSIENT,
    ("middleware/ui/robot/panels/host/system.js", "identitySave.disabled = false;"): TRANSIENT,
    ("middleware/ui/robot/panels/host/system.js", "identityInput.disabled = false;"): TRANSIENT,
    ("middleware/ui/robot/panels/setup/dock-admin.js", "add.disabled = true;"): INITIAL,
    ("middleware/ui/robot/panels/setup/dock-admin.js", "add.disabled = pending || blockers.length > 0;"): NOTE + " (gate — 막는 까닭 목록)",
    ("middleware/ui/robot/panels/setup/dock-admin.js", "remove.disabled = deleting;"): TRANSIENT + " (글자가 '삭제 중…')",
    ("middleware/ui/robot/panels/setup/waypoints.js", "save.disabled = true;"): INITIAL + " / " + TRANSIENT,
    ("middleware/ui/robot/panels/system/security.js", "add.disabled = tokenMutationPending;"): TRANSIENT,
    ("middleware/ui/robot/panels/system/security.js", "control.disabled = safetyPending;"): TRANSIENT,
    ("middleware/ui/robot/shell/mount.js", "tab.disabled = true;"): TRANSIENT + " (조작 묶음 전환 중)",
    ("middleware/ui/robot/shell/mount.js", "tab.disabled = false;"): TRANSIENT + " (전환 끝 복구)",
    ("middleware/ui/robot/status-summary.js", "toggle.disabled = items.length === 0;"): "버튼 글자가 이미 '할 일 0'이라고 말한다",
    ("operations/fleet/fleet/server/web/enrollment.js", 'el("enroll-submit").disabled = true;'): TRANSIENT + " (등록 요청)",
    ("operations/fleet/fleet/server/web/formation.js", 'querySelectorAll("input").forEach((i) => { i.disabled = status.active; });'):
        NATIVE + " (대형 상태 태그 RUNNING/HOLDING — 해제 뒤 바꾼다)",
    ("operations/fleet/fleet/server/web/vision-view.js", "fieldset.disabled = !source;"): NATIVE + " (vision-state 태그)",
    ("operations/fleet/fleet/server/web/vision-view.js", "select.disabled = result.sources.length === 0;"): NATIVE + " (vision-state 태그)",
    ("operations/fleet/fleet/server/web/vision-view.js", "select.disabled = true;"): NATIVE + " (vision-state 태그)",
}
#: Keys that cover more than one site on purpose. Every other key covers exactly one,
#: so an identical line added elsewhere in the same file is a new unexplained site.
DISABLED_SITE_COUNT = {
    ("middleware/ui/robot/app.js", 'elements["code-submit"].disabled = false;'): 2,  # 성공·실패 두 갈래의 복구
    ("middleware/ui/robot/panels/setup/waypoints.js", "save.disabled = true;"): 2,  # 초기값과 요청 중 잠금
}


def _call_args(text: str, start: int) -> list[str]:
    depth, args, current = 0, [], ""
    for char in text[start:]:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                args.append(current)
                return [arg for arg in args if arg.strip()]
            depth -= 1
        if char == "," and depth == 0:
            args.append(current)
            current = ""
            continue
        current += char
    return args


def disabled_scripts():
    for root in DISABLE_ROOTS:
        for path in sorted(root.rglob("*.js")):
            if "test" not in path.parts:
                yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8-sig")


def scan_disabled(scripts):
    """(unlisted sites, sites per list key, keys covering a different number of sites than declared)."""
    missing, used = [], Counter()
    for rel, text in scripts:
        name = rel.rsplit("/", 1)[-1]
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if DISABLE_SITE.search(line):
                window = "\n".join(lines[max(0, index - 1):index + 6])
                if REASON_WRITE.search(window):
                    continue
                key = next((k for k in DISABLED_WITHOUT_REASON
                            if k[0] == rel and k[1] in line), None)
                if key:
                    used[key] += 1
                else:
                    missing.append(f"{name}:{index + 1} {line.strip()[:80]}")
        for match in REASON_HELPER.finditer(text):
            if text[max(0, match.start() - 9):match.start()].endswith("function "):
                continue
            args = _call_args(text, match.end())
            if len(args) < 3 and args[1:2] != [" true"]:
                number = text.count("\n", 0, match.start()) + 1
                snippet = lines[number - 1].strip()
                key = next((k for k in DISABLED_WITHOUT_REASON
                            if k[0] == rel and k[1] in snippet), None)
                if key:
                    used[key] += 1
                else:
                    missing.append(f"{name}:{number} {match.group(1)} without reason")
    widened = {key: count for key, count in used.items() if count != DISABLED_SITE_COUNT.get(key, 1)}
    return missing, used, widened


def test_every_disabled_control_states_its_reason_or_is_listed():
    """D-359 §5.3 — 끄는 곳은 reason을 쓰거나(직접·setOff·setEnabled), 닫힌 목록에 이유와 함께 있다."""
    missing, used, widened = scan_disabled(disabled_scripts())
    # Fleet 역할 잠금: 공용 버튼은 reason, 네이티브 입력은 묶음의 보이는 안내에 잇는다.
    fleet = ROOT / "operations" / "fleet" / "fleet" / "server" / "web"
    lock = (fleet / "authorization.js").read_text(encoding="utf-8")
    assert 'setAttribute("reason", OPERATOR_REASON)' in lock
    assert ".role-lock-note" in lock and "aria-describedby" in lock
    # D-410 — 운용 문서(대형 잠금)와 설치 문서(카메라·보정 잠금)가 각각 자기 잠금 안내를 둔다.
    for page_name in ("index.html", "install.html"):
        page = (fleet / page_name).read_text(encoding="utf-8")
        assert page.count("data-role-lock") == page.count('class="role-lock-note"') >= 1
        assert page.count("운용자 권한이 필요합니다</ui-status>") == page.count('class="role-lock-note"')
    stale = sorted(set(DISABLED_WITHOUT_REASON) - set(used))
    assert not missing, "사유 없는 비활성:\n" + "\n".join(missing)
    assert not stale, f"목록에 남은 옛 항목: {stale}"
    assert set(DISABLED_SITE_COUNT) <= set(DISABLED_WITHOUT_REASON)
    assert not widened, (
        "한 조각이 선언과 다른 수의 자리를 덮는다 — 새 같은 줄에는 더 긴 조각으로 제 항목을 준다: "
        f"{widened}")


def test_a_copied_disabled_line_needs_its_own_entry():
    """Mutation proof (P2-4 review): an identical unexplained line elsewhere no longer rides an old key."""
    scripts = dict(disabled_scripts())
    rel = "middleware/ui/robot/panels/host/hardware.js"
    assert "refresh.disabled = true;" in scripts[rel]
    assert scan_disabled([(rel, scripts[rel])])[2] == {}
    copied = scripts[rel] + "\nfunction later(refresh) {\n  refresh.disabled = true;\n}\n"
    assert scan_disabled([(rel, copied)])[2] == {(rel, "refresh.disabled = true;"): 2}
    # same file name in another folder does not borrow the key either
    other = "middleware/ui/robot/panels/setup/hardware.js"
    assert scan_disabled([(other, "refresh.disabled = true;\n")])[0] == ["hardware.js:1 refresh.disabled = true;"]


def test_disabled_reason_is_a_shared_button_attribute():
    """사유는 title이 아니라 reason이다. ui.js가 보이는 글자와 aria-describedby로 잇는다."""
    script = UI.read_text(encoding="utf-8")
    button = script.split("class UiButton extends HTMLElement", 1)[1].split("\nclass ", 1)[0]
    observed = button.split("observedAttributes", 1)[1].split("}", 1)[0]
    assert '"reason"' in observed
    assert "aria-describedby" in button and "dataset.reason" in button
    assert "ui-button > small[data-reason]" in COMPONENTS.read_text(encoding="utf-8")
    offenders = []
    for path in _product_texts():
        if path.suffix != ".js":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\.title\s*=\s*[^;]*(?:비활성|제한|없습니다|필요)", line):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"title만으로 비활성 사유를 말한다: {offenders}"
