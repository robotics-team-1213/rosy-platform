"""Shared browser controls live in one file.

A later page may place a control. It may not invent its kind, repaint it,
or copy a token colour into a second number.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
COMMON = Path(__file__).parent.parent
COMPONENTS = COMMON / "components.css"
UI = COMMON / "ui.js"
TOKENS = COMMON / "tokens.css"
FACE = ROOT / "hmi" / "emotion" / "emotion" / "info_screen.py"
PITCH = ROOT / "site" / "games" / "games" / "web" / "styles.css"

SURFACES = (
    ROOT / "runtime" / "core_api_web" / "core_api_web" / "web",
    ROOT / "site" / "fleet" / "fleet" / "server" / "web",
    ROOT / "site" / "games" / "games" / "web",
    ROOT / "runtime" / "control" / "web" / "dashboard.html",
)
STYLE_SUFFIXES = {".css", ".html"}

RAW_SIZE = re.compile(r"font-size:\s*[0-9.]+(?:px|rem)")
RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(\s*\d")
TAG = re.compile(r"<ui-button\b([^>]*)>", re.S)
RULE = re.compile(r"([^{}]+)\{([^}]*)\}")
CONTROL = re.compile(
    r"ui-button|ui-field|ui-tag|ui-text|ui-head|ui-grid|ui-chip|ui-triage|ui-evidence|"
    r"ui-shell|ui-topbar|ui-brand|ui-section|ui-empty"
)
EVIDENCE_TAG = re.compile(r"<ui-evidence\b([^>]*)>", re.S)
PAINT = re.compile(
    r"(?<![-a-z])(background|color|font-size|font-weight|font|opacity|border-radius|border-color|border)\s*:"
)
CREATE = re.compile(r"""createElement\(\s*["']ui-button["']\s*\)""")
KIND_ATTR = re.compile(r"""setAttribute\(\s*["']kind["']\s*,\s*["']([a-z]+)["']\s*\)""")
FACE_COLOUR = {
    "--ground": "_BG",
    "--paper": "_FG",
    "--muted": "_MUTED",
    "--status-warn": "_WARN",
    "--status-crit": "_CRIT",
}


def _kinds() -> set[str]:
    match = re.search(r"const KINDS = \[(.*?)\];", UI.read_text(encoding="utf-8"), re.S)
    assert match, "ui.js가 KINDS를 선언하지 않는다"
    return set(re.findall(r'"([a-z]+)"', match.group(1)))


def _surface_texts():
    for path in SURFACES:
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
        "ui-shell", "ui-topbar", "ui-brand", "ui-section", "ui-empty",
    )
    for name in names:
        assert name in css
        assert f'"{name}"' in script
    assert not RAW_COLOR.findall(css), "components.css에 원시 색이 있다"
    assert not RAW_SIZE.findall(css)


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


def test_face_literals_match_the_token_file():
    """LCD는 DOM 부품을 쓰지 않는다. 숫자는 토큰과 같아야 한다."""
    tokens = dict(re.findall(
        r"(--[a-z0-9-]+):\s*#([0-9a-fA-F]{6})",
        TOKENS.read_text(encoding="utf-8"),
    ))
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
    "ink": "--paper",
    "ink-2": "--muted",
    "muted": "--muted",
    "route": "--series-primary",
    "goal": "--series-goal",
    "good": "--status-ok",
    "warn": "--status-warn",
    "crit": "--status-crit",
    "hist": "--muted",
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
    tokens = dict(re.findall(
        r"(--[a-z0-9-]+):\s*#([0-9a-fA-F]{6})",
        TOKENS.read_text(encoding="utf-8"),
    ))
    page = (ROOT / "runtime" / "control" / "web" / "dashboard.html").read_text(encoding="utf-8")
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
    pages = [
        path for path in ROOT.rglob("*.html")
        if path.name in {"index.html", "dashboard.html"}
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
